"""The Yellow Pages lookup job: phone numbers, websites and opening hours for businesses already in the packs that
lack them (the source "yp-lookups"; the matching rules are in placepacks/directories/yellowpages.py).

It runs slowly in the background in the owner's cloud session (where yellowpages.com answers and the GitHub API
needs no token argument), never in GitHub Actions:

    python3 tools/yp_lookup.py run --forever      look businesses up, state by state (the most people first), at
                                                  most 25,000 requests a day, one every 3 to 4 seconds; uploads the
                                                  day's results at the end of each day and waits for the next one
    python3 tools/yp_lookup.py run                one day's run only (stops at the day's limit)
    python3 tools/yp_lookup.py status             where the job is (state, place, requests today, last upload)
    python3 tools/yp_lookup.py upload             merge the results not yet uploaded into the release now
    python3 tools/yp_lookup.py try --name "Muddy Waters" --town Burlington --state VT --street "184 Main St" \
        --lat 44.4758 --lon -73.2121              one lookup, printed (to check the parsing; nothing is saved)

What it reads: for each region (states in POPULATION order; a state made of sub-regions, such as California, by
its sub-regions), the newest published "businesses" and "addresses" packs (packs.json in the release "packs"),
downloaded into the work folder and deleted once the region's work list is made. The list holds the businesses
listed now that lack a phone or opening hours (one place per business when several sources list it; a business
another source already gives a phone and hours is left out), those without a phone first, and leaves out the
places looked up in the last RECHECK_DAYS days (the newest yp-lookups file says when).
Where it keeps its state: --progress (default /home/user/notes/yp-progress): progress.json (small: the region, the
place reached, the requests of the day, the last upload, and "blocked" with the reason when a site refused) and
pending.csv (the results not yet uploaded; emptied by each upload). The job can be stopped at any time and started
again with the same command: it goes on where it stopped.
What it writes: at the end of each day (and when it stops), the newest yp-lookups-<YYYYMMDD>.csv.gz of the release
"uploaded-sources" with the pending results merged in (placepacks/details.py merge: a new result wins, except that
"nothing found" never wipes out details found before) is uploaded as yp-lookups-<today>.csv.gz, and files older
than the newest KEEP are deleted. The pack build reads the newest file each month.
Stops: any refusal or anti-bot page (HTTP 403 or 429, a CAPTCHA, "Access Denied") stops the run at once (exit code
3, progress.json says "blocked"); the day's results are uploaded and the job does NOT start again by itself: a
person decides whether to run it again later. Nothing is ever got round: no CAPTCHA, no browser, no other
connection or address.
Only the Python standard library is used.
"""

import argparse
import csv
import datetime
import json
import os
import random
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, details  # noqa: E402
from placepacks.chains.polite import Blocked, BudgetSpent, Polite  # noqa: E402
from placepacks.directories import yellowpages as yp  # noqa: E402
from placepacks.directories.common import plain_name  # noqa: E402

PROGRESS = "/home/user/notes/yp-progress"
RELEASE = "uploaded-sources"
PREFIX = "yp-lookups"
KEEP = 2                        # yp-lookups files kept in the release
RECHECK_DAYS = 180              # a place looked up this recently is not looked up again
SAME_M = 100                    # two sources' places of one name this close are one business
# The states (and DC and Puerto Rico) by population, the most people first (2020 census).
POPULATION = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA", "TN", "IN",
              "MD", "MO", "WI", "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT", "IA", "NV", "AR", "MS",
              "KS", "NM", "NE", "ID", "WV", "HI", "NH", "ME", "RI", "MT", "DE", "SD", "ND", "AK", "DC", "VT", "WY",
              "PR"]
WORK_FIELDS = ["key", "name", "type", "brand", "lat", "lon", "town", "addresses", "need"]


def region_order(regions=None):
    """[(region id, state code)] in POPULATION order; a state with sub-regions gives its sub-regions."""
    regions = regions or catalogue.regions()
    by_code = {r.get("code"): r for r in regions.values() if r.get("cc") == "US" and not r.get("parent")}
    out = []
    for code in POPULATION:
        r = by_code.get(code)
        if r:
            out += [(c, code) for c in r.get("children") or [r["id"]]]
    return out


# ------------------------------------------------------------------------------------------------ the state

class Progress:
    """progress.json and pending.csv in the progress folder (see the module docstring)."""

    def __init__(self, folder):
        """Read the state (a fresh one when there is none)."""
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "progress.json")
        self.pending = os.path.join(folder, "pending.csv")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("regions", {})
        self.data.setdefault("day", "")
        self.data.setdefault("requests_today", 0)

    def save(self):
        """Write progress.json (through a .partial file)."""
        with open(self.path + ".partial", "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, sort_keys=True)
        os.replace(self.path + ".partial", self.path)

    def region(self, rid):
        """The region's state: {"status": "", "index": 0, "total": 0, "found": 0}."""
        return self.data["regions"].setdefault(rid, {"status": "", "index": 0, "total": 0, "found": 0})

    def add(self, row):
        """Keep one result in pending.csv."""
        new = not os.path.exists(self.pending)
        with open(self.pending, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=details.DETAIL_FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)

    def pending_rows(self):
        """{key: row} of pending.csv."""
        if not os.path.exists(self.pending):
            return {}
        with open(self.pending, newline="", encoding="utf-8") as f:
            return {r["key"]: r for r in csv.DictReader(f) if r.get("key")}


# ------------------------------------------------------------------------------------------------ the release

def newest_file(gh):
    """(release, the newest yp-lookups asset or None)."""
    rel = gh.ensure_release(RELEASE, "Uploaded sources", "Files the owner's tools upload for the pack build.")
    pattern = details.file_pattern(PREFIX)
    found = sorted((a for a in gh.assets(rel) if pattern.match(a["name"])), key=lambda a: a["name"], reverse=True)
    return rel, found


def upload(progress, gh, today=None, work=None):
    """Merge pending.csv into the newest yp-lookups file and upload it as yp-lookups-<today>.csv.gz; delete files
    older than the newest KEEP; empty pending.csv. Returns the number of rows in the new file (None: nothing to
    upload)."""
    pending = progress.pending_rows()
    if not pending:
        return None
    today = today or datetime.date.today()
    scratch = tempfile.mkdtemp(prefix="yp-upload-", dir=work)
    try:
        rel, files = newest_file(gh)
        old = gh.download(files[0], os.path.join(scratch, files[0]["name"])) if files else None
        merged = details.merge(details.read_rows(old), pending)
        name = f"{PREFIX}-{today:%Y%m%d}.csv.gz"
        path = os.path.join(scratch, "new-" + name)
        count = details.write_rows(path, merged)
        gh.upload(rel, path, name)
        for a in [f for f in files if f["name"] != name][KEEP - 1:]:
            gh.delete(a)
        os.remove(progress.pending)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        progress.data["last_upload"] = {"file": name, "rows": count, "added": len(pending), "at": now}
        progress.save()
        print(f"uploaded {name}: {count:,} rows ({len(pending):,} new or updated)", flush=True)
        return count
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def recently_checked(gh, work, today):
    """The keys looked up in the last RECHECK_DAYS days (from the newest yp-lookups file)."""
    _, files = newest_file(gh)
    if not files:
        return set()
    path = gh.download(files[0], os.path.join(work, files[0]["name"]))
    limit = (today - datetime.timedelta(days=RECHECK_DAYS)).isoformat()
    keys = {k for k, r in details.read_rows(path).items() if (r.get("checked") or "") >= limit}
    os.remove(path)
    return keys


# ------------------------------------------------------------------------------------------------ the work list

def work_list(records, skip=()):
    """The places to look up from a businesses pack's places (packs_input.places, each with "addresses" and "town"
    added): those that lack a phone or opening hours, one per business (the same plain name within SAME_M metres;
    a business another source already gives a phone and hours is left out), not in skip; those without a phone
    first. Returns rows of WORK_FIELDS."""
    from placepacks.fmt import metres
    groups = {}
    for r in records:
        groups.setdefault(plain_name(r["name"]), []).append(r)
    out = []
    for name, group in groups.items():
        if not name:
            continue
        done = [r for r in group if r["phone"] and r["opening_hours"]]
        taken = []
        for r in group:
            if r["key"] in skip or (r["phone"] and r["opening_hours"]):
                continue
            if any(metres(r["lat"], r["lon"], d["lat"], d["lon"]) <= SAME_M for d in done + taken):
                continue
            taken.append(r)
            out.append({"key": r["key"], "name": r["name"], "type": r["type"], "brand": r["brand"],
                        "lat": f"{r['lat']:.6f}", "lon": f"{r['lon']:.6f}", "town": r.get("town", ""),
                        "addresses": "|".join(r.get("addresses") or []), "need": "hours" if r["phone"] else "phone"})
    out.sort(key=lambda r: (r["need"] != "phone", r["key"]))
    return out


def make_work_list(rid, gh, work, manifest, skip):
    """Download the region's businesses and addresses packs, write <work>/<rid>.csv and delete the packs. Returns
    (the number of places, a note) or (None, why the region is passed over)."""
    from placepacks.directories import packs_input
    biz, addr = manifest.get((rid, "businesses")), manifest.get((rid, "addresses"))
    if not biz:
        return None, "no businesses pack yet"
    if not addr:
        return None, "no addresses pack yet (the town and the address check need it)"
    folder = tempfile.mkdtemp(prefix=f"yp-{rid}-", dir=work)
    try:
        biz_path = gh.download_pack(biz, folder)
        addresses = packs_input.Addresses(gh.download_pack(addr, folder))
        records = []
        for p in packs_input.places(biz_path):
            if p["phone"] and p["opening_hours"]:
                records.append(p)
                continue
            p["addresses"], p["town"] = addresses.near(p["lat"], p["lon"])
            records.append(p)
        rows = work_list(records, skip)
        target = os.path.join(work, f"{rid}.csv")
        with open(target + ".partial", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=WORK_FIELDS)
            w.writeheader()
            w.writerows(rows)
        os.replace(target + ".partial", target)
        return len(rows), f"{biz['name']}"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def read_work(path):
    """The rows of a work list, with lat and lon as numbers and the addresses as a list."""
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["lat"], r["lon"] = float(r["lat"]), float(r["lon"])
            r["addresses"] = [a for a in r["addresses"].split("|") if a]
            yield r


# ------------------------------------------------------------------------------------------------ the run

def until_tomorrow(now=None):
    """Seconds until the next UTC day (and a minute more)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    return max(60.0, (tomorrow - now).total_seconds())


def run(progress, gh, work, forever=False, day_limit=yp.DAY_LIMIT, opener=None, sleep=time.sleep,
        clock=time.monotonic, today=None, regions=None, jitter=random.uniform):
    """Look businesses up (see the module docstring). Returns the exit code: 0 done (or the day's limit reached
    without --forever), 3 blocked."""
    os.makedirs(work, exist_ok=True)
    manifest = gh.packs_of(work)
    state = progress.data
    state.pop("blocked", None)
    for reg in state["regions"].values():
        if reg.get("status") == "passed over":
            reg["status"] = ""              # its packs may be published now
    skip, client = None, None
    for rid, code in region_order(regions):
        reg = progress.region(rid)
        if reg["status"] in ("done", "passed over"):
            continue
        path = os.path.join(work, f"{rid}.csv")
        if not os.path.exists(path):
            if skip is None:
                skip = recently_checked(gh, work, today or datetime.date.today())
            count, note = make_work_list(rid, gh, work, manifest, skip)
            if count is None:
                reg.update(status="passed over", note=note)
                progress.save()
                print(f"{rid}: passed over ({note})", flush=True)
                continue
            reg.update(status="working", total=count, note=note, index=min(reg.get("index", 0), count))
            progress.save()
            print(f"{rid}: {count:,} places to look up ({note})", flush=True)
        for i, record in enumerate(read_work(path)):
            if i < reg["index"]:
                continue
            while True:                           # the same place again after a wait for the next day
                day = (today or datetime.date.today()).isoformat()
                if state["day"] != day:
                    if state["day"]:
                        upload(progress, gh, today=today, work=work)
                    state.update(day=day, requests_today=0, details_today=0, searches_today=0)
                    client = None
                if state["requests_today"] >= day_limit:
                    upload(progress, gh, today=today, work=work)
                    progress.save()
                    if not forever:
                        print(f"the day's limit of {day_limit:,} requests is reached; run again tomorrow", flush=True)
                        return 0
                    wait = until_tomorrow()
                    print(f"the day's limit is reached; waiting {wait / 3600:.1f} hours", flush=True)
                    sleep(wait)
                    continue
                if client is None:
                    # One client a day: its budget is what is left of the day's requests; it keeps the pause.
                    client = Polite(day_limit - state["requests_today"], yp.PAUSE, opener=opener, sleep=sleep,
                                    clock=clock, waits=(30, 120))
                used = client.used
                sleep(jitter(0, 1.0))                   # one request every 3 to 4 seconds
                allow = state.get("details_today", 0) < yp.DETAIL_SHARE * max(1, state.get("searches_today", 0))
                try:
                    row, extra = yp.lookup(client, record, code, allow_detail=allow, today=today)
                except Blocked as e:
                    state["blocked"] = {"reason": str(e), "region": rid, "at": datetime.datetime.now(
                        datetime.timezone.utc).isoformat(timespec="seconds")}
                    state["requests_today"] += client.used - used
                    progress.save()
                    print(f"BLOCKED: {e}. The run stops here and does not start again by itself.", flush=True)
                    upload(progress, gh, today=today, work=work)
                    return 3
                except BudgetSpent:
                    state["requests_today"] = day_limit
                    continue                        # the day's limit: upload, then stop or wait
                state["requests_today"] += client.used - used
                state["searches_today"] = state.get("searches_today", 0) + (client.used - used - extra)
                state["details_today"] = state.get("details_today", 0) + extra
                progress.add(row)
                reg["index"] = i + 1
                if row["phone"] or row["website"] or row["opening_hours"]:
                    reg["found"] = reg.get("found", 0) + 1
                if reg["index"] % 25 == 0:
                    progress.save()
                break
        reg["status"] = "done"
        progress.save()
        os.remove(path)
        print(f"{rid}: done ({reg.get('found', 0):,} of {reg.get('total', 0):,} found)", flush=True)
    upload(progress, gh, today=today, work=work)
    progress.save()
    print("every region is done", flush=True)
    return 0


def main(argv=None):
    """The command line (see the module docstring)."""
    from placepacks.directories.github import GitHub
    p = argparse.ArgumentParser(description="Yellow Pages lookups for businesses already in the packs.")
    p.add_argument("action", choices=["run", "status", "upload", "try"])
    p.add_argument("--forever", action="store_true", help="go on day after day until every region is done")
    p.add_argument("--progress", default=PROGRESS)
    p.add_argument("--work", default=os.environ.get("YP_WORK") or os.path.join(tempfile.gettempdir(), "yp-work"),
                   help="where the packs and the work lists are kept for a while (large; not the progress folder)")
    p.add_argument("--restart", action="store_true", help="start a new round of every region")
    p.add_argument("--day-limit", type=int, default=yp.DAY_LIMIT)
    for name in ("name", "town", "state", "street", "lat", "lon", "type"):
        p.add_argument(f"--{name}", default="")
    a = p.parse_args(argv)
    if a.action == "try":
        record = {"key": "try", "name": a.name, "type": a.type, "brand": "", "lat": float(a.lat or 0),
                  "lon": float(a.lon or 0), "town": a.town, "addresses": [a.street] if a.street else []}
        client = Polite(3, yp.PAUSE)
        row, extra = yp.lookup(client, record, a.state)
        print(json.dumps(row, indent=1))
        return 0
    progress = Progress(a.progress)
    if a.action == "status":
        print(json.dumps(progress.data, indent=1, sort_keys=True))
        return 0
    gh = GitHub()
    if a.action == "upload":
        upload(progress, gh, work=a.work if os.path.isdir(a.work) else None)
        return 0
    if a.restart:
        progress.data["regions"] = {}
        progress.save()
    return run(progress, gh, a.work, forever=a.forever, day_limit=a.day_limit)


if __name__ == "__main__":
    sys.exit(main())
