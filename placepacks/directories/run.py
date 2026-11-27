"""Run one unit of a local-directory collector (a workflow's matrix job), list the units for the matrix, or publish
the month's set (the workflow's last job). The same shape as the chain collectors (placepacks/chains/run.py and
release.py), for the collections:

  simpleview     units: the tourism boards' sites (placepacks/directories/simpleview.py SITES)
  tempest        units: the tourism boards' sites on the Tempest platform (placepacks/directories/tempest.py SITES)
  chambermaster  units: the states, each found through the US Chamber of Commerce's directory
                 (placepacks/directories/chambermaster.py STATES)
  hotfrog        units: the states; each searches Hotfrog town by town (placepacks/directories/hotfrog.py)
  cityfacilities units: the states; each reads the layers the month's discovery found in it
                 (placepacks/directories/city_facilities.py)
  mapvendors     units: the campus-map collectors (placepacks/mapvendors UNITS: mazemap, concept3d, campus-gis),
                 reading the month's map list of the discovery (MAP_VENDORS_LIST)
  healthaccess   units: the insurers' FHIR provider directories and the shards of hospitals' own pages
                 (placepacks/health_access UNITS)
  malls          units: the mall operators and the shares of independent malls (placepacks/indoor MALL_UNITS)
  airports       units: the shares of the airports with scheduled service (placepacks/indoor AIRPORT_UNITS)
  streetaccess   units: accessible pedestrian signals, curb ramp shares, transit elevator lists and Amtrak
                 stations (placepacks/street_access UNITS)
  museumaccess   units: the shares of museums' own accessibility pages (placepacks/museum_access UNITS)

    python -m placepacks.directories.run simpleview --list [--only "visitdenver iloveny"]   the matrix
    python -m placepacks.directories.run simpleview --unit visitdenver --out out/           one unit's CSV + summary
    python -m placepacks.directories.run simpleview --unit "visitdenver visitkc" --out out/  several, one after another
    python -m placepacks.directories.run simpleview --publish --dir results/ --units "..."  the month's set

Matrix groups: a collection with many small units (the tourism boards' sites: "group_minutes" in its settings)
is run as GROUPS of units, so the monthly workflow stays well under GitHub's limits (at most 256 jobs in a matrix,
6 hours a job): matrix() packs the units into groups of about group_minutes of expected work each (a site's
expected listings times 3 seconds), and each matrix job runs its group's units one after another (run_units), every
unit with its own summary and CSV, so the release still keeps or carries over each site on its own.

The summary (out/<unit>.json) says how it went: "ok" (everything was read: the CSV is the unit's whole set),
"blocked" (a site refused us: stopped at once, never got round), "incomplete" (the request budget or the time ran
out) or "failed". Only an "ok" run writes a CSV; for every other result the publish job keeps the unit's rows of
the previous set (placepacks/chains/release.py: up to three months), so a bad month never closes places in the
packs' history. The run itself always ends with exit code 0.
Only the Python standard library is used.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import shutil
import sys
import time

from placepacks.chains.polite import Blocked, BudgetSpent, Polite

MARGIN_MIN = 10        # minutes kept free before the job's time limit, to write the files
GROUP_TIMEOUT = 350    # the longest a matrix job of a group may run, in minutes (GitHub stops a job at 360)
SECONDS_PER_ITEM = 3   # the expected seconds per listing, for packing units into groups


def collections():
    """{name: its settings}: units {id: {"title", "expected", "budget", "timeout"}}, collect(client, unit, stats),
    fields (the CSV's columns), agent, pause, and the release's tag, prefix, title and notes."""
    from placepacks import health_access, indoor, mapvendors, museum_access, street_access
    from placepacks.directories import chambermaster, city_facilities, hotfrog, simpleview, tempest
    from placepacks.mapvendors import discover
    from placepacks.street_access import open_data
    return {
        # Campus and indoor maps (placepacks/mapvendors): the units read the month's map list (MAP_VENDORS_LIST).
        "mapvendors": {"units": mapvendors.UNITS, "collect": mapvendors.collect, "fields": mapvendors.FIELDS,
                       "agent": mapvendors.USER_AGENT, "pause": mapvendors.PAUSE, "tag": mapvendors.TAG,
                       "prefix": "map-vendors", "title": "Campus and indoor maps: buildings and accessibility",
                       "extra_files": {discover.LIST_FILE: discover.LIST_FILE,
                                       discover.NEW_VENDORS_FILE: discover.NEW_VENDORS_FILE},
                       "notes": "Monthly buildings, accessible entrances, elevators, parking and other site features "
                                "of colleges, hospitals, zoos and other sites from their map platforms and campus "
                                "GIS layers (placepacks/mapvendors), read by the pack build (source map-vendors). "
                                f"The month's map list is {discover.LIST_FILE}; map vendors not yet in the "
                                f"registry are in {discover.NEW_VENDORS_FILE}. Not for download."},
        # Hospital and clinic accessibility (placepacks/health_access).
        "healthaccess": {"units": health_access.UNITS, "collect": health_access.collect,
                         "fields": health_access.FIELDS, "agent": health_access.USER_AGENT,
                         "pause": health_access.PAUSE, "tag": health_access.TAG, "prefix": "health-access",
                         "title": "Hospital and clinic accessibility",
                         "notes": "Monthly accessibility facts, hours and phone numbers of hospitals and clinics "
                                  "from health insurers' public FHIR provider directories and hospitals' own pages "
                                  "(placepacks/health_access), read by the pack build (source health-access). Not "
                                  "for download."},
        # Mall and airport directories (placepacks/indoor).
        "malls": {"units": indoor.MALL_UNITS, "collect": indoor.collect_malls, "fields": indoor.FIELDS,
                  "agent": indoor.USER_AGENT, "pause": indoor.PAUSE, "tag": indoor.MALL_TAG, "prefix": "malls",
                  "title": "Mall directories: stores and amenities",
                  "notes": "Monthly store directories (name, category, level, unit, hours, phone, website) and "
                           "amenities (guest services, wheelchairs, family restrooms ...) of US malls and outlet "
                           "centres from their own websites (placepacks/indoor/malls.py), read by the pack build "
                           "(sources mall-directories and mall-directories-businesses). Not for download."},
        "airports": {"units": indoor.AIRPORT_UNITS, "collect": indoor.collect_airports, "fields": indoor.FIELDS,
                     "agent": indoor.USER_AGENT, "pause": indoor.PAUSE, "tag": indoor.AIRPORT_TAG,
                     "prefix": "airports", "title": "Airport terminal directories",
                     "notes": "Monthly gates, shops, restaurants, restrooms, relief areas, desks, accessibility "
                              "services and ground transport of US airports from their own websites and public "
                              "Atrius maps (placepacks/indoor/airports.py), read by the pack build (sources "
                              "airport-directories and airport-directories-businesses). Not for download."},
        # Street and transit accessibility (placepacks/street_access): the signals and curb ramps units read the
        # month's layer list (STREET_ACCESS_LIST), stored in the release beside the set.
        "streetaccess": {"units": street_access.UNITS, "collect": street_access.collect,
                         "fields": street_access.FIELDS, "agent": street_access.USER_AGENT,
                         "pause": street_access.PAUSE, "tag": street_access.TAG, "prefix": "street-access",
                         "title": "Street and transit accessibility",
                         "extra_files": {open_data.LIST_FILE: open_data.RELEASE_LIST},
                         "notes": "Monthly accessible pedestrian signals and curb ramps from US cities' and "
                                  "transportation departments' open data, transit agencies' elevator and "
                                  "escalator lists and Amtrak stations' accessibility (placepacks/street_access), "
                                  "read by the pack build (sources street-access and street-access-navigation). "
                                  f"The month's layer list is {open_data.RELEASE_LIST}. Not for download."},
        # Museums' own accessibility pages (placepacks/museum_access.py).
        "museumaccess": {"units": museum_access.UNITS, "collect": museum_access.collect,
                         "fields": museum_access.FIELDS, "agent": museum_access.USER_AGENT,
                         "pause": museum_access.PAUSE, "tag": museum_access.TAG, "prefix": "museum-access",
                         "title": "Museum accessibility",
                         "notes": "Monthly accessibility facts of US museums (audio description, touch tours, "
                                  "braille, sign language, wheelchairs, sensory-friendly programs ...) from their "
                                  "own websites (placepacks/museum_access.py), read by the pack build (source "
                                  "museum-access). Not for download."},
        "hotfrog": {"units": hotfrog.STATES, "collect": hotfrog.collect, "fields": hotfrog.FIELDS,
                    "agent": hotfrog.USER_AGENT, "pause": hotfrog.PAUSE, "tag": "hotfrog-listings",
                    "prefix": "hotfrog-listings", "title": "Hotfrog business listings",
                    "notes": "Monthly business listings found town by town on Hotfrog (placepacks/directories/"
                             "hotfrog.py), read by the pack build (source hotfrog-listings). Not for download."},
        "cityfacilities": {"units": city_facilities.STATES, "collect": city_facilities.collect,
                           "fields": city_facilities.FIELDS, "agent": city_facilities.USER_AGENT,
                           "pause": city_facilities.PAUSE, "tag": "city-facilities", "prefix": "city-facilities",
                           "title": "Cities' and counties' public places",
                           "extra_files": {city_facilities.LIST_FILE: city_facilities.RELEASE_LIST},
                           "notes": "Monthly lists of public places (city halls, libraries, community and "
                                    "recreation centers ...) from US cities' and counties' open-data layers, found "
                                    "by a monthly discovery (placepacks/directories/city_facilities.py), read by "
                                    "the pack build (source city-facilities). The month's layer list is "
                                    f"{city_facilities.RELEASE_LIST}. Not for download."},
        "simpleview": {"units": simpleview.SITES, "collect": simpleview.collect, "fields": simpleview.FIELDS,
                       "agent": simpleview.USER_AGENT, "pause": simpleview.PAUSE, "tag": "simpleview-listings",
                       "group_minutes": 300,
                       "prefix": "simpleview-listings", "title": "Tourism boards' Simpleview listings",
                       "notes": "Monthly listings of tourism boards' Simpleview sites (placepacks/directories/"
                                "simpleview.py), read by the pack build (source simpleview-listings). Not for "
                                "download."},
        "tempest": {"units": tempest.SITES, "collect": tempest.collect, "fields": tempest.FIELDS,
                    "agent": tempest.USER_AGENT, "pause": tempest.PAUSE, "tag": "tempest-listings",
                    "group_minutes": 300, "prefix": "tempest-listings",
                    "title": "Tourism boards' Tempest listings",
                    "notes": "Monthly partner listings of city and county tourism boards' Tempest sites "
                             "(placepacks/directories/tempest.py), read by the pack build (source "
                             "tempest-listings). Not for download."},
        "chambermaster": {"units": chambermaster.STATES, "collect": chambermaster.collect,
                          "fields": chambermaster.FIELDS, "agent": chambermaster.USER_AGENT,
                          "pause": chambermaster.PAUSE, "tag": "chambermaster-listings",
                          "prefix": "chambermaster-listings", "title": "Chambers' ChamberMaster directories",
                          "notes": "Monthly member listings of chambers of commerce on the older ChamberMaster "
                                   "platform (placepacks/directories/chambermaster.py), read by the pack build "
                                   "(source chambermaster-listings). Not for download."},
    }


def run(collection, unit, out, opener=None, sleep=time.sleep, clock=time.monotonic, today=None, minutes=None):
    """Collect one unit into out/ (see the module docstring). minutes: the time this unit may take (default its
    own "timeout"; a group gives each unit what is left of the job's time). Returns its summary dict."""
    spec = collections()[collection]
    unit_spec = spec["units"][unit]
    os.makedirs(out, exist_ok=True)
    started = clock()
    limit = unit_spec["timeout"] if minutes is None else minutes
    client = Polite(unit_spec["budget"], spec["pause"], opener=opener, sleep=sleep, clock=clock,
                    deadline=started + 60 * max(1, limit - MARGIN_MIN), agent=spec["agent"])
    stats, rows, status, reason = {}, [], "ok", ""
    try:
        for row in spec["collect"](client, unit, stats):
            rows.append(row)
    except Blocked as e:
        status, reason = "blocked", str(e)
    except BudgetSpent as e:
        status, reason = "incomplete", str(e)
    except Exception as e:  # noqa: BLE001 - recorded in the summary; the previous set is kept
        status, reason = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    if status == "ok" and not rows and not stats.get("may_be_empty"):
        status, reason = "failed", "nothing was found (has the site changed?)"
    summary = {"chain": unit, "title": unit_spec["title"], "status": status, "reason": reason, "rows": len(rows),
               "expected": unit_spec["expected"], "endpoint": collection, "requests": client.used,
               "hosts": len(client.hosts), "seconds": round(clock() - started, 1),
               "date": (today or datetime.date.today()).isoformat(), "stats": stats}
    target = os.path.join(out, f"{unit}.csv.gz")
    if status == "ok" and rows:
        rows.sort(key=lambda r: r["key"])
        with gzip.open(target + ".partial", "wt", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=spec["fields"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(target + ".partial", target)
    elif os.path.exists(target):
        os.remove(target)
    with open(os.path.join(out, f"{unit}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"{collection} {unit}: {status} ({len(rows):,} rows, {client.used} requests"
          f"{', ' + reason if reason else ''})", flush=True)
    return summary


def expected_minutes(unit_spec):
    """About how many minutes one unit's collection takes: its expected listings at SECONDS_PER_ITEM each, plus
    five minutes for robots.txt and the sitemaps."""
    return int(unit_spec.get("expected", 0) * SECONDS_PER_ITEM / 60) + 5


def groups(units, wanted, capacity):
    """The wanted unit ids packed into groups of at most `capacity` expected minutes each (the biggest units
    first, each into the first group with room; a unit bigger than capacity gets a group of its own). Returns
    [[id, ...], ...] in a stable order."""
    packed = []
    for u in sorted(wanted, key=lambda u: (-expected_minutes(units[u]), u)):
        need = expected_minutes(units[u])
        for g in packed:
            if g[0] + need <= capacity:
                g[0] += need
                g[1].append(u)
                break
        else:
            packed.append([need, [u]])
    return [g[1] for g in packed]


def matrix(collection, only=""):
    """The matrix jobs of a run (only: ids separated by spaces or commas; empty: all). An unknown id stops with an
    error that lists the known ones. A collection without "group_minutes": [{"unit", "timeout"}], one job a unit;
    with it: [{"unit": "group-01", "units": "id id ...", "timeout"}], one job a group (see the module
    docstring)."""
    spec = collections()[collection]
    units = spec["units"]
    wanted = [u for u in only.replace(",", " ").split() if u] or list(units)
    unknown = [u for u in wanted if u not in units]
    if unknown:
        raise SystemExit(f"unknown unit(s): {', '.join(unknown)}; known: {', '.join(units)}")
    if not spec.get("group_minutes"):
        return [{"unit": u, "timeout": units[u]["timeout"]} for u in wanted]
    out = []
    for i, members in enumerate(groups(units, wanted, spec["group_minutes"]), 1):
        need = sum(expected_minutes(units[u]) for u in members)
        out.append({"unit": f"group-{i:02d}", "units": " ".join(members),
                    "timeout": min(GROUP_TIMEOUT, int(need * 1.5) + 2 * MARGIN_MIN)})
    return out


def run_units(collection, ids, out, total_minutes=GROUP_TIMEOUT, opener=None, sleep=time.sleep,
              clock=time.monotonic, today=None):
    """Run several units one after another in one job (a matrix group), sharing the job's total_minutes: each
    unit may take what is left, but at most twice its expected time (at least 30 minutes), so one slow site does
    not use up the others' time. A unit with no time left is recorded as "incomplete" without a request (its
    previous file is kept). Returns the summaries."""
    spec = collections()[collection]
    end = clock() + 60 * (total_minutes - MARGIN_MIN)
    summaries = []
    for unit in ids:
        left = (end - clock()) / 60
        if left < MARGIN_MIN + 2:
            unit_spec = spec["units"][unit]
            summary = {"chain": unit, "title": unit_spec["title"], "status": "incomplete",
                       "reason": "no time was left in the group's job", "rows": 0,
                       "expected": unit_spec["expected"], "endpoint": collection, "requests": 0, "hosts": 0,
                       "seconds": 0, "date": (today or datetime.date.today()).isoformat(), "stats": {}}
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, f"{unit}.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=1)
            summaries.append(summary)
            continue
        share = max(30, 2 * expected_minutes(spec["units"][unit])) + MARGIN_MIN
        summaries.append(run(collection, unit, out, opener=opener, sleep=sleep, clock=clock, today=today,
                             minutes=min(left, share)))
    return summaries


def publish(collection, folder, date, ran, sleep=time.sleep):
    """Publish the month's set of a collection in its release (placepacks/chains/release.py), and then its extra
    files (the city facilities' layer list: "extra_files" {file in folder: name in the release}, replaced each
    month). Returns the list."""
    from placepacks import uploaded
    from placepacks.chains import release
    spec = collections()[collection]
    listing = release.publish(folder, date, ran, sleep=sleep, units=spec["units"], tag=spec["tag"],
                              prefix=spec["prefix"], title=spec["title"], notes=spec["notes"])
    for name, target in (spec.get("extra_files") or {}).items():
        path = os.path.join(folder, name)
        if os.path.exists(path):
            renamed = os.path.join(folder, target)
            if renamed != path:
                shutil.copy(path, renamed)
            code, _, err = uploaded.run_gh(["release", "upload", spec["tag"], renamed, "--repo", uploaded.repo(),
                                            "--clobber"])
            if code != 0:
                raise RuntimeError(f"uploading {target} failed: {' '.join(str(err).split())[:200]}")
    return listing


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("collection", choices=["simpleview", "tempest", "chambermaster", "cityfacilities", "hotfrog",
                                          "mapvendors", "healthaccess", "malls", "airports", "streetaccess",
                                          "museumaccess"])
    p.add_argument("--list", action="store_true")
    p.add_argument("--only", default="")
    p.add_argument("--unit", default="", help="a unit's id, or several separated by spaces (a matrix group)")
    p.add_argument("--minutes", type=int, default=GROUP_TIMEOUT, help="the job's time for several units")
    p.add_argument("--out", default="directory-out")
    p.add_argument("--publish", action="store_true")
    p.add_argument("--dir", default="results")
    p.add_argument("--units", default="", help="the units run this time (publish; empty: every unit)")
    p.add_argument("--date", default=datetime.date.today().isoformat())
    a = p.parse_args(argv)
    if a.list:
        print(json.dumps(matrix(a.collection, a.only), separators=(",", ":")))
        return 0
    if a.publish:
        from placepacks.chains import release
        units = collections()[a.collection]["units"]
        ran = set(a.units.replace(",", " ").split()) or set(units)
        os.makedirs(a.dir, exist_ok=True)
        text = release.table(publish(a.collection, a.dir, a.date, ran))
        print(text)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write(text)
        return 0
    ids = a.unit.replace(",", " ").split()
    unknown = [u for u in ids if u not in collections()[a.collection]["units"]]
    if not ids or unknown:
        raise SystemExit(f"unknown unit {' '.join(unknown) or a.unit!r}")
    if len(ids) == 1:
        run(a.collection, ids[0], a.out)
    else:
        run_units(a.collection, ids, a.out, total_minutes=a.minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
