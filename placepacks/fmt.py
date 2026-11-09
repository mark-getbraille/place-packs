"""The place pack format: constants, the grid, the geometry blobs, the address cells and month numbers.

A pack is one SQLite file. FORMAT.md describes the tables; the Digital Accessibility Toolkit's reader
(app/toolkit/vision/osm.py, PackReader) reads exactly this. Coordinates are whole microdegrees (SCALE); the grid has
fine cells of 1/100 degree (about 1.1 km) and coarse cells of 1/10 degree. Dates are months, written YYYYMM
(202611 for November 2026); the address cells store them as months since January 2000 (month_index).
"""

import array
import datetime
import math
import struct
import sys
import zlib

PACK_FORMAT = "digital-accessibility-toolkit-osm-place-pack"
PACK_VERSION = 2
PACK_SUFFIX = ".osmpack"
SCALE = 1_000_000
FINE = 100
COARSE = 10
BIG_CELLS = 400                 # a shape touching more fine cells than this is indexed in coarse cells
EARTH_M = 6_371_008.8
SIMPLIFY_M = 5.0
ATTRIBUTION = "© OpenStreetMap contributors"
PARTS = ("core", "extra")       # core: OpenStreetMap, addresses, address ranges and Census areas; extra: the rest


# ------------------------------------------------------------------------------------------- months

def month_of(date=None):
    """YYYYMM of a date (today by default)."""
    date = date or datetime.date.today()
    return date.year * 100 + date.month


def parse_month(text):
    """YYYYMM from "2026-11", "2026-11-03", "2026-11-03T10:00:00Z", "+1923-05-00T00:00:00Z" (Wikidata) or "2026";
    None when it is not a date."""
    text = (text or "").strip().lstrip("+")
    try:
        year = int(text[:4])
    except ValueError:
        return None
    month = 1
    if len(text) >= 7 and text[4] in "-/":
        try:
            month = max(1, min(12, int(text[5:7])))
        except ValueError:
            month = 1
    return year * 100 + month if 1 <= year <= 9999 else None


def month_index(yyyymm):
    """Months since January 2000 (0 for 200001; never below 0, at most 65535), for the address cells."""
    return max(0, min(65535, (yyyymm // 100 - 2000) * 12 + yyyymm % 100 - 1))


def month_from_index(index):
    """The opposite of month_index."""
    return (2000 + index // 12) * 100 + index % 12 + 1


def add_months(yyyymm, n):
    """yyyymm moved by n months."""
    i = (yyyymm // 100) * 12 + yyyymm % 100 - 1 + n
    return (i // 12) * 100 + i % 12 + 1


# ------------------------------------------------------------------------------------------- the grid

def fine_cell(lat, lon):
    """The fine cell of a position (degrees)."""
    return int(math.floor((lat + 90.0) * FINE)) * 360 * FINE + int(math.floor((lon + 180.0) * FINE))


def coarse_cell(lat, lon):
    """The coarse cell of a position (degrees)."""
    return int(math.floor((lat + 90.0) * COARSE)) * 360 * COARSE + int(math.floor((lon + 180.0) * COARSE))


def cell_corner(cell):
    """(lat, lon) microdegrees of the south-west corner of a fine cell."""
    row, col = divmod(cell, 360 * FINE)
    return int(round((row / FINE - 90.0) * SCALE)), int(round((col / FINE - 180.0) * SCALE))


def cells_of(south, west, north, east):
    """(level, [cells]) of a bounding box in degrees: 1 and fine cells, or 0 and coarse cells when it touches more
    than BIG_CELLS fine cells."""
    def span(scale):
        rows = range(int(math.floor((south + 90) * scale)), int(math.floor((north + 90) * scale)) + 1)
        cols = range(int(math.floor((west + 180) * scale)), int(math.floor((east + 180) * scale)) + 1)
        return [r * 360 * scale + c for r in rows for c in cols]
    rows = int(math.floor((north + 90) * FINE)) - int(math.floor((south + 90) * FINE)) + 1
    cols = int(math.floor((east + 180) * FINE)) - int(math.floor((west + 180) * FINE)) + 1
    return (1, span(FINE)) if rows * cols <= BIG_CELLS else (0, span(COARSE))


# ------------------------------------------------------------------------------------------- blobs

def pack_points(points):
    """The blob of [(lat, lon) microdegrees]: little-endian int32 pairs."""
    values = array.array("i", [int(v) for p in points for v in p])
    if sys.byteorder == "big":
        values.byteswap()
    return values.tobytes()


def unpack_points(blob):
    """The opposite of pack_points."""
    values = array.array("i")
    values.frombytes(blob or b"")
    if sys.byteorder == "big":
        values.byteswap()
    return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]


def pack_rings(rings):
    """Rings joined with (0, 0) pairs between them."""
    points = []
    for i, ring in enumerate(rings):
        if i:
            points.append((0, 0))
        points.extend(ring)
    return pack_points(points)


def unpack_rings(blob):
    """The opposite of pack_rings."""
    rings, ring = [], []
    for p in unpack_points(blob):
        if p == (0, 0):
            if ring:
                rings.append(ring)
            ring = []
        else:
            ring.append(p)
    if ring:
        rings.append(ring)
    return rings


ADDRESS = struct.Struct("<HHHHH")   # dlat, dlon (microdegrees from the cell's corner), street, first, last


def encode_addresses(rows):
    """The data blob of one address cell from [(dlat, dlon, street index, number, first YYYYMM, last YYYYMM)]:
    each record ADDRESS then the number (one length byte and UTF-8, at most 20 bytes); zlib-compressed."""
    out = bytearray()
    for dlat, dlon, street, number, first, last in rows:
        raw = (number or "").encode("utf-8")[:20]
        out += ADDRESS.pack(dlat, dlon, street, month_index(first), month_index(last)) + bytes([len(raw)]) + raw
    return zlib.compress(bytes(out), 9)


def decode_addresses(blob):
    """The opposite of encode_addresses: [(dlat, dlon, street index, number, first YYYYMM, last YYYYMM)]."""
    data, rows, at = zlib.decompress(blob), [], 0
    while at < len(data):
        dlat, dlon, street, first, last = ADDRESS.unpack_from(data, at)
        at += ADDRESS.size
        size = data[at]
        number = data[at + 1:at + 1 + size].decode("utf-8", "replace")
        at += 1 + size
        rows.append((dlat, dlon, street, number, month_from_index(first), month_from_index(last)))
    return rows


# ------------------------------------------------------------------------------------------- geometry

def metres(lat1, lon1, lat2, lon2):
    """Distance in metres between two close positions in degrees."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(x, math.radians(lat2 - lat1)) * EARTH_M


def segment_metres(lat, lon, a, b):
    """Distance in metres from a position (degrees) to the segment a-b (microdegree pairs)."""
    k = math.cos(math.radians(lat))
    px, py = lon * SCALE * k, lat * SCALE
    ax, ay, bx, by = a[1] * k, a[0], b[1] * k, b[0]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) / SCALE * math.pi / 180 * EARTH_M


def simplify(points, tolerance_m=SIMPLIFY_M):
    """Douglas-Peucker simplification of [(lat, lon)] degrees (the first and last points stay)."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        a, b = points[first], points[last]
        am, bm = (a[0] * SCALE, a[1] * SCALE), (b[0] * SCALE, b[1] * SCALE)
        worst, at = 0.0, None
        for i in range(first + 1, last):
            d = segment_metres(points[i][0], points[i][1], am, bm)
            if d > worst:
                worst, at = d, i
        if at is not None and worst > tolerance_m:
            keep[at] = True
            stack += [(first, at), (at, last)]
    return [p for p, k in zip(points, keep) if k]


def micro(points):
    """[(lat, lon)] degrees -> microdegrees."""
    return [(int(round(lat * SCALE)), int(round(lon * SCALE))) for lat, lon in points]


def ring_area_m2(ring):
    """Area of a ring of (lat, lon) degrees in square metres."""
    if len(ring) < 3:
        return 0.0
    lat0 = sum(p[0] for p in ring) / len(ring)
    k, m = math.cos(math.radians(lat0)), math.pi / 180 * EARTH_M
    xy = [(p[1] * k * m, p[0] * m) for p in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]))) / 2


# ------------------------------------------------------------------------------------------- classes

def classify(category, kind):
    """The class of a named thing from its main tag (OpenStreetMap key=value, or a source's own category mapped
    to one): park, landmark, campus, water, nature, neighbourhood, street, building, business, transit, or ""."""
    category, kind = (category or "").lower(), (kind or "").lower()
    if category == "leisure" and kind in ("park", "garden", "nature_reserve", "playground", "dog_park",
                                          "recreation_ground", "golf_course", "stadium", "marina", "common"):
        return "park"
    if category == "boundary" and kind in ("national_park", "protected_area"):
        return "park"
    if category in ("tourism", "historic") or (category == "man_made" and kind in ("lighthouse", "tower", "pier",
                                                                                  "bridge")):
        return "business" if kind in ("hotel", "motel", "guest_house", "hostel") else "landmark"
    if category == "amenity" and kind in ("university", "college", "school", "hospital", "grave_yard"):
        return "campus"
    if category == "landuse" and kind in ("cemetery", "recreation_ground", "village_green"):
        return "park"
    if category == "natural" and kind in ("water", "bay", "beach"):
        return "water"
    if category in ("natural", "waterway"):
        return "nature"
    if category == "place" and kind in ("neighbourhood", "suburb", "quarter", "city_block", "locality"):
        return "neighbourhood"
    if category == "highway" and kind in ("bus_stop",):
        return "transit"
    if category in ("railway", "public_transport") and kind in ("station", "halt", "stop_position", "platform"):
        return "transit"
    if category == "highway":
        return "street"
    if category == "building":
        return "building"
    if category in ("amenity", "shop", "office", "craft", "leisure", "aeroway", "railway", "public_transport"):
        return "business"
    return ""
