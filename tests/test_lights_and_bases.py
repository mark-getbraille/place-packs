"""Lighthouses (the USCG Light List, read from its XML or its text PDFs), former military sites (FUDS), national
cemeteries and the cemetery class, state parks in PAD-US, and the Wikidata classes of lighthouses, forts and bases.
Every name, number and position here is made up."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, fmt  # noqa: E402
from placepacks.readers import wikidata  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"

# Made-up lines in the Light List's column layout (No., Name and Location, Position, Characteristic, Height, Range,
# Structure, Remarks), as pypdf gives a page's text: the longitude and the end of the structure on the next line.
LIGHT_LIST_PAGE = """LIGHT LIST VOLUME I
SEACOAST (Madeup State) - First District
(1) (2) (3) (4) (5) (6) (7) (8)
No. Name and Location Position Characteristic Height Range Structure Remarks
1 Madeup Point Light 43-30-15.120N Fl W 6s 80 20 White conical tower attached to HORN: 1 blast ev 10s.
070-10-05.400W dwelling.
2 Invented Ledge Lighted Buoy 2 43-29-00.000N Fl R 4s 4 Red.
070-09-00.000W
3 Pretend Harbor Light 43 28.5 N Iso W 6s 30 9 On skeleton tower.
070 08.2 W
4 Imaginary Island Light 43-27-30N Fl W 10s 52 14 Square white tower on granite
070-07-30W house.
5 Fictional Daybeacon 5 43-26-00.000N Green square on pile.
070-06-00.000W
"""


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def test_light_list_text_keeps_only_lighthouses_with_their_positions():
    """From the PDF text: lights named "... Light" on a tower or house are kept, with positions converted from
    degrees, minutes and seconds; buoys, daybeacons and lights on skeleton towers are left out."""
    rows = fetch.light_list_text(LIGHT_LIST_PAGE, "I")
    assert [(r[1], r[2]) for r in rows] == [("1", "Madeup Point Light"), ("4", "Imaginary Island Light")]
    assert rows[0][3:5] == (43.5042, -70.168167) and rows[1][3:5] == (43.458333, -70.125)
    assert fetch.light_position("43 28.5 N 070 08.2 W") == (43.475, -70.136667)


def test_light_list_xml_and_the_csv_the_build_reads(tmp_path):
    """The XML form (its documented fields) gives the same rows; both become one CSV that the tabular reader reads
    as lighthouse points, keyed by volume and light number."""
    xml = ("<LightList><Aid><LLNR>7</LLNR><AidName>Madeup Bluff Light</AidName>"
           "<Position>44-01-00.000N 072-00-30.000W</Position><Structure>White cylindrical tower.</Structure></Aid>"
           "<Aid><LLNR>8</LLNR><AidName>Invented Shoal Buoy 1</AidName><Position>44-00-00.000N 072-00-00.000W"
           "</Position><Structure>Green can.</Structure></Aid></LightList>")
    (tmp_path / "LightList V1.xml").write_text(xml, encoding="utf-8")
    target = tmp_path / "uscg-light-list.csv"
    assert fetch.light_list_to_csv([str(tmp_path / "LightList V1.xml")], str(target)) == 1
    entry = entry_of("uscg-light-list")
    w = PackWriter(str(tmp_path / "l.osmpack"), 202611)
    assert read_tabular(str(target), entry, dict(catalogue.regions()[VT]), w) == 1
    assert w.db.execute("SELECT key, name, cls, tag FROM points").fetchall() == [
        ("uscg-light-list:1 7", "Madeup Bluff Light", "landmark", "lighthouse")]


def test_light_list_prefers_xml_and_falls_back_to_the_pdf_volumes():
    """The Light List page's XML volumes are used when it links them (not the weekly change files); else its PDF
    volumes."""
    import io
    entry = entry_of("uscg-light-list")
    both = (b'<a href="/sites/default/files/xml/lightLists/LightList_V1.xml">'
            b'<a href="/sites/default/files/xml/lightLists/weeklyUpdates/v1d01WeeklyChanges.xml">'
            b'<a href="/sites/default/files/pdf/lightLists/LightList%20V1.pdf">')
    names = [n for _, n, _ in fetch.national_files(entry, {}, lambda url: io.BytesIO(both))]
    assert names == ["LightList_V1.xml"]
    pdfs = b'<a href="/sites/default/files/pdf/lightLists/LightList%20V2.pdf">'
    assert [n for _, n, _ in fetch.national_files(entry, {}, lambda url: io.BytesIO(pdfs))] == ["LightList%20V2.pdf"]


def test_a_source_the_prepare_job_could_not_download_is_skipped_with_the_reason(monkeypatch, tmp_path):
    """When the prepare job cannot download a national source (navcen.uscg.gov refused, for example), each region's
    build says "skipped (could not be downloaded: ...)" instead of failing."""
    import urllib.error

    def refused(*a, **k):
        raise urllib.error.HTTPError("https://www.navcen.uscg.gov/light-list", 403, "Forbidden", {}, None)
    monkeypatch.setattr(fetch, "national_files", refused)
    cat = catalogue.load()
    cat["accepted"] = [entry_of("uscg-light-list")]
    fetch.prepare(str(tmp_path), cat)
    region = catalogue.regions()[VT]
    got = fetch.fetch_source(entry_of("uscg-light-list"), region, {}, str(tmp_path / "w"), str(tmp_path))
    assert got["status"] == "skipped" and got["reason"].startswith("could not be downloaded: HTTP Error 403")
    assert fetch.status_line("uscg-light-list", got).startswith("uscg-light-list: skipped (could not be downloaded")


def test_former_military_sites_and_national_cemeteries(tmp_path):
    """FUDS properties are named as former military sites; VA national cemeteries and GNIS cemeteries have the
    cemetery class; GNIS military features keep their "(historical)" names."""
    region = dict(catalogue.regions()[VT])
    (tmp_path / "f.csv").write_text("DODFUDSPROPERTYIDPK,FEATURENAME,_lat,_lon\nD01VT0001,CAMP MADEUP,44.0,-72.0\n",
                                    encoding="utf-8")
    w = PackWriter(str(tmp_path / "f.osmpack"), 202611)
    read_tabular(str(tmp_path / "f.csv"), entry_of("fuds"), region, w)
    assert w.db.execute("SELECT name, tag FROM points").fetchall() == [
        ("Camp Madeup (former military site)", "former military site")]
    (tmp_path / "g.txt").write_text("feature_id|feature_name|feature_class|prim_lat_dec|prim_long_dec\n"
                                    "1|Invented Cemetery|Cemetery|44.0|-72.0\n"
                                    "2|Fort Pretend (historical)|Military|44.01|-72.0\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "g.osmpack"), 202611)
    read_tabular(str(tmp_path / "g.txt"), entry_of("gnis"), region, w)
    assert sorted(w.db.execute("SELECT name, cls FROM points").fetchall()) == [
        ("Fort Pretend (historical)", "landmark"), ("Invented Cemetery", "cemetery")]
    assert entry_of("va-national-cemeteries")["cls"] == "cemetery"
    assert fmt.classify("landuse", "cemetery") == "cemetery" and fmt.classify("amenity", "grave_yard") == "cemetery"


def test_every_state_park_is_kept_in_pad_us():
    """PAD-US keeps every state park, recreation area, historic site, wilderness and state forest, of any size."""
    where = entry_of("padus")["fetch"]["where"]
    assert "Des_Tp IN ('SP','SREC','SHCA','SW')" in where and "State Forest" in where
    assert where.index("GIS_Acres >= 10") < where.index(" OR Des_Tp")       # the size limit is not for state parks


def test_wikidata_asks_for_lighthouses_forts_and_bases():
    """Lighthouses, light stations, forts, military, air, naval and Coast Guard bases and stations, national
    cemeteries and state parks are in the Wikidata query, with their dates."""
    for q in ("Q39715", "Q27193297", "Q1785071", "Q245016", "Q695850", "Q1324633", "Q31407679", "Q12585720",
              "Q1761072"):
        assert q in wikidata.CLASSES and f"wd:{q}" in wikidata.query_for(catalogue.regions()[VT])
    assert wikidata.CLASSES["Q12585720"] == "cemetery"
