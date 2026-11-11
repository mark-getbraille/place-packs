"""Split the national files (fetch.py --prepare) into one slice per region, in one pass each, so a region's build
downloads only its own part (the NAD is several GB for the whole country).

    python -m placepacks.split national/ --out national-split/

  - tabular sources with a "filter" (NAD by State, NCES by STATE, the Canadian names by province): each row goes to
    the region its filter value names, as national-split/<region id>/<source id>/<source id>.csv (with the header);
  - shapefile sources (ZIP code areas): each shape goes to the US states whose box it touches, as a zipped
    shapefile national-split/<region id>/<source id>/<source id>.zip;
  - the Foursquare slice of every covered country (prepared once) goes to each region by its box, as Parquet;
  - tabular sources with "split_box" (GeoNames, the FSA's hygiene ratings): each row goes to every region of the
    source's countries whose box holds it (optionally only the regions of the row's own country column);
  - other sources without a filter (France's BAN) are not split: the region builds read the whole file, filtered by
    the extract's box.
Only the columns the reader uses are written (needed_columns), so a slice of the NAD (60 columns) stays small.
"""

import argparse
import csv
import os
import sys
import zipfile


csv.field_size_limit(2**31 - 1)   # polygon rings in one field can be many megabytes (sys.maxsize overflows on Windows)
from placepacks import catalogue
from placepacks.regions import boxes_of, touches_region
from placepacks.readers.tabular import _get, dict_rows, open_texts, parse_point, region_values


def needed_columns(entry):
    """The column names a tabular entry reads (its columns, filter, exclude and split settings), or None when it
    names none (then every column is kept)."""
    names = set()

    def add(spec):
        if isinstance(spec, dict):
            for c in spec.get("first_of", []):
                names.add(c)
        elif isinstance(spec, list):
            names.update(spec)
        elif isinstance(spec, str) and spec:
            names.add(spec)
    for spec in entry.get("columns", {}).values():
        add(spec)
    if entry.get("type_column"):
        add(entry["type_column"])
    for part in ("filter", "exclude"):
        if entry.get(part):
            add(entry[part]["column"])
    for rule in entry.get("exclude_pattern", []):
        add(rule["column"])
    if entry.get("open_when"):
        add(entry["open_when"]["column"])
    for part in ("brand_column", "brand_wikidata_column"):
        add(entry.get(part, ""))
    if entry.get("name_template"):
        import re
        names.update(re.findall(r"{([^}]+)}", entry["name_template"]))
    for spec in (entry.get("split_box") or {}).values():
        add(spec)
    return names or None


def _targets(entry, row, by_value, boxes):
    """The region ids a row goes to: by the filter's value, or by the regions' boxes (split_box)."""
    if by_value is not None:
        rid = by_value.get(_get(row, entry["filter"]["column"]).upper())
        return [rid] if rid else []
    spec = entry["split_box"]
    at = parse_point(_get(row, spec["point"])) if spec.get("point") else None
    if at is None:
        try:
            at = float(_get(row, spec["lat"])), float(_get(row, spec["lon"]))
        except (KeyError, ValueError):
            return []
        if spec.get("projection"):
            from placepacks import fmt
            lon, lat = fmt.to_lonlat(spec["projection"], at[1], at[0])
            at = lat, lon
    lat, lon = at
    cc = _get(row, spec["country"]).upper() if spec.get("country") else None
    return [rid for rid, (rcc, rboxes) in boxes.items() if (cc is None or cc == rcc) and
            any(s - 0.05 <= lat <= n + 0.05 and w - 0.05 <= lon <= e + 0.05 for w, s, e, n in rboxes)]


def split_tabular(entry, path, out, regions):
    """Route each row of a filtered (or split_box) tabular source to its regions' CSVs. Returns {region id: rows}."""
    mine = {rid: r for rid, r in regions.items() if catalogue.country_code(r) in entry["countries"] and
            (not entry.get("regions") or rid in entry["regions"])}
    by_value, boxes = None, {}
    if entry.get("filter"):
        by_value = {entry["filter"]["equals"].format(**region_values(r)).upper(): rid for rid, r in mine.items()}
    else:
        boxes = {rid: (catalogue.country_code(r), boxes_of(r)) for rid, r in mine.items()}
    keep = needed_columns(entry)
    headless = bool(entry.get("fieldnames"))
    writers, files, counts = {}, [], {}
    try:
        for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
            fieldnames = None
            for row in dict_rows(text, entry):
                if fieldnames is None:
                    # The columns the reader uses (the same for every file of the source, even when the files
                    # differ: StatCan's facility databases), else every column of the file.
                    fieldnames = sorted(keep) if keep and not headless else [c for c in row if c is not None]
                for rid in _targets(entry, row, by_value, boxes):
                    if rid not in writers:
                        folder = os.path.join(out, rid, entry["id"])
                        os.makedirs(folder, exist_ok=True)
                        ext = os.path.splitext(entry.get("member", "*.csv"))[1] or ".csv"   # what the reader reads
                        name = entry.get("split_file") or entry["id"] + ext       # a name its "member" matches
                        f = open(os.path.join(folder, name), "w", newline="", encoding="utf-8")
                        files.append(f)
                        writers[rid] = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore",
                                                      delimiter=entry.get("delimiter", ","),
                                                      quoting=csv.QUOTE_NONE if entry.get("no_quotes") else
                                                      csv.QUOTE_MINIMAL, escapechar="\\" if entry.get("no_quotes")
                                                      else None)
                        if not headless:
                            writers[rid].writeheader()
                    writers[rid].writerow({k: row.get(k) for k in fieldnames})
                    counts[rid] = counts.get(rid, 0) + 1
    finally:
        for f in files:
            f.close()
    return counts


def split_shapes(entry, path, out, regions):
    """Copy each shape to the regions whose box it touches (US only). Returns {region id: shapes}."""
    import shapefile
    targets = {rid: r for rid, r in regions.items() if catalogue.country_code(r) in entry["countries"]}
    writers, counts = {}, {}
    # The entry's text encoding (the Newberry atlas is Latin-1); a byte that does not decode is replaced, never fatal.
    with shapefile.Reader(path, encoding=entry.get("encoding", "utf-8"), encodingErrors="replace") as shp:
        fields = shp.fields[1:]
        for sr in shp.iterShapeRecords():
            pts = sr.shape.points
            if not pts:
                continue
            # Point shapes have no bbox in pyshp: take it from the points themselves.
            bbox = getattr(sr.shape, "bbox", None)
            if bbox is None:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                bbox = (min(xs), min(ys), max(xs), max(ys))
            x1, y1, x2, y2 = bbox
            for rid, r in targets.items():
                if not touches_region(r, (x1, y1, x2, y2)):
                    continue
                if rid not in writers:
                    folder = os.path.join(out, rid, entry["id"])
                    os.makedirs(folder, exist_ok=True)
                    wr = shapefile.Writer(os.path.join(folder, entry["id"]), shapeType=shp.shapeType)
                    for fld in fields:
                        wr.field(*fld)
                    writers[rid] = wr
                writers[rid].shape(sr.shape)
                writers[rid].record(*sr.record)
                counts[rid] = counts.get(rid, 0) + 1
    for rid, wr in writers.items():
        wr.close()
        base = os.path.join(out, rid, entry["id"], entry["id"])
        with zipfile.ZipFile(base + ".zip", "w", zipfile.ZIP_DEFLATED) as z:
            for ext in (".shp", ".shx", ".dbf", ".prj"):
                if os.path.exists(base + ext):
                    z.write(base + ext, entry["id"] + ext)
                    os.remove(base + ext)
    return counts


def split_parquet(entry, path, out, regions):
    """Cut a prepared national Parquet slice (fetch.prepare_parquet) into one file per region of its countries, by
    the region's box: national-split/<region id>/<source id>/<source id>.parquet. Returns {region id: rows}."""
    from placepacks.readers.parquet import connect
    con = connect()
    counts = {}
    for rid, r in regions.items():
        if catalogue.country_code(r) not in entry["countries"]:
            continue
        folder = os.path.join(out, rid, entry["id"])
        os.makedirs(folder, exist_ok=True)
        target = os.path.join(folder, entry["id"] + ".parquet")
        where = " OR ".join(f"(longitude BETWEEN {w} AND {e} AND latitude BETWEEN {s_} AND {n})"
                            for w, s_, e, n in boxes_of(r))
        con.execute(f"COPY (SELECT * FROM read_parquet('{path}') WHERE {where}) TO '{target}' (FORMAT PARQUET)")
        counts[rid] = con.execute(f"SELECT COUNT(*) FROM read_parquet('{target}')").fetchone()[0]
    con.close()
    return counts


EMPTY = "_empty.txt"


def mark_empty(entry, out, regions, counts):
    """For every region the source covers that got no rows, an empty slice folder holding EMPTY (the national number
    of rows), so the region's build says "ok (0 in this region)" rather than "not downloaded"."""
    total = sum(counts.values())
    if not total:
        return
    for rid, r in regions.items():
        if catalogue.country_code(r) not in entry["countries"] or (entry.get("regions") and rid not in
                                                                    entry["regions"]) or counts.get(rid):
            continue
        folder = os.path.join(out, rid, entry["id"])
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, EMPTY), "w", encoding="utf-8") as f:
            f.write(f"{total}\n")


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("national")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    cat, regions = catalogue.load(), catalogue.regions()
    # Slices are made for the regions as they were before sub-regions: a sub-region reads its parent's slice (the
    # workflow's "slice") and keeps what is in it.
    regions = {rid: r for rid, r in regions.items() if not r.get("parent")}
    for entry in cat["accepted"]:
        if entry["fetch"]["method"] not in ("national", "duckdb_national"):
            continue
        folder = os.path.join(a.national, entry["id"])
        if not os.path.isdir(folder):
            continue
        if entry["reader"] == "tabular" and (entry.get("filter") or entry.get("split_box")):
            # The whole folder in one pass (GeoNames has one file per country; each region gets one slice).
            try:
                counts = split_tabular(entry, folder, a.out, regions)
            except Exception as exc:  # noqa: BLE001 - reported, the build goes on without this source
                print(f"{entry['id']}: failed (not split: {type(exc).__name__}: {exc})")
                continue
            print(f"{entry['id']}: {sum(counts.values()):,} records in {len(counts)} regions")
            mark_empty(entry, a.out, regions, counts)
            continue
        for name in os.listdir(folder):
            if name.endswith(".version") or name.startswith("_"):
                continue
            path = os.path.join(folder, name)
            # One source that cannot be split is reported and left out; the others are still split.
            try:
                if entry["fetch"]["method"] == "duckdb_national" and name.endswith(".parquet"):
                    counts = split_parquet(entry, path, a.out, regions)
                elif entry["reader"] == "shapes":
                    counts = split_shapes(entry, path, a.out, regions)
                else:
                    continue
            except Exception as exc:  # noqa: BLE001 - reported, the build goes on without this source
                print(f"{entry['id']}: failed (not split: {type(exc).__name__}: {exc})")
                continue
            print(f"{entry['id']}: {sum(counts.values()):,} records in {len(counts)} regions")
            mark_empty(entry, a.out, regions, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
