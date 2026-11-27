"""Site features: what is INSIDE or AROUND a site (a college campus, a hospital, a zoo, a mall, an airport, a stadium):
its buildings, accessible entrances, elevators, accessible parking, accessible restrooms, step-free routes, help and
information desks, emergency phones, dining, stores, gates and terminals (FORMAT.md, "Site features").

The owner asked on 27 November 2026 (notes/helper-rules.txt) for a pack format that lets the Assistant answer "where
is the accessible entrance to the hospital's main building", "which building at the zoo has an elevator" or "is
there an accessible restroom". This module is that format:

  site_features (id INTEGER PRIMARY KEY, key TEXT, source TEXT, kind TEXT, name TEXT, site TEXT, building TEXT,
                 level TEXT, lat INTEGER, lon INTEGER, cell INTEGER, pts BLOB, notes TEXT)

  key       the feature's own stable key ("w123" for OpenStreetMap, "mazemap:1:poi:17" for a vendor's record)
  source    the source id (sources.json)
  kind      one of KINDS ("accessible entrance", "elevator", "building" ...)
  name      the feature's name as the source gives it ("North Entrance", "Smith Hall"); may be empty
  site      the key of the site's place in the packs ("w123" an OpenStreetMap campus area, "nces-postsecondary:166027"
            a college, "hrsa-site-dashboard:..." a hospital), or the source's own site key when no place matched
            (then the site itself is a row of kind "site")
  building  the key of the building feature (a row of kind "building") the feature is in or on; may be empty
  level     the floor or level as the source labels it ("1", "Ground", "B1", "Level 2"); may be empty
  lat, lon  the position in whole microdegrees (for a route: its middle point)
  cell      the fine grid cell of the position (fmt.fine_cell), for features_near
  pts       only for a route (kind "accessible route"): its points, packed like a line's (fmt.pack_points)
  notes     a short accessibility note from the source ("automatic door; ramp from the drop-off loop"); never an
            e-mail address; at most NOTE_LIMIT characters

The table is NEW and separate: the points, areas and lines tables keep their version 2 columns, so readers and pack
merges made before it read new packs unchanged (they never look at the table), and a pack without the table simply
has no site features. The pack version stays 2. The table has no history: each build writes the features as the
sources give them that month (like the navigation part); the site and building keys point into the same build.

Where it is written: the core part holds the OpenStreetMap features (placepacks/readers/osm_features.py, ODbL like
the rest of the core part); the extra part holds the other sources' (the campus map platforms and universities' GIS
layers: placepacks/mapvendors; hospitals' own pages and the insurers' directories: placepacks/health_access; malls
and airports: placepacks/indoor; cities' accessible pedestrian signals, station elevators and Amtrak stations:
placepacks/street_access; GTFS stations: placepacks/readers/gtfs_stations.py; museums: placepacks/museum_access.py). Both
parts are downloaded by default and read by PackReader (placepacks/lookup.py: features_of, features_near,
building_of).

The collectors' common CSV (FEATURE_FIELDS, read by the "site_features" reader below):
  key, kind, name, site, site_name, place_key, npi, building, level, lat, lon, line, notes, phone, website,
  opening_hours, address, org, vendor, map_id
A row of kind "site" describes the site itself (the organisation: its name, position, phone, website, hours and an
accessibility note); the reader ties it to the place already in the pack (resolve_site: place_key, then the NPI,
then the same name nearby, then the campus area holding it) and gives that place the details it lacks
(PackWriter.fill_details). Every other row is a feature of that site. A feature row without a site is given the
campus, hospital or other site area holding it, if any.
Only the Python standard library is used.
"""

import csv
import io
import json
import re

from placepacks import fmt
from placepacks.readers import reader

NOTE_LIMIT = 600
# The kinds of feature, in plain words (the Assistant says them as they are).
KINDS = ("accessible entrance", "entrance", "elevator", "escalator", "accessible parking", "parking",
         "accessible restroom", "restroom", "accessible route", "service desk", "information desk",
         "emergency phone", "dining", "store", "gate", "terminal", "building", "site",
         # Added for malls and airports (queue item Q3, placepacks/indoor): a family or companion-care restroom, a
         # service-animal and pet relief area, a wheelchair or scooter loan or wheelchair-assistance point, a
         # taxi, rideshare, shuttle or bus pick-up area, and an airport concourse.
         "family restroom", "pet relief area", "accessibility service", "ground transport", "concourse",
         # Added for street and transit accessibility (queue item Q4, placepacks/street_access and
         # placepacks/readers/gtfs_stations.py): an accessible pedestrian signal (an audible or vibrating crosswalk
         # signal, from cities' open data), a curb ramp (written only to the navigation part, being very many), and
         # a station's stairs (GTFS pathways).
         "accessible pedestrian signal", "curb ramp", "stairs")
# The columns of the collectors' CSV files (see the module docstring).
FEATURE_FIELDS = ["key", "kind", "name", "site", "site_name", "place_key", "npi", "building", "level", "lat", "lon",
                  "line", "notes", "phone", "website", "opening_hours", "address", "org", "vendor", "map_id"]
TABLE = ("id INTEGER PRIMARY KEY, key TEXT, source TEXT, kind TEXT, name TEXT, site TEXT, building TEXT, "
         "level TEXT, lat INTEGER, lon INTEGER, cell INTEGER, pts BLOB, notes TEXT")
COLUMNS = ("key", "source", "kind", "name", "site", "building", "level", "lat", "lon", "cell", "pts", "notes")

_ACCESS = r"(ada|accessib\w*|wheelchair|handicap\w*|disab\w*|step[- ]free|barrier[- ]free|\bhc\b)"
# A category's or a type's words -> a kind (the first that matches wins). Used for every source's own category names
# (Concept3D categories, Mazemap POI types, OpenStreetMap values, GIS layer types).
KIND_WORDS = [
    (rf"{_ACCESS}.*\b(entrance|entrances|entry|entries|door|doors)\b|\b(entrance|entry|door)s?\b.*{_ACCESS}",
     "accessible entrance"),
    (rf"{_ACCESS}.*\b(route|routes|path|paths|pathway|walkway|ramp|ramps)\b|\b(route|path)s?\b.*{_ACCESS}",
     "accessible route"),
    (rf"{_ACCESS}.*\b(parking|park|lot|lots|garage|space|spaces|stall|stalls)\b|\bparking\b.*{_ACCESS}",
     "accessible parking"),
    (rf"{_ACCESS}.*\b(restroom|restrooms|toilet|toilets|bathroom|bathrooms|washroom|washrooms|wc)\b|"
     rf"\b(restroom|toilet|bathroom|washroom)s?\b.*{_ACCESS}|\b(family|all[- ]gender|gender[- ]inclusive|unisex)\b"
     rf".*\b(restroom|toilet|bathroom)s?\b.*{_ACCESS}", "accessible restroom"),
    (r"\b(pet|animal|service animal|service dog|dog)s? (relief|potty|rest) ?(area|areas|station|stations|room)?\b|"
     r"\banimal ?relief", "pet relief area"),
    (r"\b(family|companion[- ]care|all[- ]gender|gender[- ]neutral|unisex)\b.*\b(restroom|restrooms|toilet|toilets|"
     r"bathroom|bathrooms)\b|\brestroom\W+family\b", "family restroom"),
    (r"\b(wheel ?chairs?|scooters?|mobility (device|devices|scooter|scooters|aid|aids))\b.*\b(loan|loans|loaner|"
     r"rental|rentals|rent|borrow|available|assistance|escort|service|services)\b|\btsa cares\b|"
     r"\b(wheel ?chair|passenger|special) (assistance|service|services)\b", "accessibility service"),
    (r"\b(ground transport\w*|taxis?|taxi stand|rideshares?|ride[- ]share|ride[- ]app|app[- ]based ride\w*|"
     r"shuttles?|limo\w*|bus (stop|stops|station)|transit (center|centre|station)|pick[- ]?up (area|zone|point))\b",
     "ground transport"),
    (r"\bconcourses?\b", "concourse"),
    (r"\b(entrance|entrances|entry|entries|doors?|ingang|inngang|eingang)\b", "entrance"),
    (r"\b(elevator|elevators|lift|lifts|heis|aufzug)\b", "elevator"),
    (r"\bescalators?\b", "escalator"),
    (r"\b(parking|car park|garage|parking lot|parking deck|parkering)\b", "parking"),
    (r"\b(restroom|restrooms|toilet|toilets|bathroom|bathrooms|washroom|washrooms|wc|lactation)\b", "restroom"),
    (r"\b(emergency (phone|call|telephone)s?|blue[- ]light|call ?box(es)?|code blue)\b", "emergency phone"),
    (r"\b(service desk|help ?desk|it help|patient services|registration|admitting|guest services|security desk|"
     r"customer service|accessibility (desk|office|services)|disability (resource|services)|front desk|reception)\b",
     "service desk"),
    (r"\b(information|info desk|info center|welcome (desk|center)|visitor (center|centre|information)|"
     r"concierge)\b", "information desk"),
    (r"\b(dining|food|cafe|caf\xe9|cafeteria|restaurant|restaurants|coffee|snack|food court|eatery|eateries|"
     r"concessions?)\b", "dining"),
    (r"\b(store|stores|shop|shops|bookstore|retail|gift shop|pharmacy|market)\b", "store"),
    (r"\bgates?\b", "gate"),
    (r"\bterminals?\b", "terminal"),
    (r"\b(building|buildings|hall|halls|academic|residence|dorm|library|center|centre|pavilion|tower|annex)\b",
     "building"),
]
_KIND_RE = [(re.compile(p, re.I), k) for p, k in KIND_WORDS]
# Categories never read from a source: people, offices of persons, rooms, events, and the like (no people's names).
NOT_FEATURES = re.compile(r"\b(faculty|staff|people|person|directory|offices?|rooms?|classrooms?|events?|tours?|"
                          r"photos?|videos?|360|panorama|parking permits?|construction|closures?|art|sculptures?|"
                          r"memorials?|history|athletics teams?|news)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def kind_of(*words):
    """The kind (one of KINDS) of a category or type's words, or "" when none fits. Several word lists may be given
    (a category name, then its parent's); the first that gives a kind wins."""
    for text in words:
        text = " ".join(str(text or "").replace("_", " ").split())
        if not text:
            continue
        for pattern, kind in _KIND_RE:
            if pattern.search(text):
                return kind
    return ""


def clean_note(text, limit=NOTE_LIMIT):
    """A feature's note made safe and short: HTML tags taken out, e-mail addresses taken out, spaces made single,
    cut at a word to limit characters."""
    t = re.sub(r"<[^>]+>", " ", str(text or ""))
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
         .replace("&lt;", "<").replace("&gt;", ">"))
    t = " ".join(EMAIL.sub("", t).split()).strip(" ;,")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " ..."
    return t


def line_text(points):
    """A route's points [(lat, lon)] as the CSV's "line" column ("lat lon;lat lon;...", 6 decimals)."""
    return ";".join(f"{a:.6f} {b:.6f}" for a, b in points)


def parse_line(text):
    """The points [(lat, lon)] of a CSV "line" column, or [] (a broken pair is left out)."""
    out = []
    for pair in str(text or "").split(";"):
        bits = pair.split()
        try:
            out.append((float(bits[0]), float(bits[1])))
        except (IndexError, ValueError):
            continue
    return out


def centroid(rings):
    """A position for an area's outline: the average of its first ring's corners (good enough for a building's
    door-to-door scale), or None for an empty outline."""
    ring = next((r for r in rings or [] if r), None)
    if not ring:
        return None
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


# ------------------------------------------------------------------------------------------------ writing

def store(writer):
    """The FeatureStore of a PackWriter (made, with its table, the first time it is asked for). PackWriter.finish
    calls its finish()."""
    if getattr(writer, "_features", None) is None:
        writer._features = FeatureStore(writer)
    return writer._features


class FeatureStore:
    """The site_features table of one pack being written (see the module docstring)."""

    def __init__(self, writer):
        """Make the table in the writer's database."""
        self.writer, self.db = writer, writer.db
        self.db.execute(f"CREATE TABLE IF NOT EXISTS site_features ({TABLE})")
        self.count = 0

    def add(self, key, source, kind, name, lat, lon, site="", building="", level="", line=None, notes=""):
        """One feature. kind must be one of KINDS (anything else is not written); line: [(lat, lon)] for a route
        (its middle point is then the position); notes: cleaned (clean_note). A feature outside the writer's
        sub-region (its clip) is left out. Returns True when written."""
        if kind not in KINDS or not key:
            return False
        points = [p for p in (line or []) if p]
        if len(points) >= 2:
            points = fmt.simplify(points)
            lat, lon = points[len(points) // 2]
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            return False
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
            return False
        if self.writer.clip is not None and not self.writer._inside(lat, lon):
            return False
        self.writer._extend(lat, lon)
        pts = fmt.pack_points(fmt.micro(points)) if len(points) >= 2 else None
        self.db.execute(f"INSERT INTO site_features ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                        (str(key), source, kind, " ".join(str(name or "").split()) or None, site or None,
                         building or None, " ".join(str(level or "").split()) or None, int(round(lat * fmt.SCALE)),
                         int(round(lon * fmt.SCALE)), fmt.fine_cell(lat, lon), pts, clean_note(notes) or None))
        self.count += 1
        return True

    def finish(self):
        """Keep each key once (the first row of a key and source), write the indexes. Returns {"site_features": n}."""
        db = self.db
        db.execute("DELETE FROM site_features WHERE id NOT IN (SELECT MIN(id) FROM site_features GROUP BY key, "
                   "source)")
        db.executescript("""
            CREATE INDEX IF NOT EXISTS site_features_cell ON site_features (cell);
            CREATE INDEX IF NOT EXISTS site_features_site ON site_features (site);
            CREATE INDEX IF NOT EXISTS site_features_building ON site_features (building);
            CREATE INDEX IF NOT EXISTS site_features_key ON site_features (key);
        """)
        return {"site_features": db.execute("SELECT COUNT(*) FROM site_features").fetchone()[0]}


def copy_from(writer, alias, have):
    """placepacks.combine: copy the site_features rows of an attached child pack (alias; have: its table names)
    into the parent pack being written. Returns the number of rows."""
    if "site_features" not in have:
        return 0
    store(writer)
    cols = ", ".join(COLUMNS)
    before = writer.db.execute("SELECT COUNT(*) FROM site_features").fetchone()[0]
    writer.db.execute(f"INSERT INTO main.site_features ({cols}) SELECT {cols} FROM {alias}.site_features ORDER BY id")
    return writer.db.execute("SELECT COUNT(*) FROM site_features").fetchone()[0] - before


# ------------------------------------------------------------------------------------------------ the build's reader

def _float(text):
    """A number from a CSV field, or None."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def csv_rows(path, member="*.csv"):
    """The dict rows of a collectors' CSV file, or of every CSV file in a folder (the region's slice)."""
    from placepacks.readers.tabular import open_texts
    for text in open_texts(path, member, "utf-8-sig"):
        yield from csv.DictReader(io.StringIO(text) if isinstance(text, str) else text)


def in_region(region, lat, lon):
    """True when a position is in the region (with the usual 0.05 degree margin)."""
    from placepacks.regions import in_region as inside
    return inside(region, lat, lon, 0.05)


class SiteResolver:
    """Ties a collector's site to the place already in the pack being written (see resolve)."""

    SITE_CLASSES = ("campus", "public", "landmark", "park", "business", "building", "transit")

    def __init__(self, writer):
        """writer: the PackWriter of the pack (its points and areas so far)."""
        self.db = writer.db
        self.keys = None

    def has_key(self, key):
        """True when a point or area with this key is in the pack."""
        if self.keys is None:
            self.keys = {k for (k,) in self.db.execute("SELECT key FROM points UNION SELECT key FROM areas")}
        return key in self.keys

    def by_name(self, name, lat, lon, metres=400):
        """The key of the pack's point or area of a site class with nearly the same name within metres (or whose
        outline's box holds the position), or ""."""
        from placepacks.directories.common import name_similarity
        if not name or lat is None:
            return ""
        tol = int(metres / 0.111)
        y, x = int(lat * fmt.SCALE), int(lon * fmt.SCALE)
        marks = ",".join("?" * len(self.SITE_CLASSES))
        best = (0.0, 1e18, "")
        for key, other, plat, plon in self.db.execute(
                f"SELECT key, name, lat, lon FROM points WHERE cls IN ({marks}) AND lat BETWEEN ? AND ? AND lon "
                f"BETWEEN ? AND ?", (*self.SITE_CLASSES, y - tol, y + tol, x - 2 * tol, x + 2 * tol)):
            score = name_similarity(name, other)
            if score >= 0.85:
                d = abs(plat - y) + abs(plon - x)
                if (score, -d) > (best[0], -best[1]):
                    best = (score, d, key)
        for key, other, s, w, n, e in self.db.execute(
                f"SELECT key, name, minlat, minlon, maxlat, maxlon FROM areas WHERE cls IN ({marks}) AND minlat <= ? "
                f"AND maxlat >= ? AND minlon <= ? AND maxlon >= ?", (*self.SITE_CLASSES, y + tol, y - tol, x + tol,
                                                                      x - tol)):
            score = name_similarity(name, other)
            if score >= 0.85 and score > best[0]:
                best = (score, 0, key)
        return best[2]

    def holding_area(self, lat, lon, classes=("campus",)):
        """The key of the smallest area of the classes holding the position (a campus, hospital or zoo grounds),
        or ""."""
        from placepacks.lookup import inside_rings
        y, x = int(lat * fmt.SCALE), int(lon * fmt.SCALE)
        marks = ",".join("?" * len(classes))
        for key, rings in self.db.execute(
                f"SELECT key, rings FROM areas WHERE cls IN ({marks}) AND minlat <= ? AND maxlat >= ? AND minlon <= ? "
                f"AND maxlon >= ? ORDER BY size", (*classes, y, y, x, x)):
            if inside_rings(lat, lon, fmt.unpack_rings(rings)):
                return key
        return ""

    def resolve(self, row, npi_source="cms-nppes-organisations"):
        """The pack key of a collector's site row: its place_key when that place is in the pack, else the NPI's
        organisation (npi_source), else the same name nearby, else the campus area holding it; "" when none."""
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        for key in (row.get("place_key") or "", f"{npi_source}:{row.get('npi')}" if row.get("npi") else ""):
            if key and self.has_key(key):
                return key
        name = row.get("site_name") or row.get("name") or ""
        key = self.by_name(name, lat, lon) if lat is not None else ""
        if not key and lat is not None:
            key = self.holding_area(lat, lon, ("campus", "landmark", "park", "public"))
        return key


@reader("site_features")
def read(path, entry, region, writer):
    """The "site_features" reader: a collectors' CSV (FEATURE_FIELDS)
    into the pack. Site rows give their place the details it lacks; feature rows go to site_features (unless the
    entry's "features" is false: a part that only takes the details, such as the businesses part). A site that
    matches no place is written as a row of kind "site", unless the entry's "keep_unmatched_sites" is false (the
    insurers' directories: thousands of clinics the packs do not have are not added as sites; nor are the features
    of such a site, a museum the packs do not have). The entry's "kinds"
    (a list) keeps only the features of those kinds (the street-access set's curb ramps go only to the navigation
    part); its "sites": false gives a feature without a site of its own no site at all (an accessible pedestrian
    signal is not "inside" the campus around it). Returns the number of features written plus the places that got
    details."""
    from placepacks import contact as contacts
    source = entry["id"]
    rows = []
    for row in csv_rows(path, entry.get("member", "*.csv")):
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        points = parse_line(row.get("line"))
        if (lat is None or lon is None) and points:
            lat, lon = points[len(points) // 2]
        if lat is None or lon is None or not in_region(region, lat, lon):
            continue
        rows.append(row)
    resolver = SiteResolver(writer)
    with_features = entry.get("features", True)
    feats = store(writer) if with_features else None
    sites, unmatched, count = {}, set(), 0
    # The sites first: each collector site key -> the pack key it resolves to (or its own key, written as a row of
    # kind "site").
    for row in rows:
        if (row.get("kind") or "") != "site":
            continue
        ref = row.get("site") or row.get("key")
        key = resolver.resolve(row)
        note = clean_note(row.get("notes"), 1200)
        contact = {f: row.get(f, "") for f in contacts.CONTACT_FIELDS if row.get(f)}
        if key:
            if (contact or note) and writer.fill_details(source, key, contact, note or None):
                count += 1
            sites[ref] = key
        elif with_features and entry.get("keep_unmatched_sites", True):
            if feats.add(ref, source, "site", row.get("site_name") or row.get("name"), row.get("lat"),
                         row.get("lon"), notes=note):
                count += 1
            sites[ref] = ref
        else:
            unmatched.add(ref)              # its features are left out too (a museum the packs do not have)
    if not with_features:
        return count
    only = set(entry.get("kinds") or KINDS)
    for row in rows:
        kind = row.get("kind") or ""
        if kind == "site" or kind not in KINDS or kind not in only or (row.get("site") or "") in unmatched:
            continue
        lat, lon = _float(row.get("lat")), _float(row.get("lon"))
        points = parse_line(row.get("line"))
        site = sites.get(row.get("site") or "", "")
        if not site and row.get("site"):
            site = resolver.resolve({**row, "kind": "site", "name": row.get("site_name", "")}) or row["site"]
        if not site and lat is not None and entry.get("sites", True):
            site = resolver.holding_area(lat, lon, ("campus", "landmark", "park", "public"))
        if feats.add(row.get("key"), source, kind, row.get("name"), lat, lon, site=site,
                     building=row.get("building", ""), level=row.get("level", ""), line=points,
                     notes=row.get("notes", "")):
            count += 1
    return count


def write_csv(path, rows):
    """Write collector rows (dicts with FEATURE_FIELDS) as a CSV (plain or .gz by the name). Returns the number."""
    import gzip
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FEATURE_FIELDS, extrasaction="ignore")
        w.writeheader()
        n = 0
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FEATURE_FIELDS})
            n += 1
    return n


def describe(row):
    """A feature row (a PackReader dict) as a short plain sentence part: "accessible entrance: North Entrance
    (level 1)". Data for programs; the Assistant words its own answers."""
    bits = [row.get("kind") or "feature"]
    if row.get("name"):
        bits[0] += f": {row['name']}"
    if row.get("level"):
        bits.append(f"level {row['level']}")
    return bits[0] + (f" ({', '.join(bits[1:])})" if len(bits) > 1 else "")


def to_json(rows):
    """Feature rows as compact JSON (for a program's log)."""
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
