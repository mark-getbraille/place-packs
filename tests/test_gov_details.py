"""Government places with details (November 2026, the owner's decision of 26 November): Social Security field
offices (address, phone, weekday hours), the Forest Service's Recreation Opportunities details joined to its
recreation sites, the National Park Service's Data API (hours with exceptions, phone and TTY, accessibility) and
Recreation.gov's RIDB export (deduplicated against the agencies' own points, whose details it fills), plus
California's licensing files and the government sites that refused programs (recorded as blocked). Every name,
number and place here is made up."""

import csv
import datetime
import io
import json
import os
import sqlite3
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, contact, fetch, gov_details, hours, nps_api, ridb, ssa_offices, usfs_details  # noqa: E402,E501
from placepacks.local import LocalServices  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.readers import tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
HERE = (44.0, -72.0)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def everything_in(path):
    """Every text value of every table of a pack, joined."""
    con = sqlite3.connect(path)
    out = []
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for row in con.execute(f"SELECT * FROM {table}"):
            out += [str(v) for v in row if v is not None]
    con.close()
    return "\n".join(out)


def biz(path):
    """{key: (phone, website, opening_hours)} of a pack's biz_details."""
    con = sqlite3.connect(path)
    rows = con.execute("SELECT p.key, d.phone, d.website, d.opening_hours FROM biz_details d JOIN points p ON "
                       "p.id = d.id").fetchall()
    con.close()
    return {r[0]: r[1:] for r in rows}


def notes(path):
    """{key: note} of a pack's points."""
    con = sqlite3.connect(path)
    rows = con.execute("SELECT p.key, n.text FROM points p JOIN point_notes l ON l.id = p.id JOIN notes n ON "
                       "n.id = l.note").fetchall()
    con.close()
    return dict(rows)


# ------------------------------------------------------------------------------------------- opening hours

def test_ssa_weekday_times_become_openstreetmap_hours():
    cols = ssa_offices.WEEKDAYS
    same = {c: v for d in cols.values() for c, v in zip(d, ("9:00 AM", "4:00 PM"))}
    assert hours.weekday_table(same, cols) == "Mo-Fr 09:00-16:00"
    wed = dict(same, WEDNESDAY_OPEN_TIME="9:00 AM", WEDNESDAY_CLOSE_TIME="12:00 PM")
    assert hours.weekday_table(wed, cols) == "Mo,Tu,Th,Fr 09:00-16:00; We 09:00-12:00"
    early = dict(same, FRIDAY_OPEN_TIME="8:30 AM", FRIDAY_CLOSE_TIME="3:30 PM")
    assert hours.weekday_table(early, cols) == "Mo-Th 09:00-16:00; Fr 08:30-15:30"
    closed = dict(same, MONDAY_OPEN_TIME="CLOSED", MONDAY_CLOSE_TIME="CLOSED")
    assert hours.weekday_table(closed, cols) == "Tu-Fr 09:00-16:00; Mo off"
    # A time that cannot be read gives no hours at all, never a wrong one.
    assert hours.weekday_table(dict(same, TUESDAY_OPEN_TIME="soon"), cols) == ""
    assert hours.clock("12:00 AM", closing=True) == "24:00" and hours.clock("12:30 PM") == "12:30"


def test_plain_free_text_hours_are_converted_and_the_rest_left_as_words():
    assert hours.from_text("Monday - Friday, 8:00 a.m.- 4:30 p.m.&nbsp;Eastern time, unless otherwise posted") == \
        "Mo-Fr 08:00-16:30"
    assert hours.from_text("Day use hours are 6 am to 10 pm.") == "06:00-22:00"
    assert hours.from_text("Open 24 hours a day, 7 days a week.") == "24/7"
    assert hours.from_text("Sunrise- Sunset") == "sunrise-sunset"
    assert hours.from_text("Quiet hours 10:00 pm to 6:00 am") == ""             # not opening hours
    assert hours.from_text("Open year-round") == ""
    assert hours.from_text("Check-in 2 pm, check-out 11 am") == ""


def test_nps_hours_with_exceptions_in_openstreetmap_syntax():
    week = {d: "9:00AM - 5:00PM" for d in hours.NPS_DAYS}
    week.update(saturday="Closed", sunday="Closed")
    today = datetime.date(2026, 11, 26)
    operating = [{"standardHours": week, "exceptions": [
        {"name": "Winter closure", "startDate": "2026-12-01", "endDate": "2027-04-30", "exceptionHours": {}},
        {"name": "Last year", "startDate": "2025-12-01", "endDate": "2026-01-31", "exceptionHours": {}},
        {"name": "Holiday", "startDate": "2026-11-27", "endDate": "2026-11-27",
         "exceptionHours": {d: "10:00AM - 2:00PM" for d in hours.NPS_DAYS}}]}]
    assert hours.nps_hours(operating, today) == ("Mo-Fr 09:00-17:00; Sa,Su off; 2026 Dec 01-2027 Apr 30 off; "
                                                 "2026 Nov 27 Mo-Su 10:00-14:00")
    everyday = [{"standardHours": {d: "All Day" for d in hours.NPS_DAYS}}]
    assert hours.nps_hours(everyday, today) == "24/7"
    sun = [{"standardHours": {d: "Sunrise to Sunset" for d in hours.NPS_DAYS}}]
    assert hours.nps_hours(sun, today) == "Mo-Su sunrise-sunset"
    vague = [{"standardHours": dict(week, monday="Varies with the season"), "description": "Open most days."}]
    assert hours.nps_hours(vague, today) == ""


# ------------------------------------------------------------------------------------------- Social Security

SSA_ATTRS = {"OFFICE_CODE": "901", "OFFICE_NAME": "TESTVILLE VT", "ADDRESS_LINE_1": "SOCIAL SECURITY",
             "ADDRESS_LINE_2": "STE 2B", "ADDRESS_LINE_3": "10 MADEUP ST", "CITY": "TESTVILLE", "STATE": "VT",
             "ZIP_CODE": 5000, "PHONE": "(802) 555-0150", "FAX": "(802) 555-0199",
             **{c: v for d in ssa_offices.WEEKDAYS.values() for c, v in zip(d, ("9:00 AM", "4:00 PM"))},
             # internal columns the layer also has: never asked for, never stored
             "Cost": 987654.0, "Employees": 31, "LeaseEnd": 1893456000000, "AvgWait": 47, "SqFt": 12345,
             "Utilization": 88, "households_ACSPOVINDX": 12.5, "AREA_DESC": "Madeup Area Office"}


def test_ssa_asks_only_for_the_kept_columns_and_never_stores_internal_ones(monkeypatch, tmp_path):
    seen = []

    def fake_post(url, params, waits=(), sleep=None, pause=0):
        seen.append((url, params))
        # A careless server might send more than was asked for: the converter still keeps only its columns.
        return {"features": [{"attributes": dict(SSA_ATTRS), "geometry": {"x": -72.0001, "y": 44.0001}},
                             {"attributes": dict(SSA_ATTRS, OFFICE_CODE="902", CITY="NOWHERE"), "geometry": None}]}
    monkeypatch.setattr(fetch, "post_json", fake_post)
    entry = entry_of("ssa-field-offices")
    assert ssa_offices.prepare(entry, str(tmp_path), sleep=lambda s: None) == 1
    asked = seen[0][1]["outFields"].split(",")
    assert asked == ssa_offices.KEPT and seen[0][0].endswith("/FeatureServer/0/query")
    for internal in ("Cost", "Employees", "LeaseEnd", "AvgWait", "SqFt", "Utilization", "FAX", "AREA_DESC",
                     "households_ACSPOVINDX"):
        assert internal not in asked
    path = tmp_path / "ssa-field-offices.csv"
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == gov_details.FIELDS
    assert rows[0]["name"] == "Social Security office, Testville"
    assert rows[0]["note"] == "Address: 10 Madeup St, Ste 2B, Testville, VT 05000"
    assert rows[0]["opening_hours"] == "Mo-Fr 09:00-16:00"
    text = path.read_text(encoding="utf-8")
    for value in ("987654", "555-0199", "Madeup Area Office", "12345", "1893456000000"):
        assert value not in text

    # Read into a pack: the phone and hours are the place's details, the address its note.
    out = str(tmp_path / "us-vermont-extra.osmpack")
    w = PackWriter(out, 202611)
    assert tabular.read(str(path), entry, dict(catalogue.regions()[VT]), w) == 1
    w.finish({"part": "extra", "region_id": VT})
    assert biz(out) == {"ssa-field-offices:901": ("802-555-0150", None, "Mo-Fr 09:00-16:00")}
    assert notes(out)["ssa-field-offices:901"].startswith("Address: 10 Madeup St")
    assert "987654" not in everything_in(out) and "555-0199" not in everything_in(out)

    # "The nearest Social Security office" says its address, phone and hours.
    near = LocalServices(packs=[PackReader(out)]).nearest(*HERE, "social security")
    place = near["places"][0]
    assert place["phone"] == "802-555-0150" and place["opening_hours"] == "Mo-Fr 09:00-16:00"
    assert place["address"] == "10 Madeup St, Ste 2B, Testville, VT 05000"
    assert "Phone 802-555-0150." in near["phrase"] and "Hours: Mo-Fr 09:00-16:00." in near["phrase"]


def test_ssa_entry_is_a_public_national_source_with_the_owners_licence():
    e = entry_of("ssa-field-offices")
    assert e["licence"] == "government-facts" and e["cls"] == "public" and e["tag"] == "social security office"
    assert e["fetch"]["convert"] == "ssa_offices" and e["part"] == "extra"
    assert "ssa-field-offices" in contact.GOVERNMENT_SOURCES and "ssa-field-offices" in contact.HOURS_SOURCES
    lic = catalogue.load()["licences"]["government-facts"]["name"]
    assert "26 November 2026" in lic and "never past" in lic


# ------------------------------------------------------------------------------------------- Forest Service

def write_csv(path, header, rows):
    """A small CSV."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def test_usfs_details_join_by_site_id_or_name_and_never_add_places(tmp_path):
    sites = tmp_path / "usfs-recreation-sites.csv"
    write_csv(sites, ["site_id", "site_name", "site_subtype", "site_cn", "site_phone_nbr", "_lat", "_lon"],
              [["S1", "MADEUP LAKE CAMPGROUND", "CAMPGROUND", "CN-1", "802-555-0160", "44.0", "-72.0"],
               ["S2", "PRETEND TRAILHEAD", "TRAILHEAD", "", "", "44.01", "-72.0"],
               ["S3", "LONELY PICNIC SITE", "PICNIC SITE", "CN-3", "", "44.02", "-72.0"]])
    recs = tmp_path / "details.csv"
    write_csv(recs, ["recareaname", "infra_cn", "recareaurl", "open_season_start", "open_season_end",
                     "operational_hours", "feedescription", "reservation_info", "accessibility", "openstatus",
                     "_lat", "_lon"],
              [["Madeup Lake Campground", "CN-1", "https://www.fs.usda.gov/recarea/madeup/recarea/?recid=1", "May",
                "October 31", "Day use hours are 6 am to 10 pm.", "$10 a night", "",
                "<ul><li>Accessible restroom</li></ul>", "closed", "44.0", "-72.0"],
               ["Pretend Trailhead", "", "", "", "", "Open year round, call (802) 555-0161", "", "", "", "open",
                "44.0101", "-72.0"],
               ["Elsewhere Campground", "CN-99", "", "", "", "24/7", "", "", "", "open", "45.0", "-73.0"]])
    spec = entry_of("usfs-recreation-sites")["fetch"]["join"]
    assert usfs_details.join_files(str(sites), str(recs), spec) == 2
    with open(sites, newline="", encoding="utf-8") as fh:
        rows = {r["site_id"]: r for r in csv.DictReader(fh)}
    assert len(rows) == 3                                   # the unmatched record is not a new place
    s1 = rows["S1"]
    assert s1["_hours"] == "06:00-22:00" and s1["_website"].startswith("https://www.fs.usda.gov/")
    assert s1["_note"] == ("Season: May to October 31; Fees: $10 a night; Accessibility: Accessible restroom; "
                           "Status at the last build: closed")
    assert rows["S2"]["_hours"] == "" and "Hours: Open year round" in rows["S2"]["_note"]
    assert rows["S3"]["_note"] == ""

    # The reader keeps the phone, page and hours as details and the note (without the phone inside the text).
    out = str(tmp_path / "x.osmpack")
    w = PackWriter(out, 202611)
    tabular.read(str(sites), entry_of("usfs-recreation-sites"), dict(catalogue.regions()[VT]), w)
    w.finish({"part": "extra", "region_id": VT})
    got = biz(out)
    assert got["usfs-recreation-sites:S1"] == ("802-555-0160", "https://www.fs.usda.gov/recarea/madeup/recarea/"
                                               "?recid=1", "06:00-22:00")
    assert "555-0161" not in everything_in(out)


# ------------------------------------------------------------------------------------------- National Park Service

class Answer(io.BytesIO):
    """A fake HTTP answer (a context manager with headers and a status)."""

    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}


def nps_record(**extra):
    """A made-up visitor center record of the NPS API."""
    rec = {"id": "VC-1", "name": "Madeup Visitor Center", "latitude": "44.0002", "longitude": "-72.0002",
           "url": "https://www.nps.gov/madeup/planyourvisit/vc.htm",
           "contacts": {"phoneNumbers": [{"phoneNumber": "802-555-0170", "type": "Voice"},
                                         {"phoneNumber": "802-555-0171", "type": "Fax"},
                                         {"phoneNumber": "802-555-0172", "type": "TTY"}],
                        "emailAddresses": [{"emailAddress": "someone@example.gov"}]},
           "operatingHours": [{"standardHours": {d: "9:00AM - 5:00PM" for d in hours.NPS_DAYS},
                               "description": "Open daily."}],
           "amenities": ["Restrooms", "Elevator"], "images": [{"credit": "A. Photographer", "url": "x.jpg"}],
           "addresses": [{"type": "Physical", "stateCode": "VT"}]}
    rec.update(extra)
    return rec


def test_nps_rows_keep_facts_tty_and_amenities_never_emails_or_photos():
    row = nps_api.row_of("visitorcenters", nps_record(), datetime.date(2026, 11, 26))
    assert row["phone"] == "802-555-0170" and row["opening_hours"] == "Mo-Su 09:00-17:00"
    assert row["note"] == "TTY: 802-555-0172; Amenities: Restrooms, Elevator"
    assert row["kind"] == "visitor center" and row["state"] == "VT" and row["key"] == "visitorcenters:VC-1"
    text = json.dumps(row)
    assert "example.gov" not in text and "Photographer" not in text and "555-0171" not in text
    vague = nps_record(operatingHours=[{"standardHours": {"monday": "Varies"}, "description": "Open in summer."}])
    assert nps_api.row_of("visitorcenters", vague)["note"].startswith("Hours: Open in summer; TTY")
    camp = nps_api.row_of("campgrounds", nps_record(
        amenities={"toilets": ["Flush Toilets - year round"], "showers": ["None"], "dumpStation": "Yes"},
        accessibility={"wheelchairAccess": "Two accessible sites.", "adaInfo": "", "rvAllowed": "1",
                       "rvMaxLength": "35", "accessRoads": ["Paved Roads - All vehicles OK"]},
        numberOfSitesReservable="12"))
    assert "Accessibility: Two accessible sites.; access roads: Paved Roads - All vehicles OK; RVs allowed up to " \
           "35 ft" in camp["note"]
    assert "Toilets: Flush Toilets - year round" in camp["note"] and "Showers" not in camp["note"]
    assert "Reservable sites: 12" in camp["note"]
    assert nps_api.row_of("places", nps_record(title="Closed Spot", isOpenToPublic="0")) is None
    assert nps_api.row_of("visitorcenters", nps_record(latitude="")) is None


def test_nps_needs_its_key_sends_it_in_a_header_and_pages(monkeypatch, tmp_path):
    entry = entry_of("nps-places")
    monkeypatch.delenv("NPS_API_KEY", raising=False)
    with pytest.raises(nps_api.NeedsKey):
        nps_api.prepare(entry, str(tmp_path))
    monkeypatch.setenv("NPS_API_KEY", "made-up-nps-key")
    monkeypatch.setattr(nps_api, "PAGE", 2)
    asked = []

    def opener(url, headers):
        asked.append((url, headers))
        assert "made-up-nps-key" not in url and headers["X-Api-Key"] == "made-up-nps-key"
        start = int(url.split("start=")[1].split("&")[0])
        data = [nps_record(id=f"{url.split('/v1/')[1].split('?')[0]}-{start + i}", fullName="Madeup Park",
                           title="Madeup Spot") for i in range(2)]
        data = data if start == 0 else data[:1]
        return Answer(json.dumps({"total": "3", "data": data}).encode())
    count = nps_api.prepare(entry, str(tmp_path), sleep=lambda s: None, opener=opener,
                            today=datetime.date(2026, 11, 26))
    assert count == 12 and len(asked) == 8                  # 4 endpoints x 2 pages
    assert "made-up-nps-key" not in (tmp_path / "nps-places.csv").read_text(encoding="utf-8")


def test_nps_details_go_to_the_matching_nps_poi_point(tmp_path):
    out = str(tmp_path / "n.osmpack")
    w = PackWriter(out, 202611)
    w.add_point("nps-poi:1", "nps-poi", "Madeup Visitor Center", "public", "visitor center", 44.0, -72.0)
    w.add_point("nps-places:visitorcenters:VC-1", "nps-places", "Madeup Visitor Center", "public", "visitor center",
                44.002, -72.0, note="TTY: 802-555-0172",
                contact={"phone": "802-555-0170", "opening_hours": "Mo-Su 09:00-17:00"})
    e = entry_of("nps-places")
    assert w.drop_duplicates("nps-places", e["dedupe_against"], e["dedupe_m"], carry=e["dedupe_carry"]) == 1
    w.finish({"part": "extra", "region_id": VT})
    assert biz(out) == {"nps-poi:1": ("802-555-0170", None, "Mo-Su 09:00-17:00")}
    assert notes(out) == {"nps-poi:1": "TTY: 802-555-0172"}


def test_the_nps_secret_reaches_only_the_prepare_step():
    import yaml
    path = os.path.join(ROOT, ".github", "workflows", "build-packs.yml")
    flow = yaml.safe_load(open(path, encoding="utf-8"))
    assert flow["permissions"] == {"contents": "read"} and "permissions" not in flow["jobs"]["prepare"]
    step = next(s for s in flow["jobs"]["prepare"]["steps"] if s.get("name") == "Download and split the national files")
    assert step["env"]["NPS_API_KEY"] == "${{ secrets.NPS_API_KEY }}"
    assert open(path, encoding="utf-8").read().count("secrets.NPS_API_KEY") == 1


# ------------------------------------------------------------------------------------------- Recreation.gov (RIDB)

FAC_HEADER = ["FacilityID", "FacilityName", "FacilityDescription", "FacilityTypeDescription", "FacilityPhone",
              "FacilityEmail", "FacilityAdaAccess", "FacilityAccessibilityText", "FacilityLongitude",
              "FacilityLatitude", "Reservable", "Enabled"]


def ridb_tables():
    """Made-up RIDB tables ({member: rows})."""
    fac = [dict(zip(FAC_HEADER, r)) for r in [
        ["F1", "Madeup Lake Campground", "<h2>Overview</h2><p>A lakeside campground. Call the host Bob.</p>",
         "Campground", "802-555-0180", "host@example.gov", "Y", "Two accessible sites", "-72.0003", "44.0003",
         "true", "true"],
        ["F2", "Pretend Dam Day Use", "Contact Jane Example at 802-555-0181 for details.", "Facility",
         "802-555-0182", "", "N", "", "-72.05", "44.05", "false", "true"],
        ["F3", "Madeup Lake Christmas Tree Permit", "", "Tree Permit", "", "", "", "", "-72.0", "44.0", "true",
         "true"],
        ["F4", "Nowhere Campground", "", "Campground", "", "", "", "", "0", "0", "false", "true"]]]
    return {"Facilities_API_v1.csv": fac,
            "RecAreas_API_v1.csv": [{"RecAreaID": "A1", "RecAreaName": "Pretend Lake", "RecAreaPhone": "",
                                     "RecAreaDescription": "A reservoir.", "RecAreaLatitude": "44.1",
                                     "RecAreaLongitude": "-72.1", "Enabled": "true"}],
            "OrgEntities_API_v1.csv": [{"EntityID": "F1", "OrgID": "131"}, {"EntityID": "F2", "OrgID": "130"}],
            "Organizations_API_v1.csv": [{"OrgID": "131", "OrgName": "USDA Forest Service"},
                                         {"OrgID": "130", "OrgName": "US Army Corps of Engineers"}],
            "PermitEntrances_API_v1.csv": [{"PermitEntranceID": "7", "PermitEntranceType": "Entry Point",
                                            "FacilityID": "F1", "PermitEntranceName": "Madeup Portage",
                                            "PermitEntranceDescription": "Method of travel is paddle.",
                                            "PermitEntranceAccessible": "false", "Latitude": "44.2",
                                            "Longitude": "-72.2"}]}


def test_ridb_keeps_places_with_facts_and_trims_descriptions():
    rows = {r["key"]: r for r in ridb.convert(ridb_tables())}
    assert set(rows) == {"facility:F1", "facility:F2", "area:A1", "entrance:7"}   # no permit, no zero position
    f1 = rows["facility:F1"]
    assert f1["website"] == "https://www.recreation.gov/camping/campgrounds/F1" and f1["phone"] == "802-555-0180"
    assert f1["note"] == ("Managed by: USDA Forest Service; Reservations: yes, on Recreation.gov; ADA access: yes; "
                          "Accessibility: Two accessible sites; About: A lakeside campground")
    f2 = rows["facility:F2"]
    assert f2["kind"] == "recreation site" and "Jane" not in f2["note"] and "ADA access: no" in f2["note"]
    assert rows["entrance:7"]["kind"] == "permit entry point"
    assert "example.gov" not in json.dumps(rows) and "Bob" not in json.dumps(rows)


def test_ridb_reads_only_its_members_with_range_requests(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("Media_API_v1.csv", "x" * 5000)
        z.writestr("Facilities_API_v1.csv", "FacilityID,FacilityName\nF1,Madeup\n")
    data = buf.getvalue()
    asked = []

    def opener(url, headers):
        a, b = headers["Range"][len("bytes="):].split("-")
        asked.append((int(a), int(b)))
        return Answer(data[int(a):int(b) + 1], status=206)
    got = ridb.zip_members(ridb.URL, len(data), ["Facilities_API_v1.csv"], sleep=lambda s: None, opener=opener)
    assert got == {"Facilities_API_v1.csv": b"FacilityID,FacilityName\nF1,Madeup\n"}
    assert sum(b - a + 1 for a, b in asked) < len(data) + 200      # the photos' table is never downloaded
    assert not any(a <= data.index(b"xxxx") <= b for a, b in asked[2:])

    def no_ranges(url, headers):
        return Answer(data, status=200)
    with pytest.raises(ValueError):
        ridb.zip_members(ridb.URL, len(data), ["Facilities_API_v1.csv"], sleep=lambda s: None, opener=no_ranges)


def test_ridb_places_already_listed_by_an_agency_fill_its_details_instead(tmp_path):
    path = tmp_path / "ridb.csv"
    gov_details.write_rows(str(path), ridb.convert(ridb_tables()))
    out = str(tmp_path / "r.osmpack")
    w = PackWriter(out, 202611)
    # The Forest Service's own point of the campground, 40 m away, written in capitals.
    w.add_point("usfs-recreation-sites:S1", "usfs-recreation-sites", "MADEUP LAKE CAMPGROUND".title(), "park",
                "campground", 44.0, -72.0, type="campground")
    # A BLM point with the same name as the day-use site, but 5 km away: a different place.
    w.add_point("blm-recreation-sites:G1", "blm-recreation-sites", "Pretend Dam Day Use", "park", "day use area",
                44.0, -72.05)
    entry = entry_of("ridb-recreation")
    assert tabular.read(str(path), entry, dict(catalogue.regions()[VT]), w) == 4
    gone = w.drop_duplicates(entry["id"], entry["dedupe_against"], entry["dedupe_m"], carry=entry["dedupe_carry"])
    assert gone == 1
    w.finish({"part": "extra", "region_id": VT})
    keys = {r[0] for r in sqlite3.connect(out).execute("SELECT key FROM points")}
    assert "ridb-recreation:facility:F1" not in keys and "usfs-recreation-sites:S1" in keys
    assert "ridb-recreation:facility:F2" in keys
    details = biz(out)
    assert details["usfs-recreation-sites:S1"] == ("802-555-0180", "https://www.recreation.gov/camping/campgrounds/F1",
                                                   None)
    assert notes(out)["usfs-recreation-sites:S1"].startswith("Managed by: USDA Forest Service")


def test_ridb_is_accepted_by_the_owners_decision_and_deduplicated_against_the_agencies():
    cat = catalogue.load()
    e = entry_of("ridb-recreation")
    assert e["licence"] == "government-facts" and e["dedupe_carry"] and e["dedupe_m"] == 100
    assert {"usfs-recreation-sites", "nps-poi", "nps-places", "blm-recreation-sites"} <= set(e["dedupe_against"])
    assert not any("RIDB" in r["name"] for r in cat["rejected"])
    assert "owner decided on 26 November 2026" in e["notes"]


# ------------------------------------------------------------------------------------------- the others

def test_california_lists_keep_facilities_and_centres_never_homes():
    health = entry_of("ca-health-facilities")
    assert health["class_map"]["*"] == "" and health["regions"] == ["us-california"]
    assert not any(k.startswith(("HOME HEALTH", "HOSPICE", "INTERMEDIATE CARE", "CONGREGATE"))
                   for k in health["class_map"])
    child = entry_of("ca-child-care-centers")
    assert child["class_map"]["*"] == "" and not any("HOME" in k for k in child["class_map"])
    assert "CLOSED" in child["exclude"]["values"] and "7aed8063" in child["fetch"]["url"]
    for e in (health, child):
        used = json.dumps(e["columns"]) + json.dumps(e.get("geocode", {}))
        assert "ADMIN" not in used.upper() and "PHONE" not in used.upper() and "licensee" not in used
        assert not e.get("contact_columns") and e["licence"] == "government-facts"


def test_the_government_sites_that_refused_are_recorded_as_blocked():
    rejected = {r["name"]: r["reason"] for r in catalogue.load()["rejected"]}
    for prefix in ("Head Start", "American Job Centers", "FDA certified mammography", "State Department passport",
                   "USCIS field offices", "Social Security Administration office locator"):
        reason = next(v for k, v in rejected.items() if k.startswith(prefix))
        assert "blocked" in reason, prefix
    irs = next(v for k, v in rejected.items() if k.startswith("IRS Taxpayer Assistance"))
    assert "Local Office Locator" in irs


def test_government_details_skip_the_person_name_check_but_directories_keep_it():
    assert contact.allowed("ridb-recreation", "Lost Lake Campground")
    assert not contact.allowed("overture-places", "Alice Example")
    assert contact.clean("nps-places", "Madeup Visitor Center", hours_value="Mo-Su 09:00-17:00") == \
        {"opening_hours": "Mo-Su 09:00-17:00"}
