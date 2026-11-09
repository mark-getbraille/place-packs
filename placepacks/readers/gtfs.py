"""Public transit stops from GTFS feeds (stops.txt inside each feed's .zip), keyed by the feed and the stop id.

Only feeds whose licence allows redistribution are fetched (fetch.py takes them from the Mobility Database catalogue
and keeps a feed only when its licence address is one of OPEN_LICENCES); the feed's id is the start of its file
name ("mdb-123.zip"). Stations and stops get the class "transit": "at the Main St & 5th Ave bus stop".
"""

import csv
import io
import os
import zipfile

from placepacks.readers import reader

# Licence addresses accepted for a GTFS feed (their text says redistribution is allowed with attribution or freely).
OPEN_LICENCES = ("creativecommons.org/licenses/by/", "creativecommons.org/publicdomain/zero/",
                 "opendatacommons.org/licenses/by/", "opendatacommons.org/licenses/pddl/",
                 "open.canada.ca/en/open-government-licence-canada", "www.usa.gov/government-works",
                 "www.usa.gov/publicdomain")


def licence_ok(url):
    """True when a feed's licence address is one of OPEN_LICENCES (no NC or ND Creative Commons licences)."""
    url = (url or "").lower()
    if "-nc" in url or "-nd" in url or "/by-sa" in url:
        return False
    return any(ok in url for ok in OPEN_LICENCES)


@reader("gtfs")
def read(path, entry, region, writer):
    """Add the stops of every feed .zip in path (a folder or one file). Returns the number of stops."""
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".zip")] if os.path.isdir(path) \
        else [path]
    west, south, east, north = region["bbox"]
    count = 0
    for file in files:
        feed = os.path.basename(file)[:-4]
        try:
            z = zipfile.ZipFile(file)
            raw = z.open(next(n for n in z.namelist() if os.path.basename(n) == "stops.txt"))
        except (StopIteration, zipfile.BadZipFile, OSError):
            continue
        with z, raw:
            for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace")):
                name = (row.get("stop_name") or "").strip()
                if not name or row.get("location_type", "0") not in ("", "0", "1"):
                    continue
                try:
                    lat, lon = float(row["stop_lat"]), float(row["stop_lon"])
                except (KeyError, ValueError):
                    continue
                if not (south <= lat <= north and west <= lon <= east):
                    continue
                kind = "station" if row.get("location_type") == "1" else "stop"
                writer.add_point(f"{entry['id']}:{feed}:{row.get('stop_id', '')}", entry["id"], name, "transit",
                                 f"transit={kind}", lat, lon)
                count += 1
    return count
