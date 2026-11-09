"""Sources read with DuckDB (MIT): GeoParquet (Overture Maps places, Foursquare Open Source Places), and with its
spatial extension the files in other projections (PAD-US, the National Register of Historic Places).

The catalogue entry's "query" is one SQL SELECT with the placeholders {src} (the input: a local file or folder, or
for fetch.py the source's remote address) and {west} {south} {east} {north} (the region's bounding box); it returns
the columns key, name, cls, lat, lon and, when the source has them, first and last (dates as text), or for areas
key, name, cls and geojson (the shape in longitude/latitude). Only rows with a name are kept. fetch.py runs the same
query on the remote files (range reads by bounding box), so only the region's slice is ever downloaded.

A publisher may rename columns between releases (Overture replaced "categories" by "taxonomy" and
"basic_category" in 2026). The entry's "pick" lists candidates for further placeholders, for example
{"cls": ["taxonomy.primary", "basic_category", "categories.primary"], "status": ["operating_status"]}: the input's
columns are read first (DESCRIBE), and each placeholder becomes the first candidate the input has, or NULL.
"""

import json
import os

from placepacks import fmt, types
from placepacks.readers import reader

SLICE = ".slice.parquet"            # the ending of a region's slice written by fetch_slice


def connect(spatial=False):
    """A DuckDB connection (with httpfs for s3:// and https:// inputs, and spatial when asked)."""
    import duckdb
    con = duckdb.connect()
    if spatial:
        con.execute("INSTALL spatial; LOAD spatial;")
    return con


def has_column(columns, path):
    """True when DESCRIBE's columns ({name: type text}) have path: "basic_category", or a struct field
    "taxonomy.primary"."""
    top, _, field = path.partition(".")
    if top not in columns:
        return False
    field = field.split(".")[0]                 # brand.names.primary: the struct has "names"
    return not field or f'{field} ' in columns[top].replace('"', "") or f"{field}," in columns[top]


def picked(entry, con, src, read):
    """{placeholder: SQL expression} of the entry's "pick" for this input (see the module docstring)."""
    if not entry.get("pick"):
        return {}
    cur = con.execute(f"DESCRIBE SELECT * FROM {read} LIMIT 0")
    columns = {r[0]: str(r[1]) for r in cur.fetchall()}
    return {name: next((c for c in candidates if has_column(columns, c)), "NULL")
            for name, candidates in entry["pick"].items()}


def sql(entry, src, region, con=None):
    """The entry's query for an input and a region (con: a DuckDB connection, needed for "pick")."""
    west, south, east, north = region["bbox"]
    if os.path.isdir(str(src)):
        src = os.path.join(str(src), "*.parquet")
    src = str(src).replace("'", "''")
    extra = picked(entry, con, src, f"read_parquet('{src}', hive_partitioning = 1)") if con is not None else {}
    return entry["query"].format(src=src, west=west, south=south, east=east, north=north, **extra)


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
    query = f"SELECT * FROM read_parquet('{path}')" if str(path).endswith(SLICE) else sql(entry, path, region, con)
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
        # The fine type: the source's own category made a phrase ("pizza_restaurant" -> "pizza restaurant"; the
        # last part of Foursquare's "Dining and Drinking > Restaurant > Pizzeria").
        kind = types.humanise(row.get("cls")) or entry.get("type") or None
        key = f"{source}:{row['key']}"
        first, last = fmt.parse_month(str(row.get("first") or "")), fmt.parse_month(str(row.get("last") or ""))
        if "geojson" in row:
            geo = json.loads(row["geojson"])
            polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
            rings = [[(y, x) for x, y in ring] for poly in polys for ring in poly]
            writer.add_area(key, source, name, cls, entry.get("tag", source), rings, first, last, type=kind)
        else:
            brand = (row.get("brand"), row.get("brand_qid")) if row.get("brand") else None
            writer.add_point(key, source, name, cls, entry.get("tag", source), float(row["lat"]), float(row["lon"]),
                             first, last, type=kind, brand=brand)
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
    con.execute(f"COPY ({sql(entry, entry['remote'], region, con)}) TO '{target}' (FORMAT PARQUET)")
    con.close()
