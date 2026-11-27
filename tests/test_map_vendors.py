"""Campus and indoor maps (placepacks/mapvendors): the vendor registry's fingerprints, the discovery chain (IPEDS
and Wikidata seeds, scanning an organisation's homepage and map pages with robots.txt obeyed, blocked sites, unknown
vendors written to the notes file, the month's list), the MazeMap collector, the Concept3D collector stopping at
its API's robots.txt (and reading when allowed), the campus GIS collector, the run and publish wiring, the catalogue
entry and the workflow's shape. Offline: every site, map, building, id and number here is made up; a stand-in web
answers."""

import csv
import datetime
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, features  # noqa: E402
from placepacks.chains.polite import Blocked, Polite  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.mapvendors import campus_gis, concept3d, discover, mazemap, registry  # noqa: E402

from test_web_details import workflow_shape  # noqa: E402

TODAY = datetime.date(2026, 12, 8)


class Web:
    """A stand-in web: {url or url prefix: (status, body)}; records the URLs asked."""

    def __init__(self, pages):
        """pages: {url: (status, text or bytes or dict)}; a dict is sent as JSON."""
        self.pages, self.asked = pages, []

    def __call__(self, request, timeout):
        """The Polite opener: (status, headers, body)."""
        url = request.full_url
        self.asked.append(url)
        hit = self.pages.get(url)
        if hit is None:
            hit = next((v for k, v in sorted(self.pages.items(), key=lambda kv: -len(kv[0])) if url.startswith(k)),
                       (404, "not found"))
        status, body = hit
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        return status, {"Content-Type": "text/html; charset=utf-8"}, body if isinstance(body, bytes) else \
            body.encode("utf-8")


def client(web, budget=500):
    """A polite client on the stand-in web that never sleeps."""
    return Polite(budget, 1.0, opener=web, sleep=lambda s: None, agent=discover.USER_AGENT)


def test_fingerprints_and_unknown_embeds():
    """Concept3D and MazeMap map ids from embeds and links; an Indoors viewer's app id; a plain Google map is not a
    vendor; an iframe of an unknown map host is kept as unknown, a font CDN is not."""
    page = ('<iframe src="https://map.concept3d.com/?id=1130#!ct/1234"></iframe>'
            '<a href="https://use.mazemap.com/#v=1&campusid=212&zlevel=1">Indoor map</a>'
            '<a href="https://madeup.maps.arcgis.com/apps/indoorviewer/index.html?appid=0123456789abcdef0123456789abcdef">'
            'x</a><iframe src="https://www.google.com/maps/embed?pb=1"></iframe>'
            '<iframe src="https://maps.newvendor.example/embed/77"></iframe>'
            '<script src="https://fonts.example.net/kit.js"></script>')
    got = {(f["vendor"], f["map_id"]) for f in registry.fingerprints(page, "https://www.madeup.edu/map")}
    assert got == {("concept3d", "1130"), ("mazemap", "212"),
                   ("esri-indoors", "0123456789abcdef0123456789abcdef")}
    unknown = registry.unknown_embeds(page, "https://www.madeup.edu/map", page_is_map=True)
    assert [u["host"] for u in unknown] == ["maps.newvendor.example"]
    assert registry.fingerprints("<p>vid=12 is a video</p>") == []
    assert registry.collectors() == {"concept3d": "concept3d", "mazemap": "mazemap", "locuslabs": "atrius"}
    # The owner decided on 27 November 2026 to collect Concept3D despite its robots.txt.
    assert registry.VENDORS["concept3d"]["data"] == "public"
    assert registry.VENDORS["concept3d"].get("robots_override") is True


def hd_zip():
    """A made-up IPEDS HD file (bytes) with two active colleges and a closed one."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["UNITID", "INSTNM", "CHFNM", "WEBADDR", "LATITUDE", "LONGITUD", "CYACTIVE"])
    w.writerow(["999001", "Madeup State College", "Alice Example", "www.madeup.edu/", "44.002", "-72.002", "1"])
    w.writerow(["999002", "Blocked University", "Bob Example", "blocked.example.edu", "44.1", "-72.1", "1"])
    w.writerow(["999003", "Closed College", "Carol Example", "closed.example.edu", "44.2", "-72.2", "2"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("hd2025.csv", "﻿" + buf.getvalue())
    return out.getvalue()


def site_web():
    """The made-up colleges' sites: one with a campus map page holding a MazeMap embed and an unknown vendor's
    iframe, one that refuses."""
    return Web({
        "https://www.madeup.edu/robots.txt": (200, "User-agent: *\nDisallow: /private/\n"),
        "https://www.madeup.edu/": (200, '<a href="/visit/campus-map">Campus Map</a> <a href="/private/map">Map</a>'
                                         '<a href="/news">News</a> <a href="https://other.example/map">Map</a>'),
        "https://www.madeup.edu/visit/campus-map": (200, '<iframe src="https://use.mazemap.com/embed.html#v=1&'
                                                         'campusid=212"></iframe><iframe src="https://wayfind.'
                                                         'newvendor.example/m/9"></iframe>'),
        "https://blocked.example.edu/robots.txt": (403, "<title>Just a moment...</title>"),
    })


def test_discovery_scans_and_records(tmp_path, monkeypatch):
    """The IPEDS seeds (active colleges only, never a person's name); a scan finds MazeMap on the campus map page
    (robots.txt obeyed: the disallowed page is never read; another site's link is not followed), keeps the unknown
    vendor, records the refusing site as blocked; merge makes the list, and the new vendor's line is appended to
    the notes file once."""
    orgs = discover.ipeds_orgs(hd_zip())
    assert [o["place_key"] for o in orgs] == ["nces-postsecondary:999001", "nces-postsecondary:999002"]
    assert "Example" not in json.dumps(orgs)
    web = site_web()
    monkeypatch.setattr(discover, "COLLEGE_SHARDS", 1)          # one shard holds both colleges
    result = discover.scan_shard("colleges-1", str(tmp_path / "found"), client=client(web), today=TODAY,
                                 get_bytes=lambda c: hd_zip(), log=lambda *a: None)
    assert "https://www.madeup.edu/private/map" not in web.asked and "https://other.example/map" not in web.asked
    assert [(f["vendor"], f["map_id"], f["place_key"]) for f in result["found"]] == \
        [("mazemap", "212", "nces-postsecondary:999001")]
    assert [u["host"] for u in result["unknown"]] == ["wayfind.newvendor.example"]
    assert result["blocked"][0]["org"] == "Blocked University"
    listing = discover.merge([result], {"maps": [{"vendor": "concept3d", "map_id": "5", "last_seen": "2026-11-08",
                                                  "first_seen": "2026-10-08"},
                                                 {"vendor": "mazemap", "map_id": "1", "last_seen": "2025-01-01"}]},
                             today=TODAY)
    assert [(m["vendor"], m["map_id"]) for m in listing["maps"]] == [("concept3d", "5"), ("mazemap", "212")]
    assert listing["maps"][1]["first_seen"] == "2026-12-08"
    lines = discover.new_vendor_lines(listing, {})
    assert len(lines) == 1 and "wayfind.newvendor.example" in lines[0] and "Madeup State College" in lines[0]
    notes = tmp_path / "new-map-vendors.txt"
    assert len(discover.append_notes(lines, str(notes))) == 1
    assert discover.append_notes(lines, str(notes)) == []
    assert notes.read_text().count("vendor host: wayfind.newvendor.example") == 1
    assert discover.maps_of("mazemap", listing)[0]["map_id"] == "212"


def test_wikidata_seeds_and_shards():
    """Wikidata's hospitals and venues: positions from the coordinate, each item once; the shards split the lists."""
    answer = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q999901"}, "itemLabel": {"value": "Madeup General Hospital"},
         "site": {"value": "https://www.madeuphospital.example/"}, "coord": {"value": "Point(-72.01 44.01)"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q999901"}, "itemLabel": {"value": "Madeup General Hospital"},
         "site": {"value": "https://www.madeuphospital.example/other"}, "coord": {"value": "Point(-72.01 44.01)"}}]}}
    web = Web({discover.WDQS: (200, answer)})
    orgs = discover.wikidata_orgs(client(web), ["hospital"])
    assert orgs == [{"org": "Madeup General Hospital", "kind": "hospital", "homepage": "https://www.madeuphospital.example",
                     "place_key": "wikidata:Q999901", "lat": "44.01", "lon": "-72.01"}]
    shards = [s["shard"] for s in discover.shard_list()]
    assert "colleges-8" in shards and "health-3" in shards and "showcase" in shards and len(shards) <= 256


MAZE = "https://api.mazemap.com/api/"


def maze_web():
    """A made-up MazeMap campus with two buildings and POIs: an elevator, an accessible toilet, an entrance, an
    office (never kept) and a room named after a person (never kept)."""
    poly = {"type": "Polygon", "coordinates": [[[-72.0030, 44.0010], [-72.0020, 44.0010], [-72.0020, 44.0020],
                                                [-72.0030, 44.0020], [-72.0030, 44.0010]]]}

    def poi(pid, title, types, lon, lat, building=7, floor="1", kind="point"):
        """One POI."""
        return {"poiId": pid, "kind": kind, "title": title, "types": [{"name": t} for t in types],
                "point": {"type": "Point", "coordinates": [lon, lat]}, "buildingId": building, "floorName": floor,
                "description": "Push-button door. Contact bob@example.edu", "deleted": False}
    return Web({
        f"{MAZE}campus/212/?srid=4326": (200, {"campusId": 212, "name": "Madeup Campus", "wheelchair": True,
                                               "center": {"type": "Point", "coordinates": [-72.002, 44.002]}}),
        f"{MAZE}buildings/?campusid=212&srid=4326": (200, {"buildings": [
            {"id": 7, "name": "Smith Hall", "fullOutline": poly}, {"id": 8, "name": "", "fullOutline": poly}]}),
        f"{MAZE}campus/212/pois/?fromid=0&srid=4326": (200, {"limit": 3, "pois": [
            poi(1, "Elevator A", ["Elevator"], -72.0025, 44.0015),
            poi(2, "Toilet", ["Accessible toilet"], -72.0026, 44.0016, floor="2"),
            poi(3, "Main door", ["Entrance"], -72.0021, 44.0011)]}),
        f"{MAZE}campus/212/pois/?fromid=4&srid=4326": (200, {"limit": 3, "pois": [
            poi(4, "Office 101", ["Office"], -72.0025, 44.0015, kind="room"),
            poi(5, "Dr Alice Example", ["Faculty office"], -72.0025, 44.0015, kind="room")]}),
    })


def test_mazemap_collector():
    """The campus as a site row with its discovery place_key, its named building, and only the POIs whose type names
    a kind (elevator, accessible toilet, entrance) with their floor and building; offices and people never; a note
    without the e-mail."""
    listing = {"maps": [{"vendor": "mazemap", "map_id": "212", "org": "Madeup State College",
                         "place_key": "nces-postsecondary:999001", "lat": "44.002", "lon": "-72.002",
                         "homepage": "https://www.madeup.edu"}]}
    stats = {}
    rows = list(mazemap.collect(client(maze_web()), "mazemap", stats, listing))
    kinds = {r["key"]: r["kind"] for r in rows}
    assert kinds == {"mazemap:212": "site", "mazemap:212:b:7": "building", "mazemap:212:poi:1": "elevator",
                     "mazemap:212:poi:2": "accessible restroom", "mazemap:212:poi:3": "entrance"}
    toilet = next(r for r in rows if r["key"] == "mazemap:212:poi:2")
    assert toilet["level"] == "2" and toilet["building"] == "mazemap:212:b:7"
    assert "example.edu" not in json.dumps(rows) and "Alice" not in json.dumps(rows)
    assert rows[0]["place_key"] == "nces-postsecondary:999001" and "wheelchair routes" in rows[0]["notes"]
    assert stats["features"] == 3 and stats["buildings"] == 1


def test_concept3d_stops_at_robots_and_reads_when_allowed(monkeypatch):
    """While api.concept3d.com's robots.txt disallows programs the collector reads nothing and is blocked; with
    robots allowing it, the categories map locations to kinds (people and offices never) and the accessibility
    locations get their descriptions as notes."""
    listing = {"maps": [{"vendor": "concept3d", "map_id": "1130", "org": "Madeup State College",
                         "place_key": "nces-postsecondary:999001", "lat": "44.002", "lon": "-72.002"}]}
    # Without the owner's override (as before 27 November 2026), a disallowing robots.txt blocks it.
    monkeypatch.setitem(registry.VENDORS["concept3d"], "robots_override", False)
    web = Web({concept3d.API + "robots.txt": (200, "User-agent: *\nDisallow: /\n")})
    try:
        list(concept3d.collect(client(web), "concept3d", {}, listing))
        raise AssertionError("not blocked")
    except Blocked as e:
        assert "robots.txt" in str(e)
    assert web.asked == [concept3d.API + "robots.txt"]
    monkeypatch.setitem(registry.VENDORS["concept3d"], "robots_override", True)   # the owner's decision
    key = "0" * 32
    cats = [{"catId": 1, "name": "Accessibility", "children": [{"catId": 2, "name": "Accessible Entrances"},
                                                               {"catId": 3, "name": "Elevators"}]},
            {"catId": 4, "name": "Buildings"}, {"catId": 5, "name": "Faculty Offices"}]
    locs = [{"id": 11, "name": "Smith Hall North", "catId": 2, "lat": 44.0021, "lng": -72.0021},
            {"id": 12, "name": "Smith Hall", "catId": 4, "lat": 44.0020, "lng": -72.0020},
            {"id": 13, "name": "Prof. Alice Example", "catId": 5, "lat": 44.0020, "lng": -72.0020},
            {"id": 14, "name": "Lift 1", "catId": 3, "lat": 44.0022, "lng": -72.0022}]
    web = Web({concept3d.API + "robots.txt": (404, ""), concept3d.SCRIPT: (200, f'x="key={key}"'),
               f"{concept3d.API}categories?map=1130&key={key}": (200, cats),
               f"{concept3d.API}locations?map=1130&key={key}": (200, locs),
               f"{concept3d.API}locations/11?map=1130&key={key}": (200, {"description": "<p>Automatic door</p>"}),
               f"{concept3d.API}locations/14?map=1130&key={key}": (200, {"description": ""})})
    rows = list(concept3d.collect(client(web), "concept3d", {}, listing))
    assert {r["key"]: r["kind"] for r in rows} == {"concept3d:1130": "site", "concept3d:1130:loc:11":
                                                   "accessible entrance", "concept3d:1130:loc:12": "building",
                                                   "concept3d:1130:loc:14": "elevator"}
    assert next(r for r in rows if r["key"].endswith(":11"))["notes"] == "Automatic door"


def test_campus_gis_collector():
    """ArcGIS Hub: a university's building layer is read (name, address; polygon middles); a city's layer, a room
    inventory and a layer with people fields are not."""
    hub = {"features": [
        {"properties": {"type": "Feature Service", "title": "Campus Buildings", "access": "public",
                        "url": "https://services.example.com/arcgis/rest/services/Bldgs/FeatureServer",
                        "source": "Madeup State University"}},
        {"properties": {"type": "Feature Service", "title": "Buildings", "access": "public",
                        "url": "https://services.example.com/arcgis/rest/services/CityB/FeatureServer",
                        "source": "City of Madeup"}},
        {"properties": {"type": "Feature Service", "title": "Room Inventory Buildings", "access": "public",
                        "url": "https://services.example.com/arcgis/rest/services/Rooms/FeatureServer",
                        "source": "Madeup State University"}}]}
    ring = [[-72.003, 44.001], [-72.002, 44.001], [-72.002, 44.002], [-72.003, 44.002], [-72.003, 44.001]]
    layer = "https://services.example.com/arcgis/rest/services/Bldgs/FeatureServer/0/query?"
    web = Web({campus_gis.HUB_SEARCH: (200, hub),
               layer + "where=1%3D1&outFields=%2A": (200, {
                   "geometryType": "esriGeometryPolygon",
                   "fields": [{"name": "OBJECTID"}, {"name": "BLDG_NAME"}, {"name": "ADDRESS"}],
                   "features": [{"attributes": {}, "geometry": {"rings": [ring]}}]}),
               layer + "where=1%3D1&outFields=BLDG_NAME": (200, {"features": [
                   {"attributes": {"OBJECTID": 1, "BLDG_NAME": "Science Center", "ADDRESS": "1 College St"},
                    "geometry": {"rings": [ring]}},
                   {"attributes": {"OBJECTID": 2, "BLDG_NAME": None}, "geometry": {"rings": [ring]}}]})})
    stats = {}
    rows = list(campus_gis.collect(client(web), "campus-gis", stats))
    assert len(rows) == 1 and rows[0]["name"] == "Science Center" and rows[0]["kind"] == "building"
    assert rows[0]["notes"] == "Address: 1 College St" and abs(rows[0]["lat"] - 44.0014) < 0.001
    assert stats["candidates"] == 1


def test_run_and_catalogue_and_workflow(tmp_path, monkeypatch):
    """The collection "mapvendors" in the directories' runner (its units, a blocked Concept3D run kept as
    "blocked" without a file, a MazeMap run writing its CSV), the catalogue entry read by the "site_features"
    reader, and the workflow's shape."""
    specs = dirrun.collections()
    assert set(specs["mapvendors"]["units"]) == {"mazemap", "concept3d", "campus-gis", "atrius"}
    assert specs["mapvendors"]["tag"] == "map-vendors" and specs["mapvendors"]["fields"] == features.FEATURE_FIELDS
    listing = tmp_path / "list.json"
    listing.write_text(json.dumps({"maps": [{"vendor": "mazemap", "map_id": "212", "org": "Madeup State College",
                                             "lat": "44.002", "lon": "-72.002"},
                                            {"vendor": "concept3d", "map_id": "1130"}]}))
    monkeypatch.setenv("MAP_VENDORS_LIST", str(listing))
    out = tmp_path / "out"
    summary = dirrun.run("mapvendors", "mazemap", str(out), opener=maze_web(), sleep=lambda s: None, today=TODAY)
    assert summary["status"] == "ok" and summary["rows"] == 5 and (out / "mazemap.csv.gz").exists()
    monkeypatch.setitem(registry.VENDORS["concept3d"], "robots_override", False)   # as before the owner's override
    web = Web({concept3d.API + "robots.txt": (200, "User-agent: *\nDisallow: /\n")})
    summary = dirrun.run("mapvendors", "concept3d", str(out), opener=web, sleep=lambda s: None, today=TODAY)
    assert summary["status"] == "blocked" and not (out / "concept3d.csv.gz").exists()
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "map-vendors")
    assert entry["reader"] == "site_features" and entry["fetch"] == {"method": "release_csv", "release":
                                                                       "map-vendors", "prefix": "map-vendors"}
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "map-vendors.yml"), "8")
