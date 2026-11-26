"""The US business sources of the November 2026 pass (Texas, Pennsylvania, Florida, New York, Connecticut and city
lists) and the reader behaviour they brought: the owner's-name privacy rule (a sole proprietor trading under their
own name is left out, the owner's name is never kept), keys stored as fingerprints (Texas taxpayer numbers), a large
state Socrata dataset fetched once by the prepare job and split per state, the address columns kept in a split slice
for the geocoder, and TIGER address ranges matched by ZIP code (Maryland, which the NAD leaves out). Every name,
number and place here is made up."""

import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, geocode, split  # noqa: E402
from placepacks.readers import tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
NEW = {"tx-sales-tax-outlets", "tx-mixed-beverage-permits", "tx-tobacco-retailers", "tx-hotel-tax-permits",
       "pa-sales-tax-licences", "pa-tobacco-licences", "fl-food-service", "fl-alcohol-licences", "fl-tobacco-dealers",
       "ny-retail-food-stores", "ny-tobacco-retailers", "ny-dmv-facilities", "ny-appearance-enhancement",
       "ny-cannabis-retailers", "ny-wic-vendors", "ct-state-licences", "ct-auto-dealers-repairers",
       "baton-rouge-businesses", "san-diego-county-food-facilities", "nola-occupational-licences",
       "nola-alcohol-outlets", "baltimore-liquor-licences", "sacramento-county-business-licences",
       "wake-county-restaurants", "cambridge-food-and-tobacco-permits", "dc-abca-liquor-licences",
       "sioux-falls-liquor-licences", "arlington-tx-food-establishments"}
# Columns that would carry a person's details: never downloaded, except a legal name read only to compare (the
# entry's "owner_column").
PERSONAL = re.compile(r"tp_name|tp_address|phone|email|e_mail|contact|applicant|licenseefirst|licenseelast|"
                      r"mail_?address|ownername|owner_name|license_holder_name|permit_owner", re.I)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def selected_columns(entry):
    """The source columns a fetch downloads: each Socrata query's $select (the expressions before AS) or the
    ArcGIS fields."""
    f = entry["fetch"]
    if f.get("queries"):
        out = []
        for q in f["queries"]:
            for part in re.split(r",(?![^(]*\))", q["select"]):
                out.append(re.split(r"\s+AS\s+", part.strip(), flags=re.I))
        return out
    if f.get("fields"):
        return [[c.strip(), c.strip()] for c in f["fields"].split(",")]
    return []


def test_the_new_sources_are_in_the_catalogue_with_their_licences_and_regions():
    """All 28 sources are accepted with an allowed licence, regions that exist and a privacy note; Florida's public
    records and Baltimore's CC BY 3.0 have their licence entries (CC BY 3.0 with its text); the old rejection that
    said Connecticut had only brand registrations is corrected."""
    cat = catalogue.load()
    assert catalogue.check(cat) == []
    by_id = {e["id"]: e for e in cat["accepted"]}
    assert NEW <= set(by_id)
    regions = catalogue.regions()
    for sid in NEW:
        e = by_id[sid]
        assert e["part"] == "businesses" and e["licence"] in catalogue.ALLOWED, sid
        assert e["regions"] and all(r in regions and not regions[r].get("parent") for r in e["regions"]), sid
        assert e["notes"] and e["history"], sid
    assert {by_id[s]["licence"] for s in NEW if s.startswith("fl-")} == {"FL-public-records"}
    assert "Chapter 119" in cat["licences"]["FL-public-records"]["name"]
    assert "Microdecisions" in cat["licences"]["FL-public-records"]["name"]
    assert by_id["baltimore-liquor-licences"]["licence"] == "CC-BY-3.0"
    text = open(os.path.join(ROOT, cat["licences"]["CC-BY-3.0"]["file"]), encoding="utf-8").read()
    assert "Attribution 3.0 Unported" in text
    assert by_id["sacramento-county-business-licences"]["licence"] == "CC-BY-4.0"
    names = " ".join(r["name"] + " " + r["reason"] for r in cat["rejected"])
    assert "Connecticut publishes brand registrations and suspensions only" not in names
    assert "Wake County/Raleigh" not in names and "ngch-56tr" in names


def test_no_new_source_downloads_a_persons_details():
    """No phone, e-mail, contact, applicant, mailing address or taxpayer name is downloaded; a legal or owner name
    is downloaded only to be compared by the reader (the entry's owner_column), never kept in the pack."""
    for sid in NEW:
        e = entry_of(sid)
        for expression, *alias in selected_columns(e):
            if PERSONAL.search(expression):
                assert alias and alias[-1] == e.get("owner_column") or expression == e.get("owner_column"), \
                    (sid, expression)
        if e.get("owner_column"):
            assert e["owner_column"] not in json.dumps(e["columns"]), sid       # compared, never a name or key


def test_texas_and_florida_are_read_once_and_split_per_state():
    """The large state lists are national sources (fetched once by the prepare job, not once per sub-region), split
    by their state column, located by the geocoder; their slices keep the address and owner columns."""
    for sid in ("tx-sales-tax-outlets", "tx-mixed-beverage-permits", "tx-tobacco-retailers", "tx-hotel-tax-permits",
                "fl-food-service", "fl-alcohol-licences", "fl-tobacco-dealers"):
        e = entry_of(sid)
        assert e["fetch"]["method"] == "national" and e["filter"]["equals"] == "{code}" and e["geocode"], sid
        keep = split.needed_columns(e)
        spec = e["geocode"]
        assert {spec["street"], spec["city"], spec["zip"], e["filter"]["column"]} <= keep, sid
        if e.get("owner_column"):
            assert e["owner_column"] in keep
    texas = entry_of("tx-sales-tax-outlets")["fetch"]["queries"][0]
    # The sole-owner rule is inside the portal's query: the taxpayer's name and address are compared there, never
    # selected.
    assert "org_type IN ('IS', 'PI')" in texas["where"] and "tp_name" not in texas["select"]


def test_owner_names_rule_tells_a_persons_name_from_a_trade_name():
    """A company is never a person; a trade name made of the owner's words, or with two of them, is the owner's own
    name; one shared word (a first name, a surname) leaves a trade name of its own."""
    assert tabular.is_company("Made-Up Diner L.L.C.") and tabular.is_company("INVENTED OIL CO.")
    assert not tabular.is_company("DOE JANE M") and not tabular.is_company("Jane Doe")
    assert tabular.owners_name("JANE DOE", "DOE JANE M")
    assert tabular.owners_name("Oscar E Garcia Torres", "Garcia Oscar Enriques")
    assert tabular.owners_name("Aaron S", "SCHWAB AARON M")
    assert not tabular.owners_name("Lisa's Nails", "THOMAS LISA J")
    assert not tabular.owners_name("Smith Market", "SMITH JOHN")
    assert not tabular.owners_name("Juventud Take Out", "ALVAREZ JOSE & JOSE M")


def test_a_sole_proprietor_under_their_own_name_is_left_out_and_owners_are_never_kept(tmp_path):
    """The New York salon list: a business named as its (person) holder is left out, one with a trade name of its
    own is kept, a company holder's same-named business is kept; the holders' names are nowhere in the pack."""
    entry = entry_of("ny-appearance-enhancement")
    entry["regions"] = [VT]
    (tmp_path / "salons.csv").write_text(
        "key,name,holder,point,first,last\n"
        "A1,JANE DOE,DOE JANE M,POINT (-72.0 44.0),01/03/2014,2029-05-29T00:00:00.000\n"
        "A2,MADE-UP NAILS,ROE ANNA,POINT (-72.0 44.001),2016-02-01T00:00:00.000,2029-05-29T00:00:00.000\n"
        "A3,INVENTED BARBERS,INVENTED BARBERS INC,POINT (-72.0 44.002),2018-03-01,2029-01-01\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "s.osmpack"), 202611)
    assert tabular.read(str(tmp_path / "salons.csv"), entry, dict(catalogue.regions()[VT]), w) == 2
    rows = sorted(w.db.execute("SELECT name, cls, tag, first FROM points").fetchall())
    assert rows == [("Invented Barbers", "business", "salon", 201803), ("Made-up Nails", "business", "salon", 201602)]
    everything = " ".join(str(v) for r in w.db.execute("SELECT * FROM points").fetchall() for v in r).upper()
    assert "DOE" not in everything and "ROE" not in everything


def nad_slice(folder):
    """A NAD-like slice of two shops and one home on Madeup St (ZIP 05000)."""
    path = folder / "nad.txt"
    path.write_text("AddNo_Full,StNam_Full,Post_City,Inc_Muni,State,Zip_Code,Addr_Type,Latitude,Longitude\n"
                    "10,MADEUP ST,Testville,,VT,05000,Commercial,44.0001,-72.0001\n"
                    "12,MADEUP ST,Testville,,VT,05000,Residential,44.0003,-72.0003\n"
                    "14,MADEUP ST,Testville,,VT,05000,Commercial,44.0005,-72.0005\n", encoding="utf-8")
    return str(path)


def test_texas_outlets_are_typed_located_dated_and_keyed_by_a_fingerprint(tmp_path):
    """The Texas outlets: only the region's state, typed by NAICS (a caterer and a non-storefront type left out),
    located against the NAD (a home address on its street, positions in microdegrees), dated from the first sale to the out-of-business date, and keyed by a fingerprint,
    so the taxpayer number is nowhere in the pack."""
    entry = entry_of("tx-sales-tax-outlets")
    entry["regions"] = [VT]
    region = dict(catalogue.regions()[VT])
    region["_inputs"] = {"nad": nad_slice(tmp_path)}
    (tmp_path / "tx.csv").write_text(
        "key,name,naics,street,city,zip,state,first,last\n"
        "19990000001-1,MADE-UP TACOS,722513,10 MADEUP ST,TESTVILLE,05000,VT,1998-04-01T00:00:00.000,\n"
        "29990000002-1,PRETEND HARDWARE,444140,12 Madeup Street,TESTVILLE,05000-1111,VT,2001-02-01,2015-06-30\n"
        "39990000003-1,INVENTED CATERING,722320,14 MADEUP ST,TESTVILLE,05000,VT,2010-01-01,\n"
        "49990000004-1,FICTIONAL CONSULTING,541611,14 MADEUP ST,TESTVILLE,05000,VT,2010-01-01,\n"
        "59990000005-1,OTHER STATE SHOP,448120,14 MADEUP ST,TESTVILLE,05000,NH,2010-01-01,\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "t.osmpack"), 202611)
    assert tabular.read(str(tmp_path / "tx.csv"), entry, region, w) == 2
    rows = sorted(w.db.execute("SELECT key, name, tag, lat, lon, first, last FROM points").fetchall())
    hashed = tabular.stored_key(entry, "19990000001-1")
    assert len(hashed) == 16 and re.fullmatch(r"[0-9a-f]+", hashed)
    by_name = {r[1]: r for r in rows}
    tacos, hardware = by_name["Made-up Tacos"], by_name["Pretend Hardware"]
    assert tacos[0] == f"tx-sales-tax-outlets:{hashed}" and tacos[2] == "restaurant"
    assert tacos[3] == 44000100 and tacos[5:] == (199804, 202611)    # open: up to this build
    assert hardware[3] == 44000300 and hardware[2] == "shop"              # a home: the street's middle
    assert hardware[5:] == (200102, 201506)
    everything = " ".join(str(v) for r in w.db.execute("SELECT * FROM points").fetchall() for v in r)
    assert "1999000000" not in everything and "2999000000" not in everything
    assert tabular.stored_key({"key_hash": True}, "x") == tabular.stored_key({"key_hash": True}, "x")


def test_a_state_socrata_dataset_is_fetched_once_by_the_prepare_job(monkeypatch, tmp_path):
    """A national source with Socrata queries: the prepare job pages it into national/<id>/<id>.csv with the
    portal's version beside it, keeps that copy while the version is the same, and every region's fetch reads the
    slice folder with the same version (the plan and the build agree)."""
    entry = {"id": "made-up-outlets", "fetch": {"method": "national", "domain": "data.example.gov", "page": 2,
                                                "queries": [{"dataset": "aaaa-1111", "select": "id AS key, n AS name",
                                                             "where": "n IS NOT NULL"}]}}
    pages = {"0": "key,name\n1,Made-Up Diner\n2,Invented Cafe\n", "2": "key,name\n3,Pretend Bakery\n"}
    asked = []

    def page(url, folder, pause, sleep=None):
        import urllib.parse
        offset = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["$offset"][0]
        asked.append(offset)
        return pages[offset]
    monkeypatch.setattr(fetch, "get_page", page)
    monkeypatch.setattr(fetch, "read_json", lambda url, opener=None: {"rowsUpdatedAt": 7})
    national = tmp_path / "national"
    fetch.prepare_national(entry, str(national), {})
    out = national / "made-up-outlets" / "made-up-outlets.csv"
    assert out.read_text(encoding="utf-8").splitlines() == ["key,name", "1,Made-Up Diner", "2,Invented Cafe",
                                                             "3,Pretend Bakery"]
    assert (national / "made-up-outlets" / "made-up-outlets.csv.version").read_text() == "aaaa-1111:7"
    assert asked == ["0", "2"]
    fetch.prepare_national(entry, str(national), {})          # the same version: the cached copy, no new pages
    assert asked == ["0", "2"]
    got = fetch.fetch_source(dict(entry, countries=["US"]), {"id": VT}, {}, str(tmp_path / "work"), str(national))
    assert got["ok"] and got["path"] == str(national / "made-up-outlets") and got["version"] == "aaaa-1111:7"
    plan = fetch.fetch_source(dict(entry, countries=["US"]), {"id": VT}, {}, str(tmp_path / "work"), None, True)
    assert plan["version"] == "aaaa-1111:7"


def tiger_fixture(folder):
    """A TIGER/Line ADDRFEAT-like shapefile: Made-up St in two ZIP codes with the same house numbers."""
    import shapefile
    folder.mkdir()
    with shapefile.Writer(str(folder / "tl_addrfeat"), shapeType=shapefile.POLYLINE) as w:
        for f in ("TLID", "FULLNAME", "LFROMHN", "LTOHN", "RFROMHN", "RTOHN", "ZIPL", "ZIPR"):
            w.field(f, "C", 40)
        w.line([[[-76.60, 39.30], [-76.59, 39.30]]])
        w.record("1", "Made-up St", "1", "99", "2", "98", "21201", "21201")
        w.line([[[-76.50, 39.40], [-76.49, 39.40]]])
        w.record("2", "Made-up St", "1", "99", "2", "98", "21230", "21230")
    z = folder / "tl_addrfeat.zip"
    with zipfile.ZipFile(z, "w") as out:
        for f in os.listdir(folder):
            if f.endswith((".shp", ".shx", ".dbf")):
                out.write(folder / f, f)
    return str(folder)


def test_address_ranges_are_matched_by_zip_code(tmp_path):
    """Baltimore's licences (Maryland is not in the NAD) are placed along TIGER's address ranges: the same street
    name in another ZIP code is not taken; without a ZIP the first segment that fits is used."""
    tiger = entry_of("tiger-addrfeat")
    found = geocode.locate_ranges([("51 MADE-UP STREET", "", "21230"), ("51 Made-up St", "", "21201-1234"),
                                   ("51 Made-up St", "", "21299")], tiger_fixture(tmp_path / "tiger"), tiger)
    assert abs(found[0][0] - 39.40) < 1e-6 and abs(found[1][0] - 39.30) < 1e-6 and 2 not in found
    assert found[0][2] == "range"
    entry = entry_of("baltimore-liquor-licences")
    assert entry["geocode"]["ranges_from"] == "tiger-addrfeat" and entry["fetch"]["box"] is False
    assert "Licensee" not in entry["fetch"]["fields"]


def test_county_street_short_forms_and_doubled_numbers_are_read():
    """Sacramento County writes "BL" and "WY"; some state lists write the house number twice."""
    assert geocode.split_address("2330 FAIR OAKS BL") == ("2330", "FAIR OAKS BLVD")
    assert geocode.split_address("3939 3939 HWY 35 SOUTH STE 301") == ("3939", "HWY 35 S")
    assert geocode.split_address("12 12TH ST") == ("12", "12TH ST")
