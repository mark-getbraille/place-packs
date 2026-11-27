"""Campus maps and indoor maps: buildings and accessibility features of colleges, hospitals, zoos, malls and other
sites, from the map platforms they use and from universities' own GIS layers (the owner's decisions of 27 November
2026, notes/helper-rules.txt: queue item Q2). Source "map-vendors" (the extra part's site_features table and the
sites' details; placepacks/features.py).

  registry.py    the vendors and their fingerprints (script, iframe and API hosts; map id patterns), with what is
                 known of each one's public data
  discover.py    the discovery chain: scans organisations' websites (IPEDS colleges, Wikidata hospitals and venues,
                 the vendors' own showcases) for the fingerprints; the month's list of maps (org -> vendor -> map id)
                 and the new, unknown map vendors (notes/new-map-vendors.txt)
  mazemap.py     MazeMap campuses (public API)
  concept3d.py   Concept3D maps (ready, but api.concept3d.com's robots.txt disallows programs: blocked until the
                 owner decides)
  campus_gis.py  universities' open ArcGIS building layers, found through ArcGIS Hub

The monthly workflow (.github/workflows/map-vendors.yml): discovery shards, then one collector job per unit of
UNITS (placepacks/directories/run.py, collection "mapvendors"), then the release "map-vendors" (the month's set of
CSV files, the map list map-vendors-orgs.json and new-map-vendors.txt), read by the pack build (fetch
"release_csv", reader "site_features").
Never: a login, a CAPTCHA, an anti-bot challenge, a headless or Chrome-imitating browser, another IP address; a
site that refuses is recorded as "blocked" and left. Never kept: people's names (rooms and offices are not read),
e-mail addresses, descriptions beyond an accessibility note.
Only the Python standard library is used.
"""

import importlib

from placepacks import features

USER_AGENT = "place-packs-map-vendors/1 (+https://github.com/mark-getbraille/place-packs)"
PAUSE = 1.5
FIELDS = features.FEATURE_FIELDS
TAG = "map-vendors"
# The collector units of the monthly workflow: {id: {"title", "expected", "budget", "timeout", "module"}}.
UNITS = {
    "mazemap": {"title": "MazeMap campuses", "expected": 5000, "budget": 6000, "timeout": 240,
                "module": "placepacks.mapvendors.mazemap"},
    "concept3d": {"title": "Concept3D maps", "expected": 0, "budget": 20000, "timeout": 300,
                  "module": "placepacks.mapvendors.concept3d"},
    "campus-gis": {"title": "Universities' campus GIS layers (ArcGIS Hub)", "expected": 20000, "budget": 1500,
                   "timeout": 180, "module": "placepacks.mapvendors.campus_gis"},
}


def collect(client, unit, stats):
    """One unit's rows (features.FEATURE_FIELDS): the unit's module's collect(client, unit, stats), which reads the
    discovery's map list from MAP_VENDORS_LIST (placepacks/mapvendors/discover.py read_list)."""
    module = importlib.import_module(UNITS[unit]["module"])
    yield from module.collect(client, unit, stats)
