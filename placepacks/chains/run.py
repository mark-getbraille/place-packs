"""Run one chain's collector (the workflow's matrix job), or list the chains for the matrix.

    python -m placepacks.chains.run --list [--only "avis budget"]      the matrix: [{"chain", "timeout"}]
    python -m placepacks.chains.run --chain avis --out out/            out/avis.csv.gz and out/avis.json

The summary (out/<chain>.json) says how it went:
  ok          every page or search was read: the CSV is the chain's whole set of US stores
  blocked     the chain's site refused us (403, 429, a challenge page): stopped at once, never worked round
  incomplete  the request budget or the time limit ran out first
  failed      anything else (the site changed, a page kept failing)
Only an "ok" run writes a CSV. For every other result the release job keeps the chain's stores from the previous
set (placepacks/chains/release.py), so a bad month never closes stores in the packs' history.
The run itself always ends with exit code 0 (the summary carries the result), so one chain never stops the others.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import sys
import time

from placepacks import chains
from placepacks.chains.base import FIELDS
from placepacks.chains.polite import Blocked, BudgetSpent, Polite

MARGIN_MIN = 10        # minutes kept free before the job's time limit, to write the files


def run(chain, out, opener=None, sleep=time.sleep, clock=time.monotonic, today=None):
    """Collect one chain into out/ (see the module docstring). Returns its summary dict."""
    spec = chains.CHAINS[chain]
    os.makedirs(out, exist_ok=True)
    started = clock()
    client = Polite(spec["budget"], spec["pause"], opener=opener, sleep=sleep, clock=clock,
                    deadline=started + 60 * max(5, spec["timeout_min"] - MARGIN_MIN))
    stats, rows, status, reason = {}, [], "ok", ""
    try:
        for row in spec["collect"](client, stats):
            rows.append(row)
    except Blocked as e:
        status, reason = "blocked", str(e)
    except BudgetSpent as e:
        status, reason = "incomplete", str(e)
    except Exception as e:  # noqa: BLE001 - recorded in the summary; the previous set is kept
        status, reason = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    if status == "ok" and not rows:
        status, reason = "failed", "no stores were found (has the site changed?)"
    summary = {"chain": chain, "title": spec["title"], "status": status, "reason": reason, "rows": len(rows),
               "expected": spec["expected"], "endpoint": spec["endpoint"], "requests": client.used,
               "hosts": sorted(client.hosts), "seconds": round(clock() - started, 1),
               "date": (today or datetime.date.today()).isoformat(), "stats": stats}
    target = os.path.join(out, f"{chain}.csv.gz")
    if status == "ok":
        rows.sort(key=lambda r: r["key"])
        with gzip.open(target + ".partial", "wt", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        os.replace(target + ".partial", target)
    elif os.path.exists(target):
        os.remove(target)
    with open(os.path.join(out, f"{chain}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"{chain}: {status} ({len(rows):,} stores, {client.used} requests"
          f"{', ' + reason if reason else ''})", flush=True)
    return summary


def matrix(only=""):
    """[{"chain", "timeout"}] of the chains to run (only: ids separated by spaces or commas; empty: all). An unknown
    id stops with an error that lists the known ones."""
    wanted = [c for c in only.replace(",", " ").split() if c] or list(chains.CHAINS)
    unknown = [c for c in wanted if c not in chains.CHAINS]
    if unknown:
        raise SystemExit(f"unknown chain(s): {', '.join(unknown)}; known: {', '.join(chains.CHAINS)}")
    return [{"chain": c, "timeout": chains.CHAINS[c]["timeout_min"]} for c in wanted]


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--only", default="")
    p.add_argument("--chain", default="")
    p.add_argument("--out", default="chain-out")
    a = p.parse_args(argv)
    if a.list:
        print(json.dumps(matrix(a.only), separators=(",", ":")))
        return 0
    if a.chain not in chains.CHAINS:
        raise SystemExit(f"unknown chain {a.chain!r}; known: {', '.join(chains.CHAINS)}")
    run(a.chain, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
