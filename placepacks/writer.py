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
              "lon INTEGER, cell INTEGER, ccell INTEGER, first INTEGER, last INTEGER, type, brand, note",
    "areas": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, name TEXT, cls TEXT, tag TEXT, minlat INTEGER, "
             "minlon INTEGER, maxlat INTEGER, maxlon INTEGER, size REAL, rings BLOB, first INTEGER, last INTEGER, type",
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
# Points and areas have a "type" phrase (and points a "brand") while a pack is built; finish() moves the phrases to
# the "types" table (and the brands to "brands", the notes to "notes") and
# the links to "point_types" and "area_types" (FORMAT.md), so the tables themselves keep the version 2 columns and
# readers and merges made before types existed read new packs unchanged.
TYPED = {"points": "point_types", "areas": "area_types"}
SOURCE_COLUMNS = ("id", "name", "short", "kind", "part", "licence", "licence_url", "attribution", "url", "version",
                  "date", "history_start", "history_note")


def location_key(source, cls, lat, lon):
    """The key of a record whose source has no stable id: the source, the class and the position to 4 decimals."""
    return f"loc:{source}:{cls}:{lat:.4f}:{lon:.4f}"


CLIP_MARGIN = 0.02              # degrees (about 2 km): a sub-region's packs overlap their neighbours' this much


class Keep:
    """Which rows of an older pack this pack takes as its history (merge_history): not the rows of a source that
    now belongs to another part (Overture moved from extra to businesses: the new extra does not keep it), and for a
    sub-region only the rows in it (with CLIP_MARGIN). drop_sources: source ids; clip: a region dict or None."""

    def __init__(self, drop_sources=(), clip=None):
        self.drop_sources, self.clip = set(drop_sources), clip

    def box(self, south, west, north, east):
        """True when a row with these bounds (microdegrees) is kept by the clip."""
        if self.clip is None:
            return True
        from placepacks.regions import touches_region
        s = fmt.SCALE
        return touches_region(self.clip, (west / s, south / s, east / s, north / s), CLIP_MARGIN)

    def row(self, source, south, west, north=None, east=None):
        """True when a row of source with these bounds (or this position) is kept."""
        if source in self.drop_sources:
            return False
        return self.box(south, west, south if north is None else north, west if east is None else east)


class PackWriter:
    """See the module docstring. path: the pack to write; month: this build's month (YYYYMM, default now); clip: a
    sub-region (regions.json "parent"): only the records in it are kept (within CLIP_MARGIN), whatever the readers
    give (a source read from the parent's file, OpenStreetMap when the extract could not be clipped)."""

    def __init__(self, path, month=None, clip=None):
        self.path, self.month = path, month or fmt.month_of()
        self.clip = clip
        self.tmp = path + ".partial"
        if os.path.exists(self.tmp):
            os.remove(self.tmp)
        self.db = sqlite3.connect(self.tmp)
        # A pack is built in one go into a temporary file and moved into place at the end: no journal, no waiting
        # for the disk, a large page cache (a crash only loses the temporary file).
        self.db.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF; PRAGMA cache_size = -262144; "
                              "PRAGMA temp_store = MEMORY;")
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

    def _inside(self, lat, lon):
        """True when a position is in the clip region (with CLIP_MARGIN)."""
        from placepacks.regions import in_region
        return in_region(self.clip, lat, lon, CLIP_MARGIN)

    def _touches(self, south, west, north, east):
        """True when a shape's bounds touch the clip region (with CLIP_MARGIN)."""
        from placepacks.regions import touches_region
        return touches_region(self.clip, (west, south, east, north), CLIP_MARGIN)

    def _count(self, source, table):
        """Count one record of a source."""
        self.counts[(source, table)] = self.counts.get((source, table), 0) + 1

    def add_source(self, **fields):
        """The description of a source used in this pack (SOURCE_COLUMNS)."""
        self.sources[fields["id"]] = {c: str(fields.get(c, "") or "") for c in SOURCE_COLUMNS}

    def add_point(self, key, source, name, cls, tag, lat, lon, first=None, last=None, type=None, brand=None,
                  note=None):
        """A named point; type: its fine type phrase ("pizza restaurant"), if known; brand: (brand name, Wikidata id
        or "") of a chain's location (data only, like the type); note: a short note about the place ("filming
        location of ..."), data only, never spoken."""
        if self.clip is not None and not self._inside(lat, lon):
            return
        first, last = self._span(first, last)
        self._extend(lat, lon)
        brand_text = None
        if brand and (brand[0] or "").strip():
            brand_text = f"{brand[0].strip()}|{(brand[1] or '').strip()}"
        self.db.execute("INSERT INTO points (key, source, name, cls, tag, lat, lon, cell, ccell, first, last, type, "
                        "brand, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, name, cls, tag, int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE)),
                         fmt.fine_cell(lat, lon), fmt.coarse_cell(lat, lon), first, last, type or None, brand_text,
                         (note or "").strip() or None))
        self._count(source, "points")

    def add_area(self, key, source, name, cls, tag, rings, first=None, last=None, type=None):
        """A named area: rings of (lat, lon) degrees (holes are rings too, even-odd); type: its fine type phrase."""
        # Big areas (a county, an island chain) are simplified more: 50 m instead of 5 m.
        span = max((max(p[0] for p in r) - min(p[0] for p in r)) for r in rings if r) if rings else 0
        tolerance = 50.0 if span > 0.1 else fmt.SIMPLIFY_M
        rings = [r for r in (fmt.simplify(r, tolerance) for r in rings if len(r) >= 4) if len(r) >= 4]
        if not rings:
            return
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        s, w, n, e = min(lats), min(lons), max(lats), max(lons)
        if self.clip is not None and not self._touches(s, w, n, e):
            return
        self._extend(s, w, n, e)
        first, last = self._span(first, last)
        self.db.execute("INSERT INTO areas (key, source, name, cls, tag, minlat, minlon, maxlat, maxlon, size, rings, "
                        "first, last, type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, name, cls, tag, *fmt.micro([(s, w)])[0], *fmt.micro([(n, e)])[0],
                         max(fmt.ring_area_m2(r) for r in rings), fmt.pack_rings([fmt.micro(r) for r in rings]),
                         first, last, type or None))
        self._count(source, "areas")

    def _line_row(self, points):
        """(simplified points, bounds microdegrees) of a line, or None when it is too short."""
        points = fmt.simplify(points)
        if len(points) < 2:
            return None
        lats, lons = [p[0] for p in points], [p[1] for p in points]
        s, w, n, e = min(lats), min(lons), max(lats), max(lons)
        if self.clip is not None and not self._touches(s, w, n, e):
            return None
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

    def drop_duplicates(self, source, against, metres=100):
        """Remove the points of source that another source in against already has: the same normalised name within
        metres (the national transit stops against each agency's GTFS feed). Returns the number removed."""
        from placepacks.lookup import normal_name
        tol = int(metres / 0.111)                       # microdegrees, about metres at the equator
        others = {}
        marks = ",".join("?" * len(against))
        for name, lat, lon in self.db.execute(f"SELECT name, lat, lon FROM points WHERE source IN ({marks})",
                                              list(against)):
            others.setdefault(normal_name(name), []).append((lat, lon))
        gone = []
        for pid, name, lat, lon in self.db.execute("SELECT id, name, lat, lon FROM points WHERE source = ?",
                                                    (source,)).fetchall():
            near = others.get(normal_name(name), [])
            if any(abs(lat - a) <= tol and abs(lon - b) <= tol for a, b in near):
                gone.append((pid,))
        self.db.executemany("DELETE FROM points WHERE id = ?", gone)
        return len(gone)

    def add_label(self, key, lang, name):
        """A place's name in another language (the optional "names" part): the key of the place in the main packs
        ("wikidata:Q42"), a language code ("fr") and the name. Data only."""
        if not getattr(self, "_labels", False):
            self.db.execute("CREATE TABLE labels (key TEXT, lang TEXT, name TEXT, UNIQUE (key, lang))")
            self._labels = True
        self.db.execute("INSERT OR REPLACE INTO labels VALUES (?, ?, ?)", (key, lang, " ".join(name.split())))

    def add_address(self, source, number, street, city, lat, lon):
        """An address point: house number, street and town only (no unit, no names of people)."""
        number, street = (number or "").strip(), " ".join((street or "").split())
        if not number or not street:
            return
        if self.clip is not None and not self._inside(lat, lon):
            return
        self._extend(lat, lon)
        name = f"{number} {street}"
        self.db.execute("INSERT INTO addr (key, source, name, cls, street, city, lat, lon, first, last) VALUES "
                        "(?, ?, ?, 'address', ?, ?, ?, ?, ?, ?)",
                        (location_key(source, number, lat, lon), source, name, street, (city or "").strip(),
                         int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE)), self.month, self.month))
        self._count(source, "addresses")

    # -- finishing

    def finish(self, meta, previous=None, removals=(), keep=None, dedupe=True):
        """Merge with the previous pack's history (previous: its path, a list of paths, or None for the first build;
        keep: a Keep, which of their rows to take), remove the keys of removals ([{"key", "reason", "date"}]), write
        the grid, the address cells, the sources and the meta table, and put the file in place. dedupe: False when
        the rows are already a pack's (placepacks.combine). Returns the counts {table: rows}."""
        db = self.db
        # Only the first row of a key this month (a reader may give an object twice); two sources may share a key
        # (Wikidata's places and their filming-location notes), so each source keeps its own row.
        for table in TABLES if dedupe else ():
            db.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT MIN(id) FROM {table} GROUP BY key, name, "
                       f"source)")
        previous_month, builds = "", []
        for path in ([previous] if isinstance(previous, str) else list(previous or [])):
            # Several older packs: a region's first build in new parts takes its history from the packs it had
            # before (the addresses from core and extra), a sub-region from its parent's (keep says which rows).
            month_text = merge_history(db, path, self.month, keep)
            previous_month = max(previous_month, month_text)
            prev = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            builds += [int(b) for b in dict(prev.execute("SELECT key, value FROM meta").fetchall()).get(
                "builds", month_text).split(",") if b.strip()]
            prev.close()
        builds = sorted(set(builds) | {self.month})
        for r in removals:
            for table in TABLES:
                db.execute(f"DELETE FROM {table} WHERE key = ?", (r["key"],))
            db.execute("INSERT INTO removals VALUES (?, ?, ?)", (r["key"], r.get("reason", ""), r.get("date", "")))
        self._write_types()
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
        if getattr(self, "_labels", False):
            db.execute("CREATE INDEX labels_key ON labels (key)")
        db.commit()
        db.execute("VACUUM")
        db.close()
        os.replace(self.tmp, self.path)
        return counts

    def _write_types(self):
        """Move the type phrases of points and areas to the "types" table (each phrase once) and the links to
        "point_types" and "area_types" (row id -> type id), then drop the build-time column."""
        db = self.db
        db.execute("CREATE TABLE types (id INTEGER PRIMARY KEY, name TEXT UNIQUE)")
        db.execute("INSERT INTO types (name) SELECT DISTINCT type FROM (SELECT type FROM points UNION SELECT type "
                   "FROM areas) WHERE type IS NOT NULL AND type <> '' ORDER BY type")
        for table, links in TYPED.items():
            db.execute(f"CREATE TABLE {links} (id INTEGER PRIMARY KEY, type INTEGER)")
            db.execute(f"INSERT INTO {links} SELECT r.id, t.id FROM {table} r JOIN types t ON t.name = r.type")
            db.execute(f"ALTER TABLE {table} DROP COLUMN type")
        # Brands of chain locations, the same way: each brand once (name and Wikidata id), points link to it.
        db.execute("CREATE TABLE brands (id INTEGER PRIMARY KEY, name TEXT, wikidata TEXT, UNIQUE (name, wikidata))")
        db.execute("INSERT INTO brands (name, wikidata) SELECT DISTINCT substr(brand, 1, instr(brand, '|') - 1), "
                   "substr(brand, instr(brand, '|') + 1) FROM points WHERE brand IS NOT NULL ORDER BY 1")
        db.execute("CREATE TABLE point_brands (id INTEGER PRIMARY KEY, brand INTEGER)")
        db.execute("INSERT INTO point_brands SELECT p.id, b.id FROM points p JOIN brands b ON b.name || '|' || "
                   "b.wikidata = p.brand")
        db.execute("ALTER TABLE points DROP COLUMN brand")
        # Notes about places (filming locations), the same way: each text once, points link to it. Data only.
        db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT UNIQUE)")
        db.execute("INSERT INTO notes (text) SELECT DISTINCT note FROM points WHERE note IS NOT NULL ORDER BY 1")
        db.execute("CREATE TABLE point_notes (id INTEGER PRIMARY KEY, note INTEGER)")
        db.execute("INSERT INTO point_notes SELECT p.id, n.id FROM points p JOIN notes n ON n.text = p.note")
        db.execute("ALTER TABLE points DROP COLUMN note")

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


def merge_history(db, previous, month, keep=None):
    """Merge the rows of the previous pack (path) into this month's rows in db (see the module docstring). keep: a
    Keep (which old rows this pack takes: its own part's sources, its own area), None for all.
    Returns the previous pack's month (text)."""
    keep = keep or Keep()
    prev = sqlite3.connect(f"file:{previous}?mode=ro", uri=True)
    try:
        last_month = int(dict(prev.execute("SELECT key, value FROM meta").fetchall()).get("built_month", "0"))
        db.execute("CREATE TEMP TABLE old_addr AS SELECT * FROM addr WHERE 0")
        db.executemany("INSERT INTO old_addr (key, source, name, cls, street, city, lat, lon, first, last) VALUES "
                       "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (r for r in previous_addresses(prev) if keep.row(r[1], r[6], r[7])))
    finally:
        prev.close()
    db.execute("ATTACH DATABASE ? AS prev", (previous,))
    typed = {r[0] for r in db.execute("SELECT name FROM prev.sqlite_master WHERE type = 'table'")}
    for table in TABLES:
        old = "temp.old_addr" if table == "addr" else f"prev.{table}"
        if table == "addr":
            # Addresses have no stable key in the pack: the same number and street within about 10 m.
            match = SAME["addr"]
        else:
            match = "p.key = f.key AND " + SAME[table].format(t=TOLERANCE)
        columns = [c.split()[0] for c in TABLES[table].split(", ") if not c.startswith("id ")]
        db.execute("CREATE TEMP TABLE m (fid INTEGER, pid INTEGER, pfirst INTEGER)")
        if table != "addr":
            # The matches are looked up by both ids, and this month's rows by key: without these indexes the
            # update below scans the whole match table for every row (131 s for Vermont's address ranges).
            db.execute(f"CREATE INDEX IF NOT EXISTS main.{table}_merge_key ON {table} (key)")
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
        db.execute("CREATE INDEX temp.m_fid ON m (fid)")
        db.execute("CREATE INDEX temp.m_pid ON m (pid)")
        # A continuing record keeps its old row's first month (and a source's own earlier start date).
        db.execute(f"UPDATE {table} SET first = MIN(first, (SELECT MIN(pfirst) FROM m WHERE fid = {table}.id)) "
                   f"WHERE id IN (SELECT fid FROM m)")
        # Every other old row stays as it was: closed history (renamed, moved, gone) and older rows of the key.
        cols = ", ".join(columns)
        # The previous pack's type phrases (through its types table); NULL for a pack made before types.
        links = TYPED.get(table)
        if links and links in typed and "types" in typed:
            phrase = (f"(SELECT t.name FROM prev.{links} l JOIN prev.types t ON t.id = l.type WHERE l.id = "
                      f"{old}.id)")
        else:
            phrase = "NULL"
        if table == "points" and "point_brands" in typed and "brands" in typed:
            brand = (f"(SELECT b.name || '|' || b.wikidata FROM prev.point_brands l JOIN prev.brands b ON b.id = "
                     f"l.brand WHERE l.id = {old}.id)")
        else:
            brand = "NULL"
        if table == "points" and "point_notes" in typed and "notes" in typed:
            note = f"(SELECT n.text FROM prev.point_notes l JOIN prev.notes n ON n.id = l.note WHERE l.id = {old}.id)"
        else:
            note = "NULL"
        picks = ", ".join(phrase if c == "type" else brand if c == "brand" else note if c == "note" else c
                          for c in columns)
        # Not an old row more than 180° wide that does not continue: a shape across 180° kept in every pack by its
        # world-wide box (the first full build; shapes.py now keeps only the parts in the region), not history.
        wide = (f" AND (maxlon - minlon) <= {180 * fmt.SCALE}" if "minlon" in columns else "")
        # Only the rows this pack keeps (keep): its part's sources, its area.
        if keep.drop_sources:
            wide += f" AND source NOT IN ({', '.join('?' * len(keep.drop_sources))})"
        if keep.clip is not None and table != "addr":
            db.create_function("keep_box", 4, lambda s_, w_, n_, e_: 1 if keep.box(s_, w_, n_, e_) else 0,
                               deterministic=True)
            wide += (" AND keep_box(minlat, minlon, maxlat, maxlon)" if "minlon" in columns else
                     " AND keep_box(lat, lon, lat, lon)")
        db.execute(f"INSERT INTO {table} ({cols}) SELECT {picks} FROM {old} WHERE id NOT IN (SELECT pid FROM m)"
                   + wide, sorted(keep.drop_sources))
        db.execute("DROP TABLE m")
    db.execute("DROP TABLE temp.old_addr")
    for table in TABLES:
        db.execute(f"DROP INDEX IF EXISTS main.{table}_merge_key")      # build-time only (the pack has its own)
    db.commit()
    db.execute("DETACH DATABASE prev")
    return str(last_month)
