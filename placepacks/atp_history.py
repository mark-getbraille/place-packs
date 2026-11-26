"""The All The Places history seed (the workflow's "seed_chain_history"): first and last months for every chain store
from All The Places' archived past runs, one run a quarter since the archive starts (April 2018: the runs of 2017
are listed but their files are no longer kept).

All The Places (alltheplaces.xyz, CC0) runs every week and keeps every past run. A run is one archive of one GeoJSON
file per spider (a .tar.gz until November 2022, a .zip since): 35 MB in 2018, 2.7 GB in 2026, about 16 GB for one
run a quarter. Downloading them every month would be far too slow, so this is done once, in steps that each fit in
one GitHub job, and the small result is kept in the "seeds" release; every monthly build then reads that result.

    python -m placepacks.atp_history plan [--out groups.json]
        reads the archive's list of runs (runs/history.json, one request), picks the largest (most complete) run of
        each quarter, and puts them, oldest first, in groups of at most about 5 GB of downloads (one job each).
    python -m placepacks.atp_history read --runs "RUN RUN ..." --out state-1.sqlite [--scratch DIR]
        downloads the runs of one group, ONE AT A TIME (each archive is deleted as soon as it is read), keeps the
        locations inside the covered regions' boxes, and records each store's first and last month (a "state").
    python -m placepacks.atp_history combine state-1.sqlite state-2.sqlite ... --out-dir seed-out
        puts the groups' states together, oldest first, and writes the finished seed: chain-history-<fp>-NN.csv.gz
        (at most CHUNK_ROWS rows each, so each file stays well under GitHub's 2 GB limit for a release asset) and
        chain-history.json (which files, which runs and months).
    apply(csv_path, seed_dir)            (fetch.prepare_national calls it for the "atp" converter)
        merges the seed into the latest run's CSV: a store still listed gets its first month from the seed; a store
        no longer listed comes back as a closed row (its last month is the last quarter it was seen). The pack
        writer's usual history merge does the rest, so applying the same seed every month changes nothing twice.

How a store is followed from run to run (README "History"):
  - its key is the spider's name and the chain's own reference for the store ("made_up_burgers:1234", the same key
    the monthly build uses, fetch.iter_atp), and one record is kept per key and name, from the first run it was
    seen in to the last: a store renamed in 2021 has two records, the old name closed at its last quarter;
  - a store missing from one quarter but back later (a spider that failed for a while) simply continues;
  - when a key is new but a store with the same name or brand, within about 100 m (positions rounded to 3
    decimals), disappeared at the same time, the key is taken to have changed (a spider renamed, a chain's locator
    renumbered) and the old record carries on under the new key. This is the fallback for runs whose references do
    not match: it needs the name or the brand, so a renamed spider whose stores also changed names is not followed;
  - a location the old runs list without a name (common in 2018) still counts for its key's first and last month
    once the same key has a name in another run;
  - an individual's office (an insurance agent: fetch.ATP_PERSONAL) is left out, and so is every location of a
    spider that has ever listed one, since the oldest runs do not tag them.
"""

import argparse
import csv
import datetime
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

from placepacks import catalogue, fmt

SOURCE = "alltheplaces"
CHUNK_ROWS = 8_000_000          # rows per seed file (about 400 MB compressed)
MANIFEST = "chain-history.json"
ALLOWED_HOSTS = ("https://alltheplaces-data.openaddresses.io/", "https://data.alltheplaces.xyz/")
RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")

# One state (a group's runs, or the finished seed before it is written out). rec: one row per key and name;
# nh: a hash of the name in lower case (the same name in other capitals is the same record); fkn and fkb: hashes
# of the name and of the brand with the position rounded to 3 decimals (the fallback match, 0 when there is none);
# lat and lon in microdegrees; first and last as YYYYMM.
SCHEMA = """
CREATE TABLE IF NOT EXISTS rec (key TEXT, nh INTEGER, name TEXT, brand TEXT, wd TEXT, mv TEXT, type TEXT,
                                lat INTEGER, lon INTEGER, first INTEGER, last INTEGER, fkn INTEGER, fkb INTEGER);
CREATE TABLE IF NOT EXISTS nameless (key TEXT PRIMARY KEY, first INTEGER, last INTEGER) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS personal (spider TEXT PRIMARY KEY) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS runs (month INTEGER, run TEXT PRIMARY KEY) WITHOUT ROWID;
"""
INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS rec_key ON rec (key, nh);
CREATE INDEX IF NOT EXISTS rec_fkn ON rec (fkn) WHERE fkn != 0;
CREATE INDEX IF NOT EXISTS rec_fkb ON rec (fkb) WHERE fkb != 0;
"""
COLUMNS = "key, nh, name, brand, wd, mv, type, lat, lon, first, last, fkn, fkb"


# ------------------------------------------------------------------------------------------------- small helpers

def hash64(text):
    """A signed 64-bit hash of a text (stored as an SQLite integer, much smaller than the text). 0 for no text."""
    if not text:
        return 0
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big", signed=True) or 1


def name_hash(name):
    """The hash that says two names are the same: the name in lower case, spaces trimmed."""
    return hash64((name or "").strip().casefold())


def place_hash(label, lat, lon):
    """The fallback match's hash: the name or brand with only its letters and digits, and the position rounded to
    3 decimals (about 100 m). 0 when there is no label."""
    label = re.sub(r"[\W_]+", "", (label or "").casefold())
    return hash64(f"{label}@{round(lat, 3):.3f},{round(lon, 3):.3f}") if label else 0


def month_of_run(run_id):
    """The month of a run, YYYYMM, from its id ("2026-10-03-13-32-35" -> 202610)."""
    return int(run_id[:4]) * 100 + int(run_id[5:7])


def covered_boxes(cat=None):
    """The boxes ([(west, south, east, north)]) of every region All The Places covers: the same boxes the monthly
    conversion keeps (fetch.prepare_national, convert "atp")."""
    from placepacks.regions import boxes_of
    cat = cat or catalogue.load()
    entry = next(e for e in cat["accepted"] if e["id"] == SOURCE)
    return [b for r in catalogue.regions().values()
            if catalogue.country_code(r) in entry["countries"] and not r.get("parent") for b in boxes_of(r)]


def seed_settings(cat=None):
    """The seed's settings: the alltheplaces entry's "history_seed" (history: the list of runs; from_year;
    group_bytes: how many bytes of archives one job downloads at most)."""
    cat = cat or catalogue.load()
    entry = next(e for e in cat["accepted"] if e["id"] == SOURCE)
    return {"history": "https://data.alltheplaces.xyz/runs/history.json", "from_year": 2017,
            "group_bytes": 5_000_000_000, **entry.get("history_seed", {})}


def fingerprint(runs, cat=None):
    """12 hexadecimal digits naming one seed: its runs, the covered boxes and the format of the rows."""
    data = {"runs": list(runs), "boxes": covered_boxes(cat), "format": 1}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------------------------------------- plan

def load_history(url=None, opener=None):
    """The archive's list of runs ([{"run_id", "output_url", "size_bytes", ...}]), read with one request."""
    from placepacks import fetch
    url = url or seed_settings()["history"]
    with (opener or fetch.request)(url) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_quarterly(history, from_year=2017, today=None):
    """One run per quarter, oldest first: of the runs of each quarter that have a downloadable archive, the largest
    (a run that stopped early, or whose spiders failed, is smaller). Runs before from_year are left out."""
    today = today or datetime.date.today()
    best = {}
    for run in history:
        rid, url = str(run.get("run_id", "")), str(run.get("output_url") or "")
        if not RUN_ID.match(rid) or not url.startswith(ALLOWED_HOSTS):
            continue
        year, month = int(rid[:4]), int(rid[5:7])
        if year < from_year or year * 100 + month > today.year * 100 + today.month:
            continue
        quarter = (year, (month - 1) // 3)
        size = int(run.get("size_bytes") or 0)
        if quarter not in best or size > best[quarter][0]:
            best[quarter] = (size, rid, url)
    return [{"run_id": rid, "url": url, "bytes": size} for _, (size, rid, url) in sorted(best.items())]


def groups(runs, limit):
    """The runs (oldest first) cut into consecutive groups of at most limit bytes of archives (a run larger than
    limit is a group of its own). [{"group": 1, "runs": "RUN RUN", "bytes": N}]."""
    out, current, size = [], [], 0
    for run in runs:
        if current and size + run["bytes"] > limit:
            out.append(current)
            current, size = [], 0
        current.append(run)
        size += run["bytes"]
    if current:
        out.append(current)
    return [{"group": i + 1, "runs": " ".join(r["run_id"] for r in g), "bytes": sum(r["bytes"] for r in g)}
            for i, g in enumerate(out)]


# ------------------------------------------------------------------------------------------------- the states

def open_state(path):
    """Open (or make) a state file, with its tables and indexes."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode = OFF")
    con.execute("PRAGMA synchronous = OFF")
    con.execute("PRAGMA temp_store = FILE")
    con.execute("PRAGMA cache_size = -1000000")     # about 1 GB of page cache
    con.executescript(SCHEMA + INDEXES)
    return con


def run_to_batch(archive, month, run_id, path, boxes):
    """Read one run's archive (fetch.iter_atp) into a new state file at path: one record per key and name (first
    = last = the run's month), the keys listed without a name, and the spiders that list individuals' offices.
    Returns the number of records."""
    from placepacks import fetch
    con = open_state(path)
    nameless, personal, count = set(), set(), 0

    def rows():
        """The records to insert, while the nameless keys and the personal spiders are collected on the side."""
        for row in fetch.iter_atp(archive, boxes):
            if row["skip"] == "personal":
                personal.add(row["spider"])
                continue
            if row["skip"] == "noname":
                nameless.add(row["key"])
                continue
            lat, lon = float(row["lat"]), float(row["lon"])
            yield (row["key"], name_hash(row["name"]), row["name"], row["brand"], row["brand_wikidata"],
                   row["main_value"], row["type"], round(lat * fmt.SCALE), round(lon * fmt.SCALE), month, month,
                   place_hash(row["name"], lat, lon), place_hash(row["brand"], lat, lon))

    before = con.total_changes
    # The same key and name twice in one run: the first is kept (INSERT OR IGNORE on the unique index).
    con.executemany(f"INSERT OR IGNORE INTO rec ({COLUMNS}) VALUES ({', '.join('?' * 13)})", rows())
    count = con.total_changes - before
    con.executemany("INSERT OR IGNORE INTO nameless VALUES (?, ?, ?)", ((k, month, month) for k in nameless))
    con.executemany("INSERT OR IGNORE INTO personal VALUES (?)", ((s,) for s in personal if s))
    con.execute("INSERT OR REPLACE INTO runs VALUES (?, ?)", (month, run_id))
    con.commit()
    con.close()
    return count


def merge(con, batch_path):
    """Merge a later state (batch_path: a run's, or a later group's) into the state con. Every month of the batch
    must be later than the state's (merges go oldest first). See the module docstring for the rules. Returns the
    number of keys that were found to have changed (the fallback match)."""
    con.execute("ATTACH DATABASE ? AS b", (batch_path,))
    try:
        start = con.execute("SELECT MIN(first) FROM b.rec").fetchone()[0]
        if start is None:
            start = con.execute("SELECT MIN(month) FROM b.runs").fetchone()[0] or 0
        con.execute("CREATE INDEX IF NOT EXISTS b.rec_key ON rec (key, nh)")
        # 1. Keys that changed: a batch key the state has never seen, and a state key absent from the batch whose
        #    store, with the same name or brand at the same rounded position, was last seen before the batch.
        con.executescript("""
            DROP TABLE IF EXISTS temp.newkeys; DROP TABLE IF EXISTS temp.cand; DROP TABLE IF EXISTS temp.alias;
            CREATE TEMP TABLE newkeys AS SELECT DISTINCT key, fkn, fkb FROM b.rec
                WHERE key NOT IN (SELECT key FROM main.rec);
            CREATE TEMP TABLE cand (new TEXT, old TEXT);
        """)
        for mine in ("fkn", "fkb"):
            for theirs in ("fkn", "fkb"):
                con.execute(f"INSERT INTO cand SELECT n.key, r.key FROM newkeys n JOIN main.rec r "
                            f"ON r.{theirs} = n.{mine} WHERE n.{mine} != 0 AND r.last < ? "
                            f"AND r.key NOT IN (SELECT key FROM b.rec)", (start,))
        # Only a match with no doubt: one old key for the new key and one new key for the old.
        con.executescript("""
            CREATE TEMP TABLE alias AS SELECT DISTINCT new, old FROM cand
                WHERE new IN (SELECT new FROM cand GROUP BY new HAVING COUNT(DISTINCT old) = 1)
                  AND old IN (SELECT old FROM cand GROUP BY old HAVING COUNT(DISTINCT new) = 1);
            CREATE INDEX temp.alias_old ON alias (old);
            UPDATE main.rec SET key = (SELECT new FROM temp.alias WHERE old = main.rec.key)
                WHERE key IN (SELECT old FROM temp.alias);
            INSERT OR IGNORE INTO main.nameless SELECT a.new, n.first, n.last FROM main.nameless n
                JOIN temp.alias a ON a.old = n.key;
            DELETE FROM main.nameless WHERE key IN (SELECT old FROM temp.alias);
        """)
        aliased = con.execute("SELECT COUNT(*) FROM temp.alias").fetchone()[0]
        con.executescript("DROP TABLE temp.newkeys; DROP TABLE temp.cand; DROP TABLE temp.alias;")
        # 2. The same key and name: the record continues (its first month stays, its last month moves on, and the
        #    newer run's position, brand and tags are kept where it has them).
        con.execute("""
            UPDATE main.rec SET first = MIN(main.rec.first, x.first), last = MAX(main.rec.last, x.last),
                name = CASE WHEN x.last >= main.rec.last THEN x.name ELSE main.rec.name END,
                lat = CASE WHEN x.last >= main.rec.last THEN x.lat ELSE main.rec.lat END,
                lon = CASE WHEN x.last >= main.rec.last THEN x.lon ELSE main.rec.lon END,
                brand = COALESCE(NULLIF(x.brand, ''), main.rec.brand), wd = COALESCE(NULLIF(x.wd, ''), main.rec.wd),
                mv = COALESCE(NULLIF(x.mv, ''), main.rec.mv), type = COALESCE(NULLIF(x.type, ''), main.rec.type),
                fkn = CASE WHEN x.last >= main.rec.last THEN x.fkn ELSE main.rec.fkn END,
                fkb = CASE WHEN x.fkb != 0 THEN x.fkb ELSE main.rec.fkb END
            FROM b.rec x WHERE x.key = main.rec.key AND x.nh = main.rec.nh
        """)
        # 3. New keys and new names: new records.
        con.execute(f"INSERT INTO main.rec ({COLUMNS}) SELECT {COLUMNS} FROM b.rec x WHERE NOT EXISTS "
                    "(SELECT 1 FROM main.rec r WHERE r.key = x.key AND r.nh = x.nh)")
        con.executescript("""
            INSERT INTO main.nameless SELECT key, first, last FROM b.nameless WHERE true
                ON CONFLICT (key) DO UPDATE SET first = MIN(first, excluded.first), last = MAX(last, excluded.last);
            INSERT OR IGNORE INTO main.personal SELECT spider FROM b.personal;
            INSERT OR REPLACE INTO main.runs SELECT month, run FROM b.runs;
        """)
        con.commit()
    finally:
        con.execute("DETACH DATABASE b")
    return aliased


def finish(con):
    """The last touches before the seed is written: a key's nameless sightings widen its earliest and latest
    records, and every location of a spider that lists individuals' offices is left out."""
    con.executescript("""
        CREATE INDEX IF NOT EXISTS rec_key_only ON rec (key);
        UPDATE rec SET first = (SELECT n.first FROM nameless n WHERE n.key = rec.key)
            WHERE key IN (SELECT key FROM nameless)
              AND first = (SELECT MIN(r.first) FROM rec r WHERE r.key = rec.key)
              AND (SELECT n.first FROM nameless n WHERE n.key = rec.key) < first;
        UPDATE rec SET last = (SELECT n.last FROM nameless n WHERE n.key = rec.key)
            WHERE key IN (SELECT key FROM nameless)
              AND last = (SELECT MAX(r.last) FROM rec r WHERE r.key = rec.key)
              AND (SELECT n.last FROM nameless n WHERE n.key = rec.key) > last;
    """)
    con.create_function("spider_of", 1, lambda key: (key or "").split(":", 1)[0], deterministic=True)
    con.execute("DELETE FROM rec WHERE spider_of(key) IN (SELECT spider FROM personal)")
    con.commit()


def write_seed(con, out_dir, cat=None):
    """Write the finished seed to out_dir: chain-history-<fp>-NN.csv.gz (the columns of the monthly CSV,
    fetch.ATP_FIELDS, with first and last filled) and chain-history.json. Returns the manifest."""
    from placepacks.fetch import ATP_FIELDS
    os.makedirs(out_dir, exist_ok=True)
    runs = [r for _, r in con.execute("SELECT month, run FROM runs ORDER BY month")]
    months = [m for m, in con.execute("SELECT month FROM runs ORDER BY month")]
    fp = fingerprint(runs, cat)
    files, f, w, count, total = [], None, None, 0, 0
    try:
        for key, name, brand, wd, mv, kind, lat, lon, first, last in con.execute(
                "SELECT key, name, brand, wd, mv, type, lat, lon, first, last FROM rec ORDER BY key, first"):
            if w is None or count >= CHUNK_ROWS:
                if f:
                    f.close()
                files.append(f"chain-history-{fp}-{len(files) + 1:02d}.csv.gz")
                f = gzip.open(os.path.join(out_dir, files[-1]), "wt", newline="", encoding="utf-8", compresslevel=6)
                w = csv.writer(f)
                w.writerow(ATP_FIELDS)
                count = 0
            w.writerow([key, key.split(":", 1)[0], name, "", brand or "", wd or "", "", mv or "", kind or "",
                        f"{lat / fmt.SCALE:.6f}", f"{lon / fmt.SCALE:.6f}", first, last])
            count += 1
            total += 1
    finally:
        if f:
            f.close()
    manifest = {"fingerprint": fp, "files": files, "rows": total, "runs": runs, "months": months,
                "made": datetime.date.today().isoformat()}
    with open(os.path.join(out_dir, MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


# ------------------------------------------------------------------------------------------------ the commands

def read_runs(run_ids, out, scratch=None, history=None, boxes=None, download=None):
    """Download and read the runs of one group, oldest first, ONE AT A TIME, into the state file out: each archive
    is deleted as soon as it is read, so the disk holds one archive (2.7 GB at most) and the state at a time.
    history: the archive's list of runs (read once when not given). download(url, target): fetch.download."""
    from placepacks import fetch
    history = history if history is not None else load_history()
    urls = {str(r.get("run_id")): str(r.get("output_url") or "") for r in history}
    boxes = boxes or covered_boxes()
    download = download or (lambda url, target: fetch.download(url, target, pause=2))
    work = tempfile.mkdtemp(prefix="atp-history-", dir=scratch or os.environ.get("PLACEPACKS_SCRATCH") or None)
    con = open_state(out)
    try:
        for rid in run_ids:
            url = urls.get(rid, "")
            if not RUN_ID.match(rid) or not url.startswith(ALLOWED_HOSTS):
                raise SystemExit(f"{rid}: not a run of the All The Places archive")
            archive = os.path.join(work, "run" + (".zip" if url.endswith(".zip") else ".tar.gz"))
            batch = os.path.join(work, "batch.sqlite")
            print(f"{rid}: downloading {url}", flush=True)
            download(url, archive)
            size = os.path.getsize(archive)
            count = run_to_batch(archive, month_of_run(rid), rid, batch, boxes)
            os.remove(archive)                          # one archive on the disk at a time
            merge(con, batch)
            os.remove(batch)
            total = con.execute("SELECT COUNT(*) FROM rec").fetchone()[0]
            print(f"{rid}: {size:,} bytes, {count:,} locations in the covered regions, {total:,} records so far",
                  flush=True)
    finally:
        con.close()
        shutil.rmtree(work, ignore_errors=True)


def combine(states, out_dir, scratch=None, cat=None):
    """Put the groups' states together (in the order given: oldest first) and write the finished seed."""
    work = tempfile.mkdtemp(prefix="atp-history-", dir=scratch or os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        path = os.path.join(work, "seed.sqlite")
        con = open_state(path)
        for state in states:
            merge(con, state)
            print(f"{os.path.basename(state)}: {con.execute('SELECT COUNT(*) FROM rec').fetchone()[0]:,} records",
                  flush=True)
        finish(con)
        manifest = write_seed(con, out_dir, cat)
        con.close()
        print(f"The seed: {manifest['rows']:,} records from {len(manifest['runs'])} runs in "
              f"{len(manifest['files'])} files", flush=True)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def apply(csv_path, seed_dir, scratch=None):
    """Merge the seed in seed_dir (chain-history.json and its files) into the latest run's CSV at csv_path (written
    by fetch.atp_to_csv), in place. Returns (stores given an earlier first month, closed stores added), or None
    when there is no seed. Rows are matched by key and name in lower case, like the seed's own records."""
    manifest_path = os.path.join(seed_dir or "", MANIFEST)
    if not seed_dir or not os.path.exists(manifest_path):
        return None
    from placepacks.fetch import ATP_FIELDS
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    files = [os.path.join(seed_dir, os.path.basename(n)) for n in manifest.get("files", [])]
    if not files or not all(os.path.exists(p) for p in files):
        raise ValueError("the chain history seed is incomplete (a file listed in chain-history.json is missing)")
    work = tempfile.mkdtemp(prefix="atp-apply-", dir=scratch or os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        con = sqlite3.connect(os.path.join(work, "apply.sqlite"))
        con.execute("PRAGMA journal_mode = OFF")
        con.execute("PRAGMA synchronous = OFF")
        cols = ", ".join(ATP_FIELDS)
        marks = ", ".join("?" * (len(ATP_FIELDS) + 1))
        con.execute(f"CREATE TABLE s ({cols}, nh INTEGER)")
        con.execute(f"CREATE TABLE c ({cols}, nh INTEGER)")
        for path in files:
            with gzip.open(path, "rt", newline="", encoding="utf-8") as fh:
                con.executemany(f"INSERT INTO s VALUES ({marks})",
                                ([*(r.get(c, "") for c in ATP_FIELDS), name_hash(r["name"])]
                                 for r in csv.DictReader(fh)))
        with open(csv_path, newline="", encoding="utf-8") as fh:
            con.executemany(f"INSERT INTO c VALUES ({marks})",
                            ([*(r.get(c, "") for c in ATP_FIELDS), name_hash(r["name"])] for r in csv.DictReader(fh)))
        con.execute("CREATE INDEX s_key ON s (key, nh)")
        con.execute("CREATE INDEX c_key ON c (key, nh)")
        out = csv_path + ".seeded"
        earlier = closed = 0
        with open(out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(ATP_FIELDS)
            # The stores listed now: the seed's first month (the last stays empty: still open).
            picks = ", ".join(f"c.{c}" for c in ATP_FIELDS if c not in ("first", "last"))
            for row in con.execute(f"SELECT {picks}, (SELECT MIN(s.first) FROM s WHERE s.key = c.key AND "
                                   "s.nh = c.nh), c.last FROM c ORDER BY c.rowid"):
                earlier += bool(row[-2])
                w.writerow(["" if v is None else v for v in row])
            # The stores no longer listed (or listed under another name now): closed at their last quarter.
            for row in con.execute(f"SELECT {cols} FROM s WHERE NOT EXISTS (SELECT 1 FROM c WHERE c.key = s.key "
                                   "AND c.nh = s.nh) ORDER BY s.rowid"):
                closed += 1
                w.writerow(row)
        con.close()
        os.replace(out, csv_path)
        return earlier, closed
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser(description="The All The Places history seed.")
    sub = p.add_subparsers(dest="command", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--out", default="")
    rd = sub.add_parser("read")
    rd.add_argument("--runs", required=True, help="run ids separated by spaces, oldest first")
    rd.add_argument("--out", required=True)
    rd.add_argument("--scratch", default="")
    cb = sub.add_parser("combine")
    cb.add_argument("states", nargs="+")
    cb.add_argument("--out-dir", required=True)
    cb.add_argument("--scratch", default="")
    a = p.parse_args(argv)
    if a.command == "plan":
        settings = seed_settings()
        runs = pick_quarterly(load_history(settings["history"]), int(settings["from_year"]))
        plan = groups(runs, int(settings["group_bytes"]))
        text = json.dumps(plan, separators=(",", ":"))
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                fh.write(text)
        print(f"{len(runs)} runs ({sum(r['bytes'] for r in runs) / 1e9:.1f} GB) in {len(plan)} groups", file=sys.stderr)
        print(text)
        return 0
    if a.command == "read":
        read_runs(a.runs.split(), a.out, a.scratch or None)
        return 0
    # The states in their group order (state-2 before state-10).
    states = sorted(a.states, key=lambda s: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)])
    combine(states, a.out_dir, a.scratch or None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
