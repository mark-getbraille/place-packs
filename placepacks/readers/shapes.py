"""Shapefiles in longitude/latitude (pyshp, MIT), plain or zipped, one file or a folder of them (the Census
publishes TIGER/Line address ranges per county).

  "kind": "ranges"  TIGER/Line ADDRFEAT: the street name and the house numbers on each side, keyed by TIGER's edge
                    id (TLID), so a renamed street or changed range gets a new row and the old one is kept
  "kind": "areas"   named areas (Census places, county subdivisions, ZIP code tabulation areas, school districts)
  "kind": "lines"   named lines (trails)
  "kind": "points"  named points (trailheads)
"fields": {"name": ..., "key": ..., and for ranges "lfrom", "lto", "rfrom", "rto", "zip"} (a name or a list of possible
names, the first the file has); "cls": the class; "name_format":
an optional pattern such as "the {} area" for ZIP areas. Only shapes touching the region's bounding box are read.
"""

import glob
import os

from placepacks.readers import reader
from placepacks.readers.tabular import smart_case


def files_of(path):
    """The shapefiles (.shp or .zip) of path (a file or a folder)."""
    path = str(path)
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "*.zip")) + glob.glob(os.path.join(path, "*.shp")))
    return [path]


def _number(text):
    """A house number as a whole number (the digits before any letter), or None."""
    digits = ""
    for ch in str(text or "").strip():
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def _field(rec, names):
    """A record's value of a field, or of the first of a list of possible field names that the file has ("")."""
    for name in names if isinstance(names, list) else [names]:
        if name in rec and rec[name] not in (None, ""):
            return rec[name]
    return ""


def _parts(shape):
    """The parts of a shape as lists of (lat, lon)."""
    starts = list(shape.parts) + [len(shape.points)]
    return [[(y, x) for x, y in shape.points[a:b]] for a, b in zip(starts, starts[1:])]


@reader("shapes")
def read(path, entry, region, writer):
    """Add the source's ranges, areas, lines or points to writer. Returns the number of records."""
    import shapefile
    fields, source, kind, count = entry["fields"], entry["id"], entry["kind"], 0
    west, south, east, north = region["bbox"]
    for file in files_of(path):
        with shapefile.Reader(file) as shp:
            names = [f[0] for f in shp.fields[1:]]
            for sr in shp.iterShapeRecords():
                shape, rec = sr.shape, dict(zip(names, sr.record))
                if not shape.points:
                    continue
                x1, y1, x2, y2 = shape.bbox if len(shape.points) > 1 else (*shape.points[0], *shape.points[0])
                if x2 < west or x1 > east or y2 < south or y1 > north:
                    continue
                name = smart_case(str(_field(rec, fields["name"])))
                if not name:
                    continue
                if entry.get("name_format"):
                    name = entry["name_format"].format(name)
                key = f"{source}:{_field(rec, fields['key'])}" if fields.get("key") else None
                if kind == "ranges":
                    nums = [_number(rec.get(fields[k])) for k in ("lfrom", "lto", "rfrom", "rto")]
                    if all(n is None for n in nums):
                        continue
                    zip_code = str(rec.get(fields.get("zip", ""), "") or rec.get(fields.get("zip2", ""), "") or "")
                    for part in _parts(shape):
                        writer.add_range(key or f"{source}:{name}:{part[0]}", source, name, *nums, zip_code, part)
                elif kind == "areas":
                    writer.add_area(key or f"{source}:{name}", source, name, entry["cls"], entry.get("tag", source),
                                    _parts(shape))
                elif kind == "lines":
                    for i, part in enumerate(_parts(shape)):
                        writer.add_line(f"{key or source + ':' + name}:{i}", source, name, entry["cls"],
                                        entry.get("tag", source), part)
                else:
                    lon, lat = shape.points[0]
                    writer.add_point(key or f"{source}:{name}:{lat:.4f}:{lon:.4f}", source, name, entry["cls"],
                                     entry.get("tag", source), lat, lon)
                count += 1
    return count
