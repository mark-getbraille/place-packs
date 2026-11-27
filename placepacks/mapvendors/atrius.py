"""Atrius (LocusLabs) indoor maps: the gates, shops, restaurants, restrooms, family restrooms, service-animal relief
areas, information desks, elevators and other points of an airport's (or any venue's) public Atrius map, with their
terminal, level and position (queue item Q3, notes/helper-rules.txt; source "airport-directories", and the
map-vendors unit "atrius" for other venues the discovery finds).

How a public Atrius map works (checked 27 November 2026 on the Minneapolis-Saint Paul airport's own map, maps.<the
airport's site>/?vid=<venue>): the airport serves the map page, whose script reads ./config.json from the airport's
own site; that file names the venue and the airport's Atrius account ("venueDataLoader": {"accountId", "venueId"}).
The map then reads, without a login or a key:
  https://a.locuslabs.com/accounts/<accountId>/v5.json        the account's venues and the newest file of each part
  .../v5/venueData-<venue>.json                                the venue: name, address, phone, hours, its
                                                               structures (terminals) and their levels
  .../v5/pois-3.0-<venue>.json                                 its points: name, category, position (floor,
                                                               latitude, longitude), nearby landmark, hours, phone,
                                                               website, after security or not
a.locuslabs.com is a file store: it answers 403 to robots.txt, as to any file it does not hold, so robots.txt is
taken as absent there (the files the public map reads answer to us as to the map). The airport's own map host's
robots.txt is read and obeyed.

What is kept: each point whose category names a kind (CATEGORY_KINDS), with its name (shops and restaurants: the
name, never a person's: common.store_name), the terminal as its building ("<site>:b:<structure>", a row of kind
"terminal" each), the level ("Level 2 (Ticketing/All Gates)"), its position, and a note: before or after security,
the nearby landmark ("near Gate H6"), and for desks, relief areas and accessibility points the map's own
description (an e-mail address or a sentence naming a person is never kept). Shops and restaurants with their own
phone or hours are also businesses (common.feature_row). Art, advertising, kiosks for self check-in, beacons and the
like are not kept.
Only the Python standard library is used.
"""

import re
import urllib.parse

from placepacks.chains.polite import Blocked, NotFound, RequestFailed
from placepacks.indoor import common

DATA = "https://a.locuslabs.com/accounts/{account}/v5.json"
# Atrius categories (the part before the first ".", or the whole) -> kind. The first that matches wins.
CATEGORY_KINDS = [
    (r"^restroom\.family$", "family restroom"),
    (r"^restroom\.(accessible|wheelchair|ada)", "accessible restroom"),
    (r"^restroom", "restroom"),
    (r"^services\.(animalrelief|petrelief)", "pet relief area"),
    (r"^services\.(information|infodesk)|^information", "information desk"),
    (r"^services\.(wheelchair|accessib|assistance|specialassistance)", "accessibility service"),
    (r"^services\.(mothersroom|nursing|lactation)", "restroom"),
    (r"^services\.(lostandfound|customerservice|police|security)", "service desk"),
    (r"^services\.(rentalcar|taxi|rideshare|shuttle|bus|groundtransport)|^transportation|^portal\.train",
     "ground transport"),
    (r"^portal\.elevator", "elevator"),
    (r"^portal\.escalator", "escalator"),
    (r"^gate$|^gate\.", "gate"),
    (r"^eat", "dining"),
    (r"^shop", "store"),
    (r"^element\.door|^entrance", "entrance"),
    (r"^parking", "parking"),
]
_CATS = [(re.compile(p), k) for p, k in CATEGORY_KINDS]
DESCRIBED = {"pet relief area", "information desk", "accessibility service", "family restroom",
             "accessible restroom", "service desk", "ground transport"}


def kind_of(category):
    """The kind of an Atrius category ("restroom.family" -> "family restroom"), or "" (not kept)."""
    cat = str(category or "").lower()
    return next((k for rx, k in _CATS if rx.search(cat)), "")


def config_url(map_url):
    """The config.json beside an Atrius map page ("https://maps.madeup-airport.com/?vid=xyz" ->
    "https://maps.madeup-airport.com/config.json")."""
    parts = urllib.parse.urlsplit(map_url)
    path = parts.path if parts.path.endswith("/") else parts.path.rsplit("/", 1)[0] + "/"
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", "")) + "config.json"


def is_atrius_page(page):
    """True when a page is an Atrius web map (its script creates LocusLabsMaps, or its title says Atrius Maps)."""
    return bool(re.search(r"LocusLabsMaps|<title>\s*Atrius Maps", page or "", re.I))


def account_of(config):
    """(accountId, venueId) of an Atrius map's config.json (a dict), or ("", "")."""
    loader = ((config or {}).get("plugins") or {}).get("venueDataLoader") or {}
    return str(loader.get("accountId") or ""), str(loader.get("venueId") or "")


def level_names(venue):
    """{floorId: (structure id, structure name, level label)} of a venue's structures ("Level 2 (Ticketing/All
    Gates)" when the level has details)."""
    out = {}
    for sid, s in (venue.get("structures") or {}).items():
        for lid, lv in (s.get("levels") or {}).items():
            label = " ".join(str(lv.get("name") or "").split())
            details = " ".join(str(lv.get("details") or "").split())
            out[lid] = (sid, " ".join(str(s.get("name") or "").split()), f"{label} ({details})" if details and
                        details != label else label)
    return out


def venue_rows(client, account, venue_id, site, site_name, place_key="", map_url="", stats=None):
    """The rows of one Atrius venue (site: the site key the rows use, e.g. "airport:MSP"). Yields a "site" row,
    one "terminal" row per named structure, then the points. Blocked, NotFound and RequestFailed are raised."""
    stats = stats if stats is not None else {}
    listing = client.json(DATA.format(account=urllib.parse.quote(account)))
    entry = listing.get(venue_id) or next(iter(listing.values()), None)
    if not isinstance(entry, dict) or not (entry.get("files") or {}).get("pois"):
        raise NotFound(f"Atrius venue {venue_id} is not in account {account}")
    files = entry["files"]
    venue_data = client.json(files["venueData"]) if files.get("venueData") else {}
    venue = venue_data.get(venue_id) or next(iter(venue_data.values()), {}) if venue_data else {}
    centre = venue.get("venueCenter") or []
    pois = client.json(files["pois"])
    points = list(pois.values()) if isinstance(pois, dict) else list(pois or [])
    lat = lon = None
    if isinstance(centre, list) and len(centre) == 2:
        lat, lon = centre
    elif points:
        pos = [p.get("position") or {} for p in points if (p.get("position") or {}).get("latitude")]
        if pos:
            lat = sum(p["latitude"] for p in pos) / len(pos)
            lon = sum(p["longitude"] for p in pos) / len(pos)
    row = common.site_row(site, site_name or venue.get("name", ""), lat, lon, place_key=place_key,
                          website_url=venue.get("website", ""), phone_number=venue.get("phone", ""),
                          opening_hours=venue.get("hours", "") if venue.get("hours") not in ("Mo-Su 00:00-23:59",)
                          else "24/7", notes="Indoor map with gates, shops, restaurants and restrooms (Atrius)",
                          vendor="atrius")
    if row:
        row["map_id"] = venue_id
        yield row
    levels = level_names(venue)
    structures = {}
    for floor, (sid, sname, _) in levels.items():
        structures.setdefault(sid, (sname, []))
    for p in points:
        floor = (p.get("position") or {}).get("floorId")
        if floor in levels:
            structures[levels[floor][0]][1].append(p["position"])
    for sid, (sname, spots) in structures.items():
        if not sname or not spots or sid.endswith("-global"):
            continue
        mid = (sum(s["latitude"] for s in spots) / len(spots), sum(s["longitude"] for s in spots) / len(spots))
        terminal = common.feature_row(site, f"{site}:b:{sid}", "terminal", sname, mid[0], mid[1],
                                      site_name=site_name, vendor="atrius", map_id=venue_id, business=False)
        if terminal:
            stats["terminals"] = stats.get("terminals", 0) + 1
            yield terminal
    for p in points:
        kind = kind_of(p.get("category"))
        pos = p.get("position") or {}
        if not kind or pos.get("latitude") is None:
            continue
        sid, sname, level = levels.get(pos.get("floorId"), ("", "", ""))
        bits = []
        if "isAfterSecurity" in p and kind not in ("gate",):
            bits.append("after security" if p.get("isAfterSecurity") else "before security")
        if p.get("nearbyLandmark"):
            bits.append(f"near {p['nearbyLandmark']}")
        text = "; ".join(bits)
        if kind in DESCRIBED and p.get("description"):
            text = f"{text}. {p['description']}" if text else str(p["description"])
        links = [x.get("url") for x in p.get("links") or [] if isinstance(x, dict) and x.get("type") == "primary"]
        building = f"{site}:b:{sid}" if sid and sname and not sid.endswith("-global") else ""
        out = common.feature_row(site, f"{site}:poi:{p.get('poiId')}", kind, p.get("name"), pos["latitude"],
                                 pos["longitude"], site_name=site_name, level=level, building=building,
                                 notes=common.where_note("", extra=text) if text else "",
                                 phone_number=p.get("phone", "") if kind in ("store", "dining") else "",
                                 website_url=(links[0] if links and kind in ("store", "dining") else ""),
                                 opening_hours=p.get("operationHours", "") if kind in ("store", "dining") else "",
                                 category=p.get("category", ""), vendor="atrius", map_id=venue_id)
        if out:
            stats[kind] = stats.get(kind, 0) + 1
            yield out


def from_map_page(client, map_url, site, site_name, place_key="", stats=None):
    """The rows of the Atrius map at map_url (the airport's own map page): its config.json (robots.txt of its host
    obeyed), then venue_rows. Yields nothing when the page has no Atrius account."""
    from placepacks.directories.common import Robots
    parts = urllib.parse.urlsplit(map_url)
    robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent="place-packs-indoor-directories")
    cfg = config_url(map_url)
    if not robots.allowed(cfg):
        if stats is not None:
            stats["robots"] = stats.get("robots", 0) + 1
        return
    account, venue = account_of(client.json(cfg))
    if not account or not venue:
        return
    yield from venue_rows(client, account, venue, site, site_name, place_key, map_url, stats)


def collect(client, unit, stats, listing=None):
    """The map-vendors unit "atrius": every Atrius map the discovery found (placepacks/mapvendors/discover.py: maps
    of the vendor "locuslabs" whose address is a map page), read as above. A map that is gone is passed over; a
    refusal stops the unit (Blocked)."""
    from placepacks.mapvendors.discover import read_list
    listing = read_list() if listing is None else listing
    maps = [m for m in listing.get("maps", []) if m.get("vendor") == "locuslabs" and m.get("url")]
    stats["maps"] = len(maps)
    stats.setdefault("may_be_empty", True)
    seen = set()
    for m in maps:
        page = m.get("page") or m["url"]
        if page in seen:
            continue
        seen.add(page)
        site = f"atrius:{common.slug(urllib.parse.urlsplit(page).netloc)}"
        try:
            yield from from_map_page(client, page, site, m.get("org", ""), m.get("place_key", ""), stats)
        except (NotFound, RequestFailed):
            stats["missing"] = stats.get("missing", 0) + 1
        except Blocked:
            raise
