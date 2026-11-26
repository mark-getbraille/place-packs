"""Sources the owner uploads to this repository's release "uploaded-sources" (fetch method "uploaded_national").

Why: some open datasets can only be downloaded after signing in (Foursquare Open Source Places is now the Hugging
Face dataset foursquare/fsq-os-places, Apache License 2.0, behind a free sign-in), and the build machines cannot sign
in. The owner's Program Downloader downloads them with his own sign-in and uploads the publisher's files, unchanged,
to the release "uploaded-sources": for each date, "<prefix>-<date>-<file>" (Foursquare: about 100 Parquet files,
about 12 GB), "<prefix>-<date>-NOTICE.txt" and, uploaded last, the manifest "<prefix>-<date>.json" (the files with
their sizes and SHA-256, the licence, the attribution and the NOTICE text). A date counts only once its manifest is
there; the newest such date is used.

How the build uses it (the same shape as "duckdb_national"):
  - the plan job and each region ask which date is newest (newest(); the release's file list, read once and kept a
    few minutes in a small file, so ~190 regions do not each ask GitHub); the source's version is
    "uploaded-sources/<prefix>-<date>", so a new month rebuilds the regions;
  - the prepare job (prepare()) downloads the date's files ONE AT A TIME with gh (the repository's own read-only
    token), checks each by its SHA-256 from the manifest, keeps only the entry's prepare_query columns and countries
    (its "countries" and the fetch's "also_countries": Foursquare files Puerto Rico as country PR, our region
    us-puerto-rico is in the US) into a small piece, and deletes the raw file; the pieces become
    national/<id>/<id>.parquet, which placepacks.split cuts per region like every national slice. The raw files go
    to PLACEPACKS_SCRATCH when it is set (the workflow points it at the runner's larger /mnt disk);
  - a region reads its slice with the entry's local_query (fetch.fetch_source).
When there is no manifest yet, the source is skipped with "waiting for the owner's upload from Program Downloader";
the build never fails because of it.

gh is run through run_gh() (tests replace it); the GitHub token is gh's own (GH_TOKEN) and is never printed.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

WAITING = "waiting for the owner's upload from Program Downloader"
DEFAULT_REPO = "mark-getbraille/place-packs"
CACHE_SECONDS = 600                  # how long the release's file list is reused
TRIES = 3                            # a download is tried this often
WAIT = 20                            # seconds between tries


class Waiting(Exception):
    """No complete upload is there yet (or the release cannot be read): the source is skipped with this reason."""


def run_gh(args, timeout=1800):
    """Run gh with args; returns (exit code, output, error words). Tests replace this."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", f"gh could not be run ({type(e).__name__})"
    return done.returncode, done.stdout, done.stderr


def repo():
    """The repository whose release holds the uploads (GITHUB_REPOSITORY in Actions)."""
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO


def spec(entry):
    """The entry's fetch settings with their defaults: release, prefix, also_countries."""
    f = entry["fetch"]
    return {"release": f.get("release", "uploaded-sources"), "prefix": f["prefix"],
            "also_countries": list(f.get("also_countries", []))}


def _cache_path(tag):
    """The small file the release's file list is kept in for a few minutes."""
    return os.path.join(tempfile.gettempdir(), f"placepacks-release-{re.sub(r'[^A-Za-z0-9_-]', '_', tag)}.json")


def assets(tag, now=None):
    """{name: size} of the release's files. Raises Waiting when there is no such release or it cannot be read."""
    now = time.time() if now is None else now
    path = _cache_path(tag)
    try:
        with open(path, encoding="utf-8") as f:
            kept = json.load(f)
        if kept.get("repo") == repo() and now - float(kept.get("time", 0)) < CACHE_SECONDS:
            return kept["assets"]
    except (OSError, ValueError, KeyError):
        pass
    # the release's id, then its files page by page (a release object lists only some of its files when it has
    # many: two months of Foursquare are about 200)
    code, out, err = run_gh(["api", f"repos/{repo()}/releases/tags/{tag}", "--jq", ".id"], timeout=120)
    if code == 0:
        code, out, err = run_gh(["api", f"repos/{repo()}/releases/{out.strip()}/assets?per_page=100", "--paginate",
                                 "--jq", ".[] | [.name, .size] | @tsv"], timeout=300)
    if code != 0:
        if "404" in err or "Not Found" in err:
            raise Waiting(WAITING + f" (there is no \"{tag}\" release yet)")
        raise Waiting(WAITING + f" (the release \"{tag}\" could not be read: {' '.join(err.split())[:120]})")
    found = {}
    for line in (out or "").splitlines():
        name, _, size = line.partition("\t")
        if name.strip():
            found[name.strip()] = int(size) if size.strip().isdigit() else 0
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"repo": repo(), "time": now, "assets": found}, f)
    except OSError:
        pass
    return found


def newest(entry):
    """(date, manifest name) of the newest complete upload of the entry. Raises Waiting when there is none."""
    s = spec(entry)
    pattern = re.compile(rf"^{re.escape(s['prefix'])}-(\d{{4}}-\d{{2}}-\d{{2}})\.json$")
    dates = sorted((m.group(1) for m in map(pattern.match, assets(s["release"])) if m), reverse=True)
    if not dates:
        raise Waiting(WAITING)
    return dates[0], f"{s['prefix']}-{dates[0]}.json"


def version(entry):
    """The source's version: "uploaded-sources/fsq-2026-11-17". Raises Waiting."""
    dt, _name = newest(entry)
    return f"{spec(entry)['release']}/{spec(entry)['prefix']}-{dt}"


def sha256_of(path):
    """The SHA-256 of a file, in hex."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(tag, name, folder, sha256=None, sleep=time.sleep):
    """Download one release file into folder with gh (TRIES tries), checked by its SHA-256 when given. Returns its
    path. Raises RuntimeError when it never arrives right."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name)
    last = ""
    for attempt in range(TRIES):
        code, _out, err = run_gh(["release", "download", tag, "--repo", repo(), "--pattern", name, "--dir", folder,
                                  "--clobber"])
        if code == 0 and os.path.exists(target):
            if sha256 is None or sha256_of(target) == sha256:
                return target
            last = "its SHA-256 is not the one in the manifest"
            os.remove(target)
        else:
            last = " ".join(str(err).split())[:160] or f"exit code {code}"
        if attempt + 1 < TRIES:
            sleep(WAIT)
    raise RuntimeError(f"{name} could not be downloaded from the release \"{tag}\" ({last})")


def notice_ok(notice_text, notice_path):
    """True when the repository's NOTICE file carries the dataset's notice (its non-empty lines, in any spacing)."""
    try:
        ours = " ".join(open(notice_path, encoding="utf-8").read().split()).lower()
    except OSError:
        return False
    lines = [" ".join(line.split()).lower() for line in str(notice_text or "").splitlines() if line.strip()]
    return all(line in ours for line in lines)


def prepare(entry, national, notice_path=None, sleep=time.sleep):
    """Make national/<id>/<id>.parquet from the newest upload (see the module notes). Returns the number of rows.
    Raises Waiting (no upload yet) or RuntimeError (a file could not be downloaded or read)."""
    from placepacks.readers.parquet import connect, picked
    s = spec(entry)
    tag = s["release"]
    dt, manifest_name = newest(entry)
    folder = os.path.join(national, entry["id"])
    os.makedirs(folder, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix=f"{entry['id']}-", dir=os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        manifest_path = download(tag, manifest_name, scratch, sleep=sleep)
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        files = manifest.get("files") or []
        if manifest.get("dt") != dt or not files:
            raise RuntimeError(f"the manifest {manifest_name} lists no files of {dt}")
        if notice_path and not notice_ok(manifest.get("notice"), notice_path):
            # The licence asks that the NOTICE travels with the data: the repository's NOTICE (published with the
            # packs) must carry it. Said loudly in the log, so the owner updates NOTICE.
            print(f"::warning::{entry['id']}: the dataset's NOTICE text of {dt} is not all in the repository's NOTICE "
                  f"file; add it there. It reads: {' '.join(str(manifest.get('notice')).split())[:400]}")
        countries = ", ".join(f"'{c}'" for c in list(entry["countries"]) + s["also_countries"])
        pieces = os.path.join(scratch, "pieces")
        os.makedirs(pieces)
        con = connect()
        for i, item in enumerate(files):
            name = str(item["name"])
            if "/" in name or "\\" in name or not name.startswith(f"{s['prefix']}-{dt}-"):
                raise RuntimeError(f"the manifest names a file this build will not read: {name!r}")
            raw = download(tag, name, scratch, item.get("sha256"), sleep)
            piece = os.path.join(pieces, f"{i:05d}.parquet")
            src = raw.replace("'", "''")
            # The entry's "pick" columns (Foursquare's tel and website) where the file has them, else NULL.
            extra = picked(entry, con, src, f"read_parquet('{src}')")
            con.execute(f"COPY ({entry['prepare_query'].format(src=src, countries=countries, **extra)}) TO '{piece}' "
                        "(FORMAT PARQUET, COMPRESSION ZSTD)")
            os.remove(raw)
            if (i + 1) % 10 == 0 or i + 1 == len(files):
                print(f"{entry['id']}: {i + 1} of {len(files)} files of {dt} read", flush=True)
        target = os.path.join(folder, entry["id"] + ".parquet")
        con.execute(f"COPY (SELECT * FROM read_parquet('{os.path.join(pieces, '*.parquet')}')) TO '{target}.partial' "
                    "(FORMAT PARQUET, COMPRESSION ZSTD)")
        rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{target}.partial')").fetchone()[0]
        con.close()
        os.replace(target + ".partial", target)
        with open(target + ".version", "w", encoding="utf-8") as f:
            f.write(f"{tag}/{s['prefix']}-{dt}")
        print(f"{entry['id']}: {rows:,} places of {len(entry['countries'])} countries from {tag}/{manifest_name} "
              f"({os.path.getsize(target):,} bytes)")
        return rows
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
