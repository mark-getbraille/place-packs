"""Round 13: notes on places (filming locations, data only), the optional "names" part (other-language names),
duplicates removed against another source at build time, NRCan address ranges in the packs and in the geocoder, a
long line kept when it crosses the region, Who's On First records kept by an open geometry source, and NCES schools
closed since 2015. Offline: made-up fixtures only."""

import csv
import inspect
import json
import os
import sqlite3
import sys
import zipfile

import shapefile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, fmt, geocode  # noqa: E402
from placepacks.lookup import Finder, PackReader, Result  # noqa: E402
from placepacks.readers import wikidata  # noqa: E402
from placepacks.readers.shapes import read as read_shapes  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT, PE = "us-vermont", "ca-prince-edward-island"
REGION = {"region_id": VT, "state": "Vermont", "country": "United States"}
SPOT = (44.0006, -71.9981)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def test_filming_locations_are_a_note_joined_to_the_place(tmp_path):
    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q9000001"}, "itemLabel": {"value": "Made-up Diner"},
             "coord": {"value": f"Point({SPOT[1]} {SPOT[0]})"}, "work": {"value": "http://x/Q1"},
             "workLabel": {"value": t}} for t in ("Invented Movie", "Pretend Series")]
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"results": {"bindings": rows}}), encoding="utf-8")
    w = PackWriter(str(tmp_path / "n.osmpack"), 202611)
    w.add_point("wikidata:Q9000001", "wikidata", "Made-up Diner", "business", "t", SPOT[0], SPOT[1], type="diner")
    assert wikidata.read_filming(str(path), entry_of("wikidata-filming"), dict(catalogue.regions()[VT]), w) == 1
    w.finish(REGION)
    con = sqlite3.connect(str(tmp_path / "n.osmpack"))
    assert con.execute("SELECT text FROM notes").fetchall() == [("filming location of Invented Movie; Pretend Series",)]
    assert "note" not in [r[1] for r in con.execute("PRAGMA table_info(points)")]
    r = Finder(packs=[PackReader(str(tmp_path / "n.osmpack"))], water=False).lookup(*SPOT)
    assert r.name == "Made-up Diner" and r.note.startswith("filming location of Invented Movie")
    assert [x["cls"] for x in PackReader(str(tmp_path / "n.osmpack")).search("Made-up Diner")] == ["business"]
    for detail in ("area", "street", "address"):
        assert "Invented Movie" not in r.phrase(detail)
    for name, fn in inspect.getmembers(Result, inspect.isfunction):
        assert "self.note" not in inspect.getsource(fn), name


def test_the_names_part_holds_other_language_names(tmp_path):
    assert "names" in fmt.PARTS
    e = entry_of("wikidata-labels")
    assert e["part"] == "names" and e["fetch"]["mode"] == "labels"
    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q9000002"}, "label": {"value": n},
             "lang": {"value": l}} for n, l in (("Lac Inventé", "fr"), ("Erfundener See", "de"), ("Nope", "xx"))]
    path = tmp_path / "l.json"
    path.write_text(json.dumps({"results": {"bindings": rows}}), encoding="utf-8")
    w = PackWriter(str(tmp_path / "us-vermont-names.osmpack"), 202611)
    assert wikidata.read_labels(str(path), e, dict(catalogue.regions()[VT]), w) == 1
    w.finish(dict(REGION, part="names"))
    reader = PackReader(str(tmp_path / "us-vermont-names.osmpack"))
    assert reader.labels("wikidata:Q9000002") == {"fr": "Lac Inventé", "de": "Erfundener See"}
    assert "Q5" in wikidata.labels_query((-73, 43, -72, 44), 10, ["fr"])          # people left out
    from placepacks.build import pack_name
    assert pack_name(VT, "names") == "us-vermont-names.osmpack"
    workflow = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert "for part in businesses addresses names" in workflow and '--part "$part"' in workflow


def test_transit_stations_that_gtfs_already_has_are_removed(tmp_path):
    w = PackWriter(str(tmp_path / "t.osmpack"), 202611)
    w.add_point("g1", "gtfs", "Made-up Station", "transit", "t", 44.0, -72.0)
    w.add_point("n1", "ntad-transit-stations", "MADE-UP STATION", "transit", "t", 44.0005, -72.0)    # 55 m
    w.add_point("n2", "ntad-transit-stations", "Invented Transit Center", "transit", "t", 44.01, -72.0)
    assert w.drop_duplicates("ntad-transit-stations", ["gtfs"], 150) == 1
    assert [r[0] for r in w.db.execute("SELECT name FROM points ORDER BY name")] == [
        "Invented Transit Center", "Made-up Station"]
    e = entry_of("ntad-transit-stations")
    assert e["licence"] == "CC-BY-3.0-US" and e["dedupe_against"] == ["gtfs"] and "Station" in e["fetch"]["where"]


def nrn_fixture(folder):
    """A made-up NRN zip with a ROADSEG shapefile and another shapefile beside it."""
    folder.mkdir()
    for name, rows in (("NRN_XX_ROADSEG", [("a1", "Made-up Street", "Testville", 1, 99, 2, 100),
                                           ("a2", "Made-up Street", "Othertown", 1, 49, 2, 50),
                                           ("a3", "None", "Testville", 0, 0, 0, 0)]),
                       ("NRN_XX_JUNCTION", [])):
        with shapefile.Writer(str(folder / name), shapeType=shapefile.POLYLINE) as w:
            for f in ("NID", "L_STNAME_C", "L_PLACENAM", "R_STNAME_C", "R_PLACENAM"):
                w.field(f, "C", 40)
            for f in ("L_HNUMF", "L_HNUML", "R_HNUMF", "R_HNUML"):
                w.field(f, "N", 9)
            for i, (nid, street, town, lf, ll, rf, rl) in enumerate(rows):
                lat = 46.20 + i * 0.01
                w.line([[[-63.20, lat], [-63.19, lat]]])
                w.record(nid, street, town, street, town, lf, ll, rf, rl)
    z = folder / "nrn.zip"
    with zipfile.ZipFile(z, "w") as out:
        for f in os.listdir(folder):
            if f.endswith((".shp", ".shx", ".dbf")):
                out.write(folder / f, f)
    return str(z)


def test_nrn_ranges_are_read_and_the_geocoder_falls_back_on_them(tmp_path):
    z = nrn_fixture(tmp_path / "nrn")
    e = entry_of("nrn-address-ranges")
    w = PackWriter(str(tmp_path / "r.osmpack"), 202611)
    assert read_shapes(z, e, dict(catalogue.regions()[PE]), w) == 2                  # the unnamed, unnumbered one out
    assert w.db.execute("SELECT name, lfrom, lto FROM ranges ORDER BY id").fetchall()[0] == ("Made-up Street", 1, 99)
    found = geocode.locate_ranges([("51 Made-up St", "Testville", ""), ("25 Made-up Street", "Othertown", ""),
                                   ("51 Made-up St", "Othertown", "")], z, e)
    assert found[0][2] == "range" and abs(found[0][0] - 46.20) < 1e-6 and abs(found[0][1] + 63.195) < 1e-3
    assert abs(found[1][0] - 46.21) < 1e-6 and 2 not in found                       # 51 is past Othertown's range


def test_a_long_line_that_crosses_the_region_is_kept(tmp_path):
    entry = dict(entry_of("ntad-amtrak-routes"), regions=[VT])
    f = tmp_path / "a.csv"
    path = [[[40.7, -74.0], [44.2, -72.6], [45.0, -73.2]]]
    with open(f, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["OBJECTID", "name", "_lat", "_lon", "_paths"])
        w.writerow(["1", "Invented Express", "40.7", "-74.0", json.dumps(path)])        # its point is in New York
        w.writerow(["2", "Pretend Limited", "33.0", "-90.0", json.dumps([[[33.0, -90.0], [34.0, -89.0]]])])
    wr = PackWriter(str(tmp_path / "l.osmpack"), 202611)
    read_tabular(str(f), entry, dict(catalogue.regions()[VT]), wr)
    assert [r[0] for r in wr.db.execute("SELECT DISTINCT name FROM lines")] == ["Invented Express"]


def test_whos_on_first_keeps_open_geometry_sources_only(tmp_path):
    db = tmp_path / "w.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE spr (id, name, placetype, latitude, longitude, is_current, is_deprecated, is_superseded)")
    con.execute("CREATE TABLE geojson (id, body)")
    for wid, name, src in ((1, "Made-up Heights", "quattroshapes"), (2, "Invented Flats", "osm"),
                           (3, "Pretend Hollow", "mz")):
        con.execute("INSERT INTO spr VALUES (?, ?, 'neighbourhood', 44.1, -72.5, 1, 0, 0)", (wid, name))
        con.execute("INSERT INTO geojson VALUES (?, ?)", (wid, json.dumps({"properties": {"src:geom": src}})))
    con.execute("INSERT INTO geojson VALUES (1, ?)", (json.dumps({"properties": {"src:geom": "quattroshapes"}}),))
    con.commit()
    con.close()
    out = tmp_path / "w.csv"
    assert fetch.wof_to_csv(str(db), str(out)) == 2
    assert sorted(r["name"] for r in csv.DictReader(open(out, encoding="utf-8"))) == ["Made-up Heights",
                                                                                     "Pretend Hollow"]


def test_nces_schools_closed_since_the_first_year_keep_their_years(tmp_path):
    def year_zip(code, rows):
        p = tmp_path / f"EDGE_GEOCODE_PUBLICSCH_{code}.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr(f"EDGE_GEOCODE_PUBLICSCH_{code}.TXT", "".join(
                f"{sid}|0100|{name}|50|x|y|VT|05401|50|50007|C|21|{lat}|{lon}|a|b|c|d|e|f|g|h|20xx\r\n"
                for sid, name, lat, lon in rows))
        return str(p)
    paths = [year_zip("1516", [("500000100001", "Old Madeup School", 44.1, -72.5),
                               ("500000100002", "Invented Elementary", 44.2, -72.6)]),
             year_zip("1718", [("500000100002", "Invented Elementary", 44.2, -72.6)])]
    out = tmp_path / "c.csv"
    assert fetch.nces_history_to_csv(paths, str(out)) == 1
    row = next(csv.DictReader(open(out, encoding="utf-8")))
    assert (row["name"], row["first"], row["last"]) == ("Old Madeup School", "2015-09", "2016-06")


def test_round_thirteen_sources_are_open_and_rejections_listed():
    ids = {e["id"] for e in catalogue.load()["accepted"]}
    for sid in ("ntad-rail-lines", "nhd-named-flowlines", "nhd-named-waterbodies", "nrn-address-ranges",
                "canvec-named-lakes", "whosonfirst-neighbourhoods", "nces-closed-schools", "nyc-honorary-street-names",
                "houston-historic-landmarks", "seattle-business-licences", "winnipeg-business-licences"):
        assert sid in ids and entry_of(sid)["licence"] in catalogue.ALLOWED, sid
    names = " ".join(r["name"] for r in catalogue.load()["rejected"])
    assert "Trans Canada Trail" in names and "Atlanta Regional Commission historic resources" in names
