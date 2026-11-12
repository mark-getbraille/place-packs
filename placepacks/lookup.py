"""Looking up a position in the place packs: what is there, as it was named when the picture was taken.

  PackReader(path)              one pack file (read-only); the low-level queries below
  Finder(folder=None, packs=None, water=None, nearest=None)
      .lookup(lat, lon, when=None, detail="street", altitude=None) -> Result
      .areas_at(lat, lon, when=None) -> [(name, cls, size_m2, source)]   every named area holding the point
  search_names(text, folder=None, regions=None, when=None, limit=20) -> [Result]

The order of answers (the most specific confident one first):
  1. a named area the point is inside, or a named place within 40 m (OpenStreetMap, then the other layers);
  2. an address point within 40 m ("near 120 Main Street"; National Address Database, OpenAddresses, ODA, BAN...);
  3. an address range of the street within 40 m, interpolated ("at about 120 Main Street"; TIGER/Line);
  4. a business or public facility within 60 m ("next to Riverside Library"; businesses are "listed as");
  5. the street, the neighbourhood, the town and the ZIP area.
Water and the air come first when they apply (water.WaterLayer: on a lake, off a coast, over an ocean, in the air).

History: every row has first and last months. The picture's date (when.When) chooses the rows valid then: a row
last seen in month L counts until L+1 (the packs are monthly). A date before the oldest data uses the oldest row
and says "no older record"; without a date the newest rows are used, "as listed now"; a span uses every row valid
in it, "probably". When a name changed within a month after the date, the newer one is said too: "Tony's Pizza (now
Sally's Ice Cream)". Street names work the same way: "120 Main St (now Martin Luther King Jr. Blvd)".
Several businesses at one address (a strip mall, an office building, a food court): GPS is good to 5-15 m, so when
two or more businesses valid at the picture's date are within TENANT_GAP_M of each other and none is clearly nearest,
the lookup names the place holding them (a named mall, plaza, campus or building area), else the address, else the
street; the candidates go to Result.others (never spoken). The same business from several sources (the same
normalised name within SAME_BUSINESS_M) counts once, with the earliest first and the latest last month.
Standard library only.
"""

import json
import math
import os
import sqlite3
import threading
import urllib.parse
import weakref

from placepacks import fmt
from placepacks.when import When

AREA_CLASSES = {"park", "cemetery", "landmark", "neighbourhood", "campus", "water", "nature"}
POINT_CLASSES = AREA_CLASSES | {"building", "business", "street", "public", "transit"}
FACILITY_CLASSES = {"public", "campus", "landmark", "transit", "business", "park", "cemetery"}
NOT_A_NAME = {"settlement", "town", "zip", "admin", "region", "range", "address", "county"}
BUSINESS_SOURCES = {"overture-places", "fsq-places"}


def is_business_source(pack, source):
    """True for a source of business listings (Overture, Foursquare, and every source whose kind in the pack's
    sources table is "businesses": inspections, licences, directories), whose names are said as "listed as"."""
    return source in BUSINESS_SOURCES or (pack is not None and
                                          (pack.sources.get(source) or {}).get("kind") == "businesses")
PLACE_M, ADDRESS_M, RANGE_M, FACILITY_M, STREET_M = 40, 40, 40, 60, 60
LINE_M = 60                     # a trail, a river or a railway this near names the place when nothing nearer does
STREET_CLASSES = {"street"}     # the lines that are streets ("street" for OSM's highways); others: LINE_CLASSES
LINE_CLASSES = {"trail": "on", "water": "beside", "rail": "beside", "byway": "on"}   # and their lead words
SAME_PLACE_M = 15
TENANT_GAP_M = 15               # a business is "clearly nearest" only when the next one is this much further away
SAME_BUSINESS_M = 50            # the same normalised name this near is one business (OSM + Overture + ATP + licence)
CONTAINER_CLASSES = {"business", "campus", "building", "landmark"}   # a mall, plaza, office park, campus holding tenants
TENANT_CLASSES = {"business"}


# ------------------------------------------------------------------------------------------- the result

class Result:
    """What a lookup found. See the module docstring of placepacks for the field list; every field has a default.

    kind: "place", "address", "approx_address", "nearby", "area", "water", "air" or "none"."""

    FIELDS = dict(kind="none", name="", cls="", house_number="", street="", street_then="", street_now="", town="",
                  neighbourhood="", zip_area="", county="", region="", country="", water_name="", water_cls="",
                  distance_m=None,
                  bearing="", over="", altitude_m=None, airport="", first=None, last=None, now_name="", listed=False,
                  probably=False, as_listed_now=False, no_older_record=False, when=None, latitude=None,
                  longitude=None, type="", brand="", brand_wikidata="", note="", line="", line_cls="")

    def __init__(self, **values):
        """A result with the given FIELDS (others at their defaults) and the lists of sources, names,
        attributions, dates and tenants. Raises TypeError for an unknown field."""
        for k, v in self.FIELDS.items():
            setattr(self, k, values.pop(k, v))
        self.sources = list(values.pop("sources", []))
        self.source_names = list(values.pop("source_names", []))
        self.attributions = list(values.pop("attributions", []))
        self.dates = list(values.pop("dates", []))       # [(name, first, last, source short name)] for details
        # Every business near the point when no one of them was clearly the one (several tenants at one address):
        # [{"name", "type", "brand", "distance_m"}]. Data for future programs only: never spoken or written.
        self.others = list(values.pop("others", []))
        if values:
            raise TypeError(f"unknown fields: {', '.join(values)}")

    def __bool__(self):
        """False for the empty result (kind "none": nothing found)."""
        return self.kind != "none"

    def _street(self, detail):
        """The street part: "120 Main St (now Martin Luther King Jr. Blvd)" at the address detail."""
        if not self.street or detail == "area":
            return ""
        text = self.street
        if detail == "address" and self.house_number:
            text = ("about " if self.kind == "approx_address" else "") + f"{self.house_number} {self.street}"
        if self.street_now and self.street_now != self.street:
            text += f" (now {self.street_now})"
        return text

    def _name(self):
        """The name, as listed for a business, with its newer name."""
        name = self.name
        if self.now_name and self.now_name != self.name:
            name += f" (now {self.now_name})"
        if self.listed:
            name = f"a business listed as {name}"
            if self.no_older_record and self.first:
                name += f" in {fmt.year_text(self.first // 100)}; no older record"
            elif self.as_listed_now:
                name += " (as listed now)"
        return name

    def phrase(self, detail="street", units="miles"):
        """The short place for the spoken description, with its lead word: "at Riverside Park, Main St, Springfield",
        "near 120 Main Street, Springfield", "next to Riverside Library, ...", "on Lake Champlain", "in the air, ...".
        "" when nothing was found."""
        if self.kind in ("water", "air"):
            from placepacks.water import phrase as water_phrase
            return water_phrase(self, units)
        parts, lead = [], "at"
        if self.kind == "place" or (self.kind == "area" and self.name):
            parts.append(self._name())
        elif self.kind == "address":
            lead = "near"
        elif self.kind == "approx_address":
            lead = "at" if detail == "address" else "near"
        elif self.kind == "nearby":
            lead = "next to"
            parts.append(self._name())
        street = self._street(detail)
        if street and street not in parts:
            parts.append(street)
        if not parts and self.line:
            # A trail, river or railway nearby: "on the Appalachian Trail", "beside the Deerfield River".
            name = self.line if self.line.lower().startswith("the ") else f"the {self.line}"
            parts.append(name)
            lead = LINE_CLASSES.get(self.line_cls, "near")
        if not parts and self.neighbourhood:
            parts.append(self.neighbourhood)
            lead = "in"
        if not parts and self.zip_area:
            parts.append(self.zip_area)
            lead = "in"
        if not parts:
            return ""
        if self.town and self.town not in parts:
            parts.append(self.town)
        text = f"{lead} " + ", ".join(parts)
        return ("probably " + text) if self.probably else text

    def short(self, detail="street"):
        """A few words for a file name: the name, else the street (with the house number only at the address
        detail), else the neighbourhood; water and air: "Off Edgartown", "Over the Pacific Ocean"."""
        if self.kind in ("water", "air"):
            from placepacks.water import short as water_short
            return water_short(self)
        if self.name and self.kind in ("place", "nearby", "area"):
            return self.name
        if self.street and detail != "area":
            return f"{self.house_number} {self.street}" if detail == "address" and self.house_number and \
                self.kind == "address" else self.street
        return self.neighbourhood or self.line or self.zip_area or ""

    def source_text(self):
        """"OpenStreetMap and the National Address Database"."""
        names = list(dict.fromkeys(self.source_names))
        return names[0] if len(names) == 1 else (", ".join(names[:-1]) + " and " + names[-1] if names else "")

    def details(self):
        """The long line: the dates each name covers, the picture's date, and every attribution."""
        bits = []
        for name, first, last, src in self.dates:
            bits.append(f"{name}: {month_text(first)} to {month_text(last)} ({src})")
        when = self.when.text() if isinstance(self.when, When) else ""
        head = f"Names as of {when}" if when else "Names as listed now"
        line = head + (": " + "; ".join(bits) if bits else "") + "."
        if self.attributions:
            line += " Sources: " + " ".join(dict.fromkeys(self.attributions))
        return line

    def __repr__(self):
        """A short form for test messages: the kind and the address-detail phrase."""
        return f"Result({self.kind!r}, {self.phrase('address')!r})"


def month_text(m):
    """"March 2026" ("?" for None)."""
    if not m:
        return "?"
    import calendar
    return f"{calendar.month_name[m % 100]} {fmt.year_text(m // 100)}"


# ------------------------------------------------------------------------------------------- history

def until(row_last, latest, builds=()):
    """The last month a row counts for: up to the month before the next build after its last month (the builds
    in between did not see it), else one month after it; the newest build's rows count on; a last month that is
    not a build month is the source's own end date and counts as it is."""
    builds = builds or ()
    if row_last is None or row_last >= latest:
        return 999912                   # None: a row stored without a last month is still current
    if builds and row_last not in builds:
        return row_last                 # the source's own end date (Wikidata's "demolished"), not a build month
    later = [b for b in builds if b > row_last]
    return fmt.add_months(min(later), -1) if later else fmt.add_months(row_last, 1)


def valid(row_first, row_last, when, latest, builds=()):
    """True when a row (first, last months) was valid at when (a When with a date); see until."""
    return (row_first or 0) <= when.end and until(row_last, latest, builds) >= when.start


def _last(row, latest):
    """A row's last month; a row stored without one (None) is current: latest."""
    return latest if row.get("last") is None else row["last"]


def choose(rows, when, latest, start, builds=()):
    """(the chosen rows valid at when, flags dict). rows: dicts with first and last. latest: the pack's newest
    month; start: its oldest; builds: the months the packs were built (see until). Without a date: the rows of the
    newest month (as listed now)."""
    if not rows:
        return [], {}
    builds = builds or ()
    if not when.known:
        now = [r for r in rows if _last(r, latest) >= latest]
        return (now or sorted(rows, key=lambda r: -_last(r, latest))[:1]), {"as_listed_now": True}
    if when.end < start:
        oldest = min(r["first"] or 0 for r in rows)
        return [r for r in rows if (r["first"] or 0) == oldest], {"no_older_record": True}
    ok = [r for r in rows if valid(r["first"], r["last"], when, latest, builds)]
    return ok, ({"probably": True} if when.is_range else {})


def successor(rows, chosen, when, latest):
    """The newer name of a chosen row when it changed within a month after the date (the same key, or the same
    place within SAME_PLACE_M of the same class), or ""."""
    if not when.known or chosen["last"] >= latest or chosen["last"] > fmt.add_months(when.end, 1):
        return ""
    for r in sorted(rows, key=lambda r: r["first"]):
        if r is chosen or r["first"] <= chosen["last"] or r["first"] > fmt.add_months(chosen["last"], 2):
            continue
        same = r.get("key") == chosen.get("key") or (r.get("cls") == chosen.get("cls") and "lat" in r and
                                                     fmt.metres(r["lat"], r["lon"], chosen["lat"], chosen["lon"])
                                                     <= SAME_PLACE_M)
        if same and r["name"] != chosen["name"]:
            return r["name"]
    return ""


# ------------------------------------------------------------------------------------------- one pack

def _around(lat, lon):
    """The 9 fine cells around a position."""
    return [fmt.fine_cell(lat + dy / fmt.FINE, lon + dx / fmt.FINE) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]


def inside_rings(lat, lon, rings):
    """True if the position is inside the rings (even-odd rule)."""
    y, x, inside = lat * fmt.SCALE, lon * fmt.SCALE, False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            (y1, x1), (y2, x2) = ring[i], ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


_open = weakref.WeakSet()


def close_readers(path=None):
    """Close every open PackReader (of the file path, or all): Windows cannot replace or delete an open file."""
    target = os.path.normcase(os.path.abspath(path)) if path else None
    for r in list(_open):
        if target is None or os.path.normcase(os.path.abspath(r.path)) == target:
            r.close()


class PackReader:
    """One pack (read-only). meta, sources ({id: row dict}), region, part, latest and start (months), bounds."""

    def __init__(self, path):
        """Open the pack read-only. Raises ValueError when the file is not a place pack of this format."""
        self.path = path
        try:
            self.con = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True,
                                       check_same_thread=False)
            self.meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.Error as e:
            raise ValueError(f"{os.path.basename(path)} is not a place pack ({e}).") from None
        if self.meta.get("format") != fmt.PACK_FORMAT:
            raise ValueError(f"{os.path.basename(path)} is not a place pack.")
        version = int(self.meta.get("version", "0") or 0)
        if version != fmt.PACK_VERSION:
            raise ValueError(f"{os.path.basename(path)} was made for "
                             f"{'a newer' if version > fmt.PACK_VERSION else 'an older'} version; download it again.")
        cur = self.con.execute("SELECT * FROM sources")
        names = [d[0] for d in cur.description]
        self.sources = {row[0]: dict(zip(names, row)) for row in cur.fetchall()}
        self.region = self.meta.get("region_name") or os.path.basename(path)
        self.region_id = self.meta.get("region_id", "")
        self.part = self.meta.get("part", "core")
        self.latest = int(self.meta.get("built_month", "0") or 0)
        self.start = int(self.meta.get("history_start", "0") or self.latest)
        try:
            self.bounds = tuple(float(v) for v in self.meta.get("bounds", "").split(","))
        except ValueError:
            self.bounds = ()
        self._lock = threading.Lock()
        # Each source's own history start (Wikidata may start in 1717, the businesses in 2026): a picture is "older
        # than the data" for a layer only when it is older than that layer's first month.
        self.source_start = {}
        for table in ("points", "areas", "lines", "ranges"):
            for row in self._rows(f"SELECT source, MIN(first) AS m FROM {table} GROUP BY source"):
                if row["m"]:
                    old = self.source_start.get(row["source"])
                    self.source_start[row["source"]] = row["m"] if old is None else min(old, row["m"])
        # The fine type phrases ("pizza restaurant"), in packs made since types were added (none in older ones).
        self.types = {}
        tables = {r["name"] for r in self._rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self._typed = {"types", "point_types", "area_types"} <= tables
        if self._typed:
            self.types = {r["id"]: r["name"] for r in self._rows("SELECT id, name FROM types")}
        # Brands of chain locations (data only, like the types): point id -> (name, Wikidata id).
        self.brands, self._branded = {}, {"brands", "point_brands"} <= tables
        if self._branded:
            names = {r["id"]: (r["name"], r["wikidata"]) for r in self._rows("SELECT id, name, wikidata FROM brands")}
            self.brands = {r["id"]: names.get(r["brand"]) for r in self._rows("SELECT id, brand FROM point_brands")}
        # Notes about places (filming locations; data only): point id -> text.
        self.notes = {}
        if {"notes", "point_notes"} <= tables:
            texts = {r["id"]: r["text"] for r in self._rows("SELECT id, text FROM notes")}
            self.notes = {r["id"]: texts.get(r["note"]) for r in self._rows("SELECT id, note FROM point_notes")}
        # Names of places in other languages, in the optional "names" part (data only): key -> {lang: name}.
        self.has_labels = "labels" in tables
        _open.add(self)

    def notes_for(self, key):
        """The notes of every point with this key ("wikidata:Q42": its filming locations), [] when none."""
        if not self.notes or not key:
            return []
        return [self.notes[r["id"]] for r in self._rows("SELECT id FROM points WHERE key = ?", (key,))
                if self.notes.get(r["id"])]

    def labels(self, key):
        """{language: name} of a place's key in a "names" part pack ({} in other packs)."""
        if not self.has_labels:
            return {}
        return {r["lang"]: r["name"] for r in self._rows("SELECT lang, name FROM labels WHERE key = ?", (key,))}

    def _select(self, table, where):
        """SELECT * of points or areas with their "type" phrase (None when the pack or the row has none)."""
        links = {"points": "point_types", "areas": "area_types"}[table]
        if not self._typed:
            rows = self._rows(f"SELECT * FROM {table} WHERE {where}")
            for r in rows:
                r["type"] = None
            return rows
        rows = self._rows(f"SELECT r.*, l.type AS type_id FROM {table} r LEFT JOIN {links} l ON l.id = r.id "
                          f"WHERE {where}")
        for r in rows:
            r["type"] = self.types.get(r.pop("type_id"))
            if table == "points":
                r["brand"] = self.brands.get(r["id"])
                r["note"] = self.notes.get(r["id"])
        return rows

    def close(self):
        """Close the file (a closed reader answers nothing)."""
        with self._lock:
            if self.con is not None:
                self.con.close()
                self.con = None

    def covers(self, lat, lon):
        """True when the position is within the pack's bounds (south, west, north, east)."""
        if len(self.bounds) != 4:
            return True
        s, w, n, e = self.bounds
        return s - 0.02 <= lat <= n + 0.02 and w - 0.02 <= lon <= e + 0.02

    def _rows(self, sql, args=()):
        """The rows of a query as dicts ([] when the reader is closed)."""
        with self._lock:
            if self.con is None:
                return []
            cur = self.con.execute(sql, args)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]

    def points_near(self, lat, lon, within, classes=None, coarse=False):
        """Named points within `within` metres, nearest first, each with "d" (metres)."""
        if coarse:
            cells = sorted({fmt.coarse_cell(lat + dy / fmt.COARSE, lon + dx / fmt.COARSE) for dy in (-1, 0, 1)
                            for dx in (-1, 0, 1)})
            rows = self._select("points", f"r.ccell IN ({','.join(map(str, cells))})" if self._typed else
                                f"ccell IN ({','.join(map(str, cells))})")
        else:
            cells = ",".join(map(str, _around(lat, lon)))
            rows = self._select("points", f"r.cell IN ({cells})" if self._typed else f"cell IN ({cells})")
        out = []
        for r in rows:
            if classes is not None and r["cls"] not in classes:
                continue
            r["lat"], r["lon"] = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
            r["d"] = fmt.metres(lat, lon, r["lat"], r["lon"])
            if r["d"] <= within:
                out.append(r)
        return sorted(out, key=lambda r: r["d"])

    def _grid_ids(self, what, lat, lon, around=True):
        """The ids of the areas, lines or ranges indexed in the cells at (around) a position."""
        fine = _around(lat, lon) if around else [fmt.fine_cell(lat, lon)]
        rows = self._rows(f"SELECT DISTINCT id FROM grid WHERE what = ? AND ((level = 1 AND cell IN "
                          f"({','.join(map(str, fine))})) OR (level = 0 AND cell = ?))",
                          (what, fmt.coarse_cell(lat, lon)))
        return [r["id"] for r in rows]

    def areas_at(self, lat, lon):
        """Named areas holding the position, smallest first (dicts with size)."""
        ids = self._grid_ids("a", lat, lon, around=False)
        if not ids:
            return []
        y, x = int(lat * fmt.SCALE), int(lon * fmt.SCALE)
        out = []
        ids = ",".join(map(str, ids))
        for r in self._select("areas", f"r.id IN ({ids})" if self._typed else f"id IN ({ids})"):
            if r["minlat"] <= y <= r["maxlat"] and r["minlon"] <= x <= r["maxlon"] and \
                    inside_rings(lat, lon, fmt.unpack_rings(r["rings"])):
                del r["rings"]
                out.append(r)
        return sorted(out, key=lambda r: r["size"])

    def _near_lines(self, table, what, lat, lon, within):
        """Rows of lines or ranges within `within` metres, each with "d" and "t" (where along the nearest segment)
        and "side" (+1 left, -1 right of the line's direction)."""
        ids = self._grid_ids(what, lat, lon)
        if not ids:
            return []
        out = []
        for r in self._rows(f"SELECT * FROM {table} WHERE id IN ({','.join(map(str, ids))})"):
            pts = fmt.unpack_points(r.pop("pts"))
            best = None
            total = sum(fmt.metres(a[0] / fmt.SCALE, a[1] / fmt.SCALE, b[0] / fmt.SCALE, b[1] / fmt.SCALE)
                        for a, b in zip(pts, pts[1:])) or 1.0
            run = 0.0
            for a, b in zip(pts, pts[1:]):
                seg = fmt.metres(a[0] / fmt.SCALE, a[1] / fmt.SCALE, b[0] / fmt.SCALE, b[1] / fmt.SCALE)
                d = fmt.segment_metres(lat, lon, a, b)
                if best is None or d < best[0]:
                    k = math.cos(math.radians(lat))
                    ax, ay, bx, by = a[1] * k, a[0], b[1] * k, b[0]
                    px, py = lon * fmt.SCALE * k, lat * fmt.SCALE
                    dx, dy = bx - ax, by - ay
                    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) /
                                                           (dx * dx + dy * dy)))
                    side = 1 if dx * (py - ay) - dy * (px - ax) > 0 else -1
                    best = (d, (run + t * seg) / total, side)
                run += seg
            if best and best[0] <= within:
                r["d"], r["t"], r["side"] = best
                out.append(r)
        return sorted(out, key=lambda r: r["d"])

    def lines_near(self, lat, lon, within, classes=None):
        """Named lines within `within` metres, nearest first (only those of classes when given: "street" for
        streets; "trail", "water", "rail" for trails, rivers and railways)."""
        rows = self._near_lines("lines", "l", lat, lon, within)
        return rows if classes is None else [r for r in rows if r["cls"] in classes]

    def ranges_near(self, lat, lon, within):
        """Address ranges within `within` metres, nearest first, each with "number": the house number interpolated
        on the side the position is on (None when that side has no range)."""
        out = self._near_lines("ranges", "r", lat, lon, within)
        for r in out:
            a, b = (r["lfrom"], r["lto"]) if r["side"] > 0 else (r["rfrom"], r["rto"])
            if a is None or b is None:
                a, b = (r["rfrom"], r["rto"]) if r["side"] > 0 else (r["lfrom"], r["lto"])
            if a is None or b is None:
                r["number"] = None
                continue
            n = int(round(a + (b - a) * r["t"]))
            if (n - a) % 2:                          # keep the side's odd or even numbers
                n += 1 if b >= a else -1
            r["number"] = n
        return out

    def addresses_near(self, lat, lon, within):
        """Address points within `within` metres, nearest first (dicts: number, street, city, source, first, last,
        lat, lon, d, key)."""
        rows = self._rows(f"SELECT * FROM address_cells WHERE cell IN ({','.join(map(str, _around(lat, lon)))})")
        out = []
        for row in rows:
            streets = json.loads(row["streets"])
            corner = fmt.cell_corner(row["cell"])
            for dlat, dlon, s, number, first, last in fmt.decode_addresses(row["data"]):
                plat, plon = (corner[0] + dlat) / fmt.SCALE, (corner[1] + dlon) / fmt.SCALE
                d = fmt.metres(lat, lon, plat, plon)
                if d <= within:
                    street, city, source = (streets[s].split("|") + ["", ""])[:3]
                    out.append({"number": number, "street": street, "city": city, "source": source, "first": first,
                                "last": last, "lat": plat, "lon": plon, "d": d, "name": f"{number} {street}",
                                "key": f"{plat:.5f},{plon:.5f}", "cls": "address"})
        return sorted(out, key=lambda r: r["d"])

    def search(self, text, limit=20):
        """Points and areas whose name contains text (case-insensitive), the exact ones first."""
        like = f"%{text.strip()}%"
        join = (lambda links: f" LEFT JOIN {links} l ON l.id = r.id") if self._typed else (lambda links: "")
        tid = "l.type" if self._typed else "NULL"
        rows = self._rows(f"SELECT r.key, r.source, r.name, r.cls, r.lat, r.lon, r.first, r.last, {tid} AS type_id "
                          f"FROM points r{join('point_types')} WHERE r.name LIKE ? AND r.cls IS NOT 'note' LIMIT ?",
                          (like, limit * 5))
        rows += self._rows(f"SELECT r.key, r.source, r.name, r.cls, (r.minlat + r.maxlat) / 2 AS lat, (r.minlon + "
                           f"r.maxlon) / 2 AS lon, r.first, r.last, {tid} AS type_id FROM areas r{join('area_types')} "
                           f"WHERE r.name LIKE ? LIMIT ?", (like, limit * 5))
        for r in rows:
            r["lat"], r["lon"] = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
            r["type"] = self.types.get(r.pop("type_id"))
        low = text.strip().lower()
        return sorted(rows, key=lambda r: (r["name"].lower() != low, len(r["name"])))[:limit]


# ------------------------------------------------------------------------------------------- the finder

def default_folder():
    """Where packs are kept by default: PLACEPACKS_DIR, else a "place-packs" folder in the user's data folder."""
    if os.environ.get("PLACEPACKS_DIR"):
        return os.environ["PLACEPACKS_DIR"]
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "place-packs")


def open_packs(folder=None):
    """[PackReader] of the packs in a folder (a damaged or old pack is left out)."""
    folder = folder or default_folder()
    found = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.endswith(fmt.PACK_SUFFIX):
                try:
                    found.append(PackReader(os.path.join(folder, name)))
                except ValueError:
                    continue
    return found


def builds_of(packs):
    """The months the packs were built (their "builds" meta), sorted."""
    out = set()
    for p in packs:
        out |= {int(b) for b in p.meta.get("builds", str(p.latest)).split(",") if b.strip().isdigit()}
    return sorted(out)


def normal_name(name):
    """A business name for comparing sources: lower case, without punctuation, "the", "&"/"and" and company
    suffixes ("The Corner Café, LLC" -> "corner café")."""
    import re
    words = re.sub(r"[^\w\s]", " ", (name or "").lower().replace("&", " and ")).split()
    drop = {"the", "and", "inc", "llc", "ltd", "co", "corp", "company", "incorporated", "limited"}
    return " ".join(w for w in words if w not in drop)


def _same_brand(a, b):
    """True when two rows carry the same brand (its Wikidata id, else its name): one branch listed twice
    ("Made-up Burgers" and "Made-up Burgers Main Street")."""
    ba, bb = a.get("brand"), b.get("brand")
    if not ba or not bb:
        return False
    if ba[1] and bb[1]:
        return ba[1] == bb[1]
    return normal_name(ba[0]) == normal_name(bb[0])


def merge_same_business(rows):
    """The rows grouped into businesses: rows of one key are one place (its history, even under another name), and
    the same normalised name (or the same brand) within SAME_BUSINESS_M is one business from several sources. Returns
    [(nearest row, [rows of that business])], nearest first; rows need "key", "d", "lat", "lon" and "name"."""
    groups = []
    for r in sorted(rows, key=lambda r: r["d"]):
        n = normal_name(r["name"])
        for head, members in groups:
            near = fmt.metres(r["lat"], r["lon"], head["lat"], head["lon"]) <= SAME_BUSINESS_M
            if any(m["key"] == r["key"] for m in members) or (near and (
                    normal_name(head["name"]) == n or _same_brand(head, r))):
                members.append(r)
                break
        else:
            groups.append((r, [r]))
    return groups


class Finder:
    """Looks positions up in the packs (see the module docstring).

    folder: the pack folder (default default_folder()); packs: [PackReader] instead; water: a water.WaterLayer (None:
    the built-in one, loaded on first use; False: none); nearest(lat, lon) -> (name, lat, lon) of the nearest town,
    for water and air phrases (None: the packs' and the water layer's own places)."""

    def __init__(self, folder=None, packs=None, water=None, nearest=None):
        """Keep the settings (see the class docstring); the packs are opened only when a lookup needs them."""
        self.folder = folder
        self._packs = packs
        self._water = water
        self.nearest = nearest
        self._b = []                    # the build months of the packs of the current lookup

    @property
    def packs(self):
        """The packs (read on first use)."""
        if self._packs is None:
            self._packs = open_packs(self.folder)
        return self._packs

    def reload(self):
        """Read the pack folder again (after a download)."""
        self._packs = None

    def water(self):
        """The water layer (or None)."""
        if self._water is None:
            from placepacks.water import WaterLayer
            self._water = WaterLayer()
        return self._water or None

    def _packs_at(self, lat, lon):
        """The packs whose bounds hold the position."""
        return [p for p in self.packs if p.covers(lat, lon)]

    def _valid_areas(self, rows, when, latest, start):
        """The areas of rows valid at when, choosing among the versions of each source and class together (so an
        old version is never kept beside the current one): without a date, the versions of the newest build (or,
        when a source has none, its most recent ones), as lookup() does for undated pictures; with a date, the
        versions valid then (or, before the source's history starts, its oldest ones). Order is kept."""
        groups = {}
        for r in rows:
            groups.setdefault((r.get("source"), r.get("cls")), []).append(r)
        keep = set()
        for group in groups.values():
            if not when.known:
                now = [r for r in group if _last(r, latest) >= latest]
                newest = max(_last(r, latest) for r in group)
                chosen = now or [r for r in group if _last(r, latest) == newest]
            else:
                chosen = [r for r in group if valid(r["first"], r["last"], when, latest, self._b)]
                if not chosen and when.end < self._start_for(group, start):
                    oldest = min(r["first"] or 0 for r in group)
                    chosen = [r for r in group if (r["first"] or 0) == oldest]
            keep |= {id(r) for r in chosen}
        return [r for r in rows if id(r) in keep]

    def _start_for(self, rows, start):
        """The history start of the rows' source (the oldest month of that source in any pack), else start."""
        rows = rows if isinstance(rows, list) else [rows]
        source = rows[0].get("source") if rows else None
        found = [p.source_start[source] for p in self.packs if source in getattr(p, "source_start", {})]
        return min(found) if found else start

    def _attribute(self, result, pack, source):
        """Add a source's names to a result."""
        row = pack.sources.get(source)
        if row and source not in result.sources:
            result.sources.append(source)
            result.source_names.append(row.get("short") or row.get("name") or source)
            if row.get("attribution"):
                result.attributions.append(row["attribution"])

    def lookup(self, lat, lon, when=None, detail="street", altitude=None, accuracy=None):
        """The Result for a position (kind "none" when nothing is known). accuracy: the picture's GPS accuracy in
        metres when it records one (a nearest business must be that much nearer than the next one)."""
        when = When.parse(when)
        water = self.water() if self._water is not False else None
        if water is not None:
            found = water.describe(lat, lon, altitude, nearest=self.nearest or self._nearest_town)
            if found is not None and (found.kind == "air" or not self._land_name_here(lat, lon, when)):
                found.when = when
                return found
        packs = self._packs_at(lat, lon)
        result = Result(when=when, latitude=lat, longitude=lon)
        if not packs:
            return result
        latest = max(p.latest for p in packs)
        start = min(p.start for p in packs)
        self._b = builds_of(packs)
        self._town(result, packs, lat, lon, when, latest, start)
        # 1. a named area or place
        for p in packs:
            for a in self._valid_areas(p.areas_at(lat, lon), when, latest, start):
                if a["cls"] in NOT_A_NAME or (detail == "area" and a["cls"] not in AREA_CLASSES):
                    continue
                a["lat"], a["lon"] = (a["minlat"] + a["maxlat"]) / 2e6, (a["minlon"] + a["maxlon"]) / 2e6
                self._take(result, p, [a], when, latest, start, "place")
                if result.name:
                    if a["cls"] in CONTAINER_CLASSES and detail != "area":
                        # A mall or plaza named: its tenants near the point, when none is clearly the one, are
                        # kept in others (never spoken).
                        tenants = [r for q in packs for r in q.points_near(lat, lon, PLACE_M, TENANT_CLASSES)]
                        if tenants:
                            scratch = Result(when=when)
                            if self._tenants(scratch, packs, sorted(tenants, key=lambda r: r["d"]), lat, lon, when,
                                             latest, start, accuracy, "place"):
                                result.others = scratch.others
                    break
            if result.name:
                break
        tenants_unclear = False
        if not result.name:
            classes = (AREA_CLASSES - {"neighbourhood"}) if detail == "area" else POINT_CLASSES - {"street"}
            near = [r for p in packs for r in p.points_near(lat, lon, PLACE_M, classes)]
            near.sort(key=lambda r: (r["d"] > 10, r["source"] != "osm", r["d"]))
            if near and near[0]["cls"] in TENANT_CLASSES:
                tenants_unclear = self._tenants(result, packs, near, lat, lon, when, latest, start, accuracy,
                                                "place")
                near = [] if tenants_unclear or result.name else near
            if near:
                pack = next((p for p in packs if near[0]["source"] in p.sources), packs[0])
                group = [r for r in near if r["key"] == near[0]["key"] or fmt.metres(r["lat"], r["lon"],
                                                                                       near[0]["lat"], near[0]["lon"])
                         <= SAME_PLACE_M]
                self._take(result, pack, group, when, latest, start, "place")
        # 2./3. the street, the address point and the interpolated address
        if detail != "area":
            self._street(result, packs, lat, lon, when, latest, start, detail)
        # 4. a facility nearby
        if not result.name and result.kind != "address":
            near = [r for p in packs for r in p.points_near(lat, lon, FACILITY_M, FACILITY_CLASSES)]
            if tenants_unclear:
                near = [r for r in near if r["cls"] not in TENANT_CLASSES]
            owner = {s: p for p in packs for s in p.sources}
            near.sort(key=lambda r: (is_business_source(owner.get(r["source"]), r["source"]), r["d"]))
            if near and near[0]["cls"] in TENANT_CLASSES and not tenants_unclear:
                tenants_unclear = self._tenants(result, packs, near, lat, lon, when, latest, start, accuracy,
                                                "nearby")
                near = [] if tenants_unclear or result.name else near
            if near:
                pack = next((p for p in packs if near[0]["source"] in p.sources), packs[0])
                self._take(result, pack, [near[0]] + [r for r in near[1:] if r["key"] == near[0]["key"]], when,
                           latest, start, "nearby")
        # 5. a trail, a river or a railway nearby (when nothing nearer named the place)
        if not result.name and not result.street:
            near = [(p, r) for p in packs for r in p.lines_near(lat, lon, LINE_M, set(LINE_CLASSES))]
            if near:
                near.sort(key=lambda pr: pr[1]["d"])
                p0, r0 = near[0]
                same = [r for _, r in near if r["key"].rsplit(":", 1)[0] == r0["key"].rsplit(":", 1)[0]]
                chosen, _ = choose(same, when, latest, self._start_for(same, start), self._b)
                if chosen:
                    result.line, result.line_cls = chosen[0]["name"], chosen[0]["cls"]
                    self._attribute(result, p0, chosen[0]["source"])
        if result.kind == "none" and (result.street or result.neighbourhood or result.zip_area or result.line):
            result.kind = "area"
        return result

    def _tenants(self, result, packs, near, lat, lon, when, latest, start, accuracy, kind):
        """Several businesses at one address. near: the points found (nearest first). Only the businesses valid at
        the picture's date count (past and future tenants are left out first); the same business from several
        sources counts once. One clearly nearest (the next more than TENANT_GAP_M, or the GPS accuracy, further):
        it is taken, with the dates of all its sources merged. Two or more within TENANT_GAP_M of each other and
        none clearly nearest: the named mall, plaza, campus or building area holding them is taken, else nothing
        (the address or the street names the place); the candidates go to result.others. Returns True when the
        tenants were unclear."""
        rows = [r for r in near if r["cls"] in TENANT_CLASSES]
        by_key = {}
        for r in rows:
            by_key.setdefault(r["key"], []).append(r)
        valid_rows = []
        for group in by_key.values():
            chosen, _ = choose(group, when, latest, self._start_for(group, start), self._b)
            valid_rows += chosen
        businesses = merge_same_business(valid_rows)
        if not businesses:
            return False
        gap = max(TENANT_GAP_M, accuracy or 0)
        first = businesses[0][0]
        rivals = [h for h, _ in businesses[1:] if h["d"] - first["d"] <= gap and
                  fmt.metres(h["lat"], h["lon"], first["lat"], first["lon"]) <= max(TENANT_GAP_M, gap)]
        owner = {s: p for p in packs for s in p.sources}
        if not rivals:
            members = businesses[0][1]
            history = [r for g in by_key.values() for r in g
                       if any(r["key"] == m["key"] for m in members)]
            self._take(result, owner.get(first["source"], packs[0]), history, when, latest, start, kind)
            if result.name:
                firsts = [m["first"] for m in members if m.get("first")]
                lasts = [m["last"] for m in members]
                result.first = min(firsts) if firsts else result.first
                result.last = None if any(x is None for x in lasts) else max(lasts)
                for m in members[1:]:
                    self._attribute(result, owner.get(m["source"], packs[0]), m["source"])
            return False
        from placepacks.types import most_specific
        result.others = [{"name": h["name"], "type": most_specific([m.get("type") for m in ms]) or "",
                          "brand": next((m["brand"][0] for m in ms if m.get("brand")), ""),
                          "distance_m": round(h["d"], 1)} for h, ms in businesses
                         if h is first or h in rivals]
        # The place holding them: a named mall, plaza, campus or building area at the point or at their middle.
        heads = [first] + rivals
        mid = (sum(h["lat"] for h in heads) / len(heads), sum(h["lon"] for h in heads) / len(heads))
        for p in packs:
            for at in ((lat, lon), mid):
                for a in self._valid_areas(p.areas_at(*at), when, latest, start):
                    if a["cls"] in CONTAINER_CLASSES:
                        a["lat"], a["lon"] = (a["minlat"] + a["maxlat"]) / 2e6, (a["minlon"] + a["maxlon"]) / 2e6
                        self._take(result, p, [a], when, latest, start, "place")
                        if result.name:
                            return True
        return True

    def _take(self, result, pack, rows, when, latest, start, kind):
        """Put the row valid at when (of rows: one record and its history) into result as its name."""
        chosen, flags = choose(rows, when, latest, self._start_for(rows, start), self._b)
        if not chosen:
            return
        r = chosen[0]
        result.kind, result.name, result.cls = kind, r["name"], r["cls"]
        # The most specific type any source gives this place (the same key or name) at that time ("pizza restaurant"
        # over "restaurant"); a neighbour's type is never taken.
        from placepacks.types import most_specific
        same = [c for c in chosen if c.get("key") == r.get("key") or c.get("name") == r.get("name")]
        result.type = most_specific([r.get("type")] + [c.get("type") for c in same]) or ""
        brand = next((c.get("brand") for c in [r] + same if c.get("brand")), None)
        result.brand, result.brand_wikidata = (brand[0], brand[1] or "") if brand else ("", "")
        # A note about the place (a filming location) from any source of the same place: data only, never spoken.
        result.note = next((c.get("note") for c in [r] + same if c.get("note")), None) or \
            next(iter(pack.notes_for(r.get("key"))), "")
        result.first, result.last = r["first"], r["last"]
        result.listed = is_business_source(pack, r["source"])
        result.now_name = successor(rows, r, when, latest)
        for k, v in flags.items():
            setattr(result, k, v)
        if when.is_range and len(chosen) > 1:
            names = list(dict.fromkeys(c["name"] for c in sorted(chosen, key=lambda c: c["first"])))
            result.name = " or ".join(names)
        self._attribute(result, pack, r["source"])
        result.dates.append((r["name"], r["first"], r["last"], pack.sources.get(r["source"], {}).get("short", "")))

    def _street(self, result, packs, lat, lon, when, latest, start, detail):
        """The street (with its name then and now), the address point, or the interpolated address."""
        addresses = [(p, r) for p in packs for r in p.addresses_near(lat, lon, ADDRESS_M)]
        if addresses:
            addresses.sort(key=lambda pr: pr[1]["d"])
            p0, near = addresses[0]
            same = [r for _, r in addresses if fmt.metres(r["lat"], r["lon"], near["lat"], near["lon"]) <= 5]
            chosen, flags = choose(same, when, latest, self._start_for(same, start), self._b)
            now, _ = choose(same, When(), latest, start)
            if chosen:
                a = chosen[0]
                result.house_number, result.street = a["number"], a["street"]
                if now and now[0]["street"] != a["street"]:
                    result.street_now = now[0]["street"]
                if not result.name:
                    result.kind = "address"
                    for k, v in flags.items():
                        setattr(result, k, v)
                if a.get("city") and not result.town:
                    result.town = a["city"]
                self._attribute(result, p0, a["source"])
                return
        street_undated = False
        lines = [(p, r) for p in packs for r in p.lines_near(lat, lon, STREET_M, STREET_CLASSES)]
        if lines:
            lines.sort(key=lambda pr: pr[1]["d"])
            p0, near = lines[0]
            same = [r for _, r in lines if r["key"] == near["key"]]
            chosen, line_flags = choose(same, when, latest, self._start_for(same, start), self._b)
            now, _ = choose(same, When(), latest, start)
            if chosen:
                result.street = chosen[0]["name"]
                # The street's layer has no names that old (OpenStreetMap starts at the first build): an address
                # range of that date, below, may give the name of the time instead.
                street_undated = bool(line_flags.get("no_older_record"))
                if now and now[0]["name"] != result.street:
                    result.street_now = now[0]["name"]
                self._attribute(result, p0, chosen[0]["source"])
        ranges = [(p, r) for p in packs for r in p.ranges_near(lat, lon, RANGE_M)]
        if ranges:
            ranges.sort(key=lambda pr: pr[1]["d"])
            p0, near = ranges[0]
            same = [r for _, r in ranges if r["key"] == near["key"]]
            chosen, flags = choose(same, when, latest, self._start_for(same, start), self._b)
            now, _ = choose(same, When(), latest, start)
            if chosen and chosen[0]["number"] is not None:
                r = chosen[0]
                if result.street and street_undated and not flags.get("no_older_record") and \
                        r["name"] != result.street:
                    # The range knows the street's name at the picture's date; the street layer has today's.
                    result.street_now, result.street = result.street, r["name"]
                if not result.street:
                    result.street = r["name"]
                    if now and now[0]["name"] != r["name"]:
                        result.street_now = now[0]["name"]
                if result.street == r["name"] or (now and now[0]["name"] == result.street):
                    result.house_number = str(r["number"])
                    if not result.name:
                        result.kind = "approx_address"
                        for k, v in flags.items():
                            setattr(result, k, v)
                    self._attribute(result, p0, r["source"])

    def _town(self, result, packs, lat, lon, when, latest, start):
        """The neighbourhood, the town (a Census place or county subdivision, else the nearest settlement) and the
        ZIP area, and the county as it was on the picture's date (the Newberry atlas: boundaries since the 1600s,
        each version of a county with its own dates)."""
        for p in packs:
            for a in self._valid_areas(p.areas_at(lat, lon), when, latest, start):
                if a["cls"] == "town" and not result.town:
                    result.town = a["name"]
                elif a["cls"] == "zip" and not result.zip_area:
                    result.zip_area = a["name"]
                elif a["cls"] == "county" and not result.county:
                    result.county = a["name"]
        hood = [r for p in packs for r in p.points_near(lat, lon, 1500, {"neighbourhood"})]
        if hood:
            result.neighbourhood = hood[0]["name"]
        if not result.town:
            towns = [r for p in packs for r in p.points_near(lat, lon, 10000, {"settlement"}, coarse=True)]
            towns.sort(key=lambda r: r["d"])
            if towns:
                result.town = towns[0]["name"]
        result.region = packs[0].meta.get("state", "")
        result.country = packs[0].meta.get("country", "")

    def _land_name_here(self, lat, lon, when):
        """True when a pack names a place on land right here (so a coarse coastline does not put a beach at sea)."""
        for p in self._packs_at(lat, lon):
            for a in p.areas_at(lat, lon):
                if a["cls"] not in ("water", "zip", "admin", "region", "town", "county") and a["cls"] in POINT_CLASSES:
                    return True
            if p.points_near(lat, lon, 25, POINT_CLASSES - {"street", "transit"}):
                return True
            if p.addresses_near(lat, lon, 30):
                return True
        return False

    def _nearest_town(self, lat, lon):
        """(name, lat, lon) of the nearest settlement in the packs (within about 30 km), or None."""
        best = None
        for p in self.packs:
            for r in p.points_near(lat, lon, 30000, {"settlement"}, coarse=True):
                if best is None or r["d"] < best[0]:
                    best = (r["d"], r["name"], r["lat"], r["lon"])
        return best[1:] if best else None

    def areas_at(self, lat, lon, when=None):
        """[(name, cls, size_m2, source)] of every named area holding the position, smallest first: parks,
        protected areas, islands and island chains, peninsulas, coasts, valleys, tourist regions, towns, ZIP areas,
        counties and states (those valid at when; see choose)."""
        when = When.parse(when)
        packs = self._packs_at(lat, lon)
        if not packs:
            return []
        latest, start = max(p.latest for p in packs), min(p.start for p in packs)
        self._b = builds_of(packs)
        out, seen = [], set()
        for p in packs:
            # The versions valid at when only (an undated picture: those of the newest build), chosen per source
            # and class together, as lookup() does: never an 1800s county beside today's.
            for a in self._valid_areas(p.areas_at(lat, lon), when, latest, start):
                if (a["name"], a["cls"]) not in seen:
                    seen.add((a["name"], a["cls"]))
                    out.append((a["name"], a["cls"], a["size"], a["source"]))
        return sorted(out, key=lambda t: t[2])


def search_names(text, folder=None, regions=None, when=None, limit=20, type=None):
    """Places whose name contains text, in the packs of folder (only those of the region ids in regions, if given),
    valid at when (any time when None), and with type ("bakery") in their type phrase when type is given. [Result]
    with kind "place", latitude and longitude set."""
    when = When.parse(when)
    out = []
    for p in open_packs(folder):
        if regions and p.region_id not in regions:
            continue
        for r in p.search(text, limit):
            if when.known and not valid(r["first"], r["last"], when, p.latest):
                continue
            if type and type.strip().lower() not in (r.get("type") or ""):
                continue
            res = Result(kind="place", name=r["name"], cls=r["cls"], type=r.get("type") or "", first=r["first"],
                         last=r["last"],
                         latitude=r["lat"], longitude=r["lon"], region=p.meta.get("state", ""),
                         country=p.meta.get("country", ""), when=when)
            Finder(packs=[p], water=False)._attribute(res, p, r["source"])
            out.append(res)
    return out[:limit]
