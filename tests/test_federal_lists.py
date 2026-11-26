"""The three national US government lists added in November 2026: NCUA credit union offices, CMS NPPES health care
organisations and the DOE Alternative Fuels Data Center's stations. Each is read once by the prepare job and split
per state. The tests check the catalogue entries, the newest NCUA quarter being chosen, NPPES's filters
(organisations only, never individual providers, the taxonomy allowlist, deactivated NPIs left out, the
practice address and the "Doing Business As" name, no official's name or telephone number kept), the API key sent
in a header for the AFDC (never in the address or the version), and the readers' output. Every name, number and
place here is made up."""

import csv
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, split  # noqa: E402
from placepacks.readers import tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
NEW = ("ncua-credit-union-branches", "cms-nppes-organisations", "afdc-fuel-stations")


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def nad_slice(folder):
    """A NAD-like slice of Madeup St in Testville (ZIP 05000): two shops and one home."""
    path = folder / "nad.txt"
    path.write_text("AddNo_Full,StNam_Full,Post_City,Inc_Muni,State,Zip_Code,Addr_Type,Latitude,Longitude\n"
                    "10,MADEUP ST,Testville,,VT,05000,Commercial,44.0001,-72.0001\n"
                    "12,MADEUP ST,Testville,,VT,05000,Residential,44.0003,-72.0003\n"
                    "14,MADEUP ST,Testville,,VT,05000,Commercial,44.0005,-72.0005\n", encoding="utf-8")
    return str(path)


def vermont_with_nad(tmp_path):
    """The Vermont region with the made-up NAD slice as its address points."""
    region = dict(catalogue.regions()[VT])
    region["_inputs"] = {"nad": nad_slice(tmp_path)}
    return region


def points(writer):
    """{name: (key, cls, tag, type, lat, first, last, brand)} of a pack's points."""
    return {r[0]: r[1:] for r in writer.db.execute(
        "SELECT name, key, cls, tag, type, lat, first, last, brand FROM points").fetchall()}


def everything(writer):
    """Every value of every point, as one text (to look for something that must not be there)."""
    return " ".join(str(v) for r in writer.db.execute("SELECT * FROM points").fetchall() for v in r)


# ---------------------------------------------------------------------------------------------------- the catalogue

def test_the_three_lists_are_national_sources_split_per_state_with_open_licences():
    """Each is accepted, national (read once by the prepare job), split by its state column, with a licence the
    catalogue allows; the AFDC's terms are described as a licence of their own."""
    cat = catalogue.load()
    assert catalogue.check(cat) == []
    for sid in NEW:
        e = entry_of(sid)
        assert e["part"] == "businesses" and e["countries"] == ["US"] and e["licence"] in catalogue.ALLOWED, sid
        assert e["fetch"]["method"] == "national" and e["filter"]["equals"] == "{code}", sid
        assert e["filter"]["column"] in split.needed_columns(e) and e["history"] and e["notes"], sid
    assert entry_of("ncua-credit-union-branches")["licence"] == "US-Government-Work"
    assert entry_of("cms-nppes-organisations")["licence"] == "US-Government-Work"
    terms = cat["licences"][entry_of("afdc-fuel-stations")["licence"]]
    assert "any purpose whatsoever" in terms["name"] and terms["url"].startswith("https://developer.nlr.gov/")


def test_the_address_only_lists_keep_their_address_columns_for_the_geocoder():
    """NCUA and NPPES have addresses only: located against the NAD, so their split slices keep the address
    columns; the NCUA's mailing address and telephone are never kept."""
    for sid in ("ncua-credit-union-branches", "cms-nppes-organisations"):
        e = entry_of(sid)
        spec = e["geocode"]
        assert spec["from"] == "nad" and {spec["street"], spec["city"], spec["zip"]} <= split.needed_columns(e)
    keep = split.needed_columns(entry_of("ncua-credit-union-branches"))
    assert not any(c.startswith("Mailing") or c == "PhoneNumber" for c in keep)


def test_the_nppes_allowlist_has_a_plain_name_for_every_code_and_leaves_the_rest_out():
    """Every allowed taxonomy has a plain name; hospitals (covered by other layers), federally qualified health
    centres (the HRSA layer), mail-order pharmacies, home health agencies, nursing homes and individual-only kinds
    such as nurses are not allowed."""
    e = entry_of("cms-nppes-organisations")
    assert set(e["allowlist_names"]) == set(e["class_map"]) - {"*"} and e["class_map"]["*"] == ""
    assert all(e["allowlist_names"].values())
    allowed = {"3336C0003X": "pharmacy", "261QU0200X": "urgent care", "1223G0001X": "dentist",
               "152W00000X": "optometrist", "332S00000X": "hearing aid shop", "225100000X": "physical therapy",
               "291U00000X": "medical laboratory", "332B00000X": "medical supply store", "111N00000X": "chiropractor"}
    for code, tag in allowed.items():
        assert tabular.class_of(e, code) == ("business", tag), code
    for code in ("282N00000X", "261QF0400X", "3336M0002X", "251E00000X", "314000000X", "163W00000X", ""):
        assert tabular.class_of(e, code) == ("", ""), code


# ----------------------------------------------------------------------------------------------------------- NCUA

def test_the_newest_ncua_quarter_is_chosen_from_the_listing():
    """The listing links every quarterly zip since the 1990s; the newest (year and month together) is chosen."""
    page = ('<a href="/files/publications/analysis/call-report-data-2025-12.zip">x</a>'
            '<a href="/files/publications/analysis/call-report-data-2026-03.zip">x</a>'
            '<a href="/files/publications/analysis/call-report-data-2026-06.zip">x</a>'
            '<a href="/files/publications/analysis/call-report-data-1999-09.zip">x</a>')

    class Page(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    files = fetch.national_files(entry_of("ncua-credit-union-branches"), {}, opener=lambda url: Page(page.encode()))
    assert files == [("https://ncua.gov/files/publications/analysis/call-report-data-2026-06.zip",
                      "call-report-data-2026-06.zip", None)]


NCUA_HEADER = ("CU_NUMBER,CYCLE_DATE,JOIN_NUMBER,SiteId,CU_NAME,SiteName,SiteTypeName,MainOffice,PhysicalAddressLine1,"
               "PhysicalAddressLine2,PhysicalAddressCity,PhysicalAddressStateCode,PhysicalAddressPostalCode,"
               "PhysicalAddressCountyName2,PhysicalAddressCountry,MailingAddressLine1,MailingAddressLine2,"
               "MailingAddressCity,MailingAddressStateCode,MailingAddressStateName,MailingAddressPostalCode,"
               "PhoneNumber,HoursOfOperation,MemberServices,ATM,DriveThru,Shrd_Serv_Cntr_Net\n")


def test_credit_union_offices_are_named_typed_keyed_and_located_by_their_physical_address(tmp_path):
    """Each office under its credit union's name ("Credit Union" added to NCUA's short form, "CU" written out),
    class business, tag bank, type credit union, keyed by charter and site number (site numbers repeat across
    credit unions), located by the physical address; another state's office is left out; the telephone number,
    the office's own name and the mailing address are nowhere in the pack."""
    z = tmp_path / "call-report-data-2026-06.zip"
    with zipfile.ZipFile(z, "w") as out:
        out.writestr("Credit Union Branch Information.txt", NCUA_HEADER +
                     '1,6/30/2026 0:00:00,2,500,"MADEUP VALLEY",HEADQUARTERS,Corporate Office,Yes,10 MADEUP ST,,'
                     'TESTVILLE,VT,05000,Madeup,United States,PO BOX 99,,ELSEWHERE,VT,Vermont,05999,8025550100,'
                     'M-F,1,1,0,0\n'
                     '2,6/30/2026 0:00:00,3,500,"PRETEND TEACHERS CU",Downtown Branch,Branch Office,No,'
                     '14 MADEUP ST,,TESTVILLE,VT,05000-1234,Madeup,United States,14 MADEUP ST,,TESTVILLE,VT,Vermont,'
                     '05000,8025550101,,1,1,0,0\n'
                     '3,6/30/2026 0:00:00,4,501,"INVENTED FCU",Main Office,Corporate Office,Yes,10 MADEUP ST,,'
                     'TESTVILLE,NH,05000,Madeup,United States,10 MADEUP ST,,TESTVILLE,NH,New Hampshire,05000,'
                     '6035550102,,1,1,0,0\n')
        out.writestr("FS220.txt", "CU_NUMBER,ACCT_010\n1,999\n")
    w = PackWriter(str(tmp_path / "n.osmpack"), 202611)
    entry = entry_of("ncua-credit-union-branches")
    assert tabular.read(str(z), entry, vermont_with_nad(tmp_path), w) == 2
    got = points(w)
    assert set(got) == {"Madeup Valley Credit Union", "Pretend Teachers Credit Union"}
    valley = got["Madeup Valley Credit Union"]
    assert valley[0] == "ncua-credit-union-branches:1 500" and valley[1:4] == ("business", "bank", "credit union")
    assert valley[4] == 44000100 and valley[5] == 202611              # at the physical address; from this build
    assert got["Pretend Teachers Credit Union"][0] == "ncua-credit-union-branches:2 500"
    text = everything(w)
    assert "5550100" not in text and "Headquarters" not in text and "Downtown" not in text and "Box" not in text


def test_ncua_short_names_become_full_credit_union_names():
    """NCUA's 35-character names: "Credit Union" added unless the name has it, "FCU" and "CU" written out, a
    "doing business as" name preferred, ", A", ", Inc." and a "(1234)" number dropped."""
    e = entry_of("ncua-credit-union-branches")
    from placepacks import types
    for raw, want in (("WINGS", "Wings Credit Union"), ("NAVY FEDERAL CREDIT UNION", "Navy Federal Credit Union"),
                      ("CREDIT UNION OF MADEUP, A", "Credit Union Of Madeup"),
                      ("PRETEND FED CREDIT UNION (3226)", "Pretend Fed Credit Union"),
                      ("INVENTED FCU", "Invented Federal Credit Union"),
                      ("MADEUP COMMUNITY CU D.B.A. ZING CU", "Zing Credit Union"),
                      ("POST OFFICE CU OF MADEUP, INC.", "Post Office Credit Union Of Madeup")):
        assert types.rename(e, tabular.smart_case(raw)) == want, raw


# ---------------------------------------------------------------------------------------------------------- NPPES

def nppes_header():
    """The NPPES columns the converter reads, a few it must never keep, and two of the fifteen taxonomy slots."""
    cols = list(fetch.NPPES_FIELDS.values())
    cols[2:2] = ["Provider Last Name (Legal Name)", "Provider First Name"]
    cols += ["Provider First Line Business Mailing Address", "Provider Business Mailing Address City Name",
             "Provider Business Practice Location Address Telephone Number", "Authorized Official Last Name",
             "Authorized Official First Name", "Authorized Official Telephone Number",
             "Healthcare Provider Taxonomy Code_1", "Healthcare Provider Primary Taxonomy Switch_1",
             "Healthcare Provider Taxonomy Code_2", "Healthcare Provider Primary Taxonomy Switch_2"]
    return cols


def nppes_row(cols, **values):
    """One NPPES row: the given columns by their short names (fetch.NPPES_FIELDS keys or the full names)."""
    full = {**{fetch.NPPES_FIELDS.get(k, k): v for k, v in values.items()}}
    return [full.get(c, "") for c in cols]


def nppes_zip(path):
    """A made-up NPPES monthly zip: the data file (every field quoted, as CMS writes it), its header file, and the
    Other Name Reference File."""
    cols = nppes_header()
    base = dict(country="US", state="VT", city="TESTVILLE", zip="050001234", enumerated="03/15/2010")
    tax = "Healthcare Provider Taxonomy Code_1"
    primary = "Healthcare Provider Primary Taxonomy Switch_1"
    rows = [
        # A person (entity type 1), a pharmacist at a pharmacy: never read.
        nppes_row(cols, npi="1000000001", entity="1", **{"Provider Last Name (Legal Name)": "DOE",
                                                          "Provider First Name": "JANE"}, street="10 MADEUP ST",
                  **base, **{tax: "3336C0003X", primary: "Y"}),
        # A retail pharmacy whose shop name is in the Other Name Reference File ("6"); the official and the
        # telephone numbers must not be kept.
        nppes_row(cols, npi="1000000002", entity="2", legal="MADEUP DRUG HOLDINGS LLC", other_type="6",
                  street="10 MADEUP ST", **base, **{tax: "3336C0003X", primary: "Y",
                                                    "Authorized Official Last Name": "ROE",
                                                    "Authorized Official First Name": "RICHARD",
                                                    "Authorized Official Telephone Number": "8025550199",
                                                    "Provider Business Practice Location Address Telephone Number":
                                                        "8025550198",
                                                    "Provider First Line Business Mailing Address": "PO BOX 7"}),
        # A dental practice with its DBA in the main file, at the street's home address.
        nppes_row(cols, npi="1000000003", entity="2", legal="PRETEND DENTAL GROUP PC", other="SMILE PRETEND",
                  other_type="3", street="12 MADEUP ST", **base, **{tax: "1223G0001X", primary: "Y"}),
        # A hospital that also lists a pharmacy: only the primary taxonomy counts, and hospitals are left out.
        nppes_row(cols, npi="1000000004", entity="2", legal="INVENTED GENERAL HOSPITAL", street="14 MADEUP ST",
                  **base, **{tax: "282N00000X", primary: "Y", "Healthcare Provider Taxonomy Code_2": "3336C0003X",
                             "Healthcare Provider Primary Taxonomy Switch_2": "N"}),
        # A mail-order pharmacy: not a storefront.
        nppes_row(cols, npi="1000000005", entity="2", legal="PRETEND MAIL RX INC", street="14 MADEUP ST", **base,
                  **{tax: "3336M0002X", primary: "Y"}),
        # A deactivated NPI as CMS writes it: only the number and the date.
        nppes_row(cols, npi="1000000006", deactivated="10/01/2026"),
        # An organisation deactivated (no reactivation), and one reactivated afterwards.
        nppes_row(cols, npi="1000000007", entity="2", legal="GONE URGENT CARE LLC", street="14 MADEUP ST", **base,
                  deactivated="05/01/2025", **{tax: "261QU0200X", primary: "Y"}),
        nppes_row(cols, npi="1000000008", entity="2", legal="BACK AGAIN URGENT CARE", street="14 MADEUP ST",
                  deactivated="05/01/2025", reactivated="06/01/2025",
                  **{**base, "enumerated": "08/20/2007"}, **{tax: "261QU0200X", primary: "Y"}),
        # Practice location abroad; and one in an apartment (often a home).
        nppes_row(cols, npi="1000000009", entity="2", legal="FAR AWAY OPTICAL", street="1 RUE INVENTEE",
                  **{**base, "country": "FR"}, **{tax: "156FX1800X", primary: "Y"}),
        nppes_row(cols, npi="1000000010", entity="2", legal="SOFA MEDICAL SUPPLY LLC", street="12 MADEUP ST APT 3",
                  **base, **{tax: "332B00000X", primary: "Y"}),
        # Another state's hearing aid shop: kept in the CSV, left out of Vermont by the state filter.
        nppes_row(cols, npi="1000000011", entity="2", legal="INVENTED HEARING AIDS", street="14 MADEUP ST",
                  **{**base, "state": "NH"}, **{tax: "332S00000X", primary: "Y"}),
    ]
    data = io.StringIO()
    w = csv.writer(data, quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(cols)
    w.writerows(rows)
    others = io.StringIO()
    o = csv.writer(others, quoting=csv.QUOTE_ALL, lineterminator="\n")
    o.writerow(["NPI", "Provider Other Organization Name", "Provider Other Organization Name Type Code",
                "Created Date"])
    o.writerow(["1000000002", "OLD MADEUP NAME", "4", "01/01/2012"])          # a former name: never used
    o.writerow(["1000000002", "MADEUP PHARMACY", "3", "01/01/2015"])
    o.writerow(["1000000004", "INVENTED OUTPATIENT RX", "3", "01/01/2015"])   # not kept: a hospital
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("npidata_pfile_20050523-20261109.csv", data.getvalue())
        z.writestr("npidata_pfile_20050523-20261109_fileheader.csv", ",".join(f'"{c}"' for c in cols) + "\n")
        z.writestr("othername_pfile_20050523-20261109.csv", others.getvalue())
        z.writestr("pl_pfile_20050523-20261109.csv", '"NPI"\n')
    return str(path)


def test_nppes_keeps_only_storefront_organisations_never_people(tmp_path):
    """The converter keeps active organisations (entity type 2) in the US whose primary taxonomy is allowed (the
    apartment rule is the reader's, below); people, hospitals, mail-order pharmacies, deactivated NPIs and places
    abroad are left out; the DBA name is used (never a former name); no person's name and no telephone number is
    written."""
    z = nppes_zip(tmp_path / "NPPES_Data_Dissemination_November_2026_V2.zip")
    out = tmp_path / "out.csv"
    assert fetch.nppes_to_csv(z, str(out), entry_of("cms-nppes-organisations")) == 5
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert list(rows[0]) == fetch.NPPES_OUT
    by_npi = {r["NPI"]: r for r in rows}
    assert set(by_npi) == {"1000000002", "1000000003", "1000000008", "1000000010", "1000000011"}
    assert by_npi["1000000002"]["name"] == "MADEUP PHARMACY" and by_npi["1000000002"]["street"] == "10 MADEUP ST"
    assert by_npi["1000000003"]["name"] == "SMILE PRETEND" and by_npi["1000000003"]["zip"] == "05000"
    text = out.read_text(encoding="utf-8")
    for never in ("DOE", "JANE", "ROE", "RICHARD", "555", "PO BOX", "OLD MADEUP", "HOSPITAL", "MAIL RX", "GONE",
                  "FAR AWAY"):
        assert never not in text, never


def test_nppes_places_are_located_typed_and_dated_from_their_enumeration(tmp_path):
    """The reader: Vermont's rows only, LLC/PC/Inc removed from names, typed by the allowlist's plain names,
    located by the practice address (a home address on its street, never at the house), dated from the NPI's
    enumeration; a practice in an apartment is left out."""
    z = nppes_zip(tmp_path / "NPPES_Data_Dissemination_November_2026_V2.zip")
    out = tmp_path / "nppes" / "cms-nppes-organisations.csv"
    out.parent.mkdir()
    entry = entry_of("cms-nppes-organisations")
    fetch.nppes_to_csv(z, str(out), entry)
    w = PackWriter(str(tmp_path / "p.osmpack"), 202611)
    assert tabular.read(str(out.parent), entry, vermont_with_nad(tmp_path), w) == 3
    got = points(w)
    assert set(got) == {"Madeup Pharmacy", "Smile Pretend", "Back Again Urgent Care"}
    assert got["Madeup Pharmacy"][:5] == ("cms-nppes-organisations:1000000002", "business", "pharmacy", "pharmacy",
                                          44000100)
    assert got["Madeup Pharmacy"][5] == 201003
    assert got["Smile Pretend"][2] == "dentist" and got["Smile Pretend"][4] == 44000300     # the street's middle
    assert got["Back Again Urgent Care"][2] == "urgent care" and got["Back Again Urgent Care"][5] == 200708
    from placepacks import types
    assert types.rename(entry, "Made-up Drug Holdings, L.L.C.") == "Made-up Drug Holdings"
    assert types.rename(entry, "Pretend Dental Group PC") == "Pretend Dental Group"


def test_the_nppes_zip_waits_on_the_larger_disk_and_is_deleted_once_read(monkeypatch, tmp_path):
    """prepare_national downloads the month's zip into PLACEPACKS_SCRATCH, writes national/<id>/<id>.csv and its
    version, deletes the zip, and keeps the CSV while the month's address is the same."""
    sample = nppes_zip(tmp_path / "sample.zip")
    scratch = tmp_path / "mnt"
    scratch.mkdir()
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(scratch))
    url = "https://download.cms.gov/nppes/NPPES_Data_Dissemination_November_2026_V2.zip"
    monkeypatch.setattr(fetch, "national_files", lambda entry, values: [(url, os.path.basename(url), None)])
    got = []

    def fake_download(address, target, pause=0, waits=(), sleep=None, headers=None):
        assert os.path.dirname(os.path.dirname(target)) == str(scratch)
        got.append(address)
        with open(sample, "rb") as src, open(target, "wb") as dst:
            dst.write(src.read())
        return "v", ""
    monkeypatch.setattr(fetch, "download", fake_download)
    national = tmp_path / "national"
    entry = entry_of("cms-nppes-organisations")
    fetch.prepare_national(entry, str(national), {})
    folder = national / "cms-nppes-organisations"
    assert sorted(os.listdir(folder)) == ["cms-nppes-organisations.csv", "cms-nppes-organisations.csv.version"]
    assert (folder / "cms-nppes-organisations.csv.version").read_text() == url
    assert os.listdir(scratch) == [] and got == [url]
    fetch.prepare_national(entry, str(national), {})          # the same month: not downloaded again
    assert got == [url]


# ----------------------------------------------------------------------------------------------------------- AFDC

def test_the_afdc_key_comes_from_the_secret_or_the_demo_key(monkeypatch):
    """NREL_API_KEY when it is set, else DEMO_KEY; always in the X-Api-Key header, never in the address."""
    f = entry_of("afdc-fuel-stations")["fetch"]
    assert "api_key" not in f["url"] and "status=E" in f["url"] and "access=public" in f["url"]
    monkeypatch.delenv("NREL_API_KEY", raising=False)
    assert fetch.key_headers(f) == {"X-Api-Key": "DEMO_KEY"}
    monkeypatch.setenv("NREL_API_KEY", "  made-up-key  ")
    assert fetch.key_headers(f) == {"X-Api-Key": "made-up-key"}
    assert fetch.key_headers({"method": "national"}) == {}


def test_the_afdc_key_is_sent_in_a_header_and_never_written(monkeypatch, tmp_path):
    """prepare_national sends the key in the header; the version stamp holds the download's version, not the key."""
    monkeypatch.setenv("NREL_API_KEY", "made-up-secret-key")
    seen = {}

    def fake_download(address, target, pause=0, waits=(), sleep=None, headers=None):
        seen.update(address=address, headers=headers)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("ID,State\n1,VT\n")
        return '"etag-1"', ""
    monkeypatch.setattr(fetch, "download", fake_download)
    fetch.prepare_national(entry_of("afdc-fuel-stations"), str(tmp_path), {})
    assert seen["headers"] == {"X-Api-Key": "made-up-secret-key"} and "made-up-secret" not in seen["address"]
    folder = tmp_path / "afdc-fuel-stations"
    assert sorted(os.listdir(folder)) == ["afdc-stations.csv", "afdc-stations.csv.version"]
    assert (folder / "afdc-stations.csv.version").read_text() == '"etag-1"'


AFDC_HEADER = ("Fuel Type Code,Station Name,Street Address,City,State,ZIP,Station Phone,Status Code,EV Network,"
               "Latitude,Longitude,ID,Open Date,Access Code,Facility Type\n")


def test_afdc_stations_are_classed_typed_branded_and_dated(tmp_path):
    """Electric stations are charging stations with their network as the brand (codes made plain names; a
    non-networked charger has none, an unknown code is tidied); other fuels are fuel stations typed by the fuel;
    each is dated from its open date (a propane station without one starts at the first build); another state's
    station is left out; telephone numbers are not kept."""
    path = tmp_path / "afdc-stations.csv"
    path.write_text(AFDC_HEADER +
                    "ELEC,Madeup Library,1 Madeup St,Testville,VT,05000,802-555-0100,E,eVgo Network,44.0,-72.0,"
                    "101,2019-05-01,public,LIBRARY\n"
                    "ELEC,Pretend Inn,2 Madeup St,Testville,VT,05000,,E,Non-Networked,44.001,-72.0,102,2021-07-15,"
                    "public,HOTEL\n"
                    "ELEC,Invented Grocery,3 Madeup St,Testville,VT,05000,,E,MADEUP_VOLTS,44.002,-72.0,103,"
                    "2023-01-09,public,GROCERY\n"
                    "LPG,Made-Up Propane,4 Madeup St,Testville,VT,05000,802-555-0101,E,,44.003,-72.0,104,,public,\n"
                    "E85,Pretend Fuel,5 Madeup St,Testville,VT,05000,,E,,44.004,-72.0,105,2008-03-01,public,\n"
                    "ELEC,Other State Charger,1 Made St,Elsewhere,NH,03000,,E,Tesla,44.005,-72.0,106,2020-01-01,"
                    "public,\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "a.osmpack"), 202611)
    assert tabular.read(str(path), entry_of("afdc-fuel-stations"), dict(catalogue.regions()[VT]), w) == 5
    got = points(w)
    assert got["Madeup Library"][:4] == ("afdc-fuel-stations:101", "business", "charging station",
                                         "charging station")
    assert got["Madeup Library"][5:] == (201905, 202611, "EVgo|")
    assert got["Pretend Inn"][7] is None and got["Invented Grocery"][7] == "Madeup Volts|"
    assert got["Made-Up Propane"][1:4] == ("business", "fuel", "propane station")
    assert got["Made-Up Propane"][5] == 202611                          # no open date: from this build
    assert got["Pretend Fuel"][3] == "e85 ethanol station" and got["Pretend Fuel"][5] == 200803
    assert "Other State Charger" not in got and "555" not in everything(w)


def test_the_prepare_step_gets_the_nrel_key_from_a_secret_with_read_only_permissions():
    """The secret is given to the prepare step only, and the workflow stays read-only by default."""
    import yaml
    flow = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8"))
    assert flow["permissions"] == {"contents": "read"} and "permissions" not in flow["jobs"]["prepare"]
    step = next(s for s in flow["jobs"]["prepare"]["steps"] if s.get("name") == "Download and split the national files")
    assert step["env"]["NREL_API_KEY"] == "${{ secrets.NREL_API_KEY }}"
    text = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert text.count("secrets.NREL_API_KEY") == 1
