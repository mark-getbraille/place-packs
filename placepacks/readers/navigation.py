"""The readers of the navigation part (placepacks/navigation.py says what it holds):

  osm_navigation   the region's OpenStreetMap extract (the same file as the core part's, fetch "same_as": "osm"):
                   street and path segments, intersections, crossings, signals, kerbs, tactile paving, steps,
                   ramps, elevators, entrances, stops and places with wheelchair=* (ODbL)
  gtfs_navigation  the region's open GTFS feeds (the same files as the extra part's transit stops, fetch "same_as":
                   "gtfs"): stops with wheelchair_boarding, routes, the days each timetable runs, trips with
                   wheelchair_accessible and every departure; each feed under its own open licence
"""

import csv
import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile

from placepacks import navigation
from placepacks.readers import reader
from placepacks.regions import in_region


# ------------------------------------------------------------------------------------------- OpenStreetMap

@reader("osm_navigation")
def read_osm(path, entry, region, writer, use_osmium=None, index=None):
    """Read an extract's navigation layer into writer. Returns the number of segments and features."""
    nav = navigation.store(writer)
    if use_osmium is None:
        try:
            import osmium  # noqa: F401
            use_osmium = True
        except ImportError:
            use_osmium = False
    if str(path).lower().endswith(".pbf") and not use_osmium:
        raise SystemExit("A .osm.pbf extract needs pyosmium (BSD-2-Clause): pip install osmium")
    before = _count(writer)
    if use_osmium:
        _read_osmium(path, nav, index)
    else:
        _read_xml(path, nav)
    nav._flush()
    return _count(writer) - before


def _count(writer):
    """The segments and features written so far."""
    return sum(writer.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("nav_ways", "nav_features"))


def _read_xml(path, nav):
    """A small .osm XML file with the standard library (nodes come before ways in an extract)."""
    nodes = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "node":
            pos = (float(el.get("lat")), float(el.get("lon")))
            nid = int(el.get("id"))
            nodes[nid] = pos
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                nav.node(nid, tags, *pos)
        elif el.tag == "way":
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                refs = [int(nd.get("ref")) for nd in el.findall("nd")]
                nav.way(int(el.get("id")), tags, refs, [nodes.get(r) for r in refs])
        if el.tag in ("node", "way", "relation"):
            el.clear()


def _read_osmium(path, nav, index=None):
    """An extract with pyosmium (BSD-2-Clause); the node index on disk when index is "sparse_file_array,<file>"."""
    import osmium

    class Handler(osmium.SimpleHandler):
        """pyosmium's callbacks: every tagged node and way goes to the NavStore."""
        def node(self, n):
            """A tagged node with a valid position."""
            if len(n.tags) and n.location.valid():
                nav.node(n.id, {t.k: t.v for t in n.tags}, n.location.lat, n.location.lon)

        def way(self, w):
            """A way that is a street, a path, a crossing, steps or a place: its nodes and their positions."""
            tags = w.tags
            if "highway" not in tags and "wheelchair" not in tags and "entrance" not in tags and \
                    "public_transport" not in tags and "railway" not in tags:
                return
            refs = [nd.ref for nd in w.nodes]
            points = [(nd.lat, nd.lon) if nd.location.valid() else None for nd in w.nodes]
            nav.way(w.id, {t.k: t.v for t in tags}, refs, points)

    Handler().apply_file(str(path), locations=True, idx=index or "flex_mem")


# ------------------------------------------------------------------------------------------- GTFS

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def seconds(text):
    """Seconds after the timetable day's midnight of a GTFS time ("08:05:00", "25:10:00" after midnight), or None."""
    parts = (text or "").strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return None
    return h * 3600 + m * 60 + s


def _int(text, default=0):
    """A whole number from a GTFS field ("" -> default)."""
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _rows(z, name):
    """The rows of one file of a feed (csv.DictReader), or [] when the feed does not have it."""
    found = [n for n in z.namelist() if os.path.basename(n) == name]
    if not found:
        return []
    return csv.DictReader(io.TextIOWrapper(z.open(found[0]), encoding="utf-8-sig", errors="replace"))


def feed_id(file):
    """A feed's id from its file name: "mdb-373" from "mdb-mdb-373.zip" (fetch_gtfs names each file "mdb-" and the
    Mobility Database id, which itself starts with "mdb-")."""
    name = os.path.basename(file)[:-4]
    return name[4:] if name.startswith("mdb-mdb-") else name


def read_feed(file, region, nav, licence_url=""):
    """Add one feed's stops (those in the region), routes, timetables, trips and departures. Returns the stops."""
    feed = feed_id(file)
    with zipfile.ZipFile(file) as z:
        agency = next(iter(_rows(z, "agency.txt")), {}) or {}
        stops = {}
        for row in _rows(z, "stops.txt"):
            try:
                lat, lon = float(row["stop_lat"]), float(row["stop_lon"])
            except (KeyError, ValueError, TypeError):
                continue
            kind = _int(row.get("location_type"), 0)
            if kind not in (0, 1) or not in_region(region, lat, lon):
                continue
            rid = nav.add_stop(feed, row.get("stop_id", ""), (row.get("stop_name") or "").strip(),
                               (row.get("stop_code") or "").strip(), lat, lon, _int(row.get("wheelchair_boarding")),
                               kind, (row.get("parent_station") or "").strip(),
                               (row.get("platform_code") or "").strip())
            if rid is not None:
                stops[row.get("stop_id", "")] = rid
        if not stops:
            return 0
        routes = {}
        for row in _rows(z, "routes.txt"):
            routes[row.get("route_id", "")] = nav.add_route(
                feed, row.get("route_id", ""), (row.get("route_short_name") or "").strip(),
                (row.get("route_long_name") or "").strip(), _int(row.get("route_type"), 3),
                (row.get("agency_id") or agency.get("agency_name") or "").strip())
        services, first, last = {}, None, None
        for row in _rows(z, "calendar.txt"):
            days = sum(1 << i for i, d in enumerate(DAYS) if row.get(d, "0").strip() == "1")
            start, end = _int(row.get("start_date")), _int(row.get("end_date"))
            services[row.get("service_id", "")] = nav.add_service(feed, row.get("service_id", ""), days, start, end)
            first = start if first is None else min(first, start)
            last = end if last is None else max(last, end)
        exceptions = []
        for row in _rows(z, "calendar_dates.txt"):
            sid, date = row.get("service_id", ""), _int(row.get("date"))
            if sid not in services:
                # A timetable given only by its dates (no calendar.txt row): no regular days.
                services[sid] = nav.add_service(feed, sid, 0, date, date)
            exceptions.append((services[sid], date, 1 if row.get("exception_type", "").strip() == "1" else 0))
            first = date if first is None else min(first, date)
            last = date if last is None else max(last, date)
        nav.add_service_dates(exceptions)
        trips = {}
        for row in _rows(z, "trips.txt"):
            route, service = routes.get(row.get("route_id", "")), services.get(row.get("service_id", ""))
            if route is None or service is None:
                continue
            trips[row.get("trip_id", "")] = nav.add_trip(route, service, (row.get("trip_headsign") or "").strip(),
                                                         _int(row.get("direction_id"), -1),
                                                         _int(row.get("wheelchair_accessible")),
                                                         _int(row.get("bikes_allowed")))
        batch = []
        for row in _rows(z, "stop_times.txt"):
            stop, trip = stops.get(row.get("stop_id", "")), trips.get(row.get("trip_id", ""))
            when = seconds(row.get("departure_time")) if row.get("departure_time") else seconds(row.get("arrival_time"))
            if stop is None or trip is None or when is None:
                continue
            batch.append((stop, when, trip))
            if len(batch) >= navigation.BATCH:
                nav.add_times(batch)
                batch = []
        nav.add_times(batch)
        nav.add_feed(feed, (agency.get("agency_name") or "").strip(), licence_url,
                     (agency.get("agency_timezone") or "").strip(), first or 0, last or 0)
    return len(stops)


@reader("gtfs_navigation")
def read_gtfs(path, entry, region, writer):
    """Add every feed .zip in path (a folder, with licences.json from fetch_gtfs, or one file). Returns the stops."""
    nav = navigation.store(writer)
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".zip")] \
        if os.path.isdir(path) else [path]
    licences = {}
    if os.path.isdir(path) and os.path.exists(os.path.join(path, "licences.json")):
        with open(os.path.join(path, "licences.json"), encoding="utf-8") as f:
            licences = json.load(f)
    count = 0
    for file in files:
        try:
            count += read_feed(file, region, nav, licences.get(feed_id(file), ""))
        except (zipfile.BadZipFile, OSError, KeyError):
            continue
    return count
