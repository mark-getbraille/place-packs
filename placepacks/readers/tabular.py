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
  "exclude_pattern": [{"column": ..., "pattern": a regular expression}, ...]: rows whose column matches are left
            out (home-based trades and residences in a business list whose categories are free text)
  "fieldnames": [...]: the column names of a file without a header line (GeoNames)
  "blank_values": [...]: values read as empty ("Not stated" in the NAD's city columns)
Points may also have:
  columns "projection": "lat" and "lon" are y and x in metres of a projection (fmt.PROJECTIONS: Statistics
                   Canada's Lambert)
  columns "point": one column holding the position, as "POINT (lon lat)" or "... (lat, lon)" (Socrata), in place
                   of "lat" and "lon"
  class_map keys ending in "*" match the start of the value ("722*" for every NAICS restaurant code), the longest
            first; a value "business:restaurant" gives the class "business" and the tag "restaurant"
  "name_strip": a regular expression removed from names ("/Inactive" after New York health permit names)
  "skip_names": a regular expression of names left out (licensee names that look like a person's: "Surname, Given")
  "keep_case": true: names are kept as written (postal codes such as "C0A"), not put in ordinary capitals
  "name_replace": [[pattern, replacement], ...] and "name_words" (a word table of types.json): types.rename
               ("South Louisiana, LA, Port of" -> "Port of South Louisiana")
  "skip_points": [[lat, lon], ...]: placeholder positions to leave out (a city's centre used for unknown places)
  "aggregate": true: one record per key and name, from its earliest "first" to its latest "last" (inspections,
               directory years)
  "name_template": a name made of several columns, "{FACILITY_CARRIED_007} bridge over {FEATURES_DESC_006A}" (a
               record with one of them empty is left out); "name_clean": a regular expression removed from each
               of those values first ("HWY " before a road's name in the bridge inventory)
  "type_column" and "type_map": the record's fine type ("pizza restaurant") from a column, through a table of
               types.json ("naics", "gnis", "fsa"), "humanise", or a template ("{} restaurant"); without them the
               record's tag (from class_map or the entry, when it is not the source id) is its type
  "geocode": {"street", "city", "zip": columns, "from": "nad"}: an address-only source, located by the offline
               geocoder against the region's address points (placepacks.geocode; a home is put on its street);
               "ranges_from": an address-range source ("nrn-address-ranges") for the addresses with no point
  "brand_column", "brand_wikidata_column": a chain location's brand and its Wikidata id (data only)
  "kind": "lines" with columns "paths": a column of JSON paths [[[lat, lon], ...], ...] (the arcgis fetch's
               "_paths"): written as named lines (trails, rivers), each path a line of the record
  "kind": "areas" with columns "rings": a column of JSON rings [[[lat, lon], ...], ...] (the arcgis fetch's
               "_rings"): written as named areas (PAD-US, military installations)
  "still_open_months": N: a record whose last date is within N months of the build is still open (its last month
               is the build's); "closed_column": a column that is not empty for records the source says are closed
               (they keep their own last date); "open_when": {"column", "values"}: records whose column has one
               of the values are still open, the others close at their last date (a mine "Active" since its status
               date, or "Abandoned" at it)
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

from placepacks import fmt, types
from placepacks.regions import in_region
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


# Compression methods zipfile names but cannot read (9 = Deflate64).
UNSUPPORTED_ZIP = {9}


class extracted_stream:
    """The bytes of one member of a .zip read through an external extractor ("unzip -p", Info-ZIP 6.0, or "7z e
    -so", p7zip), for compression methods Python's zipfile cannot read (Deflate64). A context manager giving a
    binary stream; the extractor is stopped when the stream is closed early, and a failed extraction raises."""

    TOOLS = (["unzip", "-p", "{zip}", "{member}"], ["7z", "e", "-so", "-bd", "{zip}", "{member}"])

    def __init__(self, path, member):
        import shutil
        self.path, self.member, self.proc = str(path), member, None
        self.command = next(([a.format(zip=self.path, member=member) for a in tool] for tool in self.TOOLS
                             if shutil.which(tool[0])), None)
        if self.command is None:
            raise RuntimeError(f"{os.path.basename(self.path)}: {member} uses a compression method Python cannot "
                               f"read (Deflate64), and neither unzip nor 7z is installed")

    def __enter__(self):
        import subprocess
        self.proc = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.proc.stdout

    def __exit__(self, kind, value, tb):
        if self.proc.poll() is None and kind is not None:
            self.proc.kill()                    # stopped early (an error, or the reader had enough)
        self.proc.stdout.close()
        err = self.proc.stderr.read().decode("utf-8", "replace").strip()
        self.proc.stderr.close()
        code = self.proc.wait()
        if kind is None and code not in (0, -9):
            raise RuntimeError(f"{self.command[0]} could not extract {self.member}: {err[:200]}")
        return False


def open_texts(path, member="*", encoding="utf-8-sig"):
    """Text streams of a file, of the members of a .zip that match member, or of the matching files in a folder."""
    path = str(path)
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.startswith("_"):
                continue                # markers (_empty.txt: the region has none of a national file's rows)
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
            infos = [i for i in z.infolist() if fnmatch.fnmatch(os.path.basename(i.filename), member)]
            for info in infos:
                if info.compress_type in zipfile.compressor_names and info.compress_type not in UNSUPPORTED_ZIP:
                    with z.open(info) as raw:
                        yield io.TextIOWrapper(raw, encoding=encoding, errors="replace", newline="")
                else:
                    # Deflate64 (method 9, the NAD's TXT.zip) and other methods Python cannot read: streamed from
                    # an external extractor's output, so a large file is never written out twice.
                    with extracted_stream(path, info.filename) as raw:
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


_WKT = re.compile(r"POINT\s*\(\s*\(?\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", re.I)
_LATLON = re.compile(r"\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)")
_PLAIN = re.compile(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$")


def parse_point(text):
    """(lat, lon) from "POINT (lon lat)", from text ending in "(lat, lon)" (Socrata's location columns) or from a
    plain "lat, lon" (Opendatasoft's geo_point_2d); None when there is no position."""
    text = text or ""
    m = _WKT.search(text)
    if m:
        return float(m.group(2)), float(m.group(1))
    m = _LATLON.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _PLAIN.match(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def position(row, cols):
    """(lat, lon) of a row (the "point" column, or "lat" and "lon"); None when it has none. With columns
    "projection" (a name in fmt.PROJECTIONS), "lat" and "lon" hold the projected y and x in metres."""
    if cols.get("point"):
        return parse_point(_get(row, cols["point"]))
    try:
        lat, lon = float(_get(row, cols["lat"])), float(_get(row, cols["lon"]))
    except ValueError:
        return None
    if cols.get("projection"):
        lon, lat = fmt.to_lonlat(cols["projection"], lon, lat)
    return lat, lon


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


def geocoded_rows(path, entry, region):
    """The rows of an address-only source located by the offline geocoder (placepacks.geocode) against the
    region's NAD slice: entry "geocode" = {"street", "city", "zip": columns, "from": the address source (nad)}.
    Each located row gets "_lat", "_lon" and "_how" ("address" or "street" for a home); the match rate is printed."""
    from placepacks import catalogue, geocode
    spec = entry["geocode"]
    flt, values = entry.get("filter"), region_values(region)
    rows = []
    for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
        for row in dict_rows(text, entry):
            if flt and _get(row, flt["column"]).upper() != flt["equals"].format(**values).upper():
                continue
            if excluded(row, entry):
                continue
            rows.append(row)
    source = spec.get("from", "nad")
    nad_path = (region.get("_inputs") or {}).get(source)
    nad_entry = next((e for e in catalogue.load()["accepted"] if e["id"] == source), None)
    requests = [(_get(r, spec["street"]), _get(r, spec.get("city", "")), _get(r, spec.get("zip", ""))) for r in rows]
    found = geocode.locate(requests, nad_path, nad_entry) if nad_entry else {}
    if spec.get("ranges_from"):
        # Addresses without a point: along the street's address range (NRCan's road network in Canada).
        ranges_entry = next((e for e in catalogue.load()["accepted"] if e["id"] == spec["ranges_from"]), None)
        ranges_path = (region.get("_inputs") or {}).get(spec["ranges_from"])
        if ranges_entry and ranges_path:
            found.update(geocode.locate_ranges(requests, ranges_path, ranges_entry, skip=set(found)))
    print(f"  {entry['id']}: {geocode.stats(found, len(rows))}" + ("" if nad_path else " (no address points for "
                                                                    "this region)"), flush=True)
    for i, (lat, lon, how) in sorted(found.items()):
        row = rows[i]
        row["_lat"], row["_lon"], row["_how"] = lat, lon, how
        yield row


def excluded(row, entry):
    """True when the row is left out by the entry's "exclude" or "exclude_pattern"."""
    exclude = entry.get("exclude")
    if exclude and _get(row, exclude["column"]).upper() in {v.upper() for v in exclude["values"]}:
        return True
    for rule in entry.get("exclude_pattern", []):
        if re.search(rule["pattern"], _get(row, rule["column"]), re.I):
            return True
    return False


def rows_of(path, entry, region):
    """The dict rows of a source in the region (filter, exclude, bounding box), with "_lat" and "_lon" added."""
    if entry.get("geocode"):
        yield from geocoded_rows(path, entry, region)
        return
    cols, values = entry["columns"], region_values(region)
    flt = entry.get("filter")
    skip = {(round(a, 4), round(b, 4)) for a, b in entry.get("skip_points", [])}
    for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
        for row in dict_rows(text, entry):
            if flt and _get(row, flt["column"]).upper() != flt["equals"].format(**values).upper():
                continue
            if excluded(row, entry):
                continue
            at = position(row, cols)
            if at is None or (round(at[0], 4), round(at[1], 4)) in skip:
                continue
            lat, lon = at
            inside = in_region(region, lat, lon, 0.05)
            if not inside and entry.get("kind") in ("lines", "areas"):
                # A long line or a big area whose middle is outside the region may still cross it (an Amtrak route).
                shape = _get(row, cols.get("paths") or cols.get("rings") or "")
                try:
                    parts = json.loads(shape) if shape else []
                except ValueError:
                    parts = []
                inside = any(in_region(region, p[0], p[1], 0.05) for part in parts for p in part)
            if not inside or (lat == lon == 0):
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
    when = entry.get("open_when")
    if when:
        # Records whose status column has one of these values are still open; the others close at their date.
        return None if _get(row, when["column"]).upper() in {v.upper() for v in when["values"]} else last
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
        name = types.rename(entry, name.strip() if entry.get("keep_case") else smart_case(name))
        if not name:
            continue
        cls, tag = entry.get("cls", ""), entry.get("tag", source)
        if cols.get("class_column"):
            cls, mapped_tag = class_of(entry, _get(row, cols["class_column"]))
            if not cls:
                continue
            tag = mapped_tag or tag
        kind = None
        if entry.get("type_column"):
            kind = types.of(entry.get("type_map"), _get(row, entry["type_column"])) or None
        if not kind:
            kind = (tag if tag and tag != source else None) or entry.get("type")
        key = _get(row, cols.get("key", ""))
        key = f"{source}:{key}" if key else None
        if key is None:
            from placepacks.writer import location_key
            key = location_key(source, cls, lat, lon)
        first = fmt.parse_month(_get(row, cols["first"])) if cols.get("first") else None
        last = fmt.parse_month(_get(row, cols["last"])) if cols.get("last") else None
        last = _open_until(entry, row, last, month) if cols.get("last") else None
        if entry["kind"] == "lines":
            try:
                paths = [[(float(a), float(b)) for a, b in path] for path in json.loads(_get(row, cols["paths"]))]
            except (ValueError, TypeError):
                continue
            for i, path in enumerate(paths):
                writer.add_line(f"{key}:{i}", source, name, cls, tag, path, first, last)
            count += 1
            continue
        if entry["kind"] == "areas":
            try:
                rings = [[(float(a), float(b)) for a, b in ring] for ring in json.loads(_get(row, cols["rings"]))]
            except (ValueError, TypeError):
                continue
            writer.add_area(key, source, name, cls, tag, rings, first, last, type=kind)
            count += 1
            continue
        if grouped is not None:
            # The same name in other capitals ("BOUDREAUX'S" and "Boudreaux's") is the same record.
            g = grouped.get((key, name.casefold()))
            if g is None:
                grouped[(key, name.casefold())] = [cls, tag, lat, lon, first, last,
                                                   last is None and bool(cols.get("last")), name, kind]
            else:
                g[8] = types.most_specific([g[8], kind]) or None
                g[4] = min(x for x in (g[4], first) if x) if (g[4] or first) else None
                still_open = g[6] or (last is None and bool(cols.get("last")))
                g[5] = None if still_open else max(x for x in (g[5], last) if x) if (g[5] or last) else None
                g[6] = still_open
            continue
        brand = None
        if entry.get("brand_column") and _get(row, entry["brand_column"]):
            brand = (_get(row, entry["brand_column"]), _get(row, entry.get("brand_wikidata_column", "")))
        writer.add_point(key, source, name, cls, tag, lat, lon, first, last, type=kind, brand=brand)
        count += 1
    for (key, _), (cls, tag, lat, lon, first, last, _, name, kind) in (grouped or {}).items():
        brand = None
        if entry.get("brand_column") and _get(row, entry["brand_column"]):
            brand = (_get(row, entry["brand_column"]), _get(row, entry.get("brand_wikidata_column", "")))
        writer.add_point(key, source, name, cls, tag, lat, lon, first, last, type=kind, brand=brand)
        count += 1
    return count
