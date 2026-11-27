"""The navigation part (placepacks/navigation.py, readers/navigation.py, navigate.py): the street network with its
intersections, crossings and accessibility details from OpenStreetMap, and the GTFS timetables, with the lookups
"what is the nearest intersection", "how do I cross here" and "the next bus from the nearest stop". Offline: the
made-up street corner and feed of tests/samples.py only."""

import datetime
import json
import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import samples  # noqa: E402
from placepacks import build, catalogue, download, fetch, fmt, manifest, navigation  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.navigate import Navigator, crossing_facts, service_runs  # noqa: E402
from placepacks.readers import navigation as nav_readers  # noqa: E402

VT = "us-vermont"
CORNER = (44.0005, -72.0000)


def build_pack(tmp_path):
    """Build the made-up navigation pack; returns its path."""
    fetched = {"osm-navigation": {"ok": True, "path": samples.nav_osm_file(str(tmp_path)), "version": "test"},
               "gtfs-navigation": {"ok": True, "path": samples.nav_gtfs_folder(str(tmp_path / "gtfs")),
                                   "version": "mdb-9999"}}
    out = str(tmp_path / "us-vermont-navigation.osmpack")
    build.build(VT, "navigation", fetched, out, removal_list=[])
    return out


@pytest.fixture()
def pack(tmp_path):
    """The made-up navigation pack, built once per test."""
    return build_pack(tmp_path)


def navigator(path):
    """A Navigator over one pack."""
    return Navigator(packs=[PackReader(path)])


def test_the_navigation_part_and_its_sources_are_in_the_catalogue():
    assert "navigation" in fmt.PARTS and "navigation" not in fmt.DEFAULT_PARTS + fmt.DETAIL_PARTS
    cat = catalogue.load()
    assert catalogue.check(cat) == []
    entries = {e["id"]: e for e in catalogue.sources_for(catalogue.regions()[VT], "navigation", cat)}
    # street-access-navigation: cities' accessible pedestrian signals and curb ramps (queue item Q4)
    assert set(entries) == {"osm-navigation", "gtfs-navigation", "street-access-navigation"}
    assert entries["osm-navigation"]["licence"] == "ODbL-1.0"          # share-alike, like the core OSM layer
    assert entries["osm-navigation"]["fetch"] == {"method": "same_as", "same_as": "osm"}
    assert entries["gtfs-navigation"]["fetch"]["same_as"] == "gtfs"
    assert build.pack_name(VT, "navigation") == "us-vermont-navigation.osmpack"
    assert manifest.split_key("us-vermont-navigation") == (VT, "navigation")
    assert manifest.release_for("navigation", datetime.date(2026, 12, 2)) == "packs-detail-20261202"
    assert download.parts_for("navigation") == ("core", "extra", "navigation")
    assert build.previous_files(VT, "navigation", "/nowhere") == []


def test_a_share_alike_source_outside_the_osm_layers_is_refused():
    cat = json.loads(json.dumps(catalogue.load()))
    e = next(x for x in cat["accepted"] if x["id"] == "gtfs-navigation")
    e["licence"] = "ODbL-1.0"
    assert any("share-alike" in p for p in catalogue.check(cat))
    e["licence"], e["fetch"]["same_as"] = "per-feed-open", "nothing-like-this"
    assert any("same_as" in p for p in catalogue.check(cat))


def test_fetch_reuses_the_osm_and_gtfs_downloads(tmp_path, monkeypatch):
    calls = []

    def fake_run(entry, region, cat, work, national, fingerprint):
        calls.append(entry["id"])
        return {"ok": True, "path": f"/x/{entry['id']}", "version": "v1"}
    monkeypatch.setattr(fetch, "run_with_limit", fake_run)
    monkeypatch.setattr(fetch, "run_parallel", lambda rest, *a: ((e, fake_run(e, *a[:5])) for e in rest))
    monkeypatch.setattr(fetch, "extract_bbox", lambda path: None)
    got = fetch.fetch_region(VT, str(tmp_path), parts=("navigation",), only={"osm-navigation", "gtfs-navigation"})
    assert sorted(calls) == ["gtfs", "osm"]                             # downloaded once, by their own sources
    assert got["osm-navigation"]["path"] == "/x/osm" and got["gtfs-navigation"]["path"] == "/x/gtfs"


def test_the_pack_holds_segments_intersections_features_and_timetables(pack):
    con = sqlite3.connect(pack)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    assert meta["part"] == "navigation" and meta["format"] == fmt.PACK_FORMAT
    assert "OpenStreetMap" in meta["notice"] and "ODbL" in meta["notice"]
    ways = dict(con.execute("SELECT key, kind FROM nav_ways"))
    assert ways == {"w200": "residential", "w201": "tertiary", "w202": "footway", "w203": "steps"}  # no driveway
    assert json.loads(con.execute("SELECT tags FROM nav_ways WHERE key = 'w200'").fetchone()[0]) == {
        "sidewalk": "both", "surface": "asphalt", "lit": "yes"}
    assert con.execute("SELECT key, streets, signals FROM nav_intersections").fetchall() == [
        ("n20", '["Elm Street", "Main Street"]', 1)]
    kinds = sorted(r[0] for r in con.execute("SELECT kind FROM nav_features"))
    assert kinds == ["accessible place", "bus stop", "crossing", "crossing", "entrance", "kerb", "steps",
                     "traffic signals"]
    assert con.execute("SELECT streets FROM nav_features WHERE key = 'n25'").fetchone()[0] == \
        '["Main Street", "footway"]'
    assert con.execute("SELECT name, code, wheelchair FROM nav_stops ORDER BY name").fetchall() == [
        ("Far Away", "102", 2), ("Made-up Station", "", 1), ("Main St & Elm St", "101", 1)]   # not "Somewhere else"
    assert con.execute("SELECT COUNT(*) FROM nav_times").fetchone()[0] == 5
    assert con.execute("SELECT feed, provider, licence_url, timezone FROM nav_feeds").fetchall() == [
        ("mdb-9999", "Made-up Transit", "https://creativecommons.org/licenses/by/4.0/", "America/New_York")]
    sources = {r[0]: r[1] for r in con.execute("SELECT id, licence FROM sources")}
    assert sources == {"osm-navigation": "ODbL-1.0", "gtfs-navigation": "per-feed-open",
                       "street-access-navigation": "government-facts"}
    assert not {"nav_tmp_names", "nav_tmp_on"} & {r[0] for r in con.execute("SELECT name FROM sqlite_master")}


def test_the_xml_and_the_osmium_readers_agree(tmp_path):
    pytest.importorskip("osmium")
    results = []
    for use in (False, True):
        from placepacks.writer import PackWriter
        w = PackWriter(str(tmp_path / f"{use}.osmpack"))
        nav_readers.read_osm(samples.nav_osm_file(str(tmp_path)), {"id": "osm-navigation"}, {}, w, use_osmium=use)
        w.finish({"part": "navigation"})
        con = sqlite3.connect(str(tmp_path / f"{use}.osmpack"))
        results.append([con.execute(f"SELECT * FROM {t} ORDER BY key").fetchall()
                        for t in ("nav_ways", "nav_intersections", "nav_features")])
    assert results[0] == results[1]


def test_nearest_intersection(pack):
    nav = navigator(pack)
    r = nav.nearest_intersection(44.0008, -71.9998)
    assert r["streets"] == ["Elm Street", "Main Street"] and r["signals"] is True and r["bearing"] == "southwest"
    assert r["phrase"] == "Elm Street and Main Street, 35 metres southwest, with traffic signals."
    assert nav.nearest_intersection(*CORNER)["phrase"].startswith("At Elm Street and Main Street")
    assert "feet" in nav.nearest_intersection(44.0008, -71.9998, units="miles")["phrase"]
    assert nav.nearest_intersection(44.03, -72.03) is None             # nothing within 400 m


def test_how_do_i_cross_here(pack):
    r = navigator(pack).crossing_here(44.00045, -72.00025)
    assert r["type"] == "traffic_signals" and r["street"] == "Main Street"
    assert r["signals"] and r["sound"] and r["vibration"] and r["button"] and r["tactile_paving"]
    assert r["kerb"] == "lowered" and r["markings"] == "zebra"
    assert r["phrase"].startswith("A crossing with traffic signals over Main Street")
    assert "push button" in r["phrase"] and "accessible pedestrian signal" in r["phrase"]
    assert "Tactile paving: yes." in r["phrase"] and "Kerb: lowered." in r["phrase"]
    assert navigator(pack).crossing_here(44.03, -72.03) is None


def test_crossing_facts_say_unknown_when_the_map_does_not():
    f = crossing_facts({"highway": "crossing"})
    assert f["type"] is None and f["signals"] is None and f["sound"] is None and f["tactile_paving"] is None
    assert crossing_facts({"crossing": "uncontrolled"})["signals"] is False
    assert crossing_facts({"crossing": "marked", "traffic_signals:sound": "no"})["sound"] is False


def test_features_and_the_street_here(pack):
    nav = navigator(pack)
    near = nav.features_near(44.0009, -71.9986, 30, {"entrance", "steps", "accessible place"})
    assert [f["kind"] for f in near][0] == "entrance" and near[0]["tags"]["wheelchair"] == "yes"
    cafe = nav.features_near(44.0003, -71.9990, 5, {"accessible place"})[0]
    assert cafe["name"] == "Made-up Café" and cafe["tags"]["wheelchair"] == "yes"
    here = nav.street_here(44.00052, -72.0010)
    assert here["name"] == "Main Street" and here["sidewalk"] == "both"
    assert here["phrase"] == "On Main Street. Sidewalks on both sides. Surface: asphalt. Lit at night."
    steps = nav.street_here(44.0012, -71.9989)
    assert steps["kind"] == "steps" and "12 steps." in steps["phrase"] and "Handrail." in steps["phrase"]


def test_the_next_bus_from_the_nearest_stop(pack):
    nav = navigator(pack)
    monday = datetime.datetime(2026, 11, 23, 8, 0)
    r = nav.next_buses(44.0006, -71.9999, when=monday)
    assert r["stop"] == "Main St & Elm St" and r["wheelchair_boarding"] == 1
    assert [(d["route"], d["time"], d["minutes"], d["wheelchair"]) for d in r["departures"]] == [
        ("7", "08:05", 5, 1), ("7", "08:35", 35, 2)]
    assert "Bus 7 to Downtown at 08:05, in 5 minutes, wheelchair accessible." in r["phrase"]
    assert "It has a shelter and a bench. No tactile paving." in r["phrase"]
    assert "Made-up Transit" in r["attribution"] and "creativecommons.org" in r["attribution"]
    # Thursday 26 November has no weekday service; Saturday 28 November has both the Saturday trip and an added run.
    assert nav.next_buses(44.0006, -71.9999, when=datetime.datetime(2026, 11, 26, 7, 0))["departures"] == []
    sat = nav.next_buses(44.0006, -71.9999, when=datetime.datetime(2026, 11, 28, 7, 0))
    assert [d["time"] for d in sat["departures"]] == ["08:05", "08:35", "09:00"]
    # A trip of Monday's timetable at 25:10 leaves at 01:10 on Tuesday morning.
    late = nav.next_buses(44.0006, -71.9999, when=datetime.datetime(2026, 11, 24, 0, 30))
    assert [(d["headsign"], d["time"]) for d in late["departures"]] == [("Night Loop", "01:10")]
    assert nav.next_buses(10.5, 10.5) is None


def test_service_runs():
    assert service_runs((0b0011111, 20261101, 20270131), datetime.date(2026, 11, 23), {})
    assert not service_runs((0b0011111, 20261101, 20270131), datetime.date(2026, 11, 22), {})
    assert not service_runs((0b0011111, 20261101, 20270131), datetime.date(2027, 3, 1), {})
    assert service_runs((0, 0, 0), datetime.date(2026, 11, 28), {20261128: 1})


def test_a_navigation_pack_does_not_disturb_the_place_lookups(pack):
    r = Finder(packs=[PackReader(pack)], water=False).lookup(*CORNER)      # an empty places layer: no answer, no error
    assert not r.name
    assert navigation.feature_kind({"highway": "bus_stop"}) == "bus stop"
    assert navigation.way_kind({"highway": "service", "service": "driveway"}) is None
    assert navigation.way_kind({"highway": "service", "service": "driveway", "name": "Mill Lane"}) == "service"
    assert navigation.way_kind({"highway": "footway", "access": "private"}) is None
