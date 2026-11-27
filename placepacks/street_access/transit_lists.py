"""Transit agencies' own lists of station elevators and escalators (queue item Q4, notes/helper-rules.txt): each
elevator or escalator becomes a site feature (kind "elevator" or "escalator") of its station, with what it serves
("Street to Brooklyn-bound platform") and whether it is ADA accessible, so the Assistant can answer "does the 1 Av
station have an elevator, and to which platform".

Read (static lists, published without a key):
  mta-elevators   New York City Transit's elevator and escalator list (the MTA's public JSON feed
                  nyct_ene_equipments.json, the same list its "elevator and escalator status" pages use), placed at
                  each station's position from the MTA's station list on data.ny.gov (dataset 39hk-dx4f, GTFS stop
                  id -> latitude and longitude)
  mbta-elevators  the MBTA's elevators and escalators (its public V3 API, /facilities, which answers without a key
                  at a low rate), each with its parent station's position and name

Not read (sources.json "rejected" and "candidates" say why): WMATA (its API needs a key: answered 401 on 27 November
2026), SEPTA (publishes only the elevators out of service now, not a list), BART, CTA and LA Metro (no static
elevator list published as data; their GTFS feeds' pathways, where given, are read by the pack build:
placepacks/readers/gtfs_stations.py). Outage feeds are not used: the packs are made monthly and a program never
sends anything anywhere, so "out of service now" cannot be answered from them.

Each row is a site features CSV row (placepacks/street_access FIELDS): the station as a "site" row (its name and
position, tied by the pack build to the transit station already in the pack by name within 400 m) and its
elevators and escalators as features of that site.
Only the Python standard library is used.
"""

import urllib.parse

from placepacks import features

MTA_EQUIPMENT = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fnyct_ene_equipments.json"
MTA_STATIONS = "https://data.ny.gov/resource/39hk-dx4f.json"
MBTA_FACILITIES = "https://api-v3.mbta.com/facilities"
MBTA_PAGE = 100


def _yes(value):
    """True for "Y", "yes", "true", 1."""
    return str(value or "").strip().lower() in ("y", "yes", "true", "1")


def station_row(key, name, lat, lon, agency, note=""):
    """The "site" row of a station. Its site_name is the station's plain name ("1 Av"), as the transit feeds name
    the stop the pack build ties it to; its name says "station"."""
    return {"key": key, "kind": "site", "site": key, "name": f"{name} station", "site_name": name,
            "lat": f"{float(lat):.6f}",
            "lon": f"{float(lon):.6f}", "notes": note, "org": agency, "vendor": "transit-lists"}


def mta_rows(equipment, stations):
    """The rows of New York City Transit's list: equipment, the feed's list of dicts; stations, data.ny.gov's
    station records. Inactive equipment and equipment of other operators (nonNYCT "Y") are left out; one without
    a known station position too."""
    where = {}
    for s in stations:
        try:
            where[str(s.get("gtfs_stop_id", "")).strip()] = (float(s["gtfs_latitude"]), float(s["gtfs_longitude"]),
                                                             s.get("stop_name", ""), str(s.get("complex_id", "")))
        except (KeyError, TypeError, ValueError):
            continue
    rows, sites = [], {}
    for e in equipment if isinstance(equipment, list) else []:
        if not _yes(e.get("isactive")) or _yes(e.get("nonNYCT")):
            continue
        kind = {"EL": "elevator", "ES": "escalator"}.get(str(e.get("equipmenttype", "")).upper())
        stop = str(e.get("elevatorsgtfsstopid") or "").split("/")[0].strip()
        if not kind or stop not in where:
            continue
        lat, lon, stop_name, complex_id = where[stop]
        site = f"mta-nyct:station:{complex_id or stop}"
        name = " ".join(str(e.get("station") or stop_name).split())
        if site not in sites:
            sites[site] = station_row(site, name, lat, lon, "MTA New York City Transit")
            rows.append(sites[site])
        serving = " ".join(str(e.get("serving") or e.get("shortdescription") or "").split())
        bits = [f"{kind.capitalize()} {e.get('equipmentno', '')}".strip()]
        if serving:
            bits.append(f"serves: {serving}")
        if e.get("linesservedbyelevator"):
            bits.append(f"lines: {e['linesservedbyelevator']}")
        bits.append("ADA accessible" if _yes(e.get("ADA")) else "not an ADA route")
        rows.append({"key": f"mta-nyct:{e.get('equipmentno')}", "kind": kind, "name": e.get("shortdescription") or
                     e.get("equipmentno"), "site": site, "site_name": name, "lat": f"{lat:.6f}",
                     "lon": f"{lon:.6f}", "notes": features.clean_note("; ".join(bits), 400),
                     "org": "MTA New York City Transit", "vendor": "transit-lists"})
    return rows


def mbta_rows(pages):
    """The rows of the MBTA's facilities (pages: the API's answers, each {"data": [...], "included": [stops]}).
    A facility takes its own position, else its station's."""
    stops, facs = {}, []
    for page in pages:
        for s in page.get("included") or []:
            if s.get("type") == "stop":
                stops[s.get("id")] = s.get("attributes") or {}
        facs += page.get("data") or []
    rows, sites = [], set()
    for f in facs:
        a = f.get("attributes") or {}
        kind = {"ELEVATOR": "elevator", "ESCALATOR": "escalator"}.get(a.get("type"))
        stop_id = (((f.get("relationships") or {}).get("stop") or {}).get("data") or {}).get("id")
        st = stops.get(stop_id) or {}
        lat, lon = a.get("latitude") or st.get("latitude"), a.get("longitude") or st.get("longitude")
        if not kind or lat is None or lon is None or not st.get("name"):
            continue
        site = f"mbta:station:{stop_id}"
        if site not in sites:
            sites.add(site)
            note = {1: "wheelchair boarding: yes", 2: "wheelchair boarding: no"}.get(st.get("wheelchair_boarding"), "")
            rows.append(station_row(site, st["name"], st["latitude"], st["longitude"], "MBTA", note))
        rows.append({"key": f"mbta:facility:{f.get('id')}", "kind": kind, "name": a.get("short_name") or
                     a.get("long_name"), "site": site, "site_name": st["name"],
                     "lat": f"{float(lat):.6f}", "lon": f"{float(lon):.6f}",
                     "notes": features.clean_note(a.get("long_name") or "", 300), "org": "MBTA",
                     "vendor": "transit-lists"})
    return rows


def collect(client, unit, stats):
    """One agency's rows (unit "mta-elevators" or "mbta-elevators")."""
    stats["may_be_empty"] = False
    if unit == "mta-elevators":
        equipment = client.json(MTA_EQUIPMENT)
        stations = client.json(MTA_STATIONS + "?" + urllib.parse.urlencode({"$limit": 5000}))
        rows = mta_rows(equipment, stations)
    else:
        pages, offset = [], 0
        while offset < 5000:
            page = client.json(MBTA_FACILITIES + "?" + urllib.parse.urlencode(
                {"filter[type]": "ELEVATOR,ESCALATOR", "include": "stop", "page[limit]": MBTA_PAGE,
                 "page[offset]": offset}))
            pages.append(page)
            if len(page.get("data") or []) < MBTA_PAGE:
                break
            offset += MBTA_PAGE
        rows = mbta_rows(pages)
    stats["elevators"] = sum(r["kind"] == "elevator" for r in rows)
    stats["escalators"] = sum(r["kind"] == "escalator" for r in rows)
    yield from rows
