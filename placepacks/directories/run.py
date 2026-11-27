"""Run one unit of a local-directory collector (a workflow's matrix job), list the units for the matrix, or publish
the month's set (the workflow's last job). The same shape as the chain collectors (placepacks/chains/run.py and
release.py), for the collections:

  simpleview     units: the tourism boards' sites (placepacks/directories/simpleview.py SITES)
  chambermaster  units: the states, each found through the US Chamber of Commerce's directory
                 (placepacks/directories/chambermaster.py STATES)

    python -m placepacks.directories.run simpleview --list [--only "visitdenver iloveny"]   the matrix
    python -m placepacks.directories.run simpleview --unit visitdenver --out out/           one unit's CSV + summary
    python -m placepacks.directories.run simpleview --publish --dir results/ --units "..."  the month's set

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
import sys
import time

from placepacks.chains.polite import Blocked, BudgetSpent, Polite

MARGIN_MIN = 10        # minutes kept free before the job's time limit, to write the files


def collections():
    """{name: its settings}: units {id: {"title", "expected", "budget", "timeout"}}, collect(client, unit, stats),
    fields (the CSV's columns), agent, pause, and the release's tag, prefix, title and notes."""
    from placepacks.directories import chambermaster, simpleview
    return {
        "simpleview": {"units": simpleview.SITES, "collect": simpleview.collect, "fields": simpleview.FIELDS,
                       "agent": simpleview.USER_AGENT, "pause": simpleview.PAUSE, "tag": "simpleview-listings",
                       "prefix": "simpleview-listings", "title": "Tourism boards' Simpleview listings",
                       "notes": "Monthly listings of tourism boards' Simpleview sites (placepacks/directories/"
                                "simpleview.py), read by the pack build (source simpleview-listings). Not for "
                                "download."},
        "chambermaster": {"units": chambermaster.STATES, "collect": chambermaster.collect,
                          "fields": chambermaster.FIELDS, "agent": chambermaster.USER_AGENT,
                          "pause": chambermaster.PAUSE, "tag": "chambermaster-listings",
                          "prefix": "chambermaster-listings", "title": "Chambers' ChamberMaster directories",
                          "notes": "Monthly member listings of chambers of commerce on the older ChamberMaster "
                                   "platform (placepacks/directories/chambermaster.py), read by the pack build "
                                   "(source chambermaster-listings). Not for download."},
    }


def run(collection, unit, out, opener=None, sleep=time.sleep, clock=time.monotonic, today=None):
    """Collect one unit into out/ (see the module docstring). Returns its summary dict."""
    spec = collections()[collection]
    unit_spec = spec["units"][unit]
    os.makedirs(out, exist_ok=True)
    started = clock()
    client = Polite(unit_spec["budget"], spec["pause"], opener=opener, sleep=sleep, clock=clock,
                    deadline=started + 60 * max(5, unit_spec["timeout"] - MARGIN_MIN), agent=spec["agent"])
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


def matrix(collection, only=""):
    """[{"unit", "timeout"}] of the units to run (only: ids separated by spaces or commas; empty: all). An unknown
    id stops with an error that lists the known ones."""
    units = collections()[collection]["units"]
    wanted = [u for u in only.replace(",", " ").split() if u] or list(units)
    unknown = [u for u in wanted if u not in units]
    if unknown:
        raise SystemExit(f"unknown unit(s): {', '.join(unknown)}; known: {', '.join(units)}")
    return [{"unit": u, "timeout": units[u]["timeout"]} for u in wanted]


def publish(collection, folder, date, ran, sleep=time.sleep):
    """Publish the month's set of a collection in its release (placepacks/chains/release.py). Returns the list."""
    from placepacks.chains import release
    spec = collections()[collection]
    return release.publish(folder, date, ran, sleep=sleep, units=spec["units"], tag=spec["tag"],
                           prefix=spec["prefix"], title=spec["title"], notes=spec["notes"])


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("collection", choices=["simpleview", "chambermaster"])
    p.add_argument("--list", action="store_true")
    p.add_argument("--only", default="")
    p.add_argument("--unit", default="")
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
    if a.unit not in collections()[a.collection]["units"]:
        raise SystemExit(f"unknown unit {a.unit!r}")
    run(a.collection, a.unit, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
