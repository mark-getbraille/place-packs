"""SQLite files a source publishes (USGS GNIS's GeoPackage gazetteers), read with the standard library: the entry's
"query" runs on the file (taken out of its .zip first) and returns the columns key, name, cls, lat, lon and, when the
source has them, type, first and last. GNIS gives the variant and former names of a feature this way (class
"variant": kept for name search, never spoken as a place's name) and its historical features."""

import os
import sqlite3
import tempfile
import zipfile

from placepacks import fmt
from placepacks.readers import reader


def _open(path, member=".gpkg"):
    """(connection, temporary folder or None) of a SQLite file, or of the first member ending in member inside a .zip."""
    path = str(path)
    if os.path.isdir(path):
        path = next(os.path.join(path, n) for n in sorted(os.listdir(path)) if n.endswith((".zip", member)))
    if path.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp()
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(member))
            z.extract(name, tmp)
        return sqlite3.connect(os.path.join(tmp, name)), tmp
    return sqlite3.connect(path), None


@reader("sqlite")
def read(path, entry, region, writer):
    """Add the query's points to writer. Returns the number of records."""
    import shutil
    con, tmp = _open(path, entry.get("member", ".gpkg"))
    west, south, east, north = region["bbox"]
    count = 0
    try:
        cur = con.execute(entry["query"])
        names = [d[0] for d in cur.description]
        for values in cur:
            row = dict(zip(names, values))
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (TypeError, ValueError):
                continue
            if not (south - 0.05 <= lat <= north + 0.05 and west - 0.05 <= lon <= east + 0.05) or lat == lon == 0:
                continue
            name = " ".join(str(row.get("name") or "").split())
            if not name:
                continue
            first = fmt.parse_month(str(row.get("first") or "")) if row.get("first") else None
            last = fmt.parse_month(str(row.get("last") or "")) if row.get("last") else None
            writer.add_point(f"{entry['id']}:{row['key']}", entry["id"], name, row.get("cls") or entry.get("cls", ""),
                             entry.get("tag", entry["id"]), lat, lon, first, last, type=row.get("type") or None)
            count += 1
    finally:
        con.close()
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    return count
