"""The regions packs are made for (regions.json): US states, Canadian provinces, and Geofabrik's regions of Western
Europe, Australia, New Zealand and Japan.

  REGIONS                      {id: region dict (id, name, country, cc, continent, geofabrik, bbox)}
  regions_for(lat, lon, resolver=None)   the regions a position may be in, best first
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
    """True when the position is in a bounding box (west, south, east, north)."""
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


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
        box = (bounds or {}).get(rid) or r["bbox"]
        if _inside(box, lat, lon):
            w, s, e, n = box
            candidates.append(((e - w) * (n - s), rid))
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
