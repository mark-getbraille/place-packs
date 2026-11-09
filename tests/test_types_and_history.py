"""Fine place types ("pizza restaurant", "hardware store", "catholic church") beside the coarse class: each source's
mapping, the types table of a pack, the history (a place renamed and re-typed keeps both, each with its own type),
packs and readers made before types existed, the most specific type of a place, and search by type. Also the round-4
sources: OpenHistoricalMap (Overpass), a CKAN SQL portal (Boston) and several files of one national source (StatCan).
Every name and place here is made up."""

import json
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, types  # noqa: E402
from placepacks.lookup import Finder, PackReader, search_names  # noqa: E402
from placepacks.readers import ohm, wikidata  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
SPOT = (44.0006, -71.9981)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


# ------------------------------------------------------------------------------------------- the mappings


def test_each_sources_type_mapping():
    """OpenStreetMap tags, NAICS codes, GNIS and FSA classes, Overture and Foursquare categories, NYC cuisines,
    Wikidata class labels: each becomes a short lower-case phrase."""
    assert types.osm({"amenity": "restaurant", "cuisine": "pizza"}) == "pizza restaurant"
    assert types.osm({"amenity": "restaurant", "cuisine": "ethiopian;coffee"}) == "ethiopian restaurant"
    assert types.osm({"shop": "hardware"}) == "hardware store"
    assert types.osm({"shop": "surf"}) == "surf shop"
    assert types.osm({"amenity": "place_of_worship", "religion": "christian", "denomination": "catholic"}) == \
        "catholic church"
    assert types.osm({"amenity": "place_of_worship", "religion": "jewish"}) == "synagogue"
    assert types.osm({"man_made": "lighthouse"}) == "lighthouse" and types.osm({"craft": "winery"}) == "winery"
    assert types.osm({"amenity": "fuel"}) == "gas station" and types.osm({"shop": "hairdresser"}) == "hair salon"
    assert types.osm({"highway": "residential"}) == ""
    assert types.naics("722511") == "restaurant" and types.naics("722515") == "coffee shop"
    assert types.naics("445110") == "grocery store" and types.naics("812112") == "beauty salon"
    assert types.naics("999999") == ""
    assert types.table("gnis", "Church") == "church" and types.table("fsa", "Pub/bar/nightclub") == "pub"
    assert types.table("cuisine", "Bakery Products/Desserts") == "bakery"
    assert types.table("cuisine", "Pizza") == "pizza restaurant"
    assert types.humanise("pizza_restaurant") == "pizza restaurant"
    assert types.humanise("Dining and Drinking > Restaurant > Pizzeria") == "pizzeria"
    assert types.humanise("..") == "" and types.of("{} restaurant", "Thai") == "thai restaurant"
    assert types.most_specific(["restaurant", "pizza restaurant", ""]) == "pizza restaurant"
    assert types.most_specific(["", None]) == ""


def test_licence_rows_get_their_naics_phrase(tmp_path):
    """A licence's NAICS code gives its type ("coffee shop"), finer than its class map's tag."""
    entry = dict(entry_of("sf-registered-businesses"), regions=[VT])
    (tmp_path / "sf.csv").write_text("key,name,naics,point,first,last\n"
                                     "1,Invented Beans,722515,POINT (-72.0 44.0),2001-01-01,\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "s.osmpack"), 202611)
    read_tabular(str(tmp_path / "sf.csv"), entry, dict(catalogue.regions()[VT]), w)
    assert w.db.execute("SELECT name, tag, type FROM points").fetchall() == [("Invented Beans", "restaurant",
                                                                               "coffee shop")]


# ------------------------------------------------------------------------------------------- the pack


def pack(path, month, rows, previous=None):
    """A pack of points [(key, name, cls, type)] at SPOT, built at month on previous."""
    w = PackWriter(str(path), month)
    for i, (key, name, cls, kind) in enumerate(rows):
        w.add_point(key, "osm", name, cls, "t", SPOT[0] + i * 1e-5, SPOT[1], type=kind)
    w.finish({"region_id": VT, "state": "Vermont", "country": "United States"}, previous=previous)
    return str(path)


def test_types_are_stored_once_and_read_back(tmp_path):
    """Each phrase is stored once (types); points link to it (point_types); the points table keeps its version 2
    columns, so readers made before types read new packs unchanged."""
    p = pack(tmp_path / "a.osmpack", 202611, [("n1", "Made-up Pizza", "business", "pizza restaurant"),
                                               ("n2", "Invented Slice", "business", "pizza restaurant"),
                                               ("n3", "Pretend Park", "park", None)])
    con = sqlite3.connect(p)
    assert con.execute("SELECT name FROM types").fetchall() == [("pizza restaurant",)]
    assert con.execute("SELECT COUNT(*) FROM point_types").fetchone()[0] == 2
    assert [r[1] for r in con.execute("PRAGMA table_info(points)")] == [
        "id", "key", "source", "name", "cls", "tag", "lat", "lon", "cell", "ccell", "first", "last"]
    con.close()
    reader = PackReader(p)
    assert {r["name"]: r["type"] for r in reader.points_near(*SPOT, 50)} == {
        "Made-up Pizza": "pizza restaurant", "Invented Slice": "pizza restaurant", "Pretend Park": None}
    assert Finder(packs=[reader], water=False).lookup(*SPOT).type == "pizza restaurant"


def test_history_keeps_each_rows_own_type(tmp_path):
    """The spot was a pizza restaurant in 2005 and an ice cream shop in 2020: both dated rows keep their types."""
    old = pack(tmp_path / "m1.osmpack", 200506, [("n8", "Tony's Pizza", "business", "pizza restaurant")])
    new = pack(tmp_path / "m2.osmpack", 202006, [("n8", "Sally's Ice Cream", "business", "ice cream shop")],
               previous=old)
    reader = PackReader(new)
    rows = sorted((r["first"], r["name"], r["type"]) for r in reader.points_near(*SPOT, 30))
    assert rows == [(200506, "Tony's Pizza", "pizza restaurant"), (202006, "Sally's Ice Cream", "ice cream shop")]
    f = Finder(packs=[reader], water=False)
    assert f.lookup(*SPOT, when="2005-07-01").type == "pizza restaurant"
    assert f.lookup(*SPOT, when="2020-07-01").type == "ice cream shop"


def strip_types(path):
    """Make a pack look like one made before types (no types tables)."""
    con = sqlite3.connect(path)
    for t in ("types", "point_types", "area_types"):
        con.execute(f"DROP TABLE {t}")
    con.commit()
    con.close()


def test_packs_made_before_types_still_work(tmp_path):
    """An older pack reads with type None and searches; a new pack built on it keeps its rows (types NULL); a
    local merge of a new pack over an older one (the downloader) works both ways and keeps the types it has."""
    from placepacks.download import merge_local
    old = pack(tmp_path / "old.osmpack", 202601, [("n1", "Made-up Diner", "business", "diner")])
    strip_types(old)
    reader = PackReader(old)
    assert reader.points_near(*SPOT, 30)[0]["type"] is None and reader.search("Diner")[0]["type"] is None
    reader.close()
    new = pack(tmp_path / "new.osmpack", 202611, [("n2", "Invented Bakery", "business", "bakery")], previous=old)
    assert {r["name"]: r["type"] for r in PackReader(new).points_near(*SPOT, 30)} == {
        "Invented Bakery": "bakery", "Made-up Diner": None}
    typed_old = pack(tmp_path / "t.osmpack", 202601, [("n9", "Pretend Deli", "business", "delicatessen")])
    fresh = pack(tmp_path / "f.osmpack", 202611, [("n2", "Invented Bakery", "business", "bakery")])
    merge_local(fresh, typed_old)
    assert {r["name"]: r["type"] for r in PackReader(fresh).points_near(*SPOT, 30)} == {
        "Invented Bakery": "bakery", "Pretend Deli": "delicatessen"}
    untyped_new = pack(tmp_path / "u.osmpack", 202611, [("n3", "Fictional Cafe", "business", "cafe")])
    strip_types(untyped_new)
    merge_local(untyped_new, str(tmp_path / "t.osmpack"))     # an older reader's pack merged with a typed one


def test_the_most_specific_type_of_a_place_and_search_by_type(tmp_path):
    """Two sources at the same place (one "restaurant", one "pizza restaurant"): the lookup says the more specific;
    search_names can keep only one type."""
    folder = tmp_path / "packs"
    folder.mkdir()
    p = pack(folder / "us-vermont-extra.osmpack", 202611, [("k1", "Made-up Pizza", "business", "restaurant"),
                                                             ("g1", "Made-up Pizza", "business", "pizza restaurant"),
                                                             ("k2", "Invented Bakery", "business", "bakery")])
    f = Finder(packs=[PackReader(p)], water=False)
    assert f.lookup(*SPOT).type == "pizza restaurant"
    found = search_names("Invented", folder=str(folder), type="bakery")
    assert [(r.name, r.type) for r in found] == [("Invented Bakery", "bakery")]
    assert search_names("Invented", folder=str(folder), type="pizza") == []


def test_wikidata_and_ohm_types_and_dates(tmp_path):
    """Wikidata asks for its classes' labels (the type); OpenHistoricalMap features get their dates and types, with
    lines, relations and features under another licence left out."""
    assert "?classLabel" in wikidata.query_for(catalogue.regions()[VT])
    answer = {"elements": [
        {"type": "node", "id": 1, "lat": 44.0, "lon": -72.0, "tags": {"name": "Made-up Mill", "man_made": "watermill",
                                                                       "start_date": "~1820", "end_date": "1910"}},
        {"type": "way", "id": 2, "center": {"lat": 44.001, "lon": -72.0},
         "tags": {"name": "Invented Depot", "railway": "station", "start_date": "1885..1890"}},
        {"type": "way", "id": 3, "center": {"lat": 44.002, "lon": -72.0},
         "tags": {"name": "Pretend Railroad", "railway": "rail", "start_date": "1850"}},
        {"type": "node", "id": 4, "lat": 44.003, "lon": -72.0,
         "tags": {"name": "Copyrighted Inn", "tourism": "hotel", "start_date": "1900", "license": "CC BY-SA 4.0"}},
        {"type": "relation", "id": 5, "tags": {"name": "Old Madeup Township", "boundary": "administrative",
                                               "start_date": "1790"}}]}
    path = tmp_path / "ohm.json"
    path.write_text(json.dumps(answer), encoding="utf-8")
    w = PackWriter(str(tmp_path / "o.osmpack"), 202611)
    assert ohm.read(str(path), entry_of("ohm"), dict(catalogue.regions()[VT]), w) == 2
    assert sorted(w.db.execute("SELECT key, name, type, first, last FROM points").fetchall()) == [
        ("ohm:n1", "Made-up Mill", "watermill", 182001, 191001),
        ("ohm:w2", "Invented Depot", "railway station", 188501, 202611)]


# ------------------------------------------------------------------------------------------- round-4 fetches


def test_ckan_sql_pages_a_grouped_query(monkeypatch, tmp_path):
    """A CKAN portal's grouped SQL is paged with LIMIT and OFFSET into one CSV (Boston's food licences)."""
    asked = []

    def answer(url, opener=None):
        import urllib.parse
        sql = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["sql"][0]
        asked.append(sql[-20:])
        records = {"OFFSET 0": [{"_id": 1, "key": "L1", "name": "Made-up Grill", "point": "(42.35, -71.06)"},
                                {"_id": 2, "key": "L2", "name": "Invented Cafe", "point": "(42.36, -71.05)"}],
                   "OFFSET 2": [{"_id": 3, "key": "L3", "name": "Pretend Deli", "point": "(42.37, -71.04)"}]}
        return {"result": {"records": records[sql[sql.index("OFFSET"):]]}}
    monkeypatch.setattr(fetch, "read_json", answer)
    entry = dict(entry_of("boston-food-establishments"))
    entry["fetch"] = dict(entry["fetch"], page=2, pause=0)
    got = fetch.fetch_ckan_sql(entry, str(tmp_path), False)
    assert got["ok"] and [a.split("LIMIT")[1].strip() for a in asked] == ["2 OFFSET 0", "2 OFFSET 2"]
    assert open(got["path"], encoding="utf-8").read().splitlines() == [
        "key,name,point", 'L1,Made-up Grill,"(42.35, -71.06)"', 'L2,Invented Cafe,"(42.36, -71.05)"',
        'L3,Pretend Deli,"(42.37, -71.04)"']


def test_several_files_of_one_source_are_split_with_their_columns(tmp_path):
    """StatCan's facility databases have different column names (Latitude or latitude, Prov_Terr or province):
    every file is split into one slice per province, with the columns the reader uses, and read back."""
    import zipfile
    from placepacks import split
    entry = entry_of("statcan-facilities")
    folder = tmp_path / "statcan-facilities"
    folder.mkdir()
    with zipfile.ZipFile(folder / "ODEF_v2.1.zip", "w") as z:
        z.writestr("ODEF_v2.1_EN/ODEF_v2_1.csv", "Index,Facility_Name,Facility_Type,Prov_Terr,Latitude,Longitude\n"
                                                  "e1,Madeup School,Public,ON,43.7,-79.4\n")
        z.writestr("ODEF_v2.1_EN/Table1_Data_Sources.csv", "Type,Data Provider\nOpen Data,Nobody\n")
    with zipfile.ZipFile(folder / "ODHF_v1.1.zip", "w") as z:
        z.writestr("ODHF_v1.1/odhf_v1.1.csv", "index,facility_name,odhf_facility_type,province,latitude,longitude\n"
                                              "1,Invented Clinic,hospitals,on,43.71,-79.41\n")
    regions = {k: v for k, v in catalogue.regions().items() if k == "ca-ontario"}
    assert split.split_tabular(entry, str(folder), str(tmp_path / "out"), regions) == {"ca-ontario": 2}
    w = PackWriter(str(tmp_path / "c.osmpack"), 202611)
    assert read_tabular(str(tmp_path / "out" / "ca-ontario" / "statcan-facilities"), entry,
                        dict(catalogue.regions()["ca-ontario"]), w) == 2
    assert sorted(w.db.execute("SELECT name, type FROM points").fetchall()) == [("Invented Clinic", "hospitals"),
                                                                                ("Madeup School", "public")]


# ------------------------------------------------------------------------------------------- round 5


def test_types_are_never_spoken(tmp_path):
    """The type is kept for future programs only: no phrase or description includes it."""
    p = pack(tmp_path / "s.osmpack", 202611, [("n1", "Made-up Pizza", "business", "pizza restaurant")])
    r = Finder(packs=[PackReader(p)], water=False).lookup(*SPOT)
    assert r.type == "pizza restaurant"
    for detail in ("area", "street", "address"):
        assert "pizza restaurant" not in r.phrase(detail)
    import inspect
    from placepacks.lookup import Result
    for name, fn in inspect.getmembers(Result, inspect.isfunction):
        assert "self.type" not in inspect.getsource(fn), name


def test_museum_disciplines_and_tourism_classes():
    """IMLS museum disciplines become types; historical societies (often a home) are left out; Wikidata's tourism
    classes are asked for in groups small enough for the service's time limit, with World Heritage Sites by their
    designation."""
    assert [types.table("mudf", d) for d in ("ART", "ZAW", "SCI", "BOT")] == [
        "art museum", "zoo", "science center", "botanical garden"]
    from placepacks.readers.tabular import class_of
    museums = entry_of("imls-museums")
    assert class_of(museums, "HSC") == ("", "") and class_of(museums, "ZAW") == ("park", "zoo")
    queries = wikidata.queries_for(catalogue.regions()[VT])
    assert all(q.count("wd:Q") <= wikidata.GROUP for q in queries) and "wdt:P1435" in queries[-1]
    for q in ("Q207694", "Q43501", "Q1825472", "Q34038", "Q40080", "Q156362", "Q18411786"):
        assert q in wikidata.CLASSES
    beach = entry_of("epa-beaches")
    import re
    assert re.sub(beach["name_strip"], "", "Madeup Town Beach - Location 2", flags=re.I) == "Madeup Town Beach"
    parks = entry_of("ontario-parks")
    assert re.sub(parks["name_strip"], "", "INVENTED LAKE PROVINCIAL PARK (RECREATIONAL CLASS)",
                  flags=re.I) == "INVENTED LAKE PROVINCIAL PARK"
