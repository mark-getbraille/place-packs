"""Street and transit accessibility (the owner's request of 27 November 2026, notes/helper-rules.txt: queue item
Q4). One monthly collection, "streetaccess" (workflow .github/workflows/street-access.yml, release
"street-access"), with these units:

  signals          accessible pedestrian signals (audible and vibrating crosswalk signals) from cities', counties'
                   and state DOTs' open data, found each month in the Socrata catalogue and ArcGIS Hub
                   (open_data.py)
  curb-ramps-1..4  curb ramp inventories (with condition, ADA compliance and detectable warning surfaces when given),
                   found the same way, in four shares (open_data.py)
  mta-elevators    New York City Transit's elevators and escalators (transit_lists.py)
  mbta-elevators   the MBTA's elevators and escalators (transit_lists.py)
  amtrak-stations  Amtrak stations' accessibility and staffed hours from Great American Stations (amtrak.py)

The rows are the site features CSV (placepacks/features.py) plus four columns (FIELDS): installed (an APS's
install date), tags (the facts as JSON, for the navigation part), layer and publisher (which government's layer).
The pack build reads the release three ways (sources.json):
  street-access             extra part, "site_features" reader: accessible pedestrian signals (kind "accessible
                            pedestrian signal", no site), station elevators and escalators (with their station),
                            Amtrak stations' notes, hours and features; curb ramps are NOT put here (too many for the
                            default download)
  street-access-navigation  navigation part, "nav_street_access" reader (placepacks/readers/street_access.py): the
                            signals and the curb ramps as navigation features, for Navigator.crossing_here
GTFS pathways (station entrances, elevators, escalators and stairs) and the stops' wheelchair boarding come from
the transit feeds the build already reads (placepacks/readers/gtfs_stations.py, source gtfs-station-features).
Sidewalk networks: OpenStreetMap's sidewalks are already in the navigation part (nav_ways, footway=sidewalk, with
surface, width and incline); cities' own sidewalk layers are NOT added (lines of every sidewalk of a city would
double the navigation part's size and do not join its routing graph).

Politeness (the owner's limits): an identified User-Agent, at least PAUSE seconds between requests to one host (10
seconds for Great American Stations, its robots.txt Crawl-delay), a request budget per unit, robots.txt read and
obeyed for websites, never past a CAPTCHA, a login or an anti-bot challenge, no headless or Chrome-imitating
browser, no other IP address: a refusal is recorded as "blocked" and left. Facts only: no people's names (a name
added to an intersection's description is taken out), no e-mail addresses, no free-text comments.
Only the Python standard library is used.
"""

import importlib

from placepacks import features
from placepacks.street_access import open_data

USER_AGENT = open_data.USER_AGENT
PAUSE = 3.0                     # the MBTA's API allows 20 requests a minute without a key
TAG = "street-access"
FIELDS = features.FEATURE_FIELDS + ["installed", "tags", "layer", "publisher"]
UNITS = {"signals": {"title": "Accessible pedestrian signals (cities' and DOTs' open data)", "expected": 10000,
                     "budget": 3000, "timeout": 300, "module": "placepacks.street_access.open_data"}}
UNITS.update({f"curb-ramps-{i}": {"title": f"Curb ramp inventories ({i} of {open_data.RAMP_SHARDS})",
                                  "expected": 100000, "budget": 4000, "timeout": 340,
                                  "module": "placepacks.street_access.open_data"}
              for i in range(1, open_data.RAMP_SHARDS + 1)})
UNITS.update({
    "mta-elevators": {"title": "New York City Transit elevators and escalators", "expected": 500, "budget": 10,
                      "timeout": 30, "module": "placepacks.street_access.transit_lists"},
    "mbta-elevators": {"title": "MBTA elevators and escalators", "expected": 400, "budget": 20, "timeout": 30,
                       "module": "placepacks.street_access.transit_lists"},
    "amtrak-stations": {"title": "Amtrak station accessibility (Great American Stations)", "expected": 500,
                        "budget": 700, "timeout": 200, "module": "placepacks.street_access.amtrak"},
})


def collect(client, unit, stats):
    """One unit's rows: its module's collect(client, unit, stats)."""
    yield from importlib.import_module(UNITS[unit]["module"]).collect(client, unit, stats)
