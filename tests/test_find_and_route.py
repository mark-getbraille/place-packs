"""Finding the nearest place of any kind (placepacks/find.py: types with plain words and synonyms, places of worship
by religion and denomination, offices, polling places with their election date) and offline directions over the
navigation part's network (placepacks/route.py: walking with cross streets and crossings, driving with one-way
streets, a direct transit ride). Offline: the made-up town of tests/samples.py only."""

import datetime
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import samples  # noqa: E402
from placepacks import build, types  # noqa: E402
from placepacks.find import Finder, find_nearest, phrases_for, plain, resolve_start  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.navigate import Navigator  # noqa: E402
from placepacks.route import directions, length_words, turn_words  # noqa: E402

VT = "us-vermont"
START = (44.0000, -72.0029)                     # on Main Street, near its west end


@pytest.fixture(scope="module")
def town(tmp_path_factory):
    """The core, navigation and services packs of the made-up town (with the made-up 2020 polling places)."""
    folder = tmp_path_factory.mktemp("town")
    osm = samples.route_osm_file(str(folder))
    nad = samples.nad_file(str(folder), [("12", "Main St", "Testville", "VT", 44.0001, -72.0029)])
    parts = {"core": {"osm": {"ok": True, "path": osm}},
             "navigation": {"osm-navigation": {"ok": True, "path": osm}},
             "services": {"osm-services": {"ok": True, "path": osm}, "nad": {"ok": True, "path": nad},
                          "cpi-polling-places": {"ok": True, "path": samples.polling_folder(str(folder / "poll"))}}}
    for part, fetched in parts.items():
        build.build(VT, part, fetched, str(folder / f"{part}.osmpack"), removal_list=[])
    return [PackReader(str(folder / f"{p}.osmpack")) for p in parts]


def test_plain_words_and_synonyms():
    assert plain("Where's the nearest hardware store?") == "hardware store"
    assert plain("the nearest pharmacies") == "pharmacy" and plain("groceries") == "grocery"
    assert "home improvement store" in phrases_for("hardware store")
    assert phrases_for("drugstore")[0] == "pharmacy" and phrases_for("grocery")[0] == "supermarket"
    assert phrases_for("bicycle", {"bicycle shop", "bicycle rental", "bakery"}) == ["bicycle", "bicycle shop",
                                                                                   "bicycle rental"]


def test_synagogues_with_a_denomination_are_synagogues():
    assert types.osm({"amenity": "place_of_worship", "religion": "jewish", "denomination": "orthodox"}) == "synagogue"
    assert types.osm({"amenity": "place_of_worship", "religion": "christian", "denomination": "orthodox"}) == \
        "orthodox church"


def test_places_of_worship_by_religion_and_denomination(town):
    f = Finder(packs=town)
    assert f.nearest("Catholic church", *START)[0]["name"] == "Saint Pretend Church"
    assert f.nearest("nearest mosque", *START)[0]["name"] == "Made-up Masjid"
    assert f.nearest("synagogue", *START)[0]["name"] == "Beth Pretend"
    assert f.nearest("church", *START)[0]["type"] == "catholic church"
    assert f.nearest("Baptist church", *START) == []


def test_find_the_nearest_hardware_store_with_walking_directions(town):
    r = find_nearest("where's the nearest hardware store?", START, packs=town)
    p = r["place"]
    assert p["name"] == "Made-up Hardware" and p["type"] == "hardware store"
    assert (p["phone"], p["opening_hours"], p["wheelchair"]) == ("+1 802 555 0199", "Mo-Sa 08:00-18:00", "yes")
    assert r["directions"]["steps"] == [
        "Walk east on Main Street for 1 block, about 260 feet, to Oak Street.",
        "Cross Oak Street at the signal; the crossing has tactile paving, a push button, a talking or vibrating "
        "signal and a curb cut.",
        "Continue east on Main Street for 1 block, about 260 feet, to Elm Street.",
        "Turn left onto Elm Street and walk north for 1 block, about 360 feet, to Pine Street.",
        "Cross Pine Street.",
        "Continue north on Elm Street for about 360 feet.",
        "Made-up Hardware is about 60 feet away, on your right."]
    assert "Phone +1 802 555 0199. Hours: Mo-Sa 08:00-18:00. Step-free access. Walking: about 0.3 miles" in r["phrase"]
    assert find_nearest("DIY", START, packs=town)["place"]["name"] == "Made-up Hardware"
    assert "metres" in find_nearest("hardware store", START, packs=town, units="metres")["phrase"]


def test_driving_respects_one_way_streets(town):
    nav = Navigator(packs=town)
    church = (44.0011, -72.0025)
    walk = directions(nav, (44.0010, -72.0011), church, mode="walk")
    drive = directions(nav, (44.0010, -72.0011), church, mode="drive")
    assert walk["steps"][0].startswith("Walk west on Pine Street")          # walking may go against the one-way
    assert "Pine Street" not in drive["steps"][0] and drive["steps"][0].startswith("Drive south on Elm Street")
    assert drive["distance_m"] > walk["distance_m"]


def test_starts_by_intersection_and_address(town, tmp_path):
    assert resolve_start("Main Street and Oak Street", town) == (44.0, -72.002)
    assert resolve_start("Oak St & Main St", town) == (44.0, -72.002)
    assert resolve_start("Nowhere Lane and Oak Street", town) is None
    w_path = str(tmp_path / "addr.osmpack")
    from placepacks.writer import PackWriter
    w = PackWriter(w_path)
    w.add_address("nad", "12", "Main St", "Testville", 44.0001, -72.0029)
    w.finish({"part": "addresses"})
    assert resolve_start("12 Main Street, Testville", [PackReader(w_path)]) == (44.0001, -72.0029)
    assert find_nearest("hardware store", "1 Nowhere Road", packs=town)["place"] is None


def test_polling_places_always_carry_their_election_date(town):
    rows = town[2].con.execute("SELECT name, election_date, located, lat IS NOT NULL FROM svc_polling "
                               "ORDER BY name").fetchall()
    assert rows == [("Nexttown School", "2020-11-03", "not located", 0), ("Testville Town Hall", "2020-11-03",
                                                                           "address", 1)]
    r = find_nearest("polling place", START, packs=town)
    assert r["place"]["name"] == "Testville Town Hall" and r["place"]["election_date"] == "2020-11-03"
    assert "general election of 2020-11-03" in r["phrase"] and "polling places change" in r["phrase"]


def test_a_direct_transit_ride(tmp_path):
    out = str(tmp_path / "nav.osmpack")
    feed = samples.nav_gtfs_folder(str(tmp_path / "g"))
    build.build(VT, "navigation", {"gtfs-navigation": {"ok": True, "path": feed}}, out, removal_list=[])
    nav = Navigator(packs=[PackReader(out)])
    r = directions(nav, (44.0007, -71.9998), (44.0301, -72.0301), mode="transit",
                   when=datetime.datetime(2026, 11, 23, 8, 0), to_name="the far place")
    assert r["mode"] == "transit" and r["departure"] == "08:05" and r["route"] == "7"
    assert r["steps"][1] == "Take bus 7 toward Downtown at 08:05 (wheelchair accessible)."
    assert r["steps"][2] == "Ride 1 stop to Far Away, arriving at 08:20."


def test_words():
    assert length_words(80) == "about 260 feet" and length_words(1609.344) == "about 1.0 miles"
    assert length_words(160, blocks=2) == "2 blocks, about 520 feet,"
    assert turn_words(0, 90) == "turn right" and turn_words(90, 0) == "turn left" and turn_words(0, 10) == "continue"
    assert turn_words(0, 40) == "turn slightly right" and turn_words(0, 180) == "make a U-turn"
