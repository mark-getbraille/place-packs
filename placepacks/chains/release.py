"""The monthly set of chain stores in this repository's release "chain-locators", and the pack build's reading of it
(the source "chain-locators", fetch method "release_csv").

Publishing (the chain-locators workflow's last job, the only one with write access):

    python -m placepacks.chains.release publish --dir results/ --date 2026-11-28 --chains "burger-king avis ..."

results/ holds what each chain's job left: <chain>.json (its summary, placepacks/chains/run.py) and, for a
complete run, <chain>.csv.gz. For every chain the set gets one file, "chain-locators-<date>-<chain>.csv.gz":
  - this run's file, when the run was "ok" and found at least half as many stores as the previous set had
    (fewer looks like a broken site, not half the chain closing);
  - otherwise the previous set's file, carried over unchanged (at most MAX_CARRY sets running), so a chain that
    fails or is blocked one month keeps its stores open in the packs' history instead of closing them all;
  - a chain that was not run this time (a hand-started run of some chains) is kept from the previous set too.
The files go up first and the list, "chain-locators-<date>.json", last: a set counts only once its list is there.
Sets older than the newest KEEP are deleted. A table of the run goes to the job summary.

Reading (the pack build's prepare job): newest() finds the newest set with a list; prepare() downloads its files
(checked by SHA-256) into one national/chain-locators/chain-locators.csv, which placepacks.split cuts per region
like All The Places. No set yet: the source is skipped, "waiting for the first chain-locators set", and the build
goes on.
The same set-and-carry pattern serves the local directories (placepacks/directories: the tourism boards' Simpleview
listings and the chambers' ChamberMaster directories): publish() takes the release, the file prefix and the list
of units (sites or states in place of chains), and the reading takes the prefix from the catalogue entry's fetch
settings ("prefix", default "chain-locators").
gh is run through placepacks.uploaded.run_gh (tests replace it), with the job's own token.
"""

import argparse
import csv
import datetime
import gzip
import json
import os
import re
import shutil
import sys
import tempfile
import time

from placepacks import uploaded

TAG = "chain-locators"
PREFIX = "chain-locators"
KEEP = 2                 # sets kept in the release
MAX_CARRY = 3            # sets in a row a chain's old file may be carried over
TOO_FEW = 0.5            # a run with fewer than this share of the previous set's stores is not used
WAITING = "waiting for the first chain-locators set (the chain-locators workflow has not published one yet)"


def _list_re(prefix):
    """The pattern of a set's list name, "<prefix>-<date>.json" (group 1: the date)."""
    return re.compile(rf"^{re.escape(prefix)}-(\d{{4}}-\d{{2}}-\d{{2}})\.json$")


def _file_re(prefix):
    """The pattern of a set's file name, "<prefix>-<date>-<unit>.csv.gz" (groups: the date, the unit)."""
    return re.compile(rf"^{re.escape(prefix)}-(\d{{4}}-\d{{2}}-\d{{2}})-([a-z0-9-]+)\.csv\.gz$")


_LIST, _FILE = _list_re(PREFIX), _file_re(PREFIX)


def _tag(entry=None):
    """The release of an entry's fetch settings (default "chain-locators")."""
    return ((entry or {}).get("fetch") or {}).get("release", TAG)


def _prefix(entry=None):
    """The file prefix of an entry's fetch settings (default "chain-locators")."""
    return ((entry or {}).get("fetch") or {}).get("prefix", PREFIX)


def _waiting(prefix):
    """The skip reason while a release has no set yet."""
    return WAITING if prefix == PREFIX else f"waiting for the first {prefix} set (its workflow has not published one)"


def newest(entry=None, names=None, prefix=None):
    """(date, list name) of the newest complete set. Raises uploaded.Waiting when there is none."""
    prefix = prefix or _prefix(entry)
    try:
        names = uploaded.assets(_tag(entry)) if names is None else names
    except uploaded.Waiting:
        raise uploaded.Waiting(_waiting(prefix)) from None
    dates = sorted((m.group(1) for m in map(_list_re(prefix).match, names) if m), reverse=True)
    if not dates:
        raise uploaded.Waiting(_waiting(prefix))
    return dates[0], f"{prefix}-{dates[0]}.json"


def version(entry=None):
    """The source's version, "chain-locators/chain-locators-2026-11-28". Raises uploaded.Waiting."""
    dt, _ = newest(entry)
    return f"{_tag(entry)}/{_prefix(entry)}-{dt}"


def sha256_of(path):
    """The SHA-256 of a file, in hex."""
    return uploaded.sha256_of(path)


def rows_in(path):
    """The number of stores in a .csv.gz file (its lines without the header)."""
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


# ------------------------------------------------------------------------------------------------ reading

def prepare(entry, national, sleep=time.sleep):
    """Make national/<id>/<id>.csv from the newest set (see the module docstring). Returns the number of stores.
    Raises uploaded.Waiting (no set yet) or RuntimeError (a file could not be downloaded or is damaged)."""
    tag, prefix = _tag(entry), _prefix(entry)
    dt, list_name = newest(entry)
    folder = os.path.join(national, entry["id"])
    os.makedirs(folder, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix=f"{entry['id']}-", dir=os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        with open(uploaded.download(tag, list_name, scratch, sleep=sleep), encoding="utf-8") as f:
            listing = json.load(f)
        files = listing.get("files") or []
        if listing.get("date") != dt or not files:
            raise RuntimeError(f"the list {list_name} names no files of {dt}")
        target = os.path.join(folder, entry["id"] + ".csv")
        count = 0
        with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
            writer = None
            for item in files:
                name = str(item.get("name", ""))
                if not _file_re(prefix).match(name) or not name.startswith(f"{prefix}-{dt}-"):
                    raise RuntimeError(f"the list names a file this build will not read: {name!r}")
                path = uploaded.download(tag, name, scratch, item.get("sha256"), sleep)
                with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    if writer is None:
                        writer = csv.DictWriter(out, fieldnames=reader.fieldnames, extrasaction="ignore")
                        writer.writeheader()
                    for row in reader:
                        writer.writerow(row)
                        count += 1
                os.remove(path)
        os.replace(target + ".partial", target)
        with open(target + ".version", "w", encoding="utf-8") as f:
            f.write(f"{tag}/{prefix}-{dt}")
        carried = [i["chain"] for i in files if i.get("status") != "new"]
        print(f"{entry['id']}: {count:,} rows of {len(files)} files from {tag}/{list_name}"
              + (f" (kept from an earlier month: {', '.join(carried)})" if carried else ""))
        return count
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ publishing

def _gh(args, what):
    """Run gh; raise RuntimeError with what failed."""
    code, out, err = uploaded.run_gh(args)
    if code != 0:
        raise RuntimeError(f"{what} failed: {' '.join(str(err).split())[:200]}")
    return out


def decide(chain, ran, summary, new_file, previous, prev_date):
    """What the set gets for one chain: (file entry or None, why). summary: this run's summary or None; new_file:
    this run's CSV path or None; previous: the previous list's file entry for the chain, or None."""
    prev_rows = int((previous or {}).get("rows") or 0)
    if not ran:
        why = "not run this time"
    elif summary is None:
        why = "the job left no summary (stopped at its time limit?)"
    elif summary.get("status") != "ok" or not new_file:
        why = f"{summary.get('status', 'failed')}: {summary.get('reason', '')}".strip(": ")
    elif prev_rows and summary.get("rows", 0) < TOO_FEW * prev_rows:
        why = f"only {summary.get('rows', 0):,} stores against {prev_rows:,} last time (has the site changed?)"
    else:
        return {"chain": chain, "path": new_file, "status": "new", "collected": summary.get("date"),
                "carried": 0}, ""
    if not previous:
        return None, why
    carried = int(previous.get("carried") or 0) + (1 if ran else 0)
    if carried > MAX_CARRY:
        return None, why + f"; its last good set ({previous.get('collected')}) is too old to keep"
    return {"chain": chain, "from": previous["name"], "status": "carried" if ran else "kept",
            "collected": previous.get("collected") or prev_date, "carried": carried, "rows": prev_rows,
            "sha256": previous.get("sha256")}, why


CHAIN_NOTES = ("Monthly store lists of big US chains read from their own store locators (placepacks/chains), read "
               "by the pack build (source chain-locators). Not for download.")


def publish(folder, date, ran, sleep=time.sleep, units=None, tag=TAG, prefix=PREFIX, title="Chain store locators",
            notes=CHAIN_NOTES):
    """Publish the set of date from folder (see the module docstring). ran: the unit ids of this run (chains, or a
    directory's sites or states); units: every unit id there is (default: the chains of placepacks/chains); tag,
    prefix, title and notes: the release, the file prefix and the release's title and text when it is made.
    Returns the list written."""
    if units is None:
        from placepacks import chains
        units = chains.CHAINS
    repo = uploaded.repo()
    try:
        os.remove(uploaded._cache_path(tag))          # a fresh file list
    except OSError:
        pass
    try:
        names = uploaded.assets(tag)
    except uploaded.Waiting:
        names = {}
        if uploaded.run_gh(["release", "view", tag, "--repo", repo])[0] != 0:
            _gh(["release", "create", tag, "--repo", repo, "--title", title, "--latest=false", "--notes", notes],
                "creating the release")
    previous, prev_date = {}, ""
    try:
        prev_date, prev_list = newest(names=names, prefix=prefix)
    except uploaded.Waiting:
        prev_list = ""
    scratch = tempfile.mkdtemp(prefix=f"{prefix}-")
    try:
        if prev_list:
            # (A second run on the same day finds that day's earlier list here, and builds on it.)
            with open(uploaded.download(tag, prev_list, scratch, sleep=sleep), encoding="utf-8") as f:
                previous = {i["chain"]: i for i in json.load(f).get("files", [])}
        files, runs, uploads = [], {}, []
        for chain in sorted(set(units) | set(previous)):
            summary = None
            path = os.path.join(folder, f"{chain}.json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    summary = json.load(f)
            new_file = os.path.join(folder, f"{chain}.csv.gz")
            new_file = new_file if os.path.exists(new_file) else None
            got, why = decide(chain, chain in ran, summary, new_file, previous.get(chain), prev_date)
            runs[chain] = {k: (summary or {}).get(k) for k in ("status", "reason", "rows", "expected", "requests",
                                                               "endpoint", "date")}
            runs[chain]["ran"] = chain in ran
            runs[chain]["used"] = (got or {}).get("status", "missing")
            runs[chain]["why"] = why
            if not got:
                continue
            name = f"{prefix}-{date}-{chain}.csv.gz"
            target = os.path.join(scratch, name)
            if got["status"] == "new":
                shutil.copy(got["path"], target)
            else:
                old = uploaded.download(tag, got["from"], scratch, got.get("sha256"), sleep)
                if old != target:
                    os.replace(old, target)
            files.append({"name": name, "chain": chain, "rows": rows_in(target), "sha256": sha256_of(target),
                          "size": os.path.getsize(target), "status": got["status"], "collected": got["collected"],
                          "carried": got["carried"]})
            uploads.append(target)
        if not files:
            raise RuntimeError("no unit has any rows to publish yet")
        listing = {"date": date, "release": tag, "title": title, "files": files, "runs": runs, "note": notes}
        list_path = os.path.join(scratch, f"{prefix}-{date}.json")
        with open(list_path, "w", encoding="utf-8") as f:
            json.dump(listing, f, indent=1)
        for path in uploads + [list_path]:          # the list last
            _gh(["release", "upload", tag, path, "--repo", repo, "--clobber"], f"uploading {os.path.basename(path)}")
        # Older sets: everything of a date older than the newest KEEP.
        list_re, file_re = _list_re(prefix), _file_re(prefix)
        dates = sorted({m.group(1) for n in names for m in [list_re.match(n) or file_re.match(n)] if m} | {date},
                       reverse=True)
        for old in dates[KEEP:]:
            for n in names:
                if n.startswith(f"{prefix}-{old}"):
                    _gh(["release", "delete-asset", tag, n, "--repo", repo, "-y"], f"deleting {n}")
        return listing
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def table(listing):
    """A Markdown table of a published list, for the job summary."""
    used = {f["chain"]: f for f in listing.get("files", [])}
    lines = [f"## {listing.get('title') or 'Chain store locators'}, {listing.get('date')}", "",
             "| Unit | This run | Rows found | Expected | Requests | In the set | Note |",
             "|---|---|---|---|---|---|---|"]
    for chain, r in sorted(listing.get("runs", {}).items()):
        f = used.get(chain)
        kept = (f"{f['rows']:,} (this run)" if f["status"] == "new" else
                f"{f['rows']:,} (from {f['collected']})") if f else "none"
        lines.append(f"| {chain} | {r.get('status') or ('not run' if not r.get('ran') else 'no summary')} | "
                     f"{r.get('rows') if r.get('rows') is not None else ''} | {r.get('expected') or ''} | "
                     f"{r.get('requests') or ''} | {kept} | {(r.get('why') or '').replace('|', '/')[:160]} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["publish"])
    p.add_argument("--dir", required=True)
    p.add_argument("--date", default=datetime.date.today().isoformat())
    p.add_argument("--chains", default="", help="the chain ids run this time (empty: every chain)")
    a = p.parse_args(argv)
    from placepacks import chains
    ran = set(a.chains.replace(",", " ").split()) or set(chains.CHAINS)
    listing = publish(a.dir, a.date, ran)
    text = table(listing)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
