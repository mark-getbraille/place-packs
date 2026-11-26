"""The federal and state place lists of the 26 November 2026 pass: NLS braille and talking-book libraries, CMS
medical equipment suppliers, BLM, Reclamation and TVA recreation sites (with BLM's accessibility descriptions kept as
notes), EPA water and electric utility service areas, HUD housing authorities, the fire department registry, federal
prisons, border crossings, locks, bike-share stations, stadiums and the FAA's private-use institutional and closed
airports; and the state lists: lottery retailers, career and blind services, licensed child care CENTRES (never
homes), state health facilities, Pennsylvania licence agents and dispensaries, and Kentucky, Utah and Connecticut
outdoor places. The tests check the catalogue entries (open licences, no personal contact column ever asked for),
the child care centre filters, the NLS page reader, notes, areas and the readers' output. Every name, number and
place here is made up."""

import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, lookup, split  # noqa: E402
from placepacks.readers import tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

FEDERAL = {"nls-talking-book-libraries", "cms-dme-suppliers", "blm-recreation-sites", "blm-accessible-recreation",
           "reclamation-recreation-sites", "tva-recreation-points", "epa-water-service-areas",
           "electric-retail-territories", "hud-public-housing-authorities", "usfa-fire-departments",
           "usfa-fire-stations", "bop-federal-prisons", "bts-border-crossings", "usace-locks", "ntad-bikeshare",
           "faa-stadiums", "faa-other-airports"}
STATE = {"ny-lottery-retailers", "fl-lottery-terminals", "ny-career-centers", "nyscb-service-contractors",
         "tx-child-care-centers", "pa-child-care-centers", "ct-child-care-centers", "de-child-care-centers",
         "co-child-care-centers", "mi-child-care-centers", "ny-health-facilities", "ia-health-facilities",
         "hi-health-facilities", "ct-nursing-facilities", "pa-hunting-licence-agents",
         "pa-medical-marijuana-dispensaries", "ky-fishing-access", "ky-wildlife-management-areas", "ky-trailheads",
         "utah-boat-ramps", "ct-deep-property-access"}
CHILD_CARE = sorted(s for s in STATE if s.endswith("child-care-centers"))
# Columns that would carry a person's name or contact details: never asked for, in any form.
PERSONAL = re.compile(r"phone|fax|e_?mail|poc\b|contact|telephone|director|responsible_person|exec_|librarian|"
                      r"administrator|headteacher|consultant|created_user|edited_user|operator_name|manager", re.I)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def region(rid):
    """A region of regions.json (a copy)."""
    return dict(catalogue.regions()[rid])


def write_csv(path, header, rows):
    """A small CSV file for a reader to read."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


class Recorder:
    """A stand-in for the pack writer: keeps every point and area the reader adds."""
    month = 202611

    def __init__(self):
        self.points, self.areas = [], []

    def add_point(self, key, source, name, cls, tag, lat, lon, first, last, type=None, brand=None, note=None):
        self.points.append({"key": key, "name": name, "cls": cls, "tag": tag, "first": first, "last": last,
                            "type": type, "note": note, "lat": lat, "lon": lon})

    def add_area(self, key, source, name, cls, tag, rings, first=None, last=None, type=None):
        self.areas.append({"key": key, "name": name, "cls": cls, "tag": tag, "type": type, "rings": rings})


def read(entry, path, rid):
    """The recorder after the tabular reader read a file for a region."""
    rec = Recorder()
    tabular.read(path, entry, region(rid), rec)
    return rec


def asked_for(entry):
    """Every column name an entry asks a publisher for or reads, as one text."""
    f = entry["fetch"]
    return " ".join([str(f.get("fields", "")), json.dumps(f.get("params", {})), json.dumps(f.get("queries", [])),
                     json.dumps(f.get("json_records", {})), json.dumps(entry.get("columns", {})),
                     json.dumps(entry.get("geocode", {})), str(entry.get("note_column", "")),
                     str(entry.get("name_template", ""))])


# --------------------------------------------------------------------------------------------------- the catalogue

def test_new_sources_are_in_the_catalogue_with_open_licences_and_no_personal_columns():
    cat = catalogue.load()
    ids = {e["id"] for e in cat["accepted"]}
    assert FEDERAL <= ids and STATE <= ids
    assert catalogue.check(cat) == []
    for sid in FEDERAL:
        assert entry_of(sid)["licence"] == "US-Government-Work", sid
    for sid in FEDERAL | STATE:
        e = entry_of(sid)
        assert e["countries"] == ["US"]
        assert not PERSONAL.search(asked_for(e)), sid
    # State lists are only built for their own state.
    for sid in STATE:
        assert len(entry_of(sid)["regions"]) == 1, sid


def test_the_rejected_list_is_updated():
    rejected = {r["name"]: r["reason"] for r in catalogue.load()["rejected"]}
    assert "National Heritage Areas, BLM recreation sites and Bureau of Reclamation lakes" not in rejected
    assert "blm-recreation-sites" in rejected["National Heritage Areas"]
    assert "Esri Master License Agreement" in rejected["EIA power plants (EIA-860)"]
    assert "abuse detection" in rejected["FDA certified mammography facilities (accessdata.fda.gov public.zip)"]
    hospices = next(v for k, v in rejected.items() if k.startswith("CMS Provider Data: nursing homes"))
    assert "hospices" in hospices and "on purpose" in hospices
    # California's licensing files are used since the owner's decision of 26 November 2026 (government data
    # regardless of the portal's terms): ca-health-facilities and ca-child-care-centers.
    assert not any(k.startswith("California CHHS") for k in rejected)


def test_hospices_and_home_care_stay_out_of_every_health_list():
    for sid in ("ny-health-facilities", "ia-health-facilities", "hi-health-facilities", "ca-health-facilities"):
        cmap = entry_of(sid)["class_map"]
        assert cmap["*"] == ""
        assert not any(re.search(r"hospice|home health|home care|foster", k, re.I) for k in cmap), sid


# ------------------------------------------------------------------------------------- child care centres, never homes

def test_every_child_care_source_asks_only_for_centres():
    for sid in CHILD_CARE:
        e = entry_of(sid)
        f = e["fetch"]
        where = f.get("where") or " ".join(q.get("where", "") for q in f.get("queries", []))
        assert "Center" in where, sid
        assert not re.search(r"home|family", where, re.I), sid
        assert e["part"] == "businesses" and e["class_map"]["*"] == ""
        assert set(v for k, v in e["class_map"].items() if k != "*") <= {"business:child care center",
                                                                        "business:preschool"}


CHILD_CARE_ROWS = {
    # source: (columns, rows: (name, kind) of which only the centres are kept, region, row maker)
    "pa-child-care-centers": ("pa", ["Child Care Center", "Family Child Care Home", "Group Child Care Home",
                                     "Other"]),
    "de-child-care-centers": ("de", ["Licensed Child Care Center", "Licensed Family Child Care",
                                     "Licensed Large Family Child Care"]),
    "co-child-care-centers": ("co", ["Child Care Center", "Family Child Care Home", "Large Family Child Care Home",
                                     "Preschool Program", "Infant/Toddler Home"]),
    "mi-child-care-centers": ("mi", ["Center", "Family Home (1-6)", "Group Home (7-12)"]),
}


def test_the_child_care_readers_drop_every_home_type_even_if_the_portal_sent_them(tmp_path):
    places = {"pa": ("us-pennsylvania", 40.27, -76.88), "de": ("us-delaware", 39.16, -75.52),
              "co": ("us-colorado", 39.74, -104.99), "mi": ("us-michigan", 42.73, -84.55)}
    for sid, (where, kinds) in CHILD_CARE_ROWS.items():
        e = entry_of(sid)
        rid, lat, lon = places[where]
        cols = e["columns"]
        header = sorted({cols["name"], cols.get("key", "k"), cols["class_column"],
                         cols.get("point") or "_lat", "" if cols.get("point") else "_lon"} - {""})
        rows = []
        for i, kind in enumerate(kinds):
            values = {cols["name"]: f"Made-Up Place {i}", cols.get("key", "k"): str(i), cols["class_column"]: kind}
            if cols.get("point"):
                values[cols["point"]] = f"POINT ({lon + i / 1000} {lat})"
            else:
                values["_lat"], values["_lon"] = str(lat), str(lon + i / 1000)
            rows.append([values[h] for h in header])
        got = read(e, write_csv(tmp_path / f"{sid}.csv", header, rows), rid).points
        kept = {kinds[int(p["name"].rsplit(" ", 1)[1])] for p in got}
        assert kept and not any(re.search(r"home|family|other", k, re.I) for k in kept), (sid, kept)
        assert all(p["cls"] == "business" for p in got)


def test_texas_and_connecticut_child_care_keep_centres_with_their_dates(tmp_path):
    e = entry_of("tx-child-care-centers")
    assert "operation_type = 'Licensed Center'" in e["fetch"]["queries"][0]["where"]
    assert e["fetch"]["method"] == "national" and e["geocode"]["from"] == "nad"
    assert tabular.class_of(e, "Licensed Center") == ("business", "child care center")
    for home in ("Registered Child-Care Home", "Licensed Child-Care Home", "Listed Family Home"):
        assert tabular.class_of(e, home) == ("", "")
    c = entry_of("ct-child-care-centers")
    where = c["fetch"]["queries"][0]["where"]
    assert "businessflag = 'Organization'" in where and "licensetype = 'Child Care Center'" in where
    assert tabular.class_of(c, "Family Child Care Home") == ("", "")
    assert c["columns"]["closed_column"] == "closed"


# ------------------------------------------------------------------------------- NLS braille and talking-book libraries

NLS_PAGE = """<html><body><div class="fyl-wrapper"><div class="sll-state-wrapper" id="vermont">
<h2 class="sll-state-name">Vermont</h2><div class="sll-library-wrapper">
<ul class="fyl-library nobullet"><h3 class="fyl-library-type">Regional Library</h3>
<li class="fyl-library-name">Made-Up Regional Library for the Blind</li>
<li class="fyl-library-address">Invented Institute Building<br> 10 Madeup St<br> P.O. Box 9</li>
<li class="fyl-library-city">Testville, VT 05000-1234</li>
<li class="fyl-library-librarian"> <b>Librarian: </b>Jane Doe</li>
<li class="fyl-library-id"> <b>Library Code: </b>VT9A</li>
<li class="fyl-library-phone"> <b>Telephone: </b>(802) 555-0100</li>
<li class="fyl-library-email"> <b>E-mail: </b> <a href="#">[email&#160;protected]</a></li></ul>
<ul class="fyl-library nobullet"><h3 class="fyl-library-type">Subregional Library</h3>
<li class="fyl-library-name">Pretend Box Library</li>
<li class="fyl-library-address">PO Box 12</li>
<li class="fyl-library-city">Testville, VT 05000</li>
<li class="fyl-library-id"> <b>Library Code: </b>VT9B</li></ul>
</div></div></div></body></html>"""


def test_the_nls_page_gives_names_and_street_addresses_never_people(tmp_path):
    page = tmp_path / "find-your-library.html"
    page.write_text(NLS_PAGE, encoding="utf-8")
    out = tmp_path / "nls.csv"
    assert fetch.nls_to_csv([str(page)], str(out)) == 1           # the post-office-box library cannot be placed
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert rows == [{"code": "VT9A", "name": "Made-Up Regional Library for the Blind", "kind": "Regional Library",
                     "street": "10 Madeup St", "city": "Testville", "state": "VT", "zip": "05000"}]
    text = out.read_text(encoding="utf-8")
    assert "Jane Doe" not in text and "555" not in text


def test_nls_libraries_are_placed_by_the_geocoder(tmp_path):
    from test_federal_lists import vermont_with_nad
    folder = tmp_path / "nls"
    folder.mkdir()
    write_csv(folder / "nls.csv", ["code", "name", "kind", "street", "city", "state", "zip"],
              [["VT9A", "Made-Up Regional Library for the Blind", "Regional Library", "10 Madeup St", "Testville",
                "VT", "05000"],
               ["NH9A", "Elsewhere Library", "Regional Library", "10 Madeup St", "Testville", "NH", "05000"]])
    w = PackWriter(str(tmp_path / "n.osmpack"), 202611)
    assert tabular.read(str(folder), entry_of("nls-talking-book-libraries"), vermont_with_nad(tmp_path), w) == 1
    name, cls, kind = w.db.execute("SELECT name, cls, type FROM points").fetchone()
    assert (name, cls, kind) == ("Made-Up Regional Library for the Blind", "public", "braille and talking book library")


# ----------------------------------------------------------------------------------------------------- notes on places

def test_notes_lose_e_mail_addresses_and_telephone_numbers_and_are_cut():
    text = "Paved path, 5% slope. Call (555) 555-0100 or 555.555.0199 or write ranger.doe@example.gov first."
    note = tabular.clean_note(text, "Accessibility: ")
    assert note.startswith("Accessibility: Paved path, 5% slope.")
    assert "555" not in note and "@" not in note
    long = tabular.clean_note("word " * 1000)
    assert len(long) <= tabular.NOTE_LIMIT + 4 and long.endswith("...")
    assert tabular.clean_note("  ;  ") == ""


def test_blm_accessibility_descriptions_become_notes(tmp_path):
    e = entry_of("blm-accessible-recreation")
    path = write_csv(tmp_path / "acc.csv", ["FacilityID", "FacilityName", "Accessibility_Description",
                                            "ADA_Long_Description", "_lat", "_lon"],
                     [["1", "Made-Up Canyon Campground", "Accessible vault toilet", "Firm gravel path to the river",
                       "38.57", "-109.55"],
                      ["2", "Invented Overlook", "", "", "38.58", "-109.56"]])
    got = {p["name"]: p for p in read(e, path, "us-utah").points}
    assert got["Made-Up Canyon Campground"]["note"] == \
        "Accessibility: Accessible vault toilet; Firm gravel path to the river"
    assert got["Invented Overlook"]["note"] is None
    # In a real pack the note goes to the notes table, never to the name.
    w = PackWriter(str(tmp_path / "b.osmpack"), 202611)
    tabular.read(path, e, region("us-utah"), w)
    assert w.db.execute("SELECT count(*) FROM points WHERE note LIKE 'Accessibility:%'").fetchone()[0] == 1


def test_blm_sites_leave_out_toilets_campsites_and_bare_kinds(tmp_path):
    e = entry_of("blm-recreation-sites")
    assert "Toilet" not in e["fetch"]["where"] and "Campsite" not in e["fetch"]["where"]
    path = write_csv(tmp_path / "blm.csv", ["GlobalID", "FET_NAME", "FET_SUBTYPE", "_lat", "_lon"], [
        ["{1}", "Made-Up Wash Campground", "Campground", "38.57", "-109.55"],
        ["{2}", "Toilet", "Point of Interest", "38.58", "-109.56"],
        ["{3}", "Invented Rapid", "Rapid", "38.59", "-109.57"],
        ["{4}", "Pretend Site 4", "Toilet", "38.60", "-109.58"]])
    got = {p["name"]: (p["cls"], p["type"]) for p in read(e, path, "us-utah").points}
    assert got == {"Made-Up Wash Campground": ("park", "campground"), "Invented Rapid": ("nature", "rapid")}


# --------------------------------------------------------------------------------------- service areas (polygons)

def test_utility_service_areas_are_areas_of_a_class_never_said_as_a_place():
    for sid, tag in (("epa-water-service-areas", "water utility service area"),
                     ("electric-retail-territories", "electric utility service area")):
        e = entry_of(sid)
        assert e["kind"] == "areas" and e["cls"] == "region" and e["tag"] == tag
        assert e["fetch"]["simplify"] > 0 and e["columns"]["rings"] == "_rings"
    assert "region" in lookup.NOT_A_NAME


def test_a_water_service_area_is_written_with_its_type_and_found_by_areas_at(tmp_path):
    e = entry_of("epa-water-service-areas")
    ring = [[44.0, -72.0], [44.0, -71.9], [44.1, -71.9], [44.1, -72.0], [44.0, -72.0]]
    path = write_csv(tmp_path / "pws.csv", ["PWSID", "PWS_Name", "_lat", "_lon", "_rings"],
                     [["VT0000001", "MADEUPVILLE WATER DEPT", "44.05", "-71.95", json.dumps([ring])]])
    rec = read(e, path, "us-vermont")
    assert rec.areas[0]["name"] == "Madeupville Water Dept"
    assert rec.areas[0]["cls"] == "region" and rec.areas[0]["type"] == "water utility service area"
    assert rec.areas[0]["key"] == "epa-water-service-areas:VT0000001"
    # Written into a real pack: Finder.areas_at lists it, a lookup never names it.
    w = PackWriter(str(tmp_path / "us-vermont-extra.osmpack"), 202611)
    tabular.read(path, e, region("us-vermont"), w)
    w.finish({"region_id": "us-vermont", "state": "Vermont", "country": "United States", "part": "extra"})
    assert ("Madeupville Water Dept", "region") in [(a[0], a[1]) for a in
                                                     lookup.Finder(folder=str(tmp_path)).areas_at(44.05, -71.95)]


# ------------------------------------------------------------------------------------------- the other federal lists

def test_dme_suppliers_keep_organisations_never_practitioners(tmp_path):
    e = entry_of("cms-dme-suppliers")
    header = ["provider_id", "practicename", "businessname", "specialitieslist", "providertypelist",
              "participationbegindate", "latitude", "longitude"]
    path = write_csv(tmp_path / "dme.csv", header, [
        ["1", "MADEUP PHARMACY #1234", "MADEUP DRUG CO, INC", "Pharmacy|Optician", "", "2009-05-01", "44.26", "-72.58"],
        ["2", "", "INVENTED BRACE AND LIMB, LLC", "Orthotic Personnel|Prosthetic Personnel",
         "CERTIFIED ORTH/PROS/PEDORTHIST", "2015-02-03", "44.27", "-72.57"],
        ["3", "PRETEND FOOT AND ANKLE CENTER", "PRETEND FOOT AND ANKLE CENTER INC", "", "PHYSICIAN – PODIATRY",
         "2012-01-01", "44.28", "-72.56"],
        ["4", "JANE DOE OD", "JANE DOE OD", "Optometrist", "", "2010-01-01", "44.29", "-72.55"],
        ["5", "DOE, JOHN", "DOE, JOHN", "Medical Supply Company Other", "", "2011-01-01", "44.30", "-72.54"]])
    got = {p["name"]: p for p in read(e, path, "us-vermont").points}
    assert set(got) == {"Madeup Pharmacy", "Invented Brace and Limb"}
    assert got["Madeup Pharmacy"]["type"] == "pharmacy" and got["Madeup Pharmacy"]["first"] == 200905
    assert got["Invented Brace and Limb"]["type"] == "orthotics and prosthetics"
    assert e["fetch"]["method"] == "json_api" and "{code}" in json.dumps(e["fetch"]["params"])


def test_fire_registry_files_with_spaces_after_commas(tmp_path):
    e = entry_of("usfa-fire-stations")
    path = tmp_path / "usfa-registry-station.csv"
    path.write_text('FDID, Fire Dept Name, Station Name, Station Addr1, Station City, Station State, Station Zip\n'
                    '"99001","Madeup Volunteer Fire Company","Station #2","10 Madeup St","Testville","VT","05000"\n'
                    '"99002","Invented Fire District","Invented Fire District","12 Madeup St","Testville","VT",'
                    '"05000"\n', encoding="utf-8")
    rows = [r for t in tabular.open_texts(str(path)) for r in tabular.dict_rows(t, e)]
    assert rows[0]["Station State"] == "VT" and rows[0]["Fire Dept Name"] == "Madeup Volunteer Fire Company"
    names = [tabular.templated(e, r) for r in rows]
    from placepacks import types
    assert [types.rename(e, n) for n in names] == ["Madeup Volunteer Fire Company Station #2",
                                                   "Invented Fire District"]
    assert {"Station State", "Station Addr1", "Fire Dept Name"} <= split.needed_columns(e)


def test_bop_keeps_institutions_and_names_them_in_full(tmp_path):
    e = entry_of("bop-federal-prisons")
    path = write_csv(tmp_path / "bop.csv", ["code", "name", "type", "faclTypeDescription", "locationtype", "latitude",
                                            "longitude", "state"], [
        ["MAD", "Madeup", "FPC", "Federal Prison Camp", "inst", "37.72", "-80.65", "WV"],
        ["INV", "Invented", "FMC", "Federal Medical Center", "inst", "37.73", "-80.66", "WV"],
        ["RRX", "Pretend", "RRM", "Residential Reentry Office", "rrm", "37.74", "-80.67", "WV"]])
    got = {p["name"]: p["type"] for p in read(e, path, "us-west-virginia").points}
    assert got == {"Federal Prison Camp Madeup": "federal prison",
                   "Federal Medical Center Invented": "federal medical center (prison)"}
    assert "contactEmail" not in json.dumps(e) and "phoneNumber" not in json.dumps(e)


def test_border_crossings_close_after_their_last_month_of_traffic(tmp_path):
    e = entry_of("bts-border-crossings")
    path = write_csv(tmp_path / "bts.csv", ["key", "name", "state", "border", "first", "last", "latitude",
                                            "longitude"], [
        ["9901", "Madeup", "Vermont", "US-Canada Border", "1996-01-01T00:00:00.000", "2018-10-01T00:00:00.000",
         "44.99", "-72.10"],
        ["9902", "Invented", "Vermont", "US-Canada Border", "1996-01-01T00:00:00.000", "2026-10-01T00:00:00.000",
         "44.99", "-72.20"]])
    got = {p["name"]: (p["first"], p["last"]) for p in read(e, path, "us-vermont").points}
    assert got == {"Madeup Port of Entry": (199601, 201810), "Invented Port of Entry": (199601, None)}


def test_bike_share_stations_get_their_years_from_the_yearly_rows(tmp_path):
    e = entry_of("ntad-bikeshare")
    path = write_csv(tmp_path / "bike.csv", ["FAC_ID", "SYSTEM_NAME", "STATION_NAME", "ASOFDATE", "_lat", "_lon"], [
        ["VT1", "Madeup Bikes", "Main St", "201812", "44.48", "-73.21"],
        ["VT1", "Madeup Bikes", "Main St", "202507", "44.48", "-73.21"],
        ["VT2", "Madeup Bikes", "Pretend Ave", "201812", "44.49", "-73.22"],
        ["VT2", "Madeup Bikes", "Pretend Ave", "202207", "44.49", "-73.22"]])
    got = {p["name"]: (p["first"], p["last"]) for p in read(e, path, "us-vermont").points}
    assert got == {"Madeup Bikes station at Main St": (201812, None),
                   "Madeup Bikes station at Pretend Ave": (201812, 202207)}


def test_other_airports_are_institutional_or_closed_never_private_owners(tmp_path):
    e = entry_of("faa-other-airports")
    where = e["fetch"]["where"]
    assert "FACILITY_USE_CODE = 'PR' AND (" in where and "%HOSP%" in where and "ARPT_STATUS <> 'O'" in where
    path = write_csv(tmp_path / "faa.csv", ["ARPT_ID", "ARPT_NAME", "SITE_TYPE_CODE", "ARPT_STATUS",
                                            "ACTIVATION_DATE", "LAST_INSPECTION", "LAST_INFO_RESPONSE", "_lat",
                                            "_lon"], [
        ["9VT1", "MADEUP MEDICAL CENTER", "H", "O", "1990/04", "", "2022/03/03", "44.26", "-72.58"],
        ["9VT2", "INVENTED MUNI", "A", "CI", "1940/04", "2022/06/10", "", "44.27", "-72.57"]])
    got = {p["name"]: (p["type"], p["first"], p["last"]) for p in read(e, path, "us-vermont").points}
    assert got == {"Madeup Medical Center": ("heliport", 199004, None),
                   "Invented Muni": ("airport", 194004, 202206)}


# --------------------------------------------------------------------------------------------- the other state lists

def test_florida_lottery_kinds_and_new_york_lottery_store_numbers(tmp_path):
    e = entry_of("fl-lottery-terminals")
    assert e["licence"] == "FL-public-records" and e["fetch"]["where"] == "STATUS = 'Active'"
    assert tabular.class_of(e, "Convenience Store - With gas pumps") == ("business", "gas station")
    assert tabular.class_of(e, "Lottery/Brightstar") == ("", "")
    n = entry_of("ny-lottery-retailers")
    path = write_csv(tmp_path / "ny.csv", ["key", "name", "point"], [
        ["1", "MADEUP MART #4521", "POINT (-73.75 42.65)"], ["2", "Doe, Jane", "POINT (-73.76 42.66)"]])
    assert [p["name"] for p in read(n, path, "us-new-york").points] == ["Madeup Mart"]


def test_state_health_facilities_types_and_opening_dates(tmp_path):
    e = entry_of("ny-health-facilities")
    path = write_csv(tmp_path / "nyh.csv", ["key", "name", "kind", "first", "latitude", "longitude"], [
        ["1", "Made-Up Hospital", "Hospital", "1901-01-01T00:00:00.000", "42.65", "-73.75"],
        ["2", "Invented Adult Home", "Adult Home", "1985-06-01T00:00:00.000", "42.66", "-73.76"],
        ["3", "Pretend Home Care", "Licensed Home Care Services Agency", "2001-01-01T00:00:00.000", "42.67", "-73.77"],
        ["4", "Pretend Hospice", "Hospice", "2001-01-01T00:00:00.000", "42.68", "-73.78"],
        ["5", "Made-Up School Clinic", "School Based Hospital Extension Clinic", "2001-01-01T00:00:00.000", "42.69",
         "-73.79"]])
    got = {p["name"]: (p["type"], p["first"]) for p in read(e, path, "us-new-york").points}
    assert got == {"Made-Up Hospital": ("hospital", 190101), "Invented Adult Home": ("adult home", 198506)}
    ia = entry_of("ia-health-facilities")
    assert tabular.class_of(ia, "Assisted Living Programs") == ("public", "assisted living residence")
    assert tabular.class_of(ia, "RCF 3-5 Bed ID/MI/DD/BI") == ("", "")
    assert tabular.class_of(ia, "Hospice") == ("", "")


def test_connecticut_nursing_registry_keeps_former_names_with_their_years():
    e = entry_of("ct-nursing-facilities")
    q = e["fetch"]["queries"][0]
    assert "min(reporting_year) AS first" in q["select"] and "facility_name" in q["group"]
    assert e["aggregate"] and e["still_open_months"] >= 24


def test_kentucky_trailheads_are_named_by_their_trail(tmp_path):
    e = entry_of("ky-trailheads")
    path = write_csv(tmp_path / "ky.csv", ["OBJECTID", "TRAIL_NAME", "_lat", "_lon"], [
        ["1", "MADEUP TRACE", "37.10", "-84.10"], ["2", "INVENTED TRAILHEAD", "37.11", "-84.11"]])
    assert sorted(p["name"] for p in read(e, path, "us-kentucky").points) == ["Invented Trailhead",
                                                                             "Madeup Trace Trailhead"]
    for sid in ("ky-fishing-access", "ky-wildlife-management-areas", "ky-trailheads", "ct-deep-property-access",
                "ia-health-facilities"):
        assert entry_of(sid)["licence"] == "CC0-1.0", sid
    assert entry_of("utah-boat-ramps")["licence"] == "CC-BY-4.0"
