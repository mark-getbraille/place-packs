"""The dated open-data sources: the NAD's address from its Socrata metadata, a download that continues after a
dropped connection, the Socrata and WFS fetches (paged, without the network), the FSA's XML files, GeoNames-like
files split by box, the tabular reader's new settings (point columns, class prefixes and tags, one record per
permit and name, open and closed dates, personal names left out), and the history of dated records over several
monthly builds (not copied every month). Every name and place here is made up."""

import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import build, catalogue, fetch, fmt, split  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"


class Answer(io.BytesIO):
    """A fake HTTP answer (a context manager with headers and a status)."""

    def __init__(self, data=b"", headers=None, status=200):
        super().__init__(data)
        self.headers, self.status = headers or {}, status


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


# ------------------------------------------------------------------------------------------- the NAD


def test_nad_address_and_version_come_from_the_socrata_metadata():
    """The NAD's file is found from data.transportation.gov's metadata: its blobId names the download, and the version
    is blobId plus rowsUpdatedAt (the monthly plan downloads it again only when either changes). When the metadata
    cannot be read, the old S3 address is tried."""
    import urllib.error
    nad = entry_of("nad")
    meta = {"blobId": "aaaa-bbbb", "blobFilename": "TXT.zip", "rowsUpdatedAt": 1700000000}
    files = fetch.national_files(nad, {"nad_release": "20"}, lambda url: Answer(json.dumps(meta).encode()))
    assert files == [("https://data.transportation.gov/api/views/fc2s-wawr/files/aaaa-bbbb?download=true&filename="
                      "TXT.zip", "NAD_TXT.zip", "aaaa-bbbb:1700000000")]

    def refused(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))
    url, name, version = fetch.national_files(nad, {"nad_release": "20"}, refused)[0]
    assert url.endswith("nationaladdressdata.s3.amazonaws.com/NAD_r20_TXT.zip") and version is None
    # The NAD's licence handling and its 12 left-out states are unchanged.
    assert nad["licence"] == "US-Government-Work" and len(nad["exclude"]["values"]) == 12


def test_nad_fingerprint_and_build_use_the_same_version(monkeypatch, tmp_path):
    """The plan (fingerprint) and the region build record the same NAD version, so a region is not rebuilt for a
    NAD that did not change."""
    monkeypatch.setattr(fetch, "read_json", lambda url, opener=None: {"blobId": "b1", "blobFilename": "TXT.zip",
                                                                      "rowsUpdatedAt": 42})
    region = catalogue.regions()[VT]
    values = catalogue.settings_for(catalogue.load(), region)
    nat = tmp_path / "national" / "nad"
    nat.mkdir(parents=True)
    (nat / "nad.txt").write_text("State\nVT\n")
    plan = fetch.fetch_source(entry_of("nad"), region, values, str(tmp_path), str(tmp_path / "national"), True)
    got = fetch.fetch_source(entry_of("nad"), region, values, str(tmp_path), str(tmp_path / "national"))
    assert plan["version"] == got["version"] == "b1:42" and got["ok"] and got["path"] == str(nat)


def test_prepare_keeps_the_cached_nad_and_removes_an_old_release(monkeypatch, tmp_path):
    """A NAD restored from the Actions cache with the same version is not downloaded again; an older release's file
    in the cache is deleted (it would otherwise be split as well)."""
    folder = tmp_path / "nad"
    folder.mkdir()
    (folder / "NAD_TXT.zip").write_bytes(b"PK")
    (folder / "NAD_TXT.zip.version").write_text("b1:42")
    (folder / "NAD_r20_TXT.zip").write_bytes(b"PK old")
    monkeypatch.setattr(fetch, "national_files", lambda e, v, opener=None: [("https://x/TXT.zip", "NAD_TXT.zip",
                                                                             "b1:42")])
    monkeypatch.setattr(fetch, "download", lambda *a, **k: (_ for _ in ()).throw(AssertionError("downloaded")))
    fetch.prepare_national(entry_of("nad"), str(tmp_path), {})
    assert sorted(os.listdir(folder)) == ["NAD_TXT.zip", "NAD_TXT.zip.version"]


def test_a_dropped_download_continues_with_a_range_request(monkeypatch, tmp_path):
    """After a dropped connection the download asks only for the rest (Range) and appends the 206 answer."""
    asked = []

    class Dropping(Answer):
        def read(self, n=-1):
            data = super().read(n)
            if not data:
                raise ConnectionError("connection reset")
            return data

    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("made-up.txt", "a made-up file " * 20)
    whole = buf.getvalue()                  # a real zip, cut after its first 10 bytes by the dropped connection

    def answer(url, *a, headers=None, **k):
        asked.append((headers or {}).get("Range"))
        if len(asked) == 1:
            return Dropping(whole[:10])
        return Answer(whole[10:], status=206, headers={"ETag": "e"})
    monkeypatch.setattr(fetch, "request", answer)
    target = str(tmp_path / "big.zip")
    fetch.download("https://x/big.zip", target, sleep=lambda s: None)
    assert asked == [None, "bytes=10-"] and open(target, "rb").read() == whole


# ------------------------------------------------------------------------------------------- Socrata and WFS


def test_socrata_fetch_pages_every_query_into_one_csv(monkeypatch, tmp_path):
    """Each query is paged with $limit and $offset; the pages of every query make one CSV with one header; the
    version is each dataset's rowsUpdatedAt."""
    entry = {"id": "made-up-licences", "fetch": {"method": "socrata", "domain": "data.example.gov", "page": 2,
                                                 "queries": [{"dataset": "aaaa-1111", "select": "id AS key, n AS name",
                                                              "where": "n IS NOT NULL", "group": "id, n"},
                                                             {"dataset": "bbbb-2222",
                                                              "select": "id AS key, n AS name, 'yes' AS closed"}]}}
    pages = {("aaaa-1111", "0"): 'key,name\n1,Made-Up Diner\n2,Invented Cafe\n',
             ("aaaa-1111", "2"): 'key,name\n3,Pretend Bakery\n',
             ("bbbb-2222", "0"): 'key,name,closed\n9,Gone Tavern,yes\n'}
    seen = []

    def page(url, folder, pause, sleep=None):
        import urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        dataset = url.split("/resource/")[1].split(".csv")[0]
        seen.append((dataset, q["$offset"][0], q["$limit"][0], q.get("$group", [""])[0], q["$order"][0]))
        return pages[(dataset, q["$offset"][0])]
    monkeypatch.setattr(fetch, "get_page", page)
    monkeypatch.setattr(fetch, "read_json", lambda url, opener=None: {"rowsUpdatedAt": 7})
    got = fetch.fetch_socrata(entry, str(tmp_path), False)
    assert got["ok"] and got["version"] == "aaaa-1111:7,bbbb-2222:7"
    assert seen == [("aaaa-1111", "0", "2", "id, n", "id, n"), ("aaaa-1111", "2", "2", "id, n", "id, n"),
                    ("bbbb-2222", "0", "2", "", ":id")]
    text = open(got["path"], encoding="utf-8").read()
    assert text.splitlines() == ["key,name", "1,Made-Up Diner", "2,Invented Cafe", "3,Pretend Bakery",
                                 "9,Gone Tavern"]
    assert fetch.fetch_socrata(entry, str(tmp_path), True) == {"ok": True, "version": "aaaa-1111:7,bbbb-2222:7",
                                                                 "path": "", "date": ""}


def test_wfs_fetch_pages_by_start_index(monkeypatch, tmp_path):
    """A WFS layer is read page by page (startIndex) as CSV; its version is the feature count."""
    entry = entry_of("vic-sands-mcdougall")
    entry["fetch"]["page"] = 2
    starts = []

    def page(url, folder, pause, sleep=None):
        start = int(url.split("startIndex=")[1].split("&")[0])
        starts.append(start)
        rows = {0: "1,POINT (144.9 -37.8),1896,Invented Grocer\n2,POINT (144.9 -37.8),1906,Invented Grocer\n",
                2: "3,POINT (145.0 -37.9),1896,Made-Up Bootmaker\n"}[start]
        return "FID,geom,directory,business_name\n" + rows
    monkeypatch.setattr(fetch, "get_page", page)
    hits = lambda url: Answer(b'<wfs:FeatureCollection numberMatched="3" numberReturned="0"/>')  # noqa: E731
    got = fetch.fetch_wfs(entry, str(tmp_path), False, hits)
    assert starts == [0, 2] and got["version"] == "3 features"
    assert len(open(got["path"], encoding="utf-8").read().splitlines()) == 4


def test_fsa_xml_files_become_one_csv(tmp_path):
    """The FSA's per-authority XML files are turned into one small CSV (the fields read, nothing else)."""
    xml = ("<?xml version=\"1.0\"?><FHRSEstablishment><EstablishmentCollection><EstablishmentDetail><FHRSID>1"
           "</FHRSID><BusinessName>MADE-UP CHIPPY</BusinessName><BusinessType>Takeaway/sandwich shop</BusinessType>"
           "<RatingValue>5</RatingValue><RatingDate>2019-04-02</RatingDate><Geocode><Longitude>-1.5</Longitude>"
           "<Latitude>53.8</Latitude></Geocode></EstablishmentDetail></EstablishmentCollection></FHRSEstablishment>")
    (tmp_path / "FHRS1en-GB.xml").write_text(xml, encoding="utf-8")
    spec = entry_of("fsa-hygiene")["fetch"]["xml_records"]
    n = fetch.xml_to_csv([str(tmp_path / "FHRS1en-GB.xml")], spec, str(tmp_path / "fsa.csv"))
    assert n == 1
    assert open(tmp_path / "fsa.csv", encoding="utf-8").read().splitlines() == [
        "FHRSID,BusinessName,BusinessType,RatingDate,Latitude,Longitude",
        "1,MADE-UP CHIPPY,Takeaway/sandwich shop,2019-04-02,53.8,-1.5"]


# ------------------------------------------------------------------------------------------- catalogue and split


def test_city_sources_apply_only_to_their_regions():
    """A city's or state's dataset is used only by its region; national ones by every region of the country."""
    regions = catalogue.regions()
    ny = {e["id"] for e in catalogue.sources_for(regions["us-new-york"], "extra")}
    vt = {e["id"] for e in catalogue.sources_for(regions[VT], "extra")}
    assert {"nyc-restaurant-inspections", "ny-liquor-licences", "fdic-branches"} <= ny
    assert "nyc-restaurant-inspections" not in vt and "fdic-branches" in vt
    bad = dict(catalogue.load())
    bad["accepted"] = bad["accepted"] + [dict(entry_of("ny-liquor-licences"), id="x", regions=["us-atlantis"])]
    assert any("us-atlantis" in p for p in catalogue.check(bad))


def test_every_new_source_has_its_licence_and_status_reason():
    """Every Socrata source names its datasets in its attribution; every source has a licence the catalogue allows;
    the rejected list says why the candidates were left out."""
    cat = catalogue.load()
    for e in cat["accepted"]:
        if e["fetch"]["method"] == "socrata":
            for q in e["fetch"]["queries"]:
                assert q["dataset"] in e["attribution"], (e["id"], q["dataset"])
            # A city's or state's dataset names its regions; a small national one (the VA's ~150 cemeteries) is
            # read by every US region and kept by its box.
            assert e.get("regions") or e["id"] in {"va-national-cemeteries"}, e["id"]
    names = " ".join(r["name"] for r in cat["rejected"])
    for rejected in ("Chicago", "Kitchener", "Sanborn", "Pleiades", "World Historical Gazetteer", "KVK", "KBO"):
        assert rejected in names, rejected


def test_geonames_like_file_is_split_by_box_and_country(tmp_path):
    """A file without a header (GeoNames) is split to the regions of its country whose box holds each row."""
    entry = entry_of("geonames")
    folder = tmp_path / "geonames"
    folder.mkdir()
    lines = ["1\tLac Inventé\tLac Invente\t\t49.6\t6.1\tH\tLK\tLU\t\t\t\t\t\t0\t\t300\tEurope/Luxembourg\t2020-01-01",
             "2\tMadeup Hill\tMadeup Hill\t\t49.5\t5.9\tT\tHLL\tBE\t\t\t\t\t\t0\t\t300\tEurope/Brussels\t2020-01-01"]
    with zipfile.ZipFile(folder / "LU.zip", "w") as z:
        z.writestr("LU.txt", lines[0] + "\n" + lines[1] + "\n")
        z.writestr("readme.txt", "not data\n")
    regions = {k: v for k, v in catalogue.regions().items() if k in ("lu-luxembourg", "be-belgium")}
    counts = split.split_tabular(entry, str(folder), str(tmp_path / "out"), regions)
    assert counts == {"lu-luxembourg": 1, "be-belgium": 1}
    region = dict(regions["lu-luxembourg"])
    w = PackWriter(str(tmp_path / "g.osmpack"), 202611)
    from placepacks.readers.tabular import read
    assert read(str(tmp_path / "out" / "lu-luxembourg" / "geonames"), entry, region, w) == 1
    assert w.db.execute("SELECT name, cls FROM points").fetchall() == [("Lac Inventé", "water")]


def test_split_keeps_only_the_columns_the_reader_uses(tmp_path):
    """A NAD slice keeps the columns the reader uses (the NAD now has 60), and "Not stated" is read as empty."""
    entry = entry_of("nad")
    path = tmp_path / "NAD.txt"
    path.write_text("OID_,AddNo_Full,StNam_Full,Post_City,Inc_Muni,State,Longitude,Latitude,Parcel_ID\n"
                    "1,12,Invented Rd,Not stated,Madeupton,VT,-72.0,44.0,P-1\n", encoding="utf-8")
    split.split_tabular(entry, str(path), str(tmp_path / "out"), catalogue.regions())
    out = tmp_path / "out" / VT / "nad" / "nad.txt"
    header = out.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "Parcel_ID" not in header and "OID_" not in header and "StNam_Full" in header
    w = PackWriter(str(tmp_path / "a.osmpack"), 202611)
    from placepacks.readers.tabular import read
    region = dict(catalogue.regions()[VT])
    assert read(str(out.parent), entry, region, w) == 1
    assert w.db.execute("SELECT city FROM addr").fetchall() == [("Madeupton",)]


# ------------------------------------------------------------------------------------------- the reader


def test_point_columns_dates_and_formats():
    """Socrata's point formats, and the US month/day/year dates of FDIC and some portals."""
    from placepacks.readers.tabular import parse_point
    assert parse_point("POINT (-72.5 44.25)") == (44.25, -72.5)
    assert parse_point("12 Invented St\nMadeupton, VT 05000\n(44.1, -72.2)") == (44.1, -72.2)
    assert parse_point("") is None
    assert fmt.parse_month("04/02/2022") == 202204 and fmt.parse_month("19961231") == 199612
    assert fmt.parse_month("2019-04-02T00:00:00.000") == 201904


def test_inspections_become_one_dated_record_per_permit_and_name(tmp_path):
    """Inspection rows are one record per permit and name, from the first to the last inspection (any capitals);
    a permit renamed keeps both names with their own dates; one inspected lately is still open; a closed one keeps
    its last date; placeholder names suffixes are removed."""
    entry = entry_of("nys-food-service-inspections")
    entry["regions"] = [VT]
    csv_text = ("key,name,lat,lon,first,last,closed\n"
                "P1,MADE-UP DINER,44.0,-72.0,2008-03-01T00:00:00.000,2015-06-01T00:00:00.000,\n"
                "P1,Made-Up Diner,44.0,-72.0,2016-01-01T00:00:00.000,2018-02-01T00:00:00.000,\n"
                "P1,Invented Pizza,44.0,-72.0,2018-05-01T00:00:00.000,2026-08-01T00:00:00.000,\n"
                "P2,Pretend Grill/Inactive/Ina,44.01,-72.0,2009-01-01T00:00:00.000,2026-06-01T00:00:00.000,yes\n")
    (tmp_path / "nys.csv").write_text(csv_text, encoding="utf-8")
    w = PackWriter(str(tmp_path / "x.osmpack"), 202611)
    from placepacks.readers.tabular import read
    assert read(str(tmp_path / "nys.csv"), entry, dict(catalogue.regions()[VT]), w) == 3
    rows = sorted(w.db.execute("SELECT key, name, first, last FROM points").fetchall())
    assert rows == [("nys-food-service-inspections:P1", "Invented Pizza", 201805, 202611),
                    ("nys-food-service-inspections:P1", "Made-up Diner", 200803, 201802),
                    ("nys-food-service-inspections:P2", "Pretend Grill", 200901, 202606)]


def test_licences_keep_storefronts_and_leave_out_personal_names(tmp_path):
    """Class prefixes and tags (NAICS 722 is a restaurant, 4541 an online shop left out); a licensee name that looks
    like a person's is left out, a company's is kept; a licence expiring next year is open now."""
    from placepacks.readers.tabular import class_of, read
    sf = entry_of("sf-registered-businesses")
    assert class_of(sf, "722511") == ("business", "restaurant") and class_of(sf, "454110") == ("", "")
    assert class_of(sf, "721199") == ("", "") and class_of(sf, "721110") == ("business", "hotel")
    assert class_of(sf, "541110") == ("", "")
    entry = entry_of("ny-liquor-licences")
    entry["regions"] = [VT]
    (tmp_path / "sla.csv").write_text(
        "key,dba,legalname,kind,point,first,last,closed\n"
        "L1,,\"DOE, JANE\",Restaurant,POINT (-72.0 44.0),2010-01-01T00:00:00.000,2027-12-31T00:00:00.000,\n"
        "L2,,\"MADE-UP TAVERN LLC, THE\",Tavern,POINT (-72.0 44.001),2001-05-01T00:00:00.000,"
        "2027-12-31T00:00:00.000,\n"
        "L3,INVENTED WINES,INVENTED WINES INC,Wholesale Wine,POINT (-72.0 44.002),2001-05-01,2027-12-31,\n"
        "L4,GONE GROCERY,GONE GROCERY INC,Grocery Store,POINT (-72.0 44.003),1999-02-01,2012-02-29,yes\n",
        encoding="utf-8")
    w = PackWriter(str(tmp_path / "l.osmpack"), 202611)
    assert read(str(tmp_path / "sla.csv"), entry, dict(catalogue.regions()[VT]), w) == 2
    rows = sorted(w.db.execute("SELECT name, tag, first, last FROM points").fetchall())
    assert rows == [("Gone Grocery", "shop", 199902, 201202), ("Made-up Tavern Llc, The", "bar", 200105, 202611)]


# ------------------------------------------------------------------------------------------- history


def test_dated_records_are_not_copied_every_month(tmp_path):
    """A closed licence (its own last date) and an open one, built three months running: one row each, the open one
    extended; a business renamed under the same licence keeps its old name as a closed row."""
    entry = dict(entry_of("colorado-liquor-licences"), regions=[VT])
    cat = catalogue.load()
    cat["accepted"] = [e for e in cat["accepted"] if e["id"] != entry["id"]] + [entry]

    def month(n, name):
        path = tmp_path / f"m{n}.csv"
        path.write_text("key,dba,legalname,kind,point,last,closed\n"
                        "C1,OLD MILL TAVERN,X INC,Tavern (city),POINT (-72.0 44.0),2015-03-31,yes\n"
                        f"C2,{name},Y INC,Hotel & Restaurant (city),POINT (-72.0 44.001),2027-06-30,\n",
                        encoding="utf-8")
        return {entry["id"]: {"path": str(path), "ok": True, "version": str(n)}}
    prev = None
    for n, m, name in ((1, 202609, "INVENTED BISTRO"), (2, 202610, "INVENTED BISTRO"), (3, 202611, "NEW NAME CAFE")):
        out = tmp_path / f"p{n}.osmpack"
        build.build(VT, "extra", month(n, name), str(out), previous=prev, month=m, only={entry["id"]}, cat=cat,
                    removal_list=[])
        prev = str(out)
    rows = PackReader(prev)._rows("SELECT key, name, first, last FROM points ORDER BY key, first")
    assert [(r["name"], r["first"], r["last"]) for r in rows] == [
        ("Old Mill Tavern", 201503, 201503),
        ("Invented Bistro", 202609, 202610), ("New Name Cafe", 202611, 202611)]
    f = Finder(packs=[PackReader(prev)], water=False)
    r = f.lookup(44.001, -72.0, when=202610)
    assert r.name == "Invented Bistro" and r.listed and r.now_name == "New Name Cafe"


# ------------------------------------------------------------------------------------------- trial build #3 fixes


def test_status_reasons_stay_on_one_table_line():
    """A reason with newlines (DuckDB's errors) is one line in sources-status.md and in the build's status line, at
    most about 200 characters."""
    from placepacks import status
    reason = "Binder Error: Referenced table \"categories\" not found!\nCandidate tables: \"read_parquet\"\n" + "x" * 400
    text = status.status({"packs": {VT + "-extra": {"size": 1, "built_month": 202611, "history_start": 202611,
                                                    "sources": {}, "status": {"overture-places": {
                                                        "status": "failed", "reason": reason}}}}})
    line = next(l for l in text.splitlines() if "overture-places" in l)
    assert line.startswith("| us-vermont-extra | overture-places | failed | Binder Error: Referenced table")
    assert line.endswith("... |") and len(line) < 260
    printed = fetch.status_line("overture-places", {"status": "failed", "reason": reason})
    assert "\n" not in printed and len(printed) < 240


def test_overture_query_picks_the_columns_the_release_has():
    """Overture's query uses taxonomy.primary when the release has it, else basic_category, else the old
    categories.primary, and leaves out permanently closed places when operating_status exists."""
    from placepacks.readers import parquet

    class Con:
        """A fake DuckDB connection answering DESCRIBE with the given columns."""

        def __init__(self, columns):
            self.columns = columns

        def execute(self, query):
            assert query.startswith("DESCRIBE")
            return self

        def fetchall(self):
            return list(self.columns.items())
    entry = entry_of("overture-places")
    region = catalogue.regions()[VT]
    new = Con({"id": "VARCHAR", "operating_status": "VARCHAR", "basic_category": "VARCHAR",
               "taxonomy": 'STRUCT("primary" VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[])'})
    q = parquet.sql(entry, "s3://x/*", region, new)
    assert "taxonomy.primary AS cls" in q and "CAST(operating_status AS VARCHAR), '') <> 'permanently_closed'" in q
    mid = Con({"id": "VARCHAR", "basic_category": "VARCHAR"})
    q = parquet.sql(entry, "s3://x/*", region, mid)
    assert "basic_category AS cls" in q and "COALESCE(CAST(NULL AS VARCHAR), '')" in q
    old = Con({"id": "VARCHAR", "categories": 'STRUCT("primary" VARCHAR, alternate VARCHAR[])'})
    assert "categories.primary AS cls" in parquet.sql(entry, "s3://x/*", region, old)
    assert parquet.classify_category(entry, "parking_lot") == "business"
    assert parquet.classify_category(entry, "elementary_school") == "campus"
    assert parquet.classify_category(entry, "park") == "park"
