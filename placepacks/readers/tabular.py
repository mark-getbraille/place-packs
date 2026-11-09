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
  "fieldnames": [...]: the column names of a file without a header line (GeoNames)
  "blank_values": [...]: values read as empty ("Not stated" in the NAD's city columns)
Points may also have:
  columns "point": one column holding the position, as "POINT (lon lat)" or "... (lat, lon)" (Socrata), in place
                   of "lat" and "lon"
  class_map keys ending in "*" match the start of the value ("722*" for every NAICS restaurant code), the longest
            first; a value "business:restaurant" gives the class "business" and the tag "restaurant"
  "name_strip": a regular expression removed from names ("/Inactive" after New York health permit names)
  "skip_names": a regular expression of names left out (licensee names that look like a person's: "Surname, Given")
  "skip_points": [[lat, lon], ...]: placeholder positions to leave out (a city's centre used for unknown places)
  "aggregate": true: one record per key and name, from its earliest "first" to its latest "last" (inspections,
               directory years)
  "name_template": a name made of several columns, "{FACILITY_CARRIED_007} bridge over {FEATURES_DESC_006A}" (a
               record with one of them empty is left out); "name_clean": a regular expression removed from each
               of those values first ("HWY " before a road's name in the bridge inventory)
  "kind": "areas" with columns "rings": a column of JSON rings [[[lat, lon], ...], ...] (the arcgis fetch's
               "_rings"): written as named areas (PAD-US, military installations)
  "still_open_months": N: a record whose last date is within N months of the build is still open (its last month
               is the build's); "closed_column": a column that is not empty for records the source says are closed
               (they keep their own last date)
Dates after the build month are the build month (writer.PackWriter). Rows without a position, or outside the
region's bounding box, are left out. Text that is all capitals is written in ordinary capitals ("MAIN ST" ->
"Main St")."""

import csv
import fnmatch
import io
import json
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
            "name": region.get("name", ""), "id": region["id"], "cc": region.get("cc", "")}


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


_WKT = re.compile(r"POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", re.I)
_LATLON = re.compile(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")


def parse_point(text):
    """(lat, lon) from "POINT (lon lat)" or from text ending in "(lat, lon)" (Socrata's location columns); None
    when there is no position."""
    text = text or ""
    m = _WKT.search(text)
    if m:
        return float(m.group(2)), float(m.group(1))
    m = _LATLON.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def position(row, cols):
    """(lat, lon) of a row (the "point" column, or "lat" and "lon"); None when it has none."""
    if cols.get("point"):
        return parse_point(_get(row, cols["point"]))
    try:
        return float(_get(row, cols["lat"])), float(_get(row, cols["lon"]))
    except ValueError:
        return None


def dict_rows(text, entry):
    """The rows of one text stream as dicts (with the entry's "fieldnames" when the file has no header line), with
    the entry's "blank_values" emptied."""
    blanks = set(entry.get("blank_values", []))
    for row in csv.DictReader(text, fieldnames=entry.get("fieldnames"), delimiter=entry.get("delimiter", ","),
                              quoting=csv.QUOTE_NONE if entry.get("no_quotes") else csv.QUOTE_MINIMAL):
        if blanks:
            for k, v in row.items():
                if isinstance(v, str) and v.strip() in blanks:
                    row[k] = ""
        yield row


def rows_of(path, entry, region):
    """The dict rows of a source in the region (filter, exclude, bounding box), with "_lat" and "_lon" added."""
    cols, values = entry["columns"], region_values(region)
    flt, exclude = entry.get("filter"), entry.get("exclude")
    skip = {(round(a, 4), round(b, 4)) for a, b in entry.get("skip_points", [])}
    west, south, east, north = region["bbox"]
    for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
        for row in dict_rows(text, entry):
            if flt and _get(row, flt["column"]).upper() != flt["equals"].format(**values).upper():
                continue
            if exclude and _get(row, exclude["column"]).upper() in {v.upper() for v in exclude["values"]}:
                continue
            at = position(row, cols)
            if at is None or (round(at[0], 4), round(at[1], 4)) in skip:
                continue
            lat, lon = at
            if not (south - 0.05 <= lat <= north + 0.05 and west - 0.05 <= lon <= east + 0.05) or (lat == lon == 0):
                continue
            row["_lat"], row["_lon"] = lat, lon
            yield row


def class_of(entry, value):
    """(class, tag) of a class column's value by the entry's class_map: the exact value, else the longest key ending
    in "*" that the value starts with, else "*"; ("", "") when the record is not wanted. A mapped value
    "business:restaurant" is the class "business" with the tag "restaurant"."""
    cmap = entry.get("class_map", {})
    found = cmap.get(value)
    if found is None:
        prefixes = sorted((k for k in cmap if k.endswith("*") and k != "*" and value.startswith(k[:-1])),
                          key=len, reverse=True)
        found = cmap[prefixes[0]] if prefixes else cmap.get("*", "")
    cls, _, tag = (found or "").partition(":")
    return cls, tag


class _Blank(dict):
    """format_map values: a missing column is empty."""

    def __missing__(self, key):
        return ""


def templated(entry, row):
    """The name of a record made by the entry's "name_template" from its columns (each cleaned by "name_clean" and
    its spaces tidied); "" when a column the template uses is empty."""
    clean = re.compile(entry["name_clean"], re.I) if entry.get("name_clean") else None
    used = re.findall(r"{([^}]+)}", entry["name_template"])
    values = _Blank()
    for name in used:
        value = (row.get(name) or "").strip().strip("'\"")
        if clean:
            value = clean.sub("", value)
        value = smart_case(" ".join(value.split()))
        if not value:
            return ""
        values[name] = value
    return entry["name_template"].format_map(values)


def _open_until(entry, row, last, month):
    """The record's last month, or None while it is still open (see "still_open_months" and "closed_column")."""
    if last is None:
        return None
    closed = entry["columns"].get("closed_column")
    if closed and _get(row, closed):
        return last
    keep = entry.get("still_open_months")
    if keep is not None and last >= fmt.add_months(month, -int(keep)):
        return None
    return last


@reader("tabular")
def read(path, entry, region, writer):
    """Add the source's addresses or named points to writer. Returns the number of records."""
    cols, source, count = entry["columns"], entry["id"], 0
    strip = re.compile(entry["name_strip"], re.I) if entry.get("name_strip") else None
    skip_name = re.compile(entry["skip_names"], re.I) if entry.get("skip_names") else None
    month = getattr(writer, "month", None) or fmt.month_of()
    grouped = {} if entry.get("aggregate") else None
    for row in rows_of(path, entry, region):
        lat, lon = row["_lat"], row["_lon"]
        if entry["kind"] == "addresses":
            number, street = _get(row, cols["number"]), smart_case(_get(row, cols["street"]))
            if number and street:
                writer.add_address(source, number, street, smart_case(_get(row, cols.get("city", ""))), lat, lon)
                count += 1
            continue
        if entry.get("name_template"):
            name = templated(entry, row)
        else:
            name = _get(row, cols["name"])
        if strip:
            name = strip.sub("", name)
        if skip_name and skip_name.search(name.strip()):
            continue
        name = smart_case(name)
        if not name:
            continue
        cls, tag = entry.get("cls", ""), entry.get("tag", source)
        if cols.get("class_column"):
            cls, mapped_tag = class_of(entry, _get(row, cols["class_column"]))
            if not cls:
                continue
            tag = mapped_tag or tag
        key = _get(row, cols.get("key", ""))
        key = f"{source}:{key}" if key else None
        if key is None:
            from placepacks.writer import location_key
            key = location_key(source, cls, lat, lon)
        first = fmt.parse_month(_get(row, cols["first"])) if cols.get("first") else None
        last = fmt.parse_month(_get(row, cols["last"])) if cols.get("last") else None
        last = _open_until(entry, row, last, month) if cols.get("last") else None
        if entry["kind"] == "areas":
            try:
                rings = [[(float(a), float(b)) for a, b in ring] for ring in json.loads(_get(row, cols["rings"]))]
            except (ValueError, TypeError):
                continue
            writer.add_area(key, source, name, cls, tag, rings, first, last)
            count += 1
            continue
        if grouped is not None:
            # The same name in other capitals ("BOUDREAUX'S" and "Boudreaux's") is the same record.
            g = grouped.get((key, name.casefold()))
            if g is None:
                grouped[(key, name.casefold())] = [cls, tag, lat, lon, first, last,
                                                   last is None and bool(cols.get("last")), name]
            else:
                g[4] = min(x for x in (g[4], first) if x) if (g[4] or first) else None
                still_open = g[6] or (last is None and bool(cols.get("last")))
                g[5] = None if still_open else max(x for x in (g[5], last) if x) if (g[5] or last) else None
                g[6] = still_open
            continue
        writer.add_point(key, source, name, cls, tag, lat, lon, first, last)
        count += 1
    for (key, _), (cls, tag, lat, lon, first, last, _, name) in (grouped or {}).items():
        writer.add_point(key, source, name, cls, tag, lat, lon, first, last)
        count += 1
    return count
