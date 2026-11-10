"""The regions packs are made for (regions.json): US states, Canadian provinces, and Geofabrik's regions of Western
Europe, Australia, New Zealand and Japan.

  REGIONS                      {id: region dict (id, name, country, cc, continent, geofabrik, bbox)}
  regions_for(lat, lon, resolver=None)   the regions a position may be in, best first
  boxes_of(region), in_region(region, lat, lon), touches_region(region, box)   a region's boxes (two for Alaska, whose
                               Aleutians cross 180°: its bbox alone would be a band round the globe)
  region_label(id)             "Vermont, United States"
  tree()                       {continent: {country: [region ids]}}, for lists grouped by continent and country
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "regions.json"), encoding="utf-8") as _f:
    REGIONS = {r["id"]: r for r in json.load(_f)["regions"]}


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


def in_region(region, lat, lon, margin=0.0):
    """True when a position is inside one of the region's boxes (widened by margin degrees)."""
    return any(s - margin <= lat <= n + margin and w - margin <= lon <= e + margin for w, s, e, n in boxes_of(region))


def touches_region(region, box, margin=0.0):
    """True when a box (west, south, east, north) overlaps one of the region's boxes."""
    x1, y1, x2, y2 = box
    return any(not (x2 < w - margin or x1 > e + margin or y2 < s - margin or y1 > n + margin)
               for w, s, e, n in boxes_of(region))


def regions_for(lat, lon, resolver=None, bounds=None):
    """The regions a position may be in, best first: resolver(lat, lon) -> region id ("" when it does not know),
    then the regions whose bounds hold the position, the smallest first. bounds: {region id: bbox} of the packs
    actually built (more exact than regions.json's country boxes for sub-regions), used first when given."""
    found = []
    if resolver is not None:
        try:
            rid = resolver(lat, lon)
        except Exception:  # noqa: BLE001 - a resolver that fails only gives no answer
            rid = ""
        if rid in REGIONS:
            found.append(rid)
    candidates = []
    for rid, r in REGIONS.items():
        boxes = [(bounds or {})[rid]] if (bounds or {}).get(rid) else boxes_of(r)
        if any(_inside(box, lat, lon) for box in boxes):
            size = sum(sum((e - w) * (n - s) for w, s, e, n in split_box(box)) for box in boxes)
            candidates.append((size, rid))
    for _, rid in sorted(candidates):
        if rid not in found:
            found.append(rid)
    return found


def tree():
    """{continent: {country: [region ids in name order]}}."""
    out = {}
    for rid, r in sorted(REGIONS.items(), key=lambda kv: (kv[1]["continent"], kv[1]["country"], kv[1]["name"])):
        out.setdefault(r["continent"], {}).setdefault(r["country"], []).append(rid)
    return out
