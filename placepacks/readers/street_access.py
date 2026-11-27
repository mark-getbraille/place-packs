"""The reader "nav_street_access": accessible pedestrian signals and curb ramps from cities' and transportation
departments' open data (placepacks/street_access/open_data.py, release "street-access") into the NAVIGATION part's
nav_features (source "street-access-navigation"), so Navigator.crossing_here can say "the city lists an accessible
pedestrian signal at this crossing, installed 2023-12-16, with a locator tone" and name the curb ramps' condition.

Each row of kind "accessible pedestrian signal" or "curb ramp" becomes one feature of that kind, at its own
position, named by its intersection, with these tags (JSON, only those given): source (the publisher), installed,
locator_tone, vibration, button, speech, type, status (signals); compliant, detectable_warning, condition (curb
ramps); description (the row's note). Other rows (station elevators, Amtrak stations) are for the extra part only.
Only the Python standard library is used.
"""

import json

from placepacks import navigation
from placepacks.features import csv_rows, in_region
from placepacks.readers import reader

KINDS = ("accessible pedestrian signal", "curb ramp")
TAGS = ("name", "source", "installed", "locator_tone", "vibration", "button", "speech", "type", "status",
        "compliant", "detectable_warning", "condition", "description")


@reader("nav_street_access")
def read(path, entry, region, writer):
    """Add the region's signals and curb ramps of the street-access CSV (a file or the region's slice folder) to
    the navigation part. Returns the number of features."""
    nav = navigation.store(writer)
    wanted = set(entry.get("kinds") or KINDS)
    count = 0
    for row in csv_rows(path, entry.get("member", "*.csv")):
        if row.get("kind") not in wanted:
            continue
        try:
            lat, lon = float(row.get("lat")), float(row.get("lon"))
        except (TypeError, ValueError):
            continue
        if not in_region(region, lat, lon):
            continue
        try:
            tags = json.loads(row.get("tags") or "{}")
        except ValueError:
            tags = {}
        tags = {k: str(v) for k, v in (tags if isinstance(tags, dict) else {}).items()}
        tags["name"] = row.get("name") or ""
        tags["description"] = row.get("notes") or ""
        if nav.add_feature(row.get("key"), row["kind"], tags, lat, lon, keep=TAGS):
            count += 1
    return count
