"""The regions packs are made for (regions.json): US states, Canadian provinces, and Geofabrik's regions of Western
Europe, Australia, New Zealand and Japan.

  REGIONS                      {id: region dict (id, name, country, cc, continent, geofabrik, bbox)}
  regions_for(lat, lon, resolver=None)   the regions a position may be in, best first (packs are made for these)
  regions_near(lat, lon, km=2)  the regions within km of a position, the one holding it first (a point near the
                               border of two sub-regions needs both packs)
  boxes_of(region), in_region(region, lat, lon), touches_region(region, box)   a region's boxes (two for Alaska, whose
                               Aleutians cross 180°: its bbox alone would be a band round the globe)
  query_boxes(region)          the boxes to ask a server for (a sub-region's whole box, not its many small boxes)
  region_label(id)             "Vermont, United States"
  tree()                       {continent: {country: [region ids]}}, for lists grouped by continent and country

Sub-regions: a region too large for one pack (England, Texas, California, Australia, ...) has "children": its packs
are made for the children ("gb-england-south-east", "us-texas-gulf-coast", "au-new-south-wales"). A child has
"parent", its parent's fields (code, fips, geofabrik: its OpenStreetMap is clipped from the parent's extract) and
"grid": the parent's box cut into cells of "step" degrees from "origin" (west, south), "size" (columns, rows); each
cell belongs to exactly one child, and the child's "boxes" are its cells joined into rectangles. A parent id is
still accepted wherever a region id is (expand(id) gives its children; packs.json keeps a combined pack of the
parent for programs that know only the parent).
  leaves()                     the ids packs are built for (every region without children)
  expand(id)                   [the children] of a parent, else [id]
  parent_of(id)                the parent id of a child, else ""
"""

import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "regions.json"), encoding="utf-8") as _f:
    REGIONS = {r["id"]: r for r in json.load(_f)["regions"]}


def leaves():
    """The ids of the regions packs are built for: every region without children, in regions.json's order."""
    return [rid for rid, r in REGIONS.items() if not r.get("children")]


def expand(region_id):
    """The children of a parent region (the packs that cover it), else [region_id]."""
    r = REGIONS.get(region_id)
    return list(r["children"]) if r and r.get("children") else [region_id]


def parent_of(region_id):
    """The parent id of a sub-region, else ""."""
    return (REGIONS.get(region_id) or {}).get("parent", "")


def region_label(region_id):
    """"Vermont, United States" (the id itself when it is not known)."""
    r = REGIONS.get(region_id)
    return f"{r['name']}, {r['country']}" if r and r["name"] != r["country"] else (r["name"] if r else region_id)


def _inside(bbox, lat, lon):
    """True when the position is in a bounding box (west, south, east, north); a box whose west is east of its
    east crosses the antimeridian (180°)."""
    return any(south <= lat <= north and west <= lon <= east for west, south, east, north in split_box(bbox))


def split_box(bbox):
    """A box as boxes that do not cross the antimeridian: [(west, south, east, north)], two when west > east."""
    west, south, east, north = bbox
    if west > east:
        return [(west, south, 180.0, north), (-180.0, south, east, north)]
    return [(west, south, east, north)]


def boxes_of(region):
    """The boxes of a region: its "boxes" when it has them (Alaska: the mainland and the Aleutians west of 180°,
    which its single bbox would join into a band round the whole globe), else its bbox, split at 180° if needed."""
    out = []
    for box in region.get("boxes") or [region["bbox"]]:
        out += split_box(tuple(box))
    return out


def query_boxes(region):
    """The boxes to ask a server for: a sub-region's whole box (its cells can be many small boxes; the readers keep
    only what is in the sub-region), else boxes_of(region)."""
    return [tuple(region["bbox"])] if region.get("grid") else boxes_of(region)


_CELLS = {}
GRID_SCAN_LIMIT = 20000         # a box over more cells than this is tested against the boxes instead


def _cells(region):
    """The set of (row, column) grid cells of a sub-region (from its boxes), cached by id."""
    key = (region["id"], len(region.get("boxes", [])))
    if key not in _CELLS:
        g = region["grid"]
        step, (w0, s0) = g["step"], g["origin"]
        cells = set()
        for w, s, e, n in region["boxes"]:
            for row in range(round((s - s0) / step), round((n - s0) / step)):
                for col in range(round((w - w0) / step), round((e - w0) / step)):
                    cells.add((row, col))
        _CELLS[key] = cells
    return _CELLS[key]


def _grid_span(region, south, west, north, east, margin):
    """(rows, columns) ranges of the grid cells a box (widened by margin) covers, clamped to the grid: a position
    just outside the parent's box (within margin) counts in the nearest edge cell. None when it is outside."""
    g = region["grid"]
    step, (w0, s0), (cols, rows) = g["step"], g["origin"], g["size"]
    top, right = s0 + rows * step, w0 + cols * step
    if north + margin < s0 or south - margin > top or east + margin < w0 or west - margin > right:
        return None

    def index(v, origin, count):
        return min(max(math.floor((v - origin) / step), 0), count - 1)
    return (range(index(south - margin, s0, rows), index(north + margin, s0, rows) + 1),
            range(index(west - margin, w0, cols), index(east + margin, w0, cols) + 1))


def in_region(region, lat, lon, margin=0.0):
    """True when a position is inside one of the region's boxes (widened by margin degrees). For a sub-region, inside
    one of its grid cells: each position of the parent's box is in exactly one child (with no margin)."""
    if region.get("grid"):
        span = _grid_span(region, lat, lon, lat, lon, margin)
        if span is None:
            return False
        cells = _cells(region)
        return any((r, c) in cells for r in span[0] for c in span[1])
    return any(s - margin <= lat <= n + margin and w - margin <= lon <= e + margin for w, s, e, n in boxes_of(region))


def touches_region(region, box, margin=0.0):
    """True when a box (west, south, east, north) overlaps one of the region's boxes."""
    x1, y1, x2, y2 = box
    if region.get("grid"):
        span = _grid_span(region, y1, x1, y2, x2, margin)
        if span is None:
            return False
        if len(span[0]) * len(span[1]) <= GRID_SCAN_LIMIT:
            cells = _cells(region)
            return any((r, c) in cells for r in span[0] for c in span[1])
    return any(not (x2 < w - margin or x1 > e + margin or y2 < s - margin or y1 > n + margin)
               for w, s, e, n in boxes_of(region))


def regions_for(lat, lon, resolver=None, bounds=None):
    """The regions a position may be in, best first: resolver(lat, lon) -> region id ("" when it does not know),
    then the regions whose bounds hold the position, the smallest first. bounds: {region id: bbox} of the packs
    actually built (more exact than regions.json's country boxes for sub-regions), used first when given. Only
    regions packs are made for: a parent (England, Texas) is given as the child holding the position."""
    found = []
    if resolver is not None:
        try:
            rid = resolver(lat, lon)
        except Exception:  # noqa: BLE001 - a resolver that fails only gives no answer
            rid = ""
        if rid in REGIONS and REGIONS[rid].get("children"):
            rid = next((c for c in REGIONS[rid]["children"] if c in REGIONS and in_region(REGIONS[c], lat, lon)), "")
        if rid in REGIONS:
            found.append(rid)
    candidates = []
    for rid, r in REGIONS.items():
        if r.get("children"):
            continue
        if r.get("grid"):
            # A sub-region: its cells (a pack's bounds overlap its neighbours').
            if in_region(r, lat, lon):
                candidates.append((sum((e - w) * (n - s) for w, s, e, n in r["boxes"]), rid))
            continue
        boxes = [(bounds or {})[rid]] if (bounds or {}).get(rid) else boxes_of(r)
        if any(_inside(box, lat, lon) for box in boxes):
            size = sum(sum((e - w) * (n - s) for w, s, e, n in split_box(box)) for box in boxes)
            candidates.append((size, rid))
    for _, rid in sorted(candidates):
        if rid not in found:
            found.append(rid)
    return found


def regions_near(lat, lon, km=2.0, resolver=None, bounds=None):
    """The regions whose packs a position needs: the best of regions_for, then the sub-regions within km of it (a
    position near the border of two sub-regions needs both packs; their cells are exact). Other regions only have
    boxes, which overlap (the UK's nations share one box), so only the best of them is given, as before."""
    best = regions_for(lat, lon, resolver, bounds)[:1]
    margin = km / 111.0
    near = [rid for rid, r in REGIONS.items() if r.get("grid") and rid not in best and
            in_region(r, lat, lon, margin)]
    return best + near


def tree():
    """{continent: {country: [region ids in name order]}}: the regions packs are made for (a parent's children
    together, in the order of the parent's name)."""
    out = {}

    def order(kv):
        r = kv[1]
        parent = REGIONS.get(r.get("parent", ""), {})
        return r["continent"], r["country"], parent.get("name", r["name"]), r["name"]
    for rid, r in sorted(REGIONS.items(), key=order):
        if not r.get("children"):
            out.setdefault(r["continent"], {}).setdefault(r["country"], []).append(rid)
    return out
