"""Shapefiles in longitude/latitude (pyshp, MIT), plain or zipped, one file or a folder of them (the Census
publishes TIGER/Line address ranges per county).

  "kind": "ranges"  TIGER/Line ADDRFEAT: the street name and the house numbers on each side, keyed by TIGER's edge
                    id (TLID), so a renamed street or changed range gets a new row and the old one is kept
  "kind": "areas"   named areas (Census places, county subdivisions, ZIP code tabulation areas, school districts)
  "kind": "lines"   named lines (trails)
  "kind": "points"  named points (trailheads)
"fields": {"name": ..., "key": ..., and for ranges "lfrom", "lto", "rfrom", "rto", "zip"} (a name or a list of possible
names, the first the file has); "cls": the class; "name_format":
an optional pattern such as "the {} area" for ZIP areas, or "name_template" with field names ("{NAME} {CNTY_TYPE}").
Areas and points may have dates: fields "first" and "last" (dates or text), and "open_from": a month (YYYYMM) from
which a last date means "still current" (the Newberry atlas of historical county boundaries ends in 2000, so its
latest versions are today's counties). "encoding": the text encoding of the .dbf (default UTF-8; a byte that does not
decode is replaced). The fine type: "type_field" through "type_map" (placepacks.types.of), else the entry's
"type", else its "tag". "class_field" with "class_map": each record's class from a field (TIGER's MTFCC
codes; tabular.class_of: an unmapped code or a code mapped to "" is left out). "name_replace" and "name_words":
types.rename (TIGER's abbreviations written out: "Marlboro Colg" -> "Marlboro College"). "skip_names": a regular expression of names left out (the atlas's non-county areas). "projection": the
shapes are in a projection (fmt.PROJECTIONS: Statistics Canada's Lambert for its boundary files) and are converted. Only
shapes touching the region's bounding box are read.
"""

import glob
import os
import re

from placepacks import fmt, types
from placepacks.readers import reader
from placepacks.readers.tabular import class_of, smart_case


def _dates(entry, rec):
    """(first, last) months of a record from the entry's "first" and "last" fields (None when it has none)."""
    fields = entry["fields"]
    first = fmt.parse_month(str(_field(rec, fields["first"]))) if fields.get("first") else None
    last = fmt.parse_month(str(_field(rec, fields["last"]))) if fields.get("last") else None
    if last is not None and entry.get("open_from") and last >= int(entry["open_from"]):
        last = None
    return first, last


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


class _Projected:
    """A shape whose points are converted from a projection (fmt.PROJECTIONS) to longitude and latitude."""

    def __init__(self, shape, name):
        self.points = [fmt.to_lonlat(name, x, y) for x, y in shape.points]
        self.parts = list(shape.parts)
        xs, ys = [p[0] for p in self.points], [p[1] for p in self.points]
        self.bbox = (min(xs), min(ys), max(xs), max(ys))


def _parts(shape):
    """The parts of a shape as lists of (lat, lon)."""
    starts = list(shape.parts) + [len(shape.points)]
    return [[(y, x) for x, y in shape.points[a:b]] for a, b in zip(starts, starts[1:])]


@reader("shapes")
def read(path, entry, region, writer):
    """Add the source's ranges, areas, lines or points to writer. Returns the number of records."""
    import shapefile
    fields, source, kind, count = entry["fields"], entry["id"], entry["kind"], 0
    skip = re.compile(entry["skip_names"], re.I) if entry.get("skip_names") else None
    west, south, east, north = region["bbox"]
    for file in files_of(path):
        with shapefile.Reader(file, encoding=entry.get("encoding", "utf-8"), encodingErrors="replace") as shp:
            names = [f[0] for f in shp.fields[1:]]
            for sr in shp.iterShapeRecords():
                shape, rec = sr.shape, dict(zip(names, sr.record))
                if not shape.points:
                    continue
                if entry.get("projection"):
                    shape = _Projected(shape, entry["projection"])
                x1, y1, x2, y2 = shape.bbox if len(shape.points) > 1 else (*shape.points[0], *shape.points[0])
                if x2 < west or x1 > east or y2 < south or y1 > north:
                    continue
                if entry.get("name_template"):
                    name = entry["name_template"].format(**{k: smart_case(str(v or "")) for k, v in rec.items()})
                else:
                    name = smart_case(str(_field(rec, fields["name"])))
                name = types.rename(entry, name)
                if not name.strip() or (skip and skip.search(name)):
                    continue
                cls, tag = entry.get("cls", ""), entry.get("tag", source)
                if entry.get("class_field"):
                    cls, mapped = class_of(entry, str(_field(rec, entry["class_field"])))
                    if not cls:
                        continue
                    tag = mapped or tag
                first, last = _dates(entry, rec)
                phrase = (types.of(entry.get("type_map"), _field(rec, entry["type_field"])) if entry.get("type_field")
                          else "") or entry.get("type") or (tag if tag not in (None, "", source) else None)
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
                    writer.add_area(key or f"{source}:{name}", source, name, cls, tag,
                                    _parts(shape), first, last, type=phrase)
                elif kind == "lines":
                    for i, part in enumerate(_parts(shape)):
                        writer.add_line(f"{key or source + ':' + name}:{i}", source, name, cls, tag, part)
                else:
                    lon, lat = shape.points[0]
                    writer.add_point(key or f"{source}:{name}:{lat:.4f}:{lon:.4f}", source, name, cls, tag, lat, lon, first, last, type=phrase)
                count += 1
    return count
