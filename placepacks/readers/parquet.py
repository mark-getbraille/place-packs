"""Sources read with DuckDB (MIT): GeoParquet (Overture Maps places, Foursquare Open Source Places), and with its
spatial extension the files in other projections (PAD-US, the National Register of Historic Places).

The catalogue entry's "query" is one SQL SELECT with the placeholders {src} (the input: a local file or folder, or
for fetch.py the source's remote address) and {west} {south} {east} {north} (the region's bounding box); it returns
the columns key, name, cls, lat, lon and, when the source has them, first and last (dates as text), or for areas
key, name, cls and geojson (the shape in longitude/latitude). Only rows with a name are kept. fetch.py runs the same
query on the remote files (range reads by bounding box), so only the region's slice is ever downloaded.
"""

import json
import os

from placepacks import fmt
from placepacks.readers import reader

SLICE = ".slice.parquet"            # the ending of a region's slice written by fetch_slice


def connect(spatial=False):
    """A DuckDB connection (with httpfs for s3:// and https:// inputs, and spatial when asked)."""
    import duckdb
    con = duckdb.connect()
    if spatial:
        con.execute("INSTALL spatial; LOAD spatial;")
    return con


def sql(entry, src, region):
    """The entry's query for an input and a region."""
    west, south, east, north = region["bbox"]
    if os.path.isdir(str(src)):
        src = os.path.join(str(src), "*.parquet")
    return entry["query"].format(src=str(src).replace("'", "''"), west=west, south=south, east=east, north=north)


def classify_category(entry, category):
    """The class of a source's category (the entry's "class_map": the first key the category starts with; "*" for
    everything else; a missing class leaves the record out)."""
    category = (category or "").lower()
    cmap = entry.get("class_map", {})
    for prefix, cls in cmap.items():
        if prefix != "*" and category.startswith(prefix):
            return cls
    return cmap.get("*", "business")


@reader("duckdb")
def read(path, entry, region, writer):
    """Add the query's points or areas to writer. Returns the number of records."""
    con = connect(entry.get("spatial", False))
    count, source = 0, entry["id"]
    # A slice written by fetch_slice already has the query's columns.
    query = f"SELECT * FROM read_parquet('{path}')" if str(path).endswith(SLICE) else sql(entry, path, region)
    cursor = con.execute(query)
    names = [d[0] for d in cursor.description]
    for values in cursor.fetchall():
        row = dict(zip(names, values))
        name = (row.get("name") or "").strip()
        if not name:
            continue
        cls = classify_category(entry, row.get("cls")) if entry.get("class_map") else (row.get("cls") or entry["cls"])
        if not cls:
            continue
        key = f"{source}:{row['key']}"
        first, last = fmt.parse_month(str(row.get("first") or "")), fmt.parse_month(str(row.get("last") or ""))
        if "geojson" in row:
            geo = json.loads(row["geojson"])
            polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
            rings = [[(y, x) for x, y in ring] for poly in polys for ring in poly]
            writer.add_area(key, source, name, cls, entry.get("tag", source), rings, first, last)
        else:
            writer.add_point(key, source, name, cls, entry.get("tag", source), float(row["lat"]), float(row["lon"]),
                             first, last)
        count += 1
    con.close()
    return count


def fetch_slice(entry, region, target):
    """Write the region's slice of a remote Parquet source to target (a local "<name>.slice.parquet" file) with
    range reads: the query's columns only."""
    con = connect(entry.get("spatial", False))
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if entry.get("s3_region"):
        con.execute(f"SET s3_region = '{entry['s3_region']}'")
    con.execute(f"COPY ({sql(entry, entry['remote'], region)}) TO '{target}' (FORMAT PARQUET)")
    con.close()
