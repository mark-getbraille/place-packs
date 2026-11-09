"""Split the national files (fetch.py --prepare) into one slice per region, in one pass each, so a region's build
downloads only its own part (the NAD is several GB for the whole country).

    python -m placepacks.split national/ --out national-split/

  - tabular sources with a "filter" (NAD by State, NCES by STATE, the Canadian names by province): each row goes to
    the region its filter value names, as national-split/<region id>/<source id>/<source id>.csv (with the header);
  - shapefile sources (ZIP code areas): each shape goes to the US states whose box it touches, as a zipped
    shapefile national-split/<region id>/<source id>/<source id>.zip;
  - sources without a filter (France's BAN) are not split: the region builds read the whole file, filtered by the
    extract's box.
"""

import argparse
import csv
import os
import sys
import zipfile

from placepacks import catalogue
from placepacks.readers.tabular import _get, open_texts, region_values


def split_tabular(entry, path, out, regions):
    """Route each row of a filtered tabular source to its region's CSV. Returns {region id: rows}."""
    flt = entry["filter"]
    by_value = {}
    for rid, r in regions.items():
        if catalogue.country_code(r) in entry["countries"]:
            by_value[flt["equals"].format(**region_values(r)).upper()] = rid
    writers, files, counts = {}, [], {}
    try:
        for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
            reader = csv.DictReader(text, delimiter=entry.get("delimiter", ","))
            for row in reader:
                rid = by_value.get(_get(row, flt["column"]).upper())
                if rid is None:
                    continue
                if rid not in writers:
                    folder = os.path.join(out, rid, entry["id"])
                    os.makedirs(folder, exist_ok=True)
                    ext = os.path.splitext(entry.get("member", "*.csv"))[1] or ".csv"   # what the reader looks for
                    f = open(os.path.join(folder, entry["id"] + ext), "w", newline="", encoding="utf-8")
                    files.append(f)
                    writers[rid] = csv.DictWriter(f, fieldnames=reader.fieldnames,
                                                  delimiter=entry.get("delimiter", ","))
                    writers[rid].writeheader()
                writers[rid].writerow(row)
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
    with shapefile.Reader(path) as shp:
        fields = shp.fields[1:]
        for sr in shp.iterShapeRecords():
            x1, y1, x2, y2 = sr.shape.bbox
            for rid, r in targets.items():
                w, s, e, n = r["bbox"]
                if x2 < w or x1 > e or y2 < s or y1 > n:
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


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("national")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    cat, regions = catalogue.load(), catalogue.regions()
    for entry in cat["accepted"]:
        if entry["fetch"]["method"] != "national":
            continue
        folder = os.path.join(a.national, entry["id"])
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.endswith(".version"):
                continue
            path = os.path.join(folder, name)
            if entry["reader"] == "tabular" and entry.get("filter"):
                counts = split_tabular(entry, path, a.out, regions)
            elif entry["reader"] == "shapes":
                counts = split_shapes(entry, path, a.out, regions)
            else:
                continue
            print(f"{entry['id']}: {sum(counts.values()):,} records in {len(counts)} regions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
