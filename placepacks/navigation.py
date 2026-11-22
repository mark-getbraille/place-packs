"""The navigation layer: the street network and the pedestrian accessibility details of a region, and its transit
schedules, written into the optional "navigation" part (us-vermont-navigation.osmpack). FORMAT.md, "The navigation
part", describes the tables; placepacks/navigate.py reads them ("what is the nearest intersection", "how do I
cross here", "the next bus from the nearest stop").

What is kept, from OpenStreetMap (ODbL, like the core part's OpenStreetMap layer):
  - nav_ways: the street and path segments (every highway way a person can walk or that has a name, without
    driveways, parking aisles, tracks and roads being built), with their walking details: sidewalks, surface,
    lighting, incline, width, steps, handrails, kerbs, crossing tags on crossing ways;
  - nav_intersections: the points where streets with different names meet ("Main Street and Elm Street"), with
    whether there are traffic signals there;
  - nav_features: crossings (with their type, markings, signals, accessible pedestrian signals, tactile paving,
    kerbs and islands), traffic signals, kerbs and curb cuts, tactile paving, steps, ramps, elevators, entrances
    (with wheelchair=*, doors and ramps), bus and tram stops with their amenities (shelter, bench, tactile
    paving, departures board), and named places that say whether a wheelchair can get in (wheelchair=*).
From the agencies' open GTFS feeds (each under its own open licence, the same feeds as the extra part's stops):
  - nav_feeds, nav_stops (with wheelchair_boarding), nav_routes, nav_services and nav_service_dates (the days each
    timetable runs), nav_trips (with wheelchair_accessible) and nav_times (every departure from every stop).

A NavStore is attached to a PackWriter (store(writer)); the readers (placepacks/readers/navigation.py) add rows to
it, and PackWriter.finish calls NavStore.finish, which works out the intersections, puts each feature on its street,
writes the grid and the indexes and drops the build-time tables. Only the standard library is used here.
"""

import json

from placepacks import fmt

# The highway kinds kept as segments. Tracks, bridleways and roads being planned or built are left out, and so are
# driveways and parking aisles without a name (very many, and no help for finding one's way).
WAY_KINDS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
             "living_street", "pedestrian", "service", "road", "footway", "path", "cycleway", "steps", "corridor",
             "elevator", "platform", "busway", "motorway_link", "trunk_link", "primary_link", "secondary_link",
             "tertiary_link"}
SKIP_SERVICE = {"driveway", "parking_aisle", "drive-through"}
# The kinds whose names make intersections (a footway called "Riverside Walk" meeting Main Street is not a cross
# street a person would name; a pedestrian street is).
STREET_KINDS = WAY_KINDS - {"footway", "path", "cycleway", "steps", "corridor", "elevator", "platform"}

# The tags kept for each segment (the walking details), and for each feature.
WAY_TAGS = ("ref", "sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "footway", "oneway", "lit",
            "surface", "smoothness", "incline", "width", "wheelchair", "tactile_paving", "maxspeed", "lanes",
            "crossing", "crossing:markings", "crossing:signals", "crossing:island", "step_count", "handrail",
            "handrail:left", "handrail:right", "handrail:center", "ramp", "ramp:wheelchair", "kerb", "bridge",
            "tunnel", "access", "foot", "segregated", "conveying", "level")
FEATURE_TAGS = ("name", "ref", "crossing", "crossing:markings", "crossing:signals", "crossing:island",
                "crossing_ref", "button_operated", "traffic_signals", "traffic_signals:sound",
                "traffic_signals:vibration", "traffic_signals:arrow", "traffic_signals:minimap",
                "traffic_signals:countdown", "tactile_paving", "kerb", "kerb:height", "barrier", "wheelchair",
                "wheelchair:description", "toilets:wheelchair", "supervised", "lit", "surface", "entrance", "door",
                "automatic_door", "access", "level", "width", "step_count", "handrail", "ramp", "ramp:wheelchair",
                "incline", "shelter", "bench", "bin", "covered", "departures_board",
                "passenger_information_display_system", "route_ref", "local_ref", "network", "operator",
                "highway", "railway", "public_transport", "amenity", "shop", "office", "healthcare", "tourism",
                "leisure", "opening_hours", "phone", "addr:housenumber", "addr:street")
APS_TAGS = ("traffic_signals:sound", "traffic_signals:vibration", "traffic_signals:arrow",
            "traffic_signals:minimap", "button_operated")

TABLES = {
    "nav_ways": "id INTEGER PRIMARY KEY, key TEXT, name TEXT, kind TEXT, tags TEXT, minlat INTEGER, "
                "minlon INTEGER, maxlat INTEGER, maxlon INTEGER, pts BLOB",
    "nav_intersections": "id INTEGER PRIMARY KEY, key TEXT, lat INTEGER, lon INTEGER, cell INTEGER, streets TEXT, "
                         "signals INTEGER",
    "nav_features": "id INTEGER PRIMARY KEY, key TEXT, kind TEXT, name TEXT, lat INTEGER, lon INTEGER, "
                    "cell INTEGER, tags TEXT, streets TEXT",
    "nav_grid": "level INTEGER, cell INTEGER, way INTEGER",
    "nav_feeds": "feed TEXT PRIMARY KEY, provider TEXT, licence_url TEXT, timezone TEXT, start INTEGER, "
                 "end INTEGER",
    "nav_stops": "id INTEGER PRIMARY KEY, key TEXT, feed TEXT, stop_id TEXT, name TEXT, code TEXT, lat INTEGER, "
                 "lon INTEGER, cell INTEGER, wheelchair INTEGER, location_type INTEGER, parent TEXT, platform TEXT",
    "nav_routes": "id INTEGER PRIMARY KEY, feed TEXT, route_id TEXT, short_name TEXT, long_name TEXT, "
                  "type INTEGER, agency TEXT",
    "nav_services": "id INTEGER PRIMARY KEY, feed TEXT, service_id TEXT, days INTEGER, start INTEGER, "
                    "end INTEGER",
    "nav_service_dates": "service INTEGER, date INTEGER, added INTEGER",
    "nav_trips": "id INTEGER PRIMARY KEY, route INTEGER, service INTEGER, headsign TEXT, direction INTEGER, "
                 "wheelchair INTEGER, bikes INTEGER",
    "nav_times": "stop INTEGER, time INTEGER, trip INTEGER, PRIMARY KEY (stop, time, trip)",
}
WITHOUT_ROWID = {"nav_times"}
BATCH = 50_000                  # rows kept in memory before they are written


def store(writer):
    """The NavStore of a PackWriter (made, with its tables, the first time it is asked for)."""
    if getattr(writer, "_nav", None) is None:
        writer._nav = NavStore(writer)
    return writer._nav


def compact_tags(tags, keep):
    """JSON text of the tags in keep that tags has (and are not empty), or "" when none."""
    picked = {k: tags[k] for k in keep if tags.get(k)}
    return json.dumps(picked, ensure_ascii=False, separators=(",", ":")) if picked else ""


def way_kind(tags):
    """The highway kind of a way when it is kept as a segment, else None."""
    kind = tags.get("highway")
    if kind not in WAY_KINDS or tags.get("area") == "yes" and kind not in ("pedestrian", "platform"):
        return None
    if kind == "service" and tags.get("service") in SKIP_SERVICE and not tags.get("name"):
        return None
    if tags.get("access") in ("private", "no") and tags.get("foot") not in ("yes", "designated", "permissive"):
        return None
    return kind


def street_name(tags):
    """The name a person would say for a street: its name, else its route number ("VT 100"), else ""."""
    return (tags.get("name") or tags.get("ref") or "").strip()


def feature_kind(tags, is_way=False):
    """The navigation feature an object is, or None: crossing, traffic signals, kerb, tactile paving, steps, ramp,
    elevator, entrance, bus stop, tram stop, platform or accessible place (a named place with wheelchair=*)."""
    highway, railway = tags.get("highway"), tags.get("railway")
    if highway == "crossing" or railway == "crossing" or (is_way and tags.get("footway") == "crossing"):
        return "crossing"
    if highway == "traffic_signals":
        return "traffic signals"
    if highway == "bus_stop" or (tags.get("public_transport") == "platform" and tags.get("bus") == "yes"):
        return "bus stop"
    if railway == "tram_stop":
        return "tram stop"
    if highway == "steps":
        return "steps"
    if highway == "elevator" or (tags.get("conveying") is None and tags.get("amenity") == "elevator"):
        return "elevator"
    if tags.get("entrance") or (tags.get("door") and not is_way):
        return "entrance"
    if tags.get("ramp") == "yes" or tags.get("ramp:wheelchair") == "yes" or tags.get("highway") == "ramp":
        return "ramp"
    if not is_way and (tags.get("barrier") == "kerb" or tags.get("kerb")):
        return "kerb"
    if not is_way and tags.get("tactile_paving") in ("yes", "contrasted", "primitive", "incorrect"):
        return "tactile paving"
    if tags.get("public_transport") == "platform" or railway == "platform":
        return "platform"
    if tags.get("wheelchair") and tags.get("name"):
        from placepacks.readers.osm import main_tag
        found = main_tag(tags)
        if found and found[2] not in ("street", "admin", "region", "settlement", "neighbourhood", "nature",
                                      "water"):
            return "accessible place"
    return None


class NavStore:
    """The navigation tables of one pack being written (see the module docstring). Rows go into the writer's
    database; the build-time tables nav_tmp_names (node -> street name, for the intersections) and nav_tmp_on (node
    -> the street a feature node lies on) are dropped by finish."""

    def __init__(self, writer):
        """Make the tables in the writer's database."""
        self.writer, self.db = writer, writer.db
        for name, columns in TABLES.items():
            self.db.execute(f"CREATE TABLE {name} ({columns})" + (" WITHOUT ROWID" if name in WITHOUT_ROWID else ""))
        self.db.execute("CREATE TABLE nav_tmp_names (node INTEGER, name TEXT, lat INTEGER, lon INTEGER)")
        self.db.execute("CREATE TABLE nav_tmp_on (node INTEGER, name TEXT)")
        self.feature_nodes = {}         # OpenStreetMap node id -> nav_features id (to put a feature on its street)
        self.signal_nodes = set()       # node ids with traffic signals (intersections "with traffic signals")
        self._names, self._on = [], []

    # -- OpenStreetMap

    def _inside(self, lat, lon):
        """True when a position is kept (always, except outside a sub-region's area)."""
        w = self.writer
        if w.clip is not None and not w._inside(lat, lon):
            return False
        w._extend(lat, lon)
        return True

    def add_feature(self, key, kind, tags, lat, lon, node=None):
        """A feature (feature_kind) at a position (degrees); node: its OpenStreetMap node id, when it is a node that
        may lie on a street. Returns its row id, or None when it is outside the pack's area."""
        if not self._inside(lat, lon):
            return None
        if kind == "crossing" and tags.get("crossing") == "traffic_signals" or kind == "traffic signals":
            if node is not None:
                self.signal_nodes.add(node)
        cur = self.db.execute("INSERT INTO nav_features (key, kind, name, lat, lon, cell, tags, streets) VALUES "
                              "(?, ?, ?, ?, ?, ?, ?, '')",
                              (key, kind, (tags.get("name") or "").strip(), int(round(lat * fmt.SCALE)),
                               int(round(lon * fmt.SCALE)), fmt.fine_cell(lat, lon), compact_tags(tags, FEATURE_TAGS)))
        if node is not None:
            self.feature_nodes[node] = cur.lastrowid
        return cur.lastrowid

    def node(self, nid, tags, lat, lon):
        """An OpenStreetMap node: kept when it is a navigation feature."""
        kind = feature_kind(tags)
        if kind:
            self.add_feature(f"n{nid}", kind, tags, lat, lon, node=nid)

    def way(self, wid, tags, refs, points):
        """An OpenStreetMap way: refs, its node ids; points, their (lat, lon) degrees (the same length, None for a
        node without a position). A street or path becomes a segment, its named nodes candidates for intersections;
        steps, crossings and ramps also become features at their middle; a named place with wheelchair=* a feature
        at its centre."""
        good = [(r, p) for r, p in zip(refs, points) if p is not None]
        if len(good) < 2:
            if good and feature_kind(tags, True) == "accessible place":
                self.add_feature(f"w{wid}", "accessible place", tags, *good[0][1])
            return
        kind = way_kind(tags)
        if kind is None:
            if tags.get("highway") is None and feature_kind(tags, True) in ("accessible place", "entrance",
                                                                            "platform"):
                lat = sum(p[0] for _, p in good) / len(good)
                lon = sum(p[1] for _, p in good) / len(good)
                self.add_feature(f"w{wid}", feature_kind(tags, True), tags, lat, lon)
            return
        coords = [p for _, p in good]
        row = self.writer._line_row(coords)
        if row is None:
            return
        simple, bounds = row
        name = street_name(tags)
        self.db.execute("INSERT INTO nav_ways (key, name, kind, tags, minlat, minlon, maxlat, maxlon, pts) VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (f"w{wid}", name, kind, compact_tags(tags, WAY_TAGS), *bounds,
                         fmt.pack_points(fmt.micro(simple))))
        label = name or kind.replace("_", " ")
        if name and kind in STREET_KINDS:
            self._names += [(r, name, int(round(p[0] * fmt.SCALE)), int(round(p[1] * fmt.SCALE))) for r, p in good]
        self._on += [(r, label) for r, _ in good if r in self.feature_nodes]
        wkind = feature_kind(tags, True)
        if wkind in ("steps", "crossing", "ramp", "elevator"):
            mid = coords[len(coords) // 2]
            self.add_feature(f"w{wid}", wkind, tags, *mid)
        if len(self._names) > BATCH or len(self._on) > BATCH:
            self._flush()

    def _flush(self):
        """Write the build-time rows kept in memory."""
        self.db.executemany("INSERT INTO nav_tmp_names VALUES (?, ?, ?, ?)", self._names)
        self.db.executemany("INSERT INTO nav_tmp_on VALUES (?, ?)", self._on)
        self._names, self._on = [], []

    # -- GTFS

    def add_feed(self, feed, provider, licence_url, timezone, start, end):
        """One GTFS feed (its id, agency, licence address, time zone and the dates its timetables cover)."""
        self.db.execute("INSERT OR REPLACE INTO nav_feeds VALUES (?, ?, ?, ?, ?, ?)",
                        (feed, provider, licence_url, timezone, start, end))

    def add_stop(self, feed, stop_id, name, code, lat, lon, wheelchair, location_type, parent, platform):
        """A stop or station; returns its row id, or None when it is outside the pack's area."""
        if not self._inside(lat, lon):
            return None
        cur = self.db.execute("INSERT INTO nav_stops (key, feed, stop_id, name, code, lat, lon, cell, wheelchair, "
                              "location_type, parent, platform) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (f"gtfs:{feed}:{stop_id}", feed, stop_id, name, code, int(round(lat * fmt.SCALE)),
                               int(round(lon * fmt.SCALE)), fmt.fine_cell(lat, lon), wheelchair, location_type,
                               parent, platform))
        return cur.lastrowid

    def add_route(self, feed, route_id, short_name, long_name, kind, agency):
        """A route; returns its row id."""
        return self.db.execute("INSERT INTO nav_routes (feed, route_id, short_name, long_name, type, agency) VALUES "
                               "(?, ?, ?, ?, ?, ?)", (feed, route_id, short_name, long_name, kind, agency)).lastrowid

    def add_service(self, feed, service_id, days, start, end):
        """A timetable's days (bit 0 Monday ... bit 6 Sunday) and its first and last date (YYYYMMDD)."""
        return self.db.execute("INSERT INTO nav_services (feed, service_id, days, start, end) VALUES (?, ?, ?, ?, ?)",
                               (feed, service_id, days, start, end)).lastrowid

    def add_service_dates(self, rows):
        """[(service row id, YYYYMMDD, 1 added or 0 removed)]: the exceptions of calendar_dates.txt."""
        self.db.executemany("INSERT INTO nav_service_dates VALUES (?, ?, ?)", rows)

    def add_trip(self, route, service, headsign, direction, wheelchair, bikes):
        """A trip of a route on a timetable; returns its row id."""
        return self.db.execute("INSERT INTO nav_trips (route, service, headsign, direction, wheelchair, bikes) "
                               "VALUES (?, ?, ?, ?, ?, ?)",
                               (route, service, headsign, direction, wheelchair, bikes)).lastrowid

    def add_times(self, rows):
        """[(stop row id, seconds after the timetable day's midnight, trip row id)]: departures."""
        self.db.executemany("INSERT OR IGNORE INTO nav_times VALUES (?, ?, ?)", rows)

    # -- finishing

    def finish(self):
        """Work out the intersections, put each feature node on its streets, write the grid and the indexes, drop
        the build-time tables. Returns the counts {table: rows}."""
        db = self.db
        self._flush()
        db.execute("CREATE INDEX nav_tmp_names_node ON nav_tmp_names (node)")
        rows = []
        for node, lat, lon, names in db.execute(
                "SELECT node, MIN(lat), MIN(lon), group_concat(DISTINCT name) FROM nav_tmp_names GROUP BY node "
                "HAVING COUNT(DISTINCT name) >= 2"):
            streets = sorted(set(names.split(",")))
            rows.append((f"n{node}", lat, lon, fmt.fine_cell(lat / fmt.SCALE, lon / fmt.SCALE),
                         json.dumps(streets, ensure_ascii=False), 1 if node in self.signal_nodes else 0))
        db.executemany("INSERT INTO nav_intersections (key, lat, lon, cell, streets, signals) VALUES "
                       "(?, ?, ?, ?, ?, ?)", rows)
        ons = {}
        for node, name in db.execute("SELECT node, name FROM nav_tmp_on"):
            ons.setdefault(node, set()).add(name)
        db.executemany("UPDATE nav_features SET streets = ? WHERE id = ?",
                       [(json.dumps(sorted(names), ensure_ascii=False), self.feature_nodes[node])
                        for node, names in ons.items() if node in self.feature_nodes])
        db.execute("DROP TABLE nav_tmp_names")
        db.execute("DROP TABLE nav_tmp_on")
        grid = []
        for wid, s, w, n, e in db.execute("SELECT id, minlat, minlon, maxlat, maxlon FROM nav_ways").fetchall():
            level, cells = fmt.cells_of(s / fmt.SCALE, w / fmt.SCALE, n / fmt.SCALE, e / fmt.SCALE)
            grid += [(level, c, wid) for c in cells]
        db.executemany("INSERT INTO nav_grid VALUES (?, ?, ?)", grid)
        db.executescript("""
            CREATE INDEX nav_grid_cell ON nav_grid (level, cell);
            CREATE INDEX nav_intersections_cell ON nav_intersections (cell);
            CREATE INDEX nav_features_cell ON nav_features (cell);
            CREATE INDEX nav_stops_cell ON nav_stops (cell);
            CREATE INDEX nav_trips_route ON nav_trips (route);
            CREATE INDEX nav_service_dates_service ON nav_service_dates (service, date);
        """)
        return {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("nav_ways", "nav_intersections", "nav_features", "nav_stops", "nav_routes", "nav_trips",
                             "nav_times")}
