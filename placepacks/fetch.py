"""Download a region's sources for a build (the workflow's fetch step), politely, and record their versions.

    python -m placepacks.fetch us-vermont --dir work/us-vermont --part all [--national national/]
    python -m placepacks.fetch us-vermont --dir work/us-vermont --fingerprint     (versions only, no downloads)
    python -m placepacks.fetch --prepare --national national/                     (the national files, once)

Each source's catalogue "fetch" says how:
  http            one file (a Geofabrik extract is checked against its .md5 file)
  national        a file for the whole country, downloaded once by --prepare and read by every region
  tiger_counties  the TIGER/Line files of the region's counties (listed from the Census directory page)
  duckdb          the region's slice of remote Parquet (Overture, Foursquare), by bounding box (range reads)
  wikidata        one query to the Wikidata Query Service, by bounding box
  gtfs            the region's feeds of the Mobility Database catalogue whose licence allows redistribution
  manual          a folder someone filled (inputs/...): used when it exists
Every request names the project in its User-Agent and waits the source's "pause" seconds before the next one; a
busy or rate-limited host (429, 5xx, "ServerBusy") is tried again after 30, 60, 120 and 240 seconds (download).
Release names that change ("latest" in the settings) are found from the publisher's own listing (s3_latest:
Overture's and Foursquare's buckets, the NAD's releases). Every source ends with one status line,
"source: ok (version)", "source: skipped (reason)" or "source: failed (error)", printed and kept in fetched.json
("status", "reason"); the build adds the rows read, and sources-status.md lists them.
fetched.json: {source id: {"path", "ok", "status", "reason", "version", "date", "error"}, "_bbox": [west, south, east,
north]}.
"""

import argparse
import datetime
import email.utils
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from placepacks import catalogue

USER_AGENT = "place-packs-builder/1 (+https://github.com/mark-getbraille/place-packs)"


def request(url, method="GET", data=None, headers=None, timeout=300):
    """Open a request with the project's User-Agent."""
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": USER_AGENT,
                                                                         **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def version_of(headers):
    """A version text from a response's ETag, Last-Modified or size."""
    return headers.get("ETag") or headers.get("Last-Modified") or headers.get("Content-Length") or ""


RETRY_WAITS = (30, 60, 120, 240)       # seconds before each new try of a busy host


def retryable(error):
    """True for a temporary refusal: 429, a 5xx answer, Azure's "ServerBusy", a dropped connection."""
    import urllib.error
    if isinstance(error, urllib.error.HTTPError):
        if error.code == 429 or error.code >= 500:
            return True
        try:
            body = error.read(2000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - no body
            body = ""
        return "ServerBusy" in body or "over the account limit" in body
    return isinstance(error, (urllib.error.URLError, ConnectionError, TimeoutError))


def download(url, target, pause=0, waits=RETRY_WAITS, sleep=time.sleep):
    """Download url to target (through a .partial file), trying a busy host again after each of waits. Returns
    (version, date)."""
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    for attempt in range(len(waits) + 1):
        try:
            with request(url) as r, open(target + ".partial", "wb") as f:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
                version, modified = version_of(r.headers), r.headers.get("Last-Modified", "")
            break
        except Exception as e:  # noqa: BLE001 - tried again when it is temporary
            if attempt >= len(waits) or not retryable(e):
                raise
            print(f"  {url}: busy ({str(e)[:80]}); trying again in {waits[attempt]} s", flush=True)
            sleep(waits[attempt])
    os.replace(target + ".partial", target)
    if pause:
        time.sleep(pause)
    date = ""
    if modified:
        try:
            date = email.utils.parsedate_to_datetime(modified).date().isoformat()
        except (TypeError, ValueError):
            date = ""
    return version, date


def md5_ok(path, url):
    """True when the file matches the published .md5 file next to url (Geofabrik)."""
    with request(url + ".md5") as r:
        expected = r.read().decode("ascii", "replace").split()[0]
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest() == expected


def s3_prefixes(bucket_url, prefix, opener=None):
    """The "folders" under prefix in a public S3 bucket (its ListObjectsV2 answer), e.g. ["release/2026-10-22.0/"]."""
    import xml.etree.ElementTree as ET
    url = f"{bucket_url.rstrip('/')}/?list-type=2&delimiter=/&prefix={urllib.parse.quote(prefix)}"
    with (opener or request)(url) as r:
        root = ET.fromstring(r.read())
    ns = {"s3": root.tag.split("}")[0][1:]} if root.tag.startswith("{") else {}
    path = "s3:CommonPrefixes/s3:Prefix" if ns else "CommonPrefixes/Prefix"
    return [e.text for e in root.findall(path, ns) if e.text]


def s3_keys(bucket_url, prefix, opener=None):
    """The object names under prefix in a public S3 bucket (one page, enough for release lists)."""
    import xml.etree.ElementTree as ET
    url = f"{bucket_url.rstrip('/')}/?list-type=2&prefix={urllib.parse.quote(prefix)}"
    with (opener or request)(url) as r:
        root = ET.fromstring(r.read())
    ns = {"s3": root.tag.split("}")[0][1:]} if root.tag.startswith("{") else {}
    path = "s3:Contents/s3:Key" if ns else "Contents/Key"
    return [e.text for e in root.findall(path, ns) if e.text]


def latest_release(entry, opener=None):
    """The newest release name of a source whose catalogue setting says "latest", from the bucket listing:
    entry["release_list"] = {"bucket": https address, "prefix": "release/", "pattern": a regex with one group}."""
    spec = entry["release_list"]
    names = s3_prefixes(spec["bucket"], spec["prefix"], opener)
    found = sorted(m.group(1) for m in (re.search(spec["pattern"], n) for n in names) if m)
    if not found:
        raise ValueError(f"no release found in {spec['bucket']}")
    return found[-1]


def nad_url(values, opener=None):
    """The address of the newest NAD text release: from the bucket's list when it can be read, else the setting's
    release (NAD_r<N>_TXT.zip)."""
    bucket = "https://nationaladdressdata.s3.amazonaws.com"
    try:
        keys = s3_keys(bucket, "NAD_r", opener)
        releases = sorted((int(m.group(1)), k) for k in keys
                          for m in [re.match(r"NAD_r(\d+)_TXT\.zip$", k)] if m)
        if releases:
            return f"{bucket}/{releases[-1][1]}"
    except Exception:  # noqa: BLE001 - no list: the setting's release
        pass
    return f"{bucket}/NAD_r{values.get('nad_release', '20')}_TXT.zip"


def resolve(entry, values, opener=None):
    """The placeholders of a source with any "latest" release replaced by the newest one found."""
    values = dict(values)
    for key in ("overture_release", "fsq_release"):
        if values.get(key) == "latest" and entry.get("release_setting") == key:
            values[key] = latest_release(entry, opener)
    return values


def extract_bbox(path):
    """[west, south, east, north] from an .osm.pbf header (None when it has none or pyosmium is missing)."""
    try:
        import osmium
        r = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
        box = r.header().box()
        r.close()
        if box.valid():
            return [box.bottom_left.lon, box.bottom_left.lat, box.top_right.lon, box.top_right.lat]
    except Exception:  # noqa: BLE001 - no box: the region's own
        pass
    return None


def fetch_source(entry, region, values, work, national, fingerprint=False):
    """Fetch one source. Returns its fetched.json entry."""
    f = entry["fetch"]
    method = f["method"]
    folder = os.path.join(work, entry["id"])
    if method in ("duckdb", "duckdb_national"):
        values = resolve(entry, values)
    url = f.get("url", "").format(**values)
    pause = f.get("pause", 1)
    out = {"ok": False, "version": "", "date": "", "path": ""}
    if method == "manual":
        path = os.path.join(catalogue.ROOT, f["folder"].format(**values))
        out.update(ok=os.path.exists(path), path=path, version="manual:" + str(int(os.path.getmtime(path)))
                   if os.path.exists(path) else "")
        if not out["ok"]:
            out.update(status="skipped", reason=f"needs a hand-supplied file in {f['folder'].format(**values)}")
        return out
    if method == "duckdb_national":
        # The source was sliced once for every covered country by --prepare (national/<id>/<id>.parquet); the
        # region's slice is read from that local file.
        local = os.path.join(national or "national", entry["id"], entry["id"] + ".parquet")
        out["version"] = entry["remote"].format(**values)
        if fingerprint:
            out["ok"] = True
            return out
        if not os.path.exists(local):
            out.update(status="skipped", reason="the national slice was not prepared (see the prepare job)")
            return out
        from placepacks.readers.parquet import fetch_slice
        target = os.path.join(folder, f["file"])
        os.makedirs(folder, exist_ok=True)
        fetch_slice({**entry, "remote": local, "query": entry["local_query"]}, region, target)
        out.update(ok=True, path=target, date=datetime.date.today().isoformat())
        return out
    if method == "duckdb":
        remote = entry["remote"].format(**values)
        out["version"] = remote
        if fingerprint:
            out["ok"] = True
            return out
        from placepacks.readers.parquet import fetch_slice
        target = os.path.join(folder, f["file"])
        os.makedirs(folder, exist_ok=True)
        fetch_slice({**entry, "remote": remote}, region, target)
        out.update(ok=True, path=target, date=datetime.date.today().isoformat())
        return out
    if method == "wikidata":
        out["version"] = datetime.date.today().strftime("%Y-%m")
        if fingerprint:
            out["ok"] = True
            return out
        from placepacks.readers.wikidata import query_for
        target = os.path.join(folder, "wikidata.json")
        os.makedirs(folder, exist_ok=True)
        body = urllib.parse.urlencode({"query": query_for(region), "format": "json"}).encode()
        with request(url, "POST", body, {"Accept": "application/sparql-results+json",
                                          "Content-Type": "application/x-www-form-urlencoded"}) as r, \
                open(target, "wb") as fh:
            fh.write(r.read())
        time.sleep(pause)
        out.update(ok=True, path=target, date=datetime.date.today().isoformat())
        return out
    if method == "national":
        if entry["id"] == "nad":
            url = nad_url(values)
        folder = os.path.join(national or "national", entry["id"])
        path = os.path.join(folder, os.path.basename(urllib.parse.urlsplit(url).path))
        stamp = path + ".version"
        if not os.path.exists(path) and os.path.isdir(folder):
            path = folder                   # the region's slice made by placepacks.split
        out.update(ok=os.path.exists(path), path=path,
                   version=open(stamp, encoding="utf-8").read() if os.path.exists(stamp) else url)
        if not out["ok"] and not fingerprint:
            out.update(status="failed", reason="the national file was not downloaded by the prepare job")
        return out
    if method == "tiger_counties":
        prefix, suffix = f["prefix"].format(**values), f["suffix"]
        with request(url) as r:
            listing = r.read().decode("utf-8", "replace")
        names = sorted(set(re.findall(rf'href="({re.escape(prefix)}\d*{re.escape(suffix)})"', listing)))
        out["version"] = f"{url} ({len(names)} files)"
        if fingerprint:
            out["ok"] = bool(names)
            return out
        for name in names:
            download(url + name, os.path.join(folder, name), pause)
        out.update(ok=bool(names), path=folder, date=datetime.date.today().isoformat())
        return out
    if method == "gtfs":
        return fetch_gtfs(entry, region, url, folder, pause, fingerprint)
    # http
    if fingerprint:
        with request(url, "HEAD") as r:
            out.update(ok=True, version=version_of(r.headers))
        return out
    target = os.path.join(folder, f.get("file") or os.path.basename(urllib.parse.urlsplit(url).path))
    version, date = download(url, target, pause)
    if f.get("md5") and not md5_ok(target, url):
        os.remove(target)
        raise ValueError("the download does not match its .md5 file")
    out.update(ok=True, path=target, version=version, date=date)
    return out


def fetch_gtfs(entry, region, url, folder, pause, fingerprint):
    """The region's GTFS feeds with an open licence (readers.gtfs.licence_ok), from the Mobility Database list."""
    import csv
    import io
    from placepacks.readers.gtfs import licence_ok
    with request(url) as r:
        text = r.read().decode("utf-8", "replace")
    feeds = []
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("data_type") != "gtfs" or row.get("status") == "deprecated":
            continue
        if row.get("location.country_code") != catalogue.country_code(region):
            continue
        if (row.get("location.subdivision_name") or "").lower() != region["name"].lower():
            continue
        if not licence_ok(row.get("urls.license")) or not row.get("urls.latest"):
            continue
        feeds.append((row["id"], row["urls.latest"], row.get("urls.license", "")))
    version = ",".join(f[0] for f in feeds)
    if not feeds:
        return {"ok": False, "version": "", "path": "", "date": "", "status": "skipped",
                "reason": "no feed of this region in the Mobility Database lists an open licence"}
    if fingerprint:
        return {"ok": True, "version": version, "path": "", "date": ""}
    for fid, latest, _ in feeds:
        try:
            download(latest, os.path.join(folder, f"mdb-{fid}.zip"), pause)
        except Exception:  # noqa: BLE001 - one feed missing does not stop the others
            continue
    with open(os.path.join(folder, "licences.json"), "w", encoding="utf-8") as fh:
        json.dump({f[0]: f[2] for f in feeds}, fh, indent=1)
    return {"ok": bool(feeds), "version": version, "path": folder, "date": datetime.date.today().isoformat()}


def status_line(source, got, rows=None):
    """"source: ok (version, rows)", "source: skipped (reason)" or "source: failed (error)"."""
    if got.get("status") == "ok":
        rows = got.get("rows", rows)
        bits = [str(got.get("version", ""))[:80] or "no version"] + ([f"{rows} rows"] if rows is not None else [])
        return f"{source}: ok ({', '.join(bits)})"
    return f"{source}: {got.get('status', 'failed')} ({str(got.get('reason', ''))[:200]})"


def fetch_region(region_id, work, parts=("core", "extra"), national=None, fingerprint=False, cat=None, only=None):
    """Fetch every source of a region's parts. Returns the fetched dict (also written to work/fetched.json)."""
    cat = cat or catalogue.load()
    region = dict(catalogue.regions()[region_id])
    os.makedirs(work, exist_ok=True)
    result = {}
    for part in parts:
        for entry in catalogue.sources_for(region, part, cat, only):
            values = catalogue.settings_for(cat, region)
            try:
                got = fetch_source(entry, region, values, work, national, fingerprint)
            except Exception as e:  # noqa: BLE001 - recorded; the build leaves the source out
                got = {"ok": False, "version": "", "path": "", "error": str(e)[:300], "status": "failed",
                       "reason": str(e)[:300]}
            if got.get("ok"):
                got["status"], got["reason"] = "ok", ""
            got.setdefault("status", "failed")
            got.setdefault("reason", got.get("error", "") or "nothing was downloaded")
            result[entry["id"]] = got
            if not fingerprint:
                print(status_line(entry["id"], got), flush=True)
            if entry["id"] == "osm" and result[entry["id"]].get("ok") and not fingerprint:
                box = extract_bbox(result["osm"]["path"])
                if box:
                    region["bbox"] = box            # the later slices use the extract's own box
                    result["_bbox"] = box
    if not fingerprint:
        with open(os.path.join(work, "fetched.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    return result


def prepare(national, cat=None):
    """Download every "national" source once into national/<source>/ (the regions read their parts)."""
    cat = cat or catalogue.load()
    any_region = next(iter(catalogue.regions().values()))
    for entry in cat["accepted"]:
        if entry["fetch"]["method"] == "duckdb_national":
            prepare_parquet(entry, national, cat)
            continue
        if entry["fetch"]["method"] != "national":
            continue
        values = catalogue.settings_for(cat, any_region)
        url = nad_url(values) if entry["id"] == "nad" else entry["fetch"]["url"].format(**values)
        target = os.path.join(national, entry["id"], os.path.basename(urllib.parse.urlsplit(url).path))
        stamp = target + ".version"
        if os.path.exists(target) and os.path.exists(stamp):
            # Restored from the Actions cache: kept unless the publisher's version changed (or cannot be asked).
            try:
                with request(url, "HEAD") as r:
                    now = version_of(r.headers)
            except Exception:  # noqa: BLE001 - the host is busy: the cached copy is used
                now = None
            if now is None or now == open(stamp, encoding="utf-8").read():
                print(f"{entry['id']}: {os.path.getsize(target):,} bytes (the cached copy)")
                continue
        try:
            version, _ = download(url, target, entry["fetch"].get("pause", 2))
            with open(target + ".version", "w", encoding="utf-8") as f:
                f.write(version or url)
            print(f"{entry['id']}: {os.path.getsize(target):,} bytes")
        except Exception as e:  # noqa: BLE001 - that layer is left out this time
            print(f"{entry['id']}: not downloaded ({e})")


def prepare_parquet(entry, national, cat):
    """Slice a large remote Parquet source once for every covered country (entry["prepare_query"], with {src} and
    {countries}) into national/<id>/<id>.parquet; each region then reads its box from that file."""
    try:
        values = resolve(entry, catalogue.settings_for(cat, next(iter(catalogue.regions().values()))))
        remote = entry["remote"].format(**values)
        countries = ", ".join(f"'{c}'" for c in entry["countries"])
        folder = os.path.join(national, entry["id"])
        os.makedirs(folder, exist_ok=True)
        from placepacks.readers.parquet import connect
        con = connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        if entry.get("s3_region"):
            con.execute(f"SET s3_region = '{entry['s3_region']}'")
        target = os.path.join(folder, entry["id"] + ".parquet")
        con.execute(f"COPY ({entry['prepare_query'].format(src=remote, countries=countries)}) TO '{target}' "
                    "(FORMAT PARQUET)")
        con.close()
        with open(target + ".version", "w", encoding="utf-8") as f:
            f.write(remote)
        print(f"{entry['id']}: {os.path.getsize(target):,} bytes ({remote})")
    except Exception as e:  # noqa: BLE001 - that layer is left out this time
        print(f"{entry['id']}: not prepared ({e})")


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("region", nargs="?")
    p.add_argument("--dir", default="")
    p.add_argument("--part", default="all", choices=("core", "extra", "all"))
    p.add_argument("--national", default="national")
    p.add_argument("--fingerprint", action="store_true")
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--fingerprint-all", default="", help="region ids (space-separated; empty: all) for the plan")
    p.add_argument("--out", default="prints.json")
    p.add_argument("--only", default="", help="only these source ids (a seed run)")
    a = p.parse_args(argv)
    if a.prepare:
        prepare(a.national)
        return 0
    if a.fingerprint_all is not None and a.region is None:
        from placepacks.manifest import fingerprint
        ids = a.fingerprint_all.replace(",", " ").split() or list(catalogue.regions())
        prints = {r: fingerprint(fetch_region(r, os.path.join("work", r), ("core", "extra"), a.national, True))
                  for r in ids}
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(prints, f, indent=1)
        return 0
    parts = ("core", "extra") if a.part == "all" else (a.part,)
    result = fetch_region(a.region, a.dir or os.path.join("work", a.region), parts, a.national, a.fingerprint,
                          only=set(a.only.split(",")) if a.only else None)
    print(json.dumps({k: {"ok": v.get("ok"), "version": v.get("version", "")[:80], "error": v.get("error", "")}
                      for k, v in result.items() if not k.startswith("_")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
