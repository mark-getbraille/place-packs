"""MazeMap collector: the buildings and the accessibility features (entrances, elevators, toilets, parking,
service desks, dining ...) of every MazeMap campus the discovery found (placepacks/mapvendors/discover.py), from
MazeMap's public API, which its own web maps read without a key (checked 27 November 2026; api.mazemap.com has no
robots.txt, so programs are allowed):

  https://api.mazemap.com/api/campus/<id>/?srid=4326                  the campus: its name and centre
  https://api.mazemap.com/api/buildings/?campusid=<id>&srid=4326      its buildings: name and outline
  https://api.mazemap.com/api/campus/<id>/pois/?fromid=<n>&srid=4326  its points of interest, 2,000 a page: each
                                                                      with its types, title, floor and building

A point of interest becomes a site feature only when its TYPE names a kind (features.kind_of: "Elevator",
"Accessible toilet", "Entrance", "Parking", "Café" ...); ordinary rooms (offices, classrooms, labs) are never kept,
so no room named after a person is ever read into the packs. The level is the POI's floor name; the building is
the POI's building. The note is the POI's own description, only for accessibility kinds, cleaned (no e-mail).
Rows (features.FEATURE_FIELDS): the campus as a "site" row (with the organisation's place_key from the discovery,
"nces-postsecondary:<UNITID>" or "wikidata:Q..."), its buildings and its features, keyed "mazemap:<campus>",
"mazemap:<campus>:b:<building id>" and "mazemap:<campus>:poi:<POI id>".
"""

from placepacks import features
from placepacks.chains.polite import NotFound

API = "https://api.mazemap.com/api/"
PAGE_LIMIT = 60                 # pages of POIs read from one campus at most (120,000 POIs)
ACCESS_KINDS = {"accessible entrance", "accessible parking", "accessible restroom", "accessible route", "elevator",
                "entrance", "service desk", "information desk"}


def _lonlat(geom):
    """(lat, lon) of a GeoJSON point or the middle of a polygon's outline, or None."""
    if not isinstance(geom, dict):
        return None
    coords = geom.get("coordinates")
    try:
        if geom.get("type") == "Point":
            return float(coords[1]), float(coords[0])
        if geom.get("type") == "Polygon":
            mid = features.centroid([[(float(p[1]), float(p[0])) for p in coords[0]]])
            return mid
        if geom.get("type") == "MultiPolygon":
            mid = features.centroid([[(float(p[1]), float(p[0])) for p in coords[0][0]]])
            return mid
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return None


def poi_kind(poi):
    """The kind of a POI from its types' names (its title only when it has no type), or ""; never "building" or
    "site" (a POI is inside a building, not one), and "" for a type of rooms, offices or people."""
    types = [t.get("name", "") for t in poi.get("types") or [] if isinstance(t, dict)]
    words = types or [poi.get("title") or ""]
    if any(features.NOT_FEATURES.search(w or "") for w in words) and not any(
            features.kind_of(w).startswith("accessible") for w in words):
        return ""
    kind = features.kind_of(*words)
    return "" if kind in ("building", "site") else kind


def collect_campus(client, m, stats):
    """The rows of one campus (m: a map of the discovery list). Yields dicts with FEATURE_FIELDS."""
    cid = str(m["map_id"])
    site = f"mazemap:{cid}"
    try:
        campus = client.json(f"{API}campus/{cid}/?srid=4326")
    except NotFound:
        stats["missing"] = stats.get("missing", 0) + 1
        return
    centre = _lonlat(campus.get("center")) or _lonlat(campus.get("geometry"))
    lat, lon = (m.get("lat"), m.get("lon")) if m.get("lat") else (centre or (None, None))
    if lat in (None, ""):
        return
    yield {"key": site, "kind": "site", "site": site, "name": campus.get("name") or m.get("org", ""),
           "site_name": m.get("org") or campus.get("name", ""), "place_key": m.get("place_key", ""),
           "lat": lat, "lon": lon, "website": m.get("homepage", ""), "org": m.get("org", ""), "vendor": "mazemap",
           "map_id": cid,
           "notes": "Indoor map with wheelchair routes (MazeMap)" if campus.get("wheelchair") else ""}
    buildings = client.json(f"{API}buildings/?campusid={cid}&srid=4326").get("buildings") or []
    for b in buildings:
        at = _lonlat(b.get("fullOutline")) or _lonlat(b.get("simpleGeom")) or _lonlat(b.get("visibleOutline"))
        if not at or not b.get("name"):
            continue
        stats["buildings"] = stats.get("buildings", 0) + 1
        yield {"key": f"{site}:b:{b['id']}", "kind": "building", "name": b["name"], "site": site,
               "site_name": m.get("org", ""), "lat": round(at[0], 7), "lon": round(at[1], 7), "vendor": "mazemap",
               "map_id": cid}
    start = 0
    for _ in range(PAGE_LIMIT):
        answer = client.json(f"{API}campus/{cid}/pois/?fromid={start}&srid=4326")
        pois = answer.get("pois") or []
        for poi in pois:
            kind = poi_kind(poi)
            at = _lonlat(poi.get("point")) or _lonlat(poi.get("geometry"))
            if not kind or not at or poi.get("deleted"):
                continue
            stats["features"] = stats.get("features", 0) + 1
            types = ", ".join(t.get("name", "") for t in poi.get("types") or [] if isinstance(t, dict))
            yield {"key": f"{site}:poi:{poi.get('poiId')}", "kind": kind,
                   "name": poi.get("title") or types, "site": site, "site_name": m.get("org", ""),
                   "building": f"{site}:b:{poi['buildingId']}" if poi.get("buildingId") else "",
                   "level": poi.get("floorName") or "", "lat": round(at[0], 7), "lon": round(at[1], 7),
                   "notes": features.clean_note(poi.get("description")) if kind in ACCESS_KINDS else "",
                   "vendor": "mazemap", "map_id": cid}
        limit = int(answer.get("limit") or 2000)
        if len(pois) < limit:
            break
        start = max(int(p.get("poiId") or 0) for p in pois) + 1


def collect(client, unit, stats, listing=None):
    """Every MazeMap campus of the discovery list (placepacks/mapvendors/discover.py maps_of). A campus that is
    gone (404) is passed over; a refusal stops the unit (Blocked, recorded by the run)."""
    from placepacks.mapvendors.discover import maps_of
    maps = maps_of("mazemap", listing)
    stats["campuses"] = len(maps)
    stats.setdefault("may_be_empty", not maps)
    for m in maps:
        yield from collect_campus(client, m, stats)
