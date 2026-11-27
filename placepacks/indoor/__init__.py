"""Indoor directories: what is inside US shopping malls and airports (the owner's decisions of 27 November 2026,
notes/helper-rules.txt: queue item Q3). Two collections, each with its monthly workflow and release:

  malls.py     mall and outlet-centre store directories and amenities (release "malls"; sources
               "mall-directories", extra part, and "mall-directories-businesses", businesses part)
  airports.py  airport terminal directories: gates, shops, restaurants, restrooms, relief areas, desks,
               accessibility services, ground transport (release "airports"; sources "airport-directories" and
               "airport-directories-businesses"); airports' Atrius maps are read by placepacks/mapvendors/atrius.py
  seeds.py     where the malls and airports are (Wikidata, OpenStreetMap, OurAirports)
  common.py    the rows, privacy filters, hours and page readers they share

The rows are the site features CSV (placepacks/features.py; common.FIELDS adds the businesses part's columns). The
pack build reads each release with the "site_features" reader (stores, desks, restrooms ... as site features with
their site, building and level; the mall's or airport's own phone, hours and website go to its place) and with the
"tabular" reader for the businesses part (the stores and restaurants that have their own phone or hours).
Run like the other directory collections (placepacks/directories/run.py, collections "malls" and "airports"):
    python -m placepacks.directories.run malls --list
    python -m placepacks.directories.run malls --unit tanger --out out/
    python -m placepacks.directories.run airports --unit airports-1 --out out/
Never: a login, a CAPTCHA, an anti-bot challenge, a headless or Chrome-imitating browser, another IP address; a
site that refuses is recorded as "blocked" and left. Never kept: people's names, e-mail addresses, descriptions,
reviews, ratings, photos.
Only the Python standard library is used.
"""

import importlib

from placepacks.indoor import common

USER_AGENT = "place-packs-indoor-directories/1 (+https://github.com/mark-getbraille/place-packs)"
PAUSE = 2.0
FIELDS = common.FIELDS
MALL_TAG = "malls"
AIRPORT_TAG = "airports"


def _mall_units():
    """The mall units: one per operator, then the independent malls' shares."""
    from placepacks.indoor import malls
    titles = {"tanger": ("Tanger outlet centres", 3000, 400), "macerich": ("Macerich malls", 6000, 400),
              "brookfield": ("Brookfield Properties malls", 15000, 1200),
              "westfield": ("Westfield US centres", 3000, 300), "cbl": ("CBL Properties malls", 8000, 400)}
    units = {u: {"title": t, "expected": e, "budget": b, "timeout": 300, "module": "placepacks.indoor.malls"}
             for u, (t, e, b) in titles.items()}
    for u in malls.NOT_READ:
        units[u] = {"title": f"{u.replace('-', ' ').title()} (not read: checked monthly)", "expected": 0,
                    "budget": 5, "timeout": 20, "module": "placepacks.indoor.malls"}
    for i in range(1, malls.INDEPENDENT_SHARDS + 1):
        units[f"independent-{i}"] = {"title": f"Independent malls' own websites ({i} of {malls.INDEPENDENT_SHARDS})",
                                     "expected": 10000, "budget": 4000, "timeout": 340,
                                     "module": "placepacks.indoor.malls"}
    return units


def _airport_units():
    """The airport units: the shares of the airports with scheduled service."""
    from placepacks.indoor import airports
    return {f"airports-{i}": {"title": f"Airports' own websites and maps ({i} of {airports.SHARDS})",
                              "expected": 5000, "budget": 1500, "timeout": 340, "module": "placepacks.indoor.airports"}
            for i in range(1, airports.SHARDS + 1)}


MALL_UNITS = _mall_units()
AIRPORT_UNITS = _airport_units()


def collect_malls(client, unit, stats):
    """One mall unit's rows (placepacks/indoor/malls.py collect)."""
    yield from importlib.import_module(MALL_UNITS[unit]["module"]).collect(client, unit, stats)


def collect_airports(client, unit, stats):
    """One airport unit's rows (placepacks/indoor/airports.py collect)."""
    yield from importlib.import_module(AIRPORT_UNITS[unit]["module"]).collect(client, unit, stats)
