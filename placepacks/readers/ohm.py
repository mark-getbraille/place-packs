"""OpenHistoricalMap (CC0): named historical features with their own dates (start_date, end_date): old businesses,
buildings, stations, forts, mills, schools. fetch.py asks OHM's Overpass API once per region for the nodes and ways
with a name and a start or end date, inside the region's box ("out center tags": a way comes as its centre), and saves
the answer (JSON); this reader reads that file.

  - the class and the fine type come from the tags as for OpenStreetMap (readers.osm.main_tag, placepacks.types.osm);
    lines (streets, railway lines, rivers), administrative boundaries and regions are left out (they are not places
    at a point);
  - first and last are the feature's start_date and end_date ("1885", "1885-06", "~1885", "1885..1890" -> 1885);
    a feature without an end date is still there;
  - OHM's data is CC0, except features that carry their own licence tag (license=* other than CC0 or public
    domain): those are left out.
Keys are "ohm:n123" and "ohm:w45" (OHM's own ids).
"""

import json
import re

from placepacks import fmt, types
from placepacks.readers import reader
from placepacks.regions import in_region
from placepacks.readers.osm import main_tag

OPEN = {"cc0", "cc0-1.0", "cc-0", "pd", "public domain", "publicdomain"}
LINES = {"street", "admin", "region"}


def ohm_date(text):
    """YYYYMM of an OHM date ("1885", "1885-06-01", "~1885", "1885..1890", "1885/1890"); None for "before 1900" and
    other words."""
    text = (text or "").strip().lstrip("~").split("..")[0].split("/")[0].strip()
    return fmt.parse_month(text) if re.match(r"-?\d{3,4}", text) else None


@reader("ohm")
def read(path, entry, region, writer):
    """Add the dated features of a saved Overpass answer. Returns the number of features."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    count = 0
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name or el.get("type") not in ("node", "way"):
            continue
        if tags.get("license") and tags["license"].strip().lower() not in OPEN:
            continue
        if (tags.get("railway") and tags["railway"] not in ("station", "halt")) or \
                (tags.get("waterway") and tags["waterway"] not in ("dam", "waterfall")):
            continue
        found = main_tag(tags)
        kind = types.osm(tags) or None
        if not found and kind:
            found = ("ohm", kind, "landmark")       # a mill, a mine, a factory: typed but outside OSM's classes
        if not found or found[2] in LINES:
            continue
        at = el if el.get("type") == "node" else (el.get("center") or {})
        try:
            lat, lon = float(at["lat"]), float(at["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not in_region(region, lat, lon, 0.05):
            continue
        first, last = ohm_date(tags.get("start_date")), ohm_date(tags.get("end_date"))
        if first is None and last is None:
            continue
        writer.add_point(f"ohm:{el['type'][0]}{el['id']}", entry["id"], name, found[2], f"{found[0]}={found[1]}",
                         lat, lon, first, last, type=kind)
        count += 1
    return count
