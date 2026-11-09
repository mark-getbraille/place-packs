"""Every Wikidata item with coordinates (tiles split on timeouts, the data-driven exclusions, homes kept only with a
heritage designation, GNIS copies left to GNIS), TIGER/Line landmarks typed by their MTFCC code with TIGER's
abbreviations written out and their history across vintages, and the round 11 entries. Offline: made-up fixtures."""

import json
import os
import sys

import shapefile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, types  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.readers import wikidata  # noqa: E402
from placepacks.readers.shapes import read as read_shapes  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
REGION = {"region_id": VT, "state": "Vermont", "country": "United States"}


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def row(q, name, cls, label, lat=44.0, lon=-72.0, **extra):
    """One SPARQL answer row."""
    b = {"item": {"value": f"http://www.wikidata.org/entity/{q}"}, "itemLabel": {"value": name},
         "coord": {"value": f"Point({lon} {lat})"}, "class": {"value": f"http://www.wikidata.org/entity/{cls}"},
         "classLabel": {"value": label}}
    for k, v in extra.items():
        b[k] = {"value": v}
    return b


def test_all_items_keep_places_and_leave_out_people_trees_homes_and_gnis_copies(tmp_path):
    rows = [row("Q9000001", "Made-up Covered Bridge", "Q1825472", "covered bridge", start="1870-01-01T00:00:00Z"),
            row("Q9000002", "Alice Example", "Q5", "human", lat=44.001),
            row("Q9000003", "Invented Oak", "Q811534", "remarkable tree", lat=44.002),
            row("Q9000004", "12 Pretend Street", "Q3947", "house", lat=44.003),
            row("Q9000005", "Old Example House", "Q3947", "house", lat=44.004, heritage="http://x/Q8"),
            row("Q9000006", "Pretend Brook", "Q47521", "stream", lat=44.005, gnis="1234"),
            row("Q9000007", "Fictional Brewpub", "Q3640372", "brewpub", lat=44.006),
            row("Q9000008", "List of made-up things", "Q13406463", "Wikimedia list article", lat=44.007),
            row("Q9000009", "Invented Mill", "Q99999999", "grist mill", lat=44.008),
            # An item in two rows (two classes): one of them a home, no designation: left out.
            row("Q9000010", "Made-up Farmhouse", "Q489357", "farmhouse", lat=44.009),
            row("Q9000010", "Made-up Farmhouse", "Q1307276", "single-family detached home", lat=44.009)]
    path = tmp_path / "wikidata.json"
    path.write_text(json.dumps({"results": {"bindings": rows}}), encoding="utf-8")
    w = PackWriter(str(tmp_path / "w.osmpack"), 202611)
    n = wikidata.read(str(path), entry_of("wikidata"), dict(catalogue.regions()[VT]), w)
    w.finish(REGION)
    got = {r["name"]: (r["cls"], r["type"], r["first"]) for r in PackReader(str(tmp_path / "w.osmpack"))
           .points_near(44.004, -72.0, 2000)}
    assert n == 4
    assert got == {"Made-up Covered Bridge": ("landmark", "covered bridge", 187001),
                   "Old Example House": ("landmark", "house", 202611),
                   "Fictional Brewpub": ("business", "brewpub", 202611),
                   "Invented Mill": ("landmark", "grist mill", 202611)}


def test_the_exclusions_are_data_with_checked_ids():
    data = json.load(open(os.path.join(ROOT, "placepacks", "wikidata_exclude.json"), encoding="utf-8"))
    assert data["exclude"]["Q5"] == "human" and data["homes"]["Q3947"] == "house"
    assert not set(data["exclude"]) & set(data["homes"])
    excluded, homes = wikidata.exclusions()
    assert "Q4167410" in excluded and "Q1307276" in homes


def test_restaurant_classes_are_known():
    for q in ("Q11707", "Q30022", "Q187456", "Q212198", "Q274393", "Q3640372", "Q1751429", "Q1226318"):
        assert wikidata.CLASSES[q] == "business"
    assert "Q18534542" not in wikidata.CLASSES          # a restaurant chain is a brand, not a place


def test_tiles_split_on_a_timeout_and_on_a_full_answer():
    """A tile that times out, or answers the row limit, is asked again as four quarters."""
    asked = []

    def ask(query):
        asked.append(query)
        if len(asked) == 1:
            raise TimeoutError("the service's 60-second limit")
        if len(asked) == 2:
            return [{"item": {"value": f"Q{i}"}} for i in range(10)]          # full: split again
        return [{"item": {"value": "Q1"}}]

    rows = fetch.wikidata_tiles(ask, [(-73.0, 43.0, -71.0, 45.0)], limit=10)
    assert len(asked) == 1 + 4 + 4 and len(rows) == 3 + 4       # timed out; 4 quarters; one full: 4 more
    assert "LIMIT 10" in asked[0] and "wikibase:box" in asked[0] and "P1435" in asked[0]
    assert "?gnis WHERE" in asked[0]


def test_big_regions_start_as_tiles():
    tiles = wikidata.first_tiles({"bbox": [-107.0, 25.0, -93.0, 37.0]})
    assert len(tiles) >= 64 and all((e - w) * (n - s) <= wikidata.ALL_TILE for w, s, e, n in tiles)
    assert wikidata.first_tiles({"bbox": [-72.5, 44.0, -71.5, 45.0]}) == [(-72.5, 44.0, -71.5, 45.0)]


def landmarks(path, rows):
    """A made-up TIGER point landmark file: rows [(id, name, mtfcc, lon, lat)]."""
    with shapefile.Writer(str(path), shapeType=shapefile.POINT) as w:
        for field in ("POINTID", "FULLNAME", "MTFCC"):
            w.field(field, "C", 40)
        for pid, name, code, lon, lat in rows:
            w.point(lon, lat)
            w.record(pid, name, code)
    return str(path) + ".shp"


def test_tiger_landmarks_are_typed_named_in_full_and_homes_left_out(tmp_path):
    shp = landmarks(tmp_path / "tl_2025_50_pointlm", [
        ("1", "Madeup Hosp", "K1231", -72.0, 44.0), ("2", "Invented Colg", "K2540", -72.0, 44.001),
        ("3", "Pretend Apartments", "K1121", -72.0, 44.002), ("4", "Mt Example", "C3022", -72.0, 44.003),
        ("5", "Survey Mark 7", "C3080", -72.0, 44.004)])
    w = PackWriter(str(tmp_path / "t.osmpack"), 202611)
    assert read_shapes(shp, entry_of("tiger-pointlm"), dict(catalogue.regions()[VT]), w) == 3
    w.finish(REGION)
    got = {r["name"]: (r["cls"], r["type"]) for r in PackReader(str(tmp_path / "t.osmpack"))
           .points_near(44.002, -72.0, 1000)}
    assert got == {"Madeup Hospital": ("public", "hospital"), "Invented College": ("campus", "college or university"),
                   "Mount Example": ("nature", "summit")}


def test_a_landmark_gone_from_a_later_vintage_keeps_its_last_seen_year(tmp_path):
    entry = entry_of("tiger-pointlm")
    prev = None
    for year, rows in ((2014, [("1", "Old Madeup Sch", "K2543", -72.0, 44.0), ("2", "Invented Ch", "K3544", -72.0, 44.001)]),
                       (2017, [("2", "Invented Ch", "K3544", -72.0, 44.001)])):
        folder = tmp_path / str(year)
        folder.mkdir()
        w = PackWriter(str(tmp_path / f"{year}.osmpack"), year * 100 + 1)
        read_shapes(landmarks(folder / f"tl_{year}_50_pointlm", rows), entry, dict(catalogue.regions()[VT]), w)
        w.finish(REGION, previous=prev)
        prev = str(tmp_path / f"{year}.osmpack")
    got = {r["name"]: (r["first"], r["last"]) for r in PackReader(prev).points_near(44.0, -72.0, 500)}
    assert got["Old Madeup School"] == (201401, 201401) and got["Invented Church"][0] == 201401
    f = Finder(packs=[PackReader(prev)], water=False)
    assert f.lookup(44.0, -72.0, when="2014-06-01").name == "Old Madeup School"


def test_tiger_landmarks_are_seeded_with_the_address_ranges():
    settings = catalogue.load()["settings"]
    assert {"tiger-addrfeat", "tiger-pointlm", "tiger-arealm", "tiger-mil"} <= set(settings["tiger_seed_sources"])
    workflow = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert "tiger_seed_sources" in workflow and '--only "$SEED"' in workflow


def test_names_are_written_out_and_rearranged():
    assert types.expand_words("Radford Army Ammunition Plnt", "tiger_words") == "Radford Army Ammunition Plant"
    assert types.expand_words("St Michaels Ch", "tiger_words") == "St Michaels Church"
    ports = entry_of("usace-principal-ports")
    assert types.rename(ports, "South Louisiana, LA, Port of") == "Port of South Louisiana"
    assert types.rename(ports, "Central Louisiana Regional, LA") == "Central Louisiana Regional Port"
    assert types.rename({"name_replace": [["(?i)\\s+of Canada$", ""]]}, "Banff National Park Of Canada") == "Banff National Park"


def test_round_eleven_sources_are_open_and_rejections_are_listed():
    cat = catalogue.load()
    for sid in ("tiger-pointlm", "tiger-arealm", "tiger-mil", "fws-fish-hatcheries", "usfs-offices", "noaa-nerrs",
                "usace-principal-ports", "ny-thruway-travel-plazas", "ny-thruway-park-and-ride",
                "ny-farmers-markets", "pa-park-and-ride", "bc-rec-sites", "alltheplaces"):
        assert entry_of(sid)["licence"] in catalogue.ALLOWED, sid
    rejected = " ".join(r["name"] for r in cat["rejected"])
    for name in ("Ontario Heritage Trust", "DBpedia", "Wikimapia", "National Hydro Network"):
        assert name in rejected
    assert "INTTYPE1 IN ('O','S')" in entry_of("fws-fish-hatcheries")["fetch"]["where"]     # no easements
