"""Writing a pack, and merging it with the history of the pack published before (never replacing it).

PackWriter collects this month's records (add_point, add_area, add_line, add_range, add_address, add_source), each
with first and last = this month (or the dates the source itself gives, such as Wikidata's start and end), then
finish(meta, previous=..., removals=...) merges them with the previous pack's rows (merge_history) and writes the
indexes, the grid and the address cells.

The history rule (README "History"):
  - a record still present (the same stable key, the same name and class, within a few metres) continues its old
    row: the row keeps its first month and its last month becomes this month;
  - a record that disappeared, or whose name, class or position changed, keeps its old row as it was: closed, its
    last month is the last build it was seen in;
  - a changed or new record gets a new row from this month;
  - nothing is ever deleted, except the keys of removals (a licence problem or a takedown request; removals.json).
Records are matched by the source's stable id (OpenStreetMap type and id, Overture's GERS id, Foursquare's id,
GNIS feature id, Wikidata Q-id, ...) and, for a source without ids, by a key made from the position (4 decimals),
the class and the source, with a second pass that matches the same name and class within about 5 metres.
"""

import json
import os
import sqlite3

from placepacks import fmt

TABLES = {
    "points": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, tag TEXT, lat INTEGER, "
              "lon INTEGER, cell INTEGER, ccell INTEGER, first INTEGER, last INTEGER",
    "areas": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, tag TEXT, minlat INTEGER, "
             "minlon INTEGER, maxlat INTEGER, maxlon INTEGER, size REAL, rings BLOB, first INTEGER, last INTEGER",
    "lines": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, tag TEXT, minlat INTEGER, "
             "minlon INTEGER, maxlat INTEGER, maxlon INTEGER, pts BLOB, first INTEGER, last INTEGER",
    "ranges": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, lfrom INTEGER, lto INTEGER, "
              "rfrom INTEGER, rto INTEGER, zip TEXT, minlat INTEGER, minlon INTEGER, maxlat INTEGER, "
              "maxlon INTEGER, pts BLOB, first INTEGER, last INTEGER",
    "addr": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, street TEXT, city TEXT, "
            "lat INTEGER, lon INTEGER, first INTEGER, last INTEGER",
}
# What "the same record" means in each table, besides the key: the same name and class, and the position within
# TOLERANCE microdegrees (about 25 m), or for shapes the same bounding box within it.
TOLERANCE = 250
SAME = {
    "points": "p.name IS f.name AND p.cls IS f.cls AND abs(p.lat - f.lat) <= {t} AND abs(p.lon - f.lon) <= {t}",
    "areas": "p.name IS f.name AND p.cls IS f.cls AND abs(p.minlat - f.minlat) <= {t} AND "
             "abs(p.maxlon - f.maxlon) <= {t}",
    "lines": "p.name IS f.name AND p.cls IS f.cls",
    "ranges": "p.name IS f.name AND p.lfrom IS f.lfrom AND p.lto IS f.lto AND p.rfrom IS f.rfrom AND p.rto IS f.rto",
    "addr": "p.name IS f.name AND p.street IS f.street AND abs(p.lat - f.lat) <= 100 AND abs(p.lon - f.lon) <= 100",
}
NEAR = 50                       # microdegrees (about 5 m): the second pass for records without a stable id
SOURCE_COLUMNS = ("id", "name", "short", "kind", "part", "licence", "licence_url", "attribution", "url", "version",
                  "date", "history_start", "history_note")


def location_key(source, cls, lat, lon):
    """The key of a record whose source has no stable id: the source, the class and the position to 4 decimals."""
    return f"loc:{source}:{cls}:{lat:.4f}:{lon:.4f}"


class PackWriter:
    """See the module docstring. path: the pack to write; month: this build's month (YYYYMM, default now)."""

    def __init__(self, path, month=None):
        self.path, self.month = path, month or fmt.month_of()
        self.tmp = path + ".partial"
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        self.db = sqlite3.connect(self.tmp)
        self.db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        self.db.execute("CREATE TABLE sources (" + ", ".join(f"{c} TEXT" for c in SOURCE_COLUMNS) + ")")
        self.db.execute("CREATE TABLE removals (key TEXT, reason TEXT, date TEXT)")
        for name, columns in TABLES.items():
            self.db.execute(f"CREATE TABLE {name} ({columns})")
        self.db.execute("CREATE TABLE address_cells (cell INTEGER PRIMARY KEY, streets TEXT, data BLOB)")
        self.db.execute("CREATE TABLE grid (level INTEGER, cell INTEGER, what TEXT, id INTEGER)")
        self.counts = {}
        self.bounds = [90.0, 180.0, -90.0, -180.0]
        self.sources = {}

    # -- adding this month's records

    def _span(self, first, last):
        """(first, last) months: the given ones (a source's own dates), else this month. A date after this month (a
        licence that expires next year, a start date typed in the future) is this month: the pack only says what
        was true up to its build. A record without a start date starts at its last month."""
        last = min(last or self.month, self.month)
        first = min(first or last, self.month)     # no start date: from its own end (a closed licence) or now
        return min(first, last), last

    def _extend(self, south, west, north=None, east=None):
        """Grow the pack's bounds."""
        north, east = south if north is None else north, west if east is None else east
        b = self.bounds
        b[0], b[1], b[2], b[3] = min(b[0], south), min(b[1], west), max(b[2], north), max(b[3], east)

    def _count(self, source, table):
        """Count one record of a source."""
        self.counts[(source, table)] = self.counts.get((source, table), 0) + 1

    def add_source(self, **fields):
        """The description of a source used in this pack (SOURCE_COLUMNS)."""
        self.sources[fields["id"]] = {c: str(fields.get(c, "") or "") for c in SOURCE_COLUMNS}

    def add_point(self, key, source, name, cls, tag, lat, lon, first=None, last=None):
        """A named point."""
        first, last = self._span(first, last)
        self._extend(lat, lon)
        self.db.execute("INSERT INTO points (key, source, name, cls, tag, lat, lon, cell, ccell, first, last) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, name, cls, tag, int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE)),
                         fmt.fine_cell(lat, lon), fmt.coarse_cell(lat, lon), first, last))
        self._count(source, "points")

    def add_area(self, key, source, name, cls, tag, rings, first=None, last=None):
        """A named area: rings of (lat, lon) degrees (holes are rings too, even-odd)."""
        # Big areas (a county, an island chain) are simplified more: 50 m instead of 5 m.
        span = max((max(p[0] for p in r) - min(p[0] for p in r)) for r in rings if r) if rings else 0
        tolerance = 50.0 if span > 0.1 else fmt.SIMPLIFY_M
        rings = [r for r in (fmt.simplify(r, tolerance) for r in rings if len(r) >= 4) if len(r) >= 4]
        if not rings:
            return
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        s, w, n, e = min(lats), min(lons), max(lats), max(lons)
        self._extend(s, w, n, e)
        first, last = self._span(first, last)
        self.db.execute("INSERT INTO areas (key, source, name, cls, tag, minlat, minlon, maxlat, maxlon, size, rings, "
                        "first, last) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, name, cls, tag, *fmt.micro([(s, w)])[0], *fmt.micro([(n, e)])[0],
                         max(fmt.ring_area_m2(r) for r in rings), fmt.pack_rings([fmt.micro(r) for r in rings]),
                         first, last))
        self._count(source, "areas")

    def _line_row(self, points):
        """(simplified points, bounds microdegrees) of a line, or None when it is too short."""
        points = fmt.simplify(points)
        if len(points) < 2:
            return None
        lats, lons = [p[0] for p in points], [p[1] for p in points]
        s, w, n, e = min(lats), min(lons), max(lats), max(lons)
        self._extend(s, w, n, e)
        return points, (*fmt.micro([(s, w)])[0], *fmt.micro([(n, e)])[0])

    def add_line(self, key, source, name, cls, tag, points, first=None, last=None):
        """A named street or path: [(lat, lon)] degrees."""
        row = self._line_row(points)
        if row is None:
            return
        points, bounds = row
        first, last = self._span(first, last)
        self.db.execute("INSERT INTO lines (key, source, name, cls, tag, minlat, minlon, maxlat, maxlon, pts, first, "
                        "last) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, name, cls, tag, *bounds, fmt.pack_points(fmt.micro(points)), first, last))
        self._count(source, "lines")

    def add_range(self, key, source, street, lfrom, lto, rfrom, rto, zip_code, points):
        """An address range along a street (TIGER/Line): house numbers on the left and right side."""
        row = self._line_row(points)
        if row is None:
            return
        points, bounds = row
        self.db.execute("INSERT INTO ranges (key, source, name, cls, lfrom, lto, rfrom, rto, zip, minlat, minlon, "
                        "maxlat, maxlon, pts, first, last) VALUES (?, ?, ?, 'range', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, ?)", (key, source, street, lfrom, lto, rfrom, rto, zip_code, *bounds,
                                  fmt.pack_points(fmt.micro(points)), self.month, self.month))
        self._count(source, "ranges")

    def add_address(self, source, number, street, city, lat, lon):
        """An address point: house number, street and town only (no unit, no names of people)."""
        number, street = (number or "").strip(), " ".join((street or "").split())
        if not number or not street:
            return
        self._extend(lat, lon)
        name = f"{number} {street}"
        self.db.execute("INSERT INTO addr (key, source, name, cls, street, city, lat, lon, first, last) VALUES "
                        "(?, ?, ?, 'address', ?, ?, ?, ?, ?, ?)",
                        (location_key(source, number, lat, lon), source, name, street, (city or "").strip(),
                         int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE)), self.month, self.month))
        self._count(source, "addresses")

    # -- finishing

    def finish(self, meta, previous=None, removals=()):
        """Merge with the previous pack's history (previous: its path, or None for the first build), remove the
        keys of removals ([{"key", "reason", "date"}]), write the grid, the address cells, the sources and the meta
        table, and put the file in place. Returns the counts {table: rows}."""
        db = self.db
        # Only the first row of a key this month (a reader may give an object twice).
        for table in TABLES:
            db.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT MIN(id) FROM {table} GROUP BY key, name)")
        previous_month, builds = "", []
        if previous:
            previous_month = merge_history(db, previous, self.month)
            prev = sqlite3.connect(f"file:{previous}?mode=ro", uri=True)
            builds = [int(b) for b in dict(prev.execute("SELECT key, value FROM meta").fetchall()).get(
                "builds", previous_month).split(",") if b.strip()]
            prev.close()
        builds = sorted(set(builds) | {self.month})
        for r in removals:
            for table in TABLES:
                db.execute(f"DELETE FROM {table} WHERE key = ?", (r["key"],))
            db.execute("INSERT INTO removals VALUES (?, ?, ?)", (r["key"], r.get("reason", ""), r.get("date", "")))
        self._write_addresses()
        self._write_grid()
        for fields in self.sources.values():
            db.execute(f"INSERT INTO sources VALUES ({', '.join('?' * len(SOURCE_COLUMNS))})",
                       [fields[c] for c in SOURCE_COLUMNS])
        counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("points", "areas", "lines",
                                                                                      "ranges")}
        counts["addresses"] = self._address_count
        oldest = db.execute("SELECT MIN(m) FROM (SELECT MIN(first) m FROM points UNION ALL SELECT MIN(first) FROM "
                            "areas UNION ALL SELECT MIN(first) FROM lines)").fetchone()[0]
        values = {"format": fmt.PACK_FORMAT, "version": str(fmt.PACK_VERSION), "built_month": str(self.month),
                  "builds": ",".join(map(str, builds)),
                  "previous_month": previous_month, "history_start": str(oldest or self.month),
                  "bounds": ",".join(f"{v:.6f}" for v in self.bounds),
                  **{k: str(v) for k, v in counts.items()}, **{k: str(v) for k, v in meta.items() if v is not None}}
        db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", sorted(values.items()))
        db.executescript("""
            CREATE INDEX points_cell ON points (cell);
            CREATE INDEX points_ccell ON points (ccell);
            CREATE INDEX points_key ON points (key);
            CREATE INDEX grid_cell ON grid (what, level, cell);
        """)
        db.commit()
        db.execute("VACUUM")
        db.close()
        os.replace(self.tmp, self.path)
        return counts

    def _write_addresses(self):
        """Pack the address rows into one compressed record list per fine cell (address_cells). The cell's street list
        holds "street|town|source id"; each record points into it."""
        db = self.db
        cells = {}
        for source, name, street, city, lat, lon, first, last in db.execute(
                "SELECT source, name, street, city, lat, lon, first, last FROM addr ORDER BY lat, lon"):
            cell = fmt.fine_cell(lat / fmt.SCALE, lon / fmt.SCALE)
            corner = fmt.cell_corner(cell)
            streets, rows = cells.setdefault(cell, ([], []))
            label = f"{street}|{city}|{source}"
            if label not in streets:
                streets.append(label)
            number = name[:-len(street)].strip() if name.endswith(street) else name.split(" ")[0]
            rows.append((max(0, min(65535, lat - corner[0])), max(0, min(65535, lon - corner[1])),
                         streets.index(label), number, first, last))
        self._address_count = sum(len(r) for _, r in cells.values())
        db.executemany("INSERT INTO address_cells VALUES (?, ?, ?)",
                       [(c, json.dumps(s, ensure_ascii=False), fmt.encode_addresses(r)) for c, (s, r) in cells.items()])
        db.execute("DROP TABLE addr")

    def _write_grid(self):
        """The grid rows of every area, line and range (points carry their cells)."""
        db = self.db
        rows = []
        for what, table in (("a", "areas"), ("l", "lines"), ("r", "ranges")):
            for rid, s, w, n, e in db.execute(f"SELECT id, minlat, minlon, maxlat, maxlon FROM {table}").fetchall():
                level, cells = fmt.cells_of(s / fmt.SCALE, w / fmt.SCALE, n / fmt.SCALE, e / fmt.SCALE)
                rows += [(level, c, what, rid) for c in cells]
        db.executemany("INSERT INTO grid VALUES (?, ?, ?, ?)", rows)


def previous_addresses(prev):
    """The address rows of a previous pack (its address cells decoded), as addr table rows."""
    rows = []
    for cell, streets, data in prev.execute("SELECT cell, streets, data FROM address_cells"):
        streets = json.loads(streets)
        corner = fmt.cell_corner(cell)
        for dlat, dlon, street, number, first, last in fmt.decode_addresses(data):
            name, city, source = (streets[street].split("|") + ["", ""])[:3]
            lat, lon = corner[0] + dlat, corner[1] + dlon
            rows.append((location_key(source, number, lat / fmt.SCALE, lon / fmt.SCALE), source, f"{number} {name}",
                         "address", name, city, lat, lon, first, last))
    return rows


def merge_history(db, previous, month):
    """Merge the rows of the previous pack (path) into this month's rows in db (see the module docstring).
    Returns the previous pack's month (text)."""
    prev = sqlite3.connect(f"file:{previous}?mode=ro", uri=True)
    try:
        last_month = int(dict(prev.execute("SELECT key, value FROM meta").fetchall()).get("built_month", "0"))
        db.execute("CREATE TEMP TABLE old_addr AS SELECT * FROM addr WHERE 0")
        db.executemany("INSERT INTO old_addr (key, source, name, cls, street, city, lat, lon, first, last) VALUES "
                       "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", previous_addresses(prev))
    finally:
        prev.close()
    db.execute("ATTACH DATABASE ? AS prev", (previous,))
    for table in TABLES:
        old = "temp.old_addr" if table == "addr" else f"prev.{table}"
        if table == "addr":
            # Addresses have no stable key in the pack: the same number and street within about 10 m.
            match = SAME["addr"]
        else:
            match = "p.key = f.key AND " + SAME[table].format(t=TOLERANCE)
        columns = [c.split()[0] for c in TABLES[table].split(", ") if not c.startswith("id ")]
        db.execute("CREATE TEMP TABLE m (fid INTEGER, pid INTEGER, pfirst INTEGER)")
        # The same record as an old row when that row was still open at the last build, or when the source gives the
        # record its own end (a closed licence, a demolished building: f.last before this month) and the old row
        # ends no later: the source still lists it, so it continues instead of being copied every month.
        db.execute(f"INSERT INTO m SELECT f.id, p.id, p.first FROM {table} f JOIN {old} p ON (p.last >= ? OR "
                   f"(f.last < ? AND p.last <= f.last)) AND {match}", (last_month, month))
        if table != "addr":
            # The second pass: records without a stable id, the same name and class within about 5 m.
            db.execute(f"INSERT INTO m SELECT f.id, p.id, p.first FROM {table} f JOIN {old} p ON p.last >= ? AND "
                       f"f.key LIKE 'loc:%' AND p.key LIKE 'loc:%' AND p.source = f.source AND p.name IS f.name AND "
                       f"p.cls IS f.cls AND f.id NOT IN (SELECT fid FROM m) AND p.id NOT IN (SELECT pid FROM m)"
                       + (f" AND abs(p.lat - f.lat) <= {NEAR} AND abs(p.lon - f.lon) <= {NEAR}"
                          if table == "points" else " AND 0"), (last_month,))
        # A continuing record keeps its old row's first month (and a source's own earlier start date).
        db.execute(f"UPDATE {table} SET first = MIN(first, (SELECT MIN(pfirst) FROM m WHERE fid = {table}.id)) "
                   f"WHERE id IN (SELECT fid FROM m)")
        # Every other old row stays as it was: closed history (renamed, moved, gone) and older rows of the key.
        cols = ", ".join(columns)
        db.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM {old} WHERE id NOT IN (SELECT pid FROM m)")
        db.execute("DROP TABLE m")
    db.execute("DROP TABLE temp.old_addr")
    db.commit()
    db.execute("DETACH DATABASE prev")
    return str(last_month)
