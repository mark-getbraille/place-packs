"""Concept3D collector: the buildings and accessibility features of every Concept3D interactive map the discovery
found (map ids such as "map.concept3d.com/?id=1130" in colleges', hospitals', zoos' and cities' pages).

How Concept3D's own web map gets its data (seen in its public script, map.concept3d.com/js/index.js, 27 November
2026): it asks https://api.concept3d.com/ for "categories?map=<id>" (the map's category tree: "Accessible
Entrances", "Accessible Parking", "Elevators", "Buildings", "Dining" ...) and "locations?map=<id>" (each location's
name, position and category), with a public key written into that script. This collector would read the same two
answers per map, plus the description of each accessibility location (at most DETAILS_PER_MAP), taking the key from
the script at run time (no key is kept in this repository).

BUT api.concept3d.com's robots.txt says "User-agent: * Disallow: /" (checked 27 November 2026). The standing rule
for what place-packs publishes is to obey robots.txt, except for big chains' store locators and government websites
(the owner's decisions of 26 November 2026), and the campus-map approval of 27 November did not change that. So the
collector reads robots.txt first and, while it disallows programs, stops at once with "blocked" (the run's summary
records it, with the number of maps waiting) and reads nothing. registry.VENDORS["concept3d"]["robots_override"] is
the one switch that would let it read, to be set only by the owner's explicit decision (then the data could also
go to the personal-use-only layer instead of the public packs).

Rows when it may read (features.FEATURE_FIELDS): the organisation as a "site" row ("concept3d:<map id>", with the
discovery's place_key), each location whose category names a kind (features.kind_of of the category, then its
parent category; categories of people, offices, rooms, events and tours are never read) keyed
"concept3d:<map id>:loc:<location id>", buildings included.
"""

import re

from placepacks import features
from placepacks.chains.polite import Blocked, NotFound, RequestFailed
from placepacks.mapvendors import registry

API = "https://api.concept3d.com/"
SCRIPT = "https://map.concept3d.com/js/index.js"
DETAILS_PER_MAP = 150
ACCESS_KINDS = {"accessible entrance", "accessible parking", "accessible restroom", "accessible route", "elevator"}


def public_key(client):
    """The public key written into Concept3D's own web map script (read at run time, never stored)."""
    text = client.fetch(SCRIPT)
    m = re.search(r"key=([0-9a-f]{32})", text) or re.search(r"api\.concept3d\.com/\"\s*,\s*\w+\s*=\s*\"([0-9a-f]{32})",
                                                              text)
    if not m:
        raise RequestFailed("the web map's script holds no public key (has it changed?)")
    return m.group(1)


def flatten(categories, parent=""):
    """{category id: (name, parent name)} of a category answer (a list, or a dict with "children" lists),
    whatever its depth."""
    out = {}
    items = categories if isinstance(categories, list) else [categories] if isinstance(categories, dict) else []
    for c in items:
        if not isinstance(c, dict):
            continue
        cid = c.get("catId", c.get("id"))
        name = " ".join(str(c.get("name") or "").split())
        if cid is not None:
            out[str(cid)] = (name, parent)
        for key in ("children", "categories", "subcategories"):
            if isinstance(c.get(key), list):
                out.update(flatten(c[key], name or parent))
    return out


def location_kind(loc, cats):
    """The kind of a location from its category (then the category's parent), or "" (a category of people, offices,
    rooms, events or tours is never read)."""
    name, parent = cats.get(str(loc.get("catId", loc.get("categoryId", ""))), ("", ""))
    if features.NOT_FEATURES.search(name) and not features.kind_of(name).startswith("accessible"):
        return ""
    return features.kind_of(name, parent)


def _position(loc):
    """(lat, lon) of a location, or None."""
    try:
        lat = float(loc.get("lat", loc.get("latitude")))
        lon = float(loc.get("lng", loc.get("lon", loc.get("longitude"))))
    except (TypeError, ValueError):
        return None
    return (lat, lon) if (lat or lon) else None


def collect_map(client, m, key, stats):
    """The rows of one Concept3D map (m: a map of the discovery list)."""
    mid = str(m["map_id"])
    site = f"concept3d:{mid}"
    try:
        cats = flatten(client.json(f"{API}categories?map={mid}&key={key}"))
        locs = client.json(f"{API}locations?map={mid}&key={key}")
    except NotFound:
        stats["missing"] = stats.get("missing", 0) + 1
        return
    locs = locs if isinstance(locs, list) else (locs or {}).get("locations") or []
    if m.get("lat"):
        yield {"key": site, "kind": "site", "site": site, "name": m.get("org", ""), "site_name": m.get("org", ""),
               "place_key": m.get("place_key", ""), "lat": m["lat"], "lon": m["lon"],
               "website": m.get("homepage", ""), "org": m.get("org", ""), "vendor": "concept3d", "map_id": mid}
    details = 0
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        kind, at = location_kind(loc, cats), _position(loc)
        if not kind or kind == "site" or not at:
            continue
        note = ""
        if kind in ACCESS_KINDS and details < DETAILS_PER_MAP and loc.get("id") is not None:
            details += 1
            try:
                detail = client.json(f"{API}locations/{loc['id']}?map={mid}&key={key}")
                note = features.clean_note((detail or {}).get("description"))
            except NotFound:
                pass
        stats["features"] = stats.get("features", 0) + 1
        yield {"key": f"{site}:loc:{loc.get('id')}", "kind": kind, "name": loc.get("name") or "", "site": site,
               "site_name": m.get("org", ""), "level": loc.get("level") or loc.get("floor") or "",
               "lat": at[0], "lon": at[1], "notes": note, "vendor": "concept3d", "map_id": mid}


def collect(client, unit, stats, listing=None):
    """Every Concept3D map of the discovery list, when api.concept3d.com's robots.txt allows programs (or the
    owner's override is set); otherwise Blocked at once (see the module docstring)."""
    from placepacks.directories.common import Robots
    from placepacks.mapvendors.discover import maps_of
    maps = maps_of("concept3d", listing)
    stats["maps"] = len(maps)
    stats.setdefault("may_be_empty", not maps)
    robots = Robots(client, API, agent="place-packs-map-vendors")
    if not robots.allowed(API + "locations") and not registry.VENDORS["concept3d"].get("robots_override"):
        stats["robots"] = "disallowed"
        raise Blocked(f"api.concept3d.com's robots.txt disallows programs: {len(maps)} maps wait for the owner's "
                      "decision (nothing was read)")
    if not maps:
        return
    key = public_key(client)
    for m in maps:
        yield from collect_map(client, m, key, stats)
