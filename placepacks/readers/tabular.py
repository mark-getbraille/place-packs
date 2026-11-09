"""Delimited text sources (CSV, pipe-separated), plain or inside a .zip: address points and named points.

The catalogue entry says how to read it:
  "kind": "addresses" or "points"
  "delimiter": "," (default) or "|"
  "member": a pattern of the file inside a .zip ("*.csv", "*Text*.txt"); every matching member is read
  "columns": {"lat": ..., "lon": ...,
              addresses: "number": a column or a list joined with spaces, "street": a list joined with spaces
                         (prefix, name, type, suffix), "city": a list, the first that is not empty,
              points:    "name", "key" (a stable id column), "class_column" with "class_map" {value: class} (or
                         the entry's fixed "cls"), "first" / "last" (date columns, when the source has them)}
  "filter": {"column": ..., "equals": "{code}"}: only rows of the region ("{code}" is its postal code, "{fips}",
            "{pruid}", "{name}"); without a filter, only rows inside the region's bounding box
  "exclude": {"column": ..., "values": [...]}: rows left out (the NAD states whose data may not be public domain)
Rows without a position, or outside the region's bounding box, are left out. Text that is all capitals is written
in ordinary capitals ("MAIN ST" -> "Main St")."""

import csv
import fnmatch
import io
import os
import re
import zipfile

from placepacks import fmt
from placepacks.readers import reader

csv.field_size_limit(10_000_000)


def smart_case(text):
    """"MAIN ST" -> "Main St", "MCDONALD'S" -> "McDonald's"; text with lower-case letters stays as it is."""
    text = " ".join((text or "").split())
    if not text or text != text.upper():
        return text
    words = []
    for w in text.lower().split(" "):
        w = w[:1].upper() + w[1:]
        if w.startswith("Mc") and len(w) > 2:
            w = "Mc" + w[2:3].upper() + w[3:]
        if w.lower() in ("n", "s", "e", "w", "ne", "nw", "se", "sw"):
            w = w.upper()                   # compass directions: "N Main St"
        elif re.fullmatch(r"\d+(st|nd|rd|th)", w, re.I):
            w = w.lower()                   # ordinals: "120th"
        words.append(w)
    return " ".join(words)


def region_values(region):
    """The placeholders of filters."""
    return {"code": region.get("code", ""), "fips": region.get("fips", ""), "pruid": region.get("pruid", ""),
            "name": region.get("name", ""), "id": region["id"]}


def open_texts(path, member="*", encoding="utf-8-sig"):
    """Text streams of a file, of the members of a .zip that match member, or of the matching files in a folder."""
    path = str(path)
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            plain = name[:-3] if name.endswith(".gz") else name
            if fnmatch.fnmatch(plain, member) or name.endswith(".zip"):
                yield from open_texts(os.path.join(path, name), member, encoding)
        return
    if path.lower().endswith(".gz"):
        import gzip
        with gzip.open(path, "rt", encoding=encoding, errors="replace", newline="") as f:
            yield f
        return
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if fnmatch.fnmatch(os.path.basename(name), member):
                    with z.open(name) as raw:
                        yield io.TextIOWrapper(raw, encoding=encoding, errors="replace", newline="")
        return
    with open(path, encoding=encoding, errors="replace", newline="") as f:
        yield f


def _get(row, spec):
    """A column's value, or the space-joined values of a list of columns, or the first non-empty of a list given as
    {"first_of": [...]}."""
    if isinstance(spec, dict):
        return next((row.get(c, "").strip() for c in spec.get("first_of", []) if row.get(c, "").strip()), "")
    if isinstance(spec, list):
        return " ".join(row.get(c, "").strip() for c in spec if row.get(c, "").strip())
    return (row.get(spec, "") or "").strip() if spec else ""


def rows_of(path, entry, region):
    """The dict rows of a source in the region (filter, exclude, bounding box), with "_lat" and "_lon" added."""
    cols, values = entry["columns"], region_values(region)
    flt, exclude = entry.get("filter"), entry.get("exclude")
    west, south, east, north = region["bbox"]
    for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
        for row in csv.DictReader(text, delimiter=entry.get("delimiter", ",")):
            if flt and _get(row, flt["column"]).upper() != flt["equals"].format(**values).upper():
                continue
            if exclude and _get(row, exclude["column"]).upper() in {v.upper() for v in exclude["values"]}:
                continue
            try:
                lat, lon = float(_get(row, cols["lat"])), float(_get(row, cols["lon"]))
            except ValueError:
                continue
            if not (south - 0.05 <= lat <= north + 0.05 and west - 0.05 <= lon <= east + 0.05) or (lat == lon == 0):
                continue
            row["_lat"], row["_lon"] = lat, lon
            yield row


@reader("tabular")
def read(path, entry, region, writer):
    """Add the source's addresses or named points to writer. Returns the number of records."""
    cols, source, count = entry["columns"], entry["id"], 0
    for row in rows_of(path, entry, region):
        lat, lon = row["_lat"], row["_lon"]
        if entry["kind"] == "addresses":
            number, street = _get(row, cols["number"]), smart_case(_get(row, cols["street"]))
            if number and street:
                writer.add_address(source, number, street, smart_case(_get(row, cols.get("city", ""))), lat, lon)
                count += 1
            continue
        name = smart_case(_get(row, cols["name"]))
        if not name:
            continue
        cls = entry.get("cls", "")
        if cols.get("class_column"):
            value = _get(row, cols["class_column"])
            cls = entry.get("class_map", {}).get(value, entry.get("class_map", {}).get("*", ""))
            if not cls:
                continue
        key = _get(row, cols.get("key", ""))
        key = f"{source}:{key}" if key else None
        if key is None:
            from placepacks.writer import location_key
            key = location_key(source, cls, lat, lon)
        first = fmt.parse_month(_get(row, cols["first"])) if cols.get("first") else None
        last = fmt.parse_month(_get(row, cols["last"])) if cols.get("last") else None
        writer.add_point(key, source, name, cls, entry.get("tag", source), lat, lon, first, last)
        count += 1
    return count
