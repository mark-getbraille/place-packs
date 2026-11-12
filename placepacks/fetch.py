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
  overpass        one query to an Overpass API (OpenHistoricalMap), by bounding box
  gtfs            the region's feeds of the Mobility Database catalogue whose licence allows redistribution
  socrata         a Socrata open-data portal's dataset(s), through its SODA API without an app token: each query's
                  $select/$where/$group (one row per permit or licence and name, with its first and last date),
                  paged with $limit/$offset into one CSV; the version is each dataset's rowsUpdatedAt
  wfs             a WFS layer (GeoServer) as CSV, paged with startIndex/count; the version is its feature count
  ckan_sql        a CKAN portal's datastore SQL (datastore_search_sql): each query grouped to one row per licence
                  and name, paged with LIMIT/OFFSET into one CSV (Boston); the version is the month
  arcgis          an ArcGIS REST layer (FeatureServer or MapServer, no token): the ids inside the region's box (and
                  the entry's "where"), then the records in chunks of ids, as CSV with "_lat" and "_lon" (and
                  "_rings" for polygons, read as areas); dates become YYYY-MM-DD; the version is the layer's last edit
                  date and the number of records; polylines come with "_paths" (read as named lines)
  manual          a folder someone filled (inputs/...): used when it exists
A national source's file may be named by the publisher's metadata instead of a fixed address ("socrata_blob": the
NAD's file on data.transportation.gov, whose version is its blobId and rowsUpdatedAt), one file per country
("per_country": GeoNames) or every file a listing page links to ("listing": the FSA's hygiene ratings, one XML file
per local authority, turned into one CSV by "xml_records"), or only the newest of them ("latest": a regular
expression whose first group is the year, for the NCES and IMLS files renamed every year). A downloaded .zip whose
offsets are shifted (the Newberry atlas) is repaired (repair_zip).
Every request names the project in its User-Agent and waits the source's "pause" seconds before the next one; a
busy or rate-limited host (429, 5xx, "ServerBusy") is tried again after 30, 60, 120 and 240 seconds (download).
Release names that change ("latest" in the settings) are found from the publisher's own listing (s3_latest:
Overture's and Foursquare's buckets; the NAD from its Socrata metadata, with the old S3 bucket as a fallback). An
interrupted download continues where it stopped (a Range request) when the host allows it. Every source ends
with one status line,
"source: ok (version)", "source: skipped (reason)" or "source: failed (error)", printed and kept in fetched.json
("status", "reason"); the build adds the rows read, and sources-status.md lists them.
fetched.json: {source id: {"path", "ok", "status", "reason", "version", "date", "error"}, "_bbox": [west, south, east,
north]}.
"""

import argparse
import csv
import datetime
import email.utils
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request


csv.field_size_limit(2**31 - 1)   # polygon rings in one field can be many megabytes (sys.maxsize overflows on Windows)
from placepacks import catalogue, fmt

USER_AGENT = "place-packs-builder/1 (+https://github.com/mark-getbraille/place-packs)"
FAILED = "_not_downloaded.txt"      # national/<id>/: why the prepare job could not download a source


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
    partial = target + ".partial"
    if os.path.exists(partial):
        os.remove(partial)
    for attempt in range(len(waits) + 1):
        try:
            # After a dropped connection, ask only for the rest (the NAD is 8.5 GB); a host that answers with the
            # whole file (200) is written from the start.
            done = os.path.getsize(partial) if os.path.exists(partial) else 0
            with request(url, headers={"Range": f"bytes={done}-"} if done else None) as r, \
                    open(partial, "ab" if done and getattr(r, "status", 200) == 206 else "wb") as f:
                while True:
                    block = r.read(1 << 20)
                    if not block:
                        break
                    f.write(block)
                version, modified = version_of(r.headers), r.headers.get("Last-Modified", "")
            if target.lower().endswith(".zip"):
                import zipfile
                with open(partial, "rb") as fh:
                    head = fh.read(512).lstrip()
                if (head.startswith(b"PK") and not zipfile.is_zipfile(partial)) or head[:1] == b"<":
                    # A cut-off download or an error page in place of the file: tried again from the start.
                    os.remove(partial)
                    raise ConnectionError("the download is not a complete zip file")
            break
        except Exception as e:  # noqa: BLE001 - tried again when it is temporary
            if attempt >= len(waits) or not retryable(e):
                raise
            print(f"  {url}: busy ({str(e)[:80]}); trying again in {waits[attempt]} s", flush=True)
            sleep(waits[attempt])
    os.replace(partial, target)
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


def read_json(url, opener=None):
    """The JSON answer of url."""
    with (opener or request)(url) as r:
        return json.loads(r.read().decode("utf-8"))


def socrata_blob(spec, values, opener=None):
    """(address, file name, version) of a file published as a Socrata "blob" (the NAD on data.transportation.gov):
    spec = {"metadata": the view's JSON address, "download": an address with {blobId} and {blobFilename}, "file":
    the local name with {blobFilename}}. The version is the blobId and rowsUpdatedAt, so a new file (or a file
    replaced under the same id) is downloaded again and an unchanged one is not."""
    meta = read_json(spec["metadata"].format(**values), opener)
    blob, name = meta.get("blobId"), meta.get("blobFilename") or "data.zip"
    if not blob:
        raise ValueError("the metadata names no file (blobId)")
    url = spec["download"].format(**{**values, "blobId": blob, "blobFilename": urllib.parse.quote(name)})
    return url, spec.get("file", "{blobFilename}").format(blobFilename=name), f"{blob}:{meta.get('rowsUpdatedAt', '')}"


def national_files(entry, values, opener=None):
    """[(address, local file name, version or None)] of a national source. None: the version comes from the
    download's ETag or Last-Modified."""
    f = entry["fetch"]
    if f.get("socrata_blob"):
        try:
            return [socrata_blob(f["socrata_blob"], values, opener)]
        except Exception as e:  # noqa: BLE001 - the old address, when the metadata cannot be read
            print(f"  {entry['id']}: the publisher's metadata could not be read ({str(e)[:100]}); trying the old "
                  f"address", flush=True)
            url = nad_url(values, opener) if entry["id"] == "nad" else f["url"].format(**values)
            return [(url, os.path.basename(urllib.parse.urlsplit(url).path), None)]
    if f.get("json_url"):
        # The address of the newest file, read from a small JSON document (All The Places' runs/latest.json).
        meta = read_json(f["metadata"], opener)
        url = meta[f["json_url"]]
        return [(url, f.get("file") or os.path.basename(urllib.parse.urlsplit(url).path), str(meta.get(f.get(
            "version_key", ""), "")) or None)]
    if f.get("urls"):
        # Several fixed files of one source (StatCan's facility databases).
        # "names": the local file names when the addresses have none of their own (one export per year).
        names = f.get("names") or [os.path.basename(urllib.parse.urlsplit(u).path) for u in f["urls"]]
        return [(u.format(**values), n, None) for u, n in zip(f["urls"], names)]
    if f.get("per_country"):
        out = []
        for cc in entry["countries"]:
            url = f["url"].format(**{**values, "cc": cc})
            out.append((url, os.path.basename(urllib.parse.urlsplit(url).path), None))
        return out
    if f.get("listing"):
        with (opener or request)(f["listing"]) as r:
            page = r.read().decode("utf-8", "replace")
        names = sorted(set(re.findall(f["pattern"], page)))
        if not names and f.get("fallback_pattern"):
            names = sorted(set(re.findall(f["fallback_pattern"], page)))     # the Light List's PDFs, without XML
        if f.get("latest") and names:
            def year(n):
                """The number the "latest" pattern finds in a file name (-1 when none): the newest is kept."""
                m = re.search(f["latest"], os.path.basename(n))
                return int(m.group(1)) if m else -1
            names = [max(names, key=year)]
        return [(urllib.parse.urljoin(f["listing"], n), os.path.basename(urllib.parse.urlsplit(n).path), None)
                for n in names]
    url = nad_url(values, opener) if entry["id"] == "nad" else f["url"].format(**values)
    # "file": the local name when the address has none of its own (a Dataverse file id).
    return [(url, f.get("file") or os.path.basename(urllib.parse.urlsplit(url).path), None)]


def _json_documents(paths):
    """The JSON documents of files: each file, or each .json/.geojson member of a .zip."""
    import zipfile
    for path in paths:
        if str(path).lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.lower().endswith((".json", ".geojson")):
                        yield json.loads(z.read(name).decode("utf-8"))
        else:
            with open(path, encoding="utf-8") as fh:
                yield json.load(fh)


def json_to_csv(paths, spec, target):
    """Write the records of JSON files (or of the JSON files inside .zip files) as one CSV: spec = {"records": the key of the list of records (dotted for a
    nested one), "fields": [the record's keys, dotted for nested ones, a number for a list's item:
    "geometry.coordinates.0"]} (NOAA's station list, GeoJSON features). Returns the rows."""
    rows = 0
    with open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([k.replace(".", "_") for k in spec["fields"]])
        for data in _json_documents(paths):
            for part in spec["records"].split("."):
                data = data.get(part, []) if isinstance(data, dict) else []
            for rec in data:
                values = []
                for key in spec["fields"]:
                    v = rec
                    for part in key.split("."):
                        if isinstance(v, list) and part.isdigit():
                            v = v[int(part)] if int(part) < len(v) else ""
                        else:
                            v = v.get(part, "") if isinstance(v, dict) else ""
                    values.append("" if v is None else v)
                w.writerow(values)
                rows += 1
    return rows


def _xml_streams(path):
    """The XML streams of a file: the file itself, or each .xml member of a .zip."""
    import zipfile
    if str(path).lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(".xml"):
                    with z.open(name) as fh:
                        yield fh
    else:
        with open(path, "rb") as fh:
            yield fh


def xml_to_csv(paths, spec, target):
    """Write the records of XML files (or of the .xml files inside .zip files) as one CSV: spec = {"record": the
    element of one record, "fields": [child element names, found at any depth inside the record; a path
    "Name/EN" for one child of another; "@attr" for an attribute of the record]}; a field written "column=path"
    names its column. Returns the number of records."""
    import xml.etree.ElementTree as ET
    specs = [f.split("=", 1) if "=" in f else [f.replace("/", "_").lstrip("@"), f] for f in spec["fields"]]
    count = 0
    with open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([c for c, _ in specs])
        for path in paths:
            for stream in _xml_streams(path):
                for _, el in ET.iterparse(stream, events=("end",)):
                    if el.tag != spec["record"]:
                        continue
                    values = {c.tag: (c.text or "").strip() for c in el.iter()}
                    row = []
                    for _, f in specs:
                        if f.startswith("@"):
                            row.append(el.get(f[1:], ""))
                        elif "/" in f:
                            found = el.find(f)
                            row.append((found.text or "").strip() if found is not None else "")
                        else:
                            row.append(values.get(f, ""))
                    w.writerow(row)
                    count += 1
                    el.clear()
    return count


def repair_zip(path):
    """Rewrite a .zip whose member offsets are shifted (a prefix the central directory does not count, as in the
    Newberry atlas: unzip "re-compensates", Python's zipfile refuses) as a plain .zip. Returns True when it was
    rewritten; a .zip that reads as it is is left alone."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            if not infos:
                return False
            if infos[0].compress_type == 9:
                return False            # Deflate64 (the NAD): Python cannot open it; read through unzip or 7z
            try:
                with z.open(infos[0]) as fh:
                    fh.read(1)
                return False
            except NotImplementedError:
                return False
            except zipfile.BadZipFile:
                pass
            with open(path, "rb") as fh:
                start = fh.read(1 << 20).find(b"PK\x03\x04")
            delta = start - min(i.header_offset for i in z.infolist())
            for i in z.infolist():
                i.header_offset += delta
            with zipfile.ZipFile(path + ".fixed", "w", zipfile.ZIP_DEFLATED) as out:
                for i in infos:
                    out.writestr(i.filename, z.read(i))
    except zipfile.BadZipFile:
        return False
    os.replace(path + ".fixed", path)
    return True


def post_json(url, params, waits=RETRY_WAITS, sleep=time.sleep, pause=0):
    """The JSON answer of a POST form request (ArcGIS queries: long id lists do not fit in an address), with the
    retries of download() for a busy host. An ArcGIS error inside a 200 answer raises ValueError."""
    data = urllib.parse.urlencode(params).encode()
    for attempt in range(len(waits) + 1):
        try:
            with request(url, "POST", data, {"Content-Type": "application/x-www-form-urlencoded"}) as r:
                answer = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - tried again when it is temporary
            if attempt >= len(waits) or not retryable(e):
                raise
            print(f"  {url}: busy ({str(e)[:80]}); trying again in {waits[attempt]} s", flush=True)
            sleep(waits[attempt])
    if pause:
        time.sleep(pause)
    if isinstance(answer, dict) and answer.get("error"):
        raise ValueError(f"ArcGIS error: {str(answer['error'].get('message', answer['error']))[:200]}")
    return answer


def _arcgis_value(value, is_date):
    """A CSV value of an ArcGIS attribute: dates (milliseconds since 1970) as YYYY-MM-DD."""
    if value is None:
        return ""
    if is_date and isinstance(value, (int, float)):
        return (datetime.datetime(1970, 1, 1) + datetime.timedelta(milliseconds=value)).date().isoformat()
    return str(value).strip()


def _arcgis_paths(geom):
    """The paths of an ArcGIS polyline as [[[lat, lon], ...], ...] (None for other shapes or none)."""
    if not geom or not geom.get("paths"):
        return None
    paths = [[[round(y, 6), round(x, 6)] for x, y in path] for path in geom["paths"] if len(path) >= 2]
    return paths or None


def _arcgis_geometry(geom):
    """(lat, lon, rings) of an ArcGIS JSON geometry in longitude/latitude: a point's position, or a polygon's rings
    [[[lat, lon], ...], ...] with the middle of its box as its position (a polyline: its first point); (None, None,
    None) without one."""
    if not geom:
        return None, None, None
    if "x" in geom:
        return geom.get("y"), geom.get("x"), None
    if geom.get("paths"):
        x, y = geom["paths"][0][0]
        return y, x, None
    if geom.get("rings"):
        rings = [[[round(y, 6), round(x, 6)] for x, y in ring] for ring in geom["rings"] if len(ring) >= 4]
        if not rings:
            return None, None, None
        lats = [p[0] for p in rings[0]]
        lons = [p[1] for p in rings[0]]
        return (min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2, rings
    if geom.get("points"):
        x, y = geom["points"][0]
        return y, x, None
    return None, None, None


def arcgis_busy(error):
    """True for an answer that means "too much at once, ask again later": an ArcGIS busy message, a 429 or 5xx (a 504
    on a big page), a timeout or a dropped connection after post_json's own retries."""
    import urllib.error
    if isinstance(error, ValueError):
        return bool(ARCGIS_BUSY.search(str(error))) or str(error).strip() == "ArcGIS error:"
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(error, (urllib.error.URLError, ConnectionError, TimeoutError, OSError))


def arcgis_ids(url, query, box, sleep, source, depth=0):
    """The object ids of a query. A busy server is asked again after a pause; a query that still fails (a big
    state's box over a large layer: an empty "ArcGIS error:" or a 504) is asked as the box's four quarters, down to
    three levels."""
    for attempt in range(len(ARCGIS_WAITS)):
        try:
            return set(post_json(url + "/query", {**query, "returnIdsOnly": "true"}, sleep=sleep).get("objectIds")
                       or [])
        except Exception as e:  # noqa: BLE001 - a busy server: again, then smaller boxes
            if not arcgis_busy(e):
                raise
            error = e
            if box is not None and depth < 3:
                break                       # a box can be cut: quarters at once rather than waiting
            print(f"  {source}: the id query was refused ({str(e)[:60]}); again in {ARCGIS_WAITS[attempt]} s",
                  flush=True)
            sleep(ARCGIS_WAITS[attempt])
    else:
        raise error
    w, s_, e, n = box
    mx, my = (w + e) / 2, (s_ + n) / 2
    print(f"  {source}: the id query was refused ({str(error)[:60]}); asking for the box in quarters", flush=True)
    out = set()
    for quarter in ((w, s_, mx, my), (mx, s_, e, my), (w, my, mx, n), (mx, my, e, n)):
        q = dict(query, geometry=",".join(str(v) for v in quarter))
        out |= arcgis_ids(url, q, quarter, sleep, source, depth + 1)
    return out


# ArcGIS answers that mean "too much at once, ask again later": treated like a 429 (fetch_arcgis splits the request).
ARCGIS_BUSY = re.compile(r"too many|non-cacheable|unable to perform operation|exceeded|timeout|timed out|busy", re.I)
ARCGIS_WAITS = (20, 60, 120, 240, 300)
ARCGIS_SPLITS = 8                       # halvings of one chunk before a single record is left out


def fetch_arcgis(entry, region, folder, fingerprint, sleep=time.sleep):
    """An ArcGIS REST layer (see the module docstring): fetch = {"url": the layer's address (…/FeatureServer/0),
    "where": an SQL filter, "fields": the attributes to keep ("A,B,C"), "box": false for a table without shapes
    (filtered by "where" only), "page": ids per request, "simplify": degrees for polygons (maxAllowableOffset)}."""
    f = entry["fetch"]
    if f.get("urls"):
        # Several layers of the same kind (the NPS battlefields of three wars): fetched one after the other into one
        # CSV, each with its own ids.
        got = None
        parts, version, rows = [], [], 0
        for i, url in enumerate(f["urls"]):
            sub = dict(entry, id=f"{entry['id']}-{i}", fetch=dict(f, url=url, urls=None))
            got = fetch_arcgis(sub, region, folder, fingerprint, sleep)
            version.append(got["version"])
            if not fingerprint and got.get("path"):
                parts.append(got["path"])
        version = " ".join(version)
        if fingerprint:
            return {"ok": True, "version": version, "path": "", "date": ""}
        target = os.path.join(folder, entry["id"] + ".csv")
        with open(target, "w", newline="", encoding="utf-8") as out:
            writer = None
            for path in parts:
                with open(path, newline="", encoding="utf-8") as fh:
                    for row in csv.DictReader(fh):
                        if writer is None:
                            writer = csv.DictWriter(out, fieldnames=list(row), extrasaction="ignore")
                            writer.writeheader()
                        writer.writerow(row)
                        rows += 1
                os.remove(path)
        # No record in the region's box: an empty file (the build says "ok (0 in this region)").
        return {"ok": True, "version": version, "path": target, "date": datetime.date.today().isoformat()}
    url = f["url"].rstrip("/")
    meta = post_json(url, {"f": "json"}, sleep=sleep)
    dates = {fd["name"] for fd in meta.get("fields", []) if fd.get("type") == "esriFieldTypeDate"}
    base = {"f": "json", "where": f.get("where", "1=1")}
    from placepacks.regions import query_boxes
    found = set()
    for west, south, east, north in (query_boxes(region) if f.get("box", True) and meta.get("geometryType")
                                     else [(None, None, None, None)]):
        # One envelope per box of the region (Alaska has two: its bbox alone would be a band round the globe).
        query = dict(base)
        if west is not None:
            query.update(geometry=f"{west},{south},{east},{north}", geometryType="esriGeometryEnvelope", inSR="4326",
                         spatialRel="esriSpatialRelIntersects")
        found |= arcgis_ids(url, query, (west, south, east, north) if west is not None else None, sleep, entry["id"])
    ids = sorted(found)
    edited = (meta.get("editingInfo") or {}).get("lastEditDate") or ""
    version = f"{edited}:{len(ids)} records"
    if fingerprint:
        return {"ok": True, "version": version, "path": "", "date": ""}
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, entry["id"] + ".csv")
    fields = [x.strip() for x in f["fields"].split(",") if x.strip()]
    polygons = meta.get("geometryType") == "esriGeometryPolygon"
    polylines = meta.get("geometryType") == "esriGeometryPolyline"
    header = fields + ["_lat", "_lon"] + (["_rings"] if polygons else []) + (["_paths"] if polylines else [])
    page, rows = int(f.get("page", 500)), 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(header)
        def features(chunk, simplify, tries=0):
            """The features of a chunk of ids. A server that refuses heavy geometry ("Too many large geometry
            non-cacheable requests", PAD-US) or is busy is treated like a 429: after a pause the chunk is asked for
            in two halves, with its geometry simplified more, down to single records."""
            params = {"f": "json", "objectIds": ",".join(str(x) for x in chunk), "outFields": ",".join(fields),
                      "returnGeometry": "true" if meta.get("geometryType") else "false", "outSR": "4326"}
            if meta.get("geometryType"):
                params["geometryPrecision"] = 6                 # about 0.1 m: smaller answers
            if (polygons or polylines) and simplify:
                params["maxAllowableOffset"] = simplify
            try:
                return post_json(url + "/query", params, sleep=sleep, pause=f.get("pause", 0.5)).get("features", [])
            except Exception as e:  # noqa: BLE001 - a busy or overloaded server: fewer and simpler, below
                if not arcgis_busy(e):
                    raise
                why = str(e)[:60]
                if tries >= ARCGIS_SPLITS:
                    if len(chunk) == 1:
                        # One record the server will not give even alone and simplified: left out, not the layer.
                        print(f"  {entry['id']}: record {chunk[0]} left out ({why})", flush=True)
                        skipped.append(chunk[0])
                        return []
                    raise
            print(f"  {entry['id']}: the server refused {len(chunk)} records ({why}); trying again in "
                  f"{ARCGIS_WAITS[min(tries, len(ARCGIS_WAITS) - 1)]} s with fewer and simpler", flush=True)
            sleep(ARCGIS_WAITS[min(tries, len(ARCGIS_WAITS) - 1)])
            simpler = max(simplify or 0, 0.0002) * 2 if (polygons or polylines) else simplify
            if len(chunk) == 1:
                return features(chunk, simpler, tries + 1)
            half = len(chunk) // 2
            return features(chunk[:half], simpler, tries + 1) + features(chunk[half:], simpler, tries + 1)

        skipped = []
        chunks = [ids[i:i + page] for i in range(0, len(ids), page)]
        # "parallel": pages asked for several at a time (the large NHD layers), written in order.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, int(f.get("parallel", 1)))) as pool:
            pages = pool.map(lambda c: features(c, f.get("simplify")), chunks)
            all_features = (feat for got in pages for feat in got)
            for feat in all_features:
                attrs = feat.get("attributes") or {}
                lat, lon, rings = _arcgis_geometry(feat.get("geometry"))
                row = [_arcgis_value(attrs.get(name), name in dates) for name in fields]
                row += ["" if lat is None else f"{lat:.6f}", "" if lon is None else f"{lon:.6f}"]
                if polygons:
                    row.append(json.dumps(rings, separators=(",", ":")) if rings else "")
                if polylines:
                    paths = _arcgis_paths(feat.get("geometry"))
                    row.append(json.dumps(paths, separators=(",", ":")) if paths else "")
                w.writerow(row)
                rows += 1
    os.replace(target + ".partial", target)
    return {"ok": True, "version": version, "path": target, "date": datetime.date.today().isoformat()}


# ------------------------------------------------------------------------------------------- Wikidata, all items


def wikidata_tiles(ask, tiles, pause=0, limit=None, query=None):
    """Every row of the "all" mode over tiles, splitting a tile into four when it times out (or is refused once the
    retries are spent) or fills the row limit, down to wikidata.MIN_TILE degrees. ask(query) returns the rows;
    query(box, limit): the query of a tile (default wikidata.all_query)."""
    from placepacks.readers import wikidata as wd
    limit = limit or wd.ALL_LIMIT
    rows, todo, skipped = [], list(tiles), []
    while todo:
        box = todo.pop()
        small = box[2] - box[0] <= wd.MIN_TILE or box[3] - box[1] <= wd.MIN_TILE
        try:
            got = ask((query or wd.all_query)(box, limit))
        except Exception as e:  # noqa: BLE001 - a timeout (504): ask for the four quarters instead
            if small:
                # The smallest tile still fails: it is left out (said in the log), the rest of the region is kept.
                skipped.append(box)
                print(f"  Wikidata: a tile of {box} could not be read ({str(e)[:80]}); left out", flush=True)
                continue
            todo += wd.split_tile(box)
            continue
        finally:
            time.sleep(pause)
        if len(got) >= limit and not small:
            todo += wd.split_tile(box)
            continue
        rows += got
    if skipped and not rows:
        raise ValueError(f"no tile of the region could be read ({len(skipped)} tried)")
    return rows


# ------------------------------------------------------------------------------------------- NCES school years


def _nces_rows(path):
    """(id, name, lat, lon) of the schools of one yearly EDGE file, whichever form the year has: a pipe-separated
    .TXT without a header (id, district id, name, ..., latitude and longitude in the 13th and 14th fields), else a
    shapefile (NCESSCH, NAME, LAT..., LON...)."""
    import io
    import zipfile
    import shapefile
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        txt = next((n for n in names if n.lower().endswith(".txt")), None)
        if txt:
            for line in io.TextIOWrapper(z.open(txt), encoding="utf-8", errors="replace"):
                f = line.rstrip("\r\n").split("|")
                if len(f) > 13 and f[0].isdigit():
                    yield f[0], f[2], f[12], f[13]
            return
        shp = next((n for n in names if n.lower().endswith(".shp")), None)
    if not shp:
        return
    with shapefile.Reader(f"{path}/{shp}", encoding="utf-8", encodingErrors="replace") as r:
        fields = [f[0] for f in r.fields[1:]]
        lat_f = next(n for n in fields if n.upper().startswith("LAT"))
        lon_f = next(n for n in fields if n.upper().startswith("LON"))
        for rec in r.iterRecords():
            d = dict(zip(fields, rec))
            if d.get("NCESSCH"):
                yield str(d["NCESSCH"]), d.get("NAME") or d.get("SCH_NAME") or "", d[lat_f], d[lon_f]


def nces_history_to_csv(paths, target):
    """The public schools of NCES's yearly EDGE geocode files (one .zip a school year, "..._1516.zip") that are gone
    from the newest year, as CSV: id, name, lat, lon, first (September of its first year), last (June after its last
    year). Returns the rows. The schools still open come from the current year's source."""
    import re as _re
    seen, newest = {}, None
    years = sorted(((int(m.group(1)), p) for p in paths for m in [_re.search(r"_(\d{4})\.zip$", p)] if m))
    for code, path in years:
        y1 = 2000 + code // 100                       # 1516 -> autumn 2015
        newest = code
        for sid, name, lat, lon in _nces_rows(path):
            s_ = seen.setdefault(sid, {"first": y1, "code": code})
            s_.update(name=name, lat=lat, lon=lon, last=y1 + 1, code=code)
    count = 0
    with open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["id", "name", "lat", "lon", "first", "last"])
        for sid, s_ in seen.items():
            if s_["code"] == newest or not s_["name"]:
                continue
            w.writerow([sid, s_["name"], s_["lat"], s_["lon"], f"{s_['first']}-09", f"{s_['last']}-06"])
            count += 1
    return count


# ------------------------------------------------------------------------------------------- Who's On First

# The geometry sources (src:geom) of Who's On First records whose licence allows a pack: Mapzen and Who's On First's
# own work (CC0), Mesoshapes (CC0), Natural Earth and the US Census (public domain), Quattroshapes, Zetashapes,
# GeoNames and GeoPlanet (CC BY), Statistics Canada (OGL-Canada). OpenStreetMap-derived records (ODbL) and unknown
# sources are left out.
WOF_OPEN = {"mz", "mapzen", "whosonfirst", "wof", "meso", "naturalearth", "ne", "us-census", "uscensus", "census",
            "quattroshapes", "quattroshapes_pg", "qs", "qs_pg", "zetashapes", "zs", "geonames", "gn", "geoplanet", "gp", "woe", "statcan"}
WOF_PLACETYPES = ("neighbourhood", "macrohood", "microhood", "borough", "campus")


def wof_to_csv(db_path, target):
    """Write the current neighbourhoods (and boroughs and campuses) of a Who's On First SQLite bundle whose geometry
    source is open (WOF_OPEN) as CSV: id, name, placetype, source, lat, lon. Returns the rows."""
    import sqlite3
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    count = 0
    marks = ",".join("?" * len(WOF_PLACETYPES))
    with open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["id", "name", "placetype", "source", "lat", "lon"])
        rows = con.execute(f"SELECT s.id, s.name, s.placetype, s.latitude, s.longitude, g.body FROM spr s JOIN geojson g "
                           f"ON g.id = s.id WHERE s.placetype IN ({marks}) AND s.is_current != 0 AND "
                           f"s.is_deprecated = 0 AND s.is_superseded = 0", WOF_PLACETYPES)
        seen = set()
        for wid, name, placetype, lat, lon, body in rows:
            if wid in seen:
                continue                # a record's alternate geometries come as more rows: one place each
            try:
                props = json.loads(body).get("properties", {})
            except ValueError:
                continue
            src = str(props.get("src:geom", "")).lower()
            if src not in WOF_OPEN or not name:
                continue
            seen.add(wid)
            w.writerow([wid, name, placetype, src, f"{lat:.6f}", f"{lon:.6f}"])
            count += 1
    con.close()
    return count


def bunzip(path, target):
    """Decompress a .bz2 file to target in pieces (a WOF bundle is several GB unpacked)."""
    import bz2
    with bz2.open(path, "rb") as src, open(target, "wb") as dst:
        while True:
            chunk = src.read(1 << 22)
            if not chunk:
                break
            dst.write(chunk)


# ------------------------------------------------------------------------------------------- All The Places

# Offices of individual people (an insurance agent's or an estate agent's own office, a financial adviser): left out.
ATP_PERSONAL = {"office": {"insurance", "estate_agent", "financial_advisor", "financial", "lawyer", "tax_advisor",
                           "accountant"}}
_PERSON = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.?)?(?: [A-Z][a-z'-]+){1,2}(?:,? (?:Jr|Sr|II|III)\.?)?$")


def atp_to_csv(zip_path, target, boxes):
    """Write the chain locations of an All The Places run (a .zip of one GeoJSON FeatureCollection per spider) that
    fall in any of boxes ([(west, south, east, north)]) as one CSV: key, spider, name, branch, brand, brand_wikidata,
    the OSM-style tags that give the class and type, lat, lon. Offices of individuals and names that are a person's
    are left out. Returns the number of rows."""
    import zipfile
    from placepacks import types as place_types
    from placepacks.readers.osm import main_tag
    count = 0
    fields = ["key", "spider", "name", "branch", "brand", "brand_wikidata", "main_key", "main_value", "type", "lat",
              "lon"]
    with zipfile.ZipFile(zip_path) as z, open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(fields)
        for info in z.infolist():
            if not info.filename.endswith(".geojson"):
                continue
            try:
                data = json.loads(z.read(info).decode("utf-8"))
            except ValueError:
                continue
            for feat in data.get("features", []):
                geom, tags = feat.get("geometry") or {}, feat.get("properties") or {}
                if geom.get("type") != "Point":
                    continue
                lon, lat = geom["coordinates"][:2]
                if not any(wb <= lon <= eb and sb <= lat <= nb for wb, sb, eb, nb in boxes):
                    continue
                if any(tags.get(k) in v for k, v in ATP_PERSONAL.items()):
                    continue
                name = (tags.get("name") or tags.get("brand") or "").strip()
                if not name or _PERSON.match(name):
                    continue
                found = main_tag({k: str(v) for k, v in tags.items()})
                spider = tags.get("@spider", "")
                w.writerow([f"{spider}:{tags.get('ref') or feat.get('id', '')}", spider, name, tags.get("branch", ""),
                            tags.get("brand", ""), tags.get("brand:wikidata", ""), found[0] if found else "",
                            found[1] if found else "", place_types.osm({k: str(v) for k, v in tags.items()}),
                            f"{lat:.6f}", f"{lon:.6f}"])
                count += 1
    return count


# ------------------------------------------------------------------------------------------- the USCG Light List

# Positions as the Light List prints them: degrees-minutes-seconds ("41-04-15.534N") or degrees and minutes
# ("41 04.3 N"); longitudes have up to three degree digits.
_DMS = r"(\d{1,3})-(\d{1,2})-(\d{1,2}(?:\.\d+)?)\s*([NSEW])"
_DM = r"(\d{1,3})\s+(\d{1,2}(?:\.\d+)?)\s*([NSEW])\b"
_ENTRY = re.compile(r"^\s*(\d{1,5}(?:\.\d{1,3})?)\s+(\S.*)$")
# A lighthouse or major light: its structure is a tower or a house (not a skeleton tower, pole, post, dolphin or
# spindle), and it is not a buoy or a daybeacon.
_KEEP = re.compile(r"\b(tower|lighthouse|house|dwelling|light station)\b", re.I)
_SKIP = re.compile(r"\b(skeleton|pole|post|dolphin|spindle|buoy|daybeacon|daymark)\b", re.I)


def _degrees(match):
    """Signed decimal degrees of a _DMS or _DM match."""
    parts = match.groups()
    if len(parts) == 4:
        value = int(parts[0]) + int(parts[1]) / 60 + float(parts[2]) / 3600
    else:
        value = int(parts[0]) + float(parts[1]) / 60
    return -value if parts[-1] in "SW" else value


def light_position(text):
    """(lat, lon) of the first latitude and longitude in text (either format), or None."""
    for pattern in (_DMS, _DM):
        found = [m for m in re.finditer(pattern, text)]
        lat = next((m for m in found if m.group(len(m.groups())) in "NS"), None)
        lon = next((m for m in found if m.group(len(m.groups())) in "EW"), None)
        if lat and lon:
            return round(_degrees(lat), 6), round(_degrees(lon), 6)
    return None


def is_lighthouse(name, block):
    """True for a lighthouse or major light: named "... Light", its entry describes a tower or house, and it is not
    a skeleton tower, pole, buoy or daybeacon."""
    return bool(re.search(r"\blight\b", name, re.I)) and not re.search(r"\b(buoy|daybeacon|range)\b", name, re.I) \
        and bool(_KEEP.search(block)) and not _SKIP.search(block)


def light_list_text(text, volume):
    """The lighthouses of one Light List volume's text (the PDF's columns, read line by line: No., Name and Location,
    Position, Characteristic, Height, Range, Structure, Remarks). Returns [(volume, number, name, lat, lon,
    structure text)]."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if _ENTRY.match(line) and
              light_position(" ".join(lines[i:i + 3]))]
    out = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else min(len(lines), i + 8)
        block = " ".join(x.strip() for x in lines[i:end])
        number, rest = _ENTRY.match(lines[i]).groups()
        at = re.search(_DMS, rest) or re.search(_DM, rest)
        name = " ".join((rest[:at.start()] if at else rest).split()).strip(" .,")
        position = light_position(block)
        if position and name and is_lighthouse(name, block):
            out.append((volume, number, name, *position, block[:200]))
    return out


def light_list_xml(path, volume):
    """The lighthouses of a Light List XML file: every element with a child whose tag holds "name" and one whose
    text holds a position (the documented fields: LLNR, Aid Name, Position, Characteristic, Height, Range,
    Structure, Remarks)."""
    import xml.etree.ElementTree as ET
    out = []
    for _, el in ET.iterparse(path, events=("end",)):
        kids = {c.tag.split("}")[-1].lower(): " ".join((c.text or "").split()) for c in el}
        name = next((v for k, v in kids.items() if "name" in k), "")
        position = light_position(" ".join(v for k, v in kids.items() if "pos" in k or "lat" in k or "lon" in k))
        if not name or not position:
            continue
        number = next((v for k, v in kids.items() if "llnr" in k or k in ("number", "no")), "")
        block = " ".join(kids.values())
        if is_lighthouse(name, block):
            out.append((volume, number, name, *position, kids.get("structure", "")[:200]))
        el.clear()
    return out


def light_list_to_csv(paths, target):
    """Write the lighthouses of the downloaded Light List volumes (XML preferred, else text PDFs read with pypdf) as
    one CSV. A volume whose PDF has no text layer (scanned) is reported and left out. Returns the number kept."""
    rows = []
    for path in sorted(paths):
        volume = (re.search(r"V(?:ol(?:ume)?)?[ _%20-]*([IVX]+|\d)", os.path.basename(path), re.I) or
                  re.search(r"(\d)", os.path.basename(path)))
        volume = volume.group(1) if volume else os.path.basename(path)
        if path.lower().endswith(".xml"):
            rows += light_list_xml(path, volume)
            continue
        from pypdf import PdfReader
        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        if len(text.strip()) < 1000:
            print(f"  {os.path.basename(path)}: no text layer (a scanned volume); not read")
            continue
        rows += light_list_text(text, volume)
    with open(target, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["volume", "llnr", "name", "lat", "lon", "structure"])
        w.writerows(rows)
    return len(rows)


def get_page(url, folder, pause, sleep=time.sleep):
    """The text of one page of an API answer (downloaded through download(), so a busy host is tried again)."""
    tmp = os.path.join(folder, ".page")
    download(url, tmp, pause, sleep=sleep)
    with open(tmp, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    os.remove(tmp)
    return text


def socrata_version(domain, datasets, opener=None):
    """"<id>:<rowsUpdatedAt>,..." of a Socrata portal's datasets (their metadata, one small request each)."""
    return ",".join(f"{d}:{read_json(f'https://{domain}/api/views/{d}.json', opener).get('rowsUpdatedAt', '')}"
                    for d in datasets)


def append_csv(text, writer_state, out):
    """Append the rows of one CSV page to out (the header of the first page only). Returns the rows added."""
    reader = csv.DictReader(io.StringIO(text))
    if writer_state.get("w") is None:
        writer_state["w"] = csv.DictWriter(out, fieldnames=reader.fieldnames or [], extrasaction="ignore")
        writer_state["w"].writeheader()
    n = 0
    for row in reader:
        writer_state["w"].writerow(row)
        n += 1
    return n


def fetch_socrata(entry, folder, fingerprint, opener=None, sleep=time.sleep):
    """A Socrata source (see the module docstring): fetch = {"domain", "queries": [{"dataset", "select", "where",
    "group", "order"}], "page": rows per request}. Every query's $select gives the same column names (aliases), so
    the pages make one CSV. Returns the fetched.json entry."""
    f = entry["fetch"]
    queries, page = f["queries"], int(f.get("page", 50000))
    version = socrata_version(f["domain"], list(dict.fromkeys(q["dataset"] for q in queries)), opener)
    if fingerprint:
        return {"ok": True, "version": version, "path": "", "date": ""}
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, entry["id"] + ".csv")
    state, rows = {}, 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        for q in queries:
            offset = 0
            while True:
                params = {"$select": q["select"], "$limit": page, "$offset": offset,
                          "$order": q.get("order") or q.get("group") or ":id"}
                if q.get("where"):
                    params["$where"] = q["where"]
                if q.get("group"):
                    params["$group"] = q["group"]
                url = f"https://{f['domain']}/resource/{q['dataset']}.csv?" + urllib.parse.urlencode(params)
                got = append_csv(get_page(url, folder, f.get("pause", 1), sleep), state, out)
                rows += got
                if got < page:
                    break
                offset += page
    os.replace(target + ".partial", target)
    return {"ok": rows > 0, "version": version, "path": target, "date": datetime.date.today().isoformat(),
            **({} if rows else {"status": "failed", "reason": "the portal returned no rows"})}


def fetch_ckan_sql(entry, folder, fingerprint, opener=None):
    """A CKAN datastore SQL source (see the module docstring): fetch = {"url": the portal's datastore_search_sql
    address, "queries": [SQL without LIMIT, with an ORDER BY], "page": rows per request}. Returns the fetched.json
    entry."""
    f = entry["fetch"]
    version = datetime.date.today().strftime("%Y-%m")
    if fingerprint:
        return {"ok": True, "version": version, "path": "", "date": ""}
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, entry["id"] + ".csv")
    page, rows, fields = int(f.get("page", 5000)), 0, None
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        w = None
        for sql in f["queries"]:
            offset = 0
            while True:
                url = f["url"] + "?" + urllib.parse.urlencode({"sql": f"{sql} LIMIT {page} OFFSET {offset}"})
                records = read_json(url, opener).get("result", {}).get("records", [])
                for rec in records:
                    if w is None:
                        fields = [k for k in rec if not k.startswith("_")]
                        w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
                        w.writeheader()
                    w.writerow({k: "" if rec.get(k) is None else rec.get(k) for k in fields})
                rows += len(records)
                if len(records) < page:
                    break
                offset += page
                time.sleep(f.get("pause", 1))
    os.replace(target + ".partial", target)
    return {"ok": rows > 0, "version": version, "path": target, "date": datetime.date.today().isoformat()}


def fetch_wfs(entry, folder, fingerprint, opener=None, sleep=time.sleep):
    """A WFS layer as CSV (see the module docstring): fetch = {"url": GetFeature address with the layer,
    "properties": the columns, "sort": a column for stable paging, "page": features per request}."""
    f = entry["fetch"]
    with (opener or request)(f["url"] + "&resultType=hits") as r:
        found = re.search(r'numberMatched="(\d+)"', r.read(4000).decode("utf-8", "replace"))
    total = int(found.group(1)) if found else 0
    version = f"{total} features"
    if fingerprint:
        return {"ok": bool(total), "version": version, "path": "", "date": ""}
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, entry["id"] + ".csv")
    page, state, rows, start = int(f.get("page", 5000)), {}, 0, 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        while start < max(total, 1):
            url = (f["url"] + "&" + urllib.parse.urlencode({"outputFormat": "csv", "srsName": "EPSG:4326",
                                                             "propertyName": f["properties"], "sortBy": f["sort"],
                                                             "count": page, "startIndex": start}))
            got = append_csv(get_page(url, folder, f.get("pause", 1), sleep), state, out)
            rows += got
            if got == 0:
                break
            start += got
    os.replace(target + ".partial", target)
    return {"ok": rows > 0, "version": version, "path": target, "date": datetime.date.today().isoformat()}


def resolve(entry, values, opener=None):
    """The placeholders of a source with any "latest" release replaced by the newest one found."""
    values = dict(values)
    for key in ("overture_release", "fsq_release"):
        if values.get(key) == "latest" and entry.get("release_setting") == key:
            try:
                values[key] = latest_release(entry, opener)
            except ValueError as e:
                if entry.get("unavailable_reason") and "no release found" in str(e):
                    raise SourceUnavailable(entry["unavailable_reason"]) from e
                raise
    return values


class SourceUnavailable(Exception):
    """A source that its publisher no longer offers openly: reported as skipped (its "unavailable_reason")."""


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
        from placepacks.readers import wikidata as wd
        target = os.path.join(folder, "wikidata.json")
        os.makedirs(folder, exist_ok=True)

        def ask(query, retries=RETRY_WAITS):
            """One SPARQL query's rows; a busy service is tried again."""
            body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
            for attempt in range(len(retries) + 1):
                try:
                    with request(url, "POST", body, {"Accept": "application/sparql-results+json",
                                                      "Content-Type": "application/x-www-form-urlencoded"}) as r:
                        return json.loads(r.read().decode("utf-8")).get("results", {}).get("bindings", [])
                except Exception as e:  # noqa: BLE001 - tried again when it is temporary
                    if attempt >= len(retries) or not retryable(e):
                        raise
                    time.sleep(retries[attempt])

        def count(box):
            """The number of items with coordinates in a tile (None when the service would not say)."""
            try:
                rows = ask(wd.count_query(box), RETRY_WAITS[:1])
                time.sleep(min(pause, 2))
                return int(rows[0]["n"]["value"]) if rows else 0
            except Exception:  # noqa: BLE001 - the tile is asked for anyway, and split if it times out
                return None

        # The tiles are planned once with fast counts: empty tiles (sea, ice) are skipped, dense ones split, so
        # Alaska asks for a few dozen tiles and Vermont for a few, not a thousand fixed-size ones.
        # The plan is made once per region and shared by the Wikidata sources (places, names, filming locations).
        plan_file = os.path.join(os.path.dirname(folder), "_wikidata_tiles.json")
        planned = None
        if os.path.exists(plan_file):
            try:
                planned = [tuple(t) for t in json.load(open(plan_file, encoding="utf-8"))]
            except ValueError:
                planned = None
        if planned is None:
            planned = wd.plan_tiles(region, count)
            try:
                with open(plan_file, "w", encoding="utf-8") as fh:
                    json.dump(planned, fh)
            except OSError:
                pass
        print(f"  {entry['id']}: {len(planned)} Wikidata tiles", flush=True)
        bindings = []
        if f.get("mode") == "filming":
            bindings = wikidata_tiles(lambda q: ask(q, RETRY_WAITS[:2]), planned, pause,
                                      f.get("limit", wd.ALL_LIMIT), query=wd.filming_query)
        elif f.get("mode") == "labels":
            # Other-language names of the items with coordinates, tile by tile (the optional "names" part).
            bindings = wikidata_tiles(lambda q: ask(q, RETRY_WAITS[:2]), planned, pause,
                                      f.get("limit", wd.ALL_LIMIT), query=lambda box, n: wd.labels_query(box, n,
                                                                                                         f["languages"]))
        elif f.get("mode", "all") == "all":
            # A tile that times out is split at once rather than asked again and again.
            bindings = wikidata_tiles(lambda q: ask(q, RETRY_WAITS[:2]), planned, pause,
                                      f.get("limit", wd.ALL_LIMIT))
        else:
            # The class query ("mode": "classes"), one group of classes at a time, tile by tile like the others: a
            # tile that times out (504) is split into four.
            ids = list(wd.CLASSES)
            for i in range(0, len(ids), wd.GROUP):
                group = " ".join(f"wd:{q}" for q in ids[i:i + wd.GROUP])
                bindings += wikidata_tiles(lambda q: ask(q, RETRY_WAITS[:2]), planned,
                                           pause, f.get("limit", wd.ALL_LIMIT),
                                           query=lambda box, n, g=group: wd.class_query(box, g))
        with open(target, "w", encoding="utf-8") as fh:
            json.dump({"results": {"bindings": bindings}}, fh)
        out.update(ok=True, path=target, date=datetime.date.today().isoformat())
        return out
    if method == "national":
        folder = os.path.join(national or "national", entry["id"])
        failed = os.path.join(folder, FAILED)
        if os.path.exists(failed) and not fingerprint:
            out.update(status="skipped", reason="could not be downloaded: " +
                       open(failed, encoding="utf-8").read().strip())
            return out
        if f.get("socrata_blob"):
            # The publisher's own version (blobId and rowsUpdatedAt), the same in the plan and in the build.
            url, name, version = national_files(entry, values)[0]
            path = os.path.join(folder, name)
        elif f.get("per_country") or f.get("listing") or f.get("urls") or f.get("json_url"):
            path, version = folder, ""
        else:
            path, version = os.path.join(folder, os.path.basename(urllib.parse.urlsplit(url).path)), ""
        stamp = path + ".version"
        if not os.path.exists(path) and os.path.isdir(folder):
            path = folder                   # the region's slice made by placepacks.split
        out.update(ok=os.path.exists(path), path=path,
                   version=version or (open(stamp, encoding="utf-8").read() if os.path.exists(stamp) else url))
        if not out["ok"] and not fingerprint:
            out.update(status="failed", reason="the national file was not downloaded by the prepare job")
        return out
    if method == "tiger_counties":
        prefix, suffix = f["prefix"].format(**values), f["suffix"]
        with request(url) as r:
            listing = r.read().decode("utf-8", "replace")
        names = sorted(set(re.findall(rf'href="({re.escape(prefix)}\d*{re.escape(suffix)})"', listing)))
        if region.get("counties"):
            # A sub-region of a state: only its counties' files (and those next to it; regions.json "counties").
            mine = set(region["counties"])
            names = [n for n in names if len(n) - len(prefix) - len(suffix) != 3 or
                     n[len(prefix):len(prefix) + 3] in mine]
        out["version"] = f"{url} ({len(names)} files)"
        if fingerprint:
            out["ok"] = bool(names)
            return out
        # The counties several at a time ("parallel", default 8: polite for www2.census.gov, which serves them as
        # static files); a file already there (a rerun) is not fetched again.
        from concurrent.futures import ThreadPoolExecutor
        todo = [n for n in names if not os.path.exists(os.path.join(folder, n))]
        with ThreadPoolExecutor(max_workers=max(1, int(f.get("parallel", 8)))) as pool:
            for _ in pool.map(lambda n: download(url + n, os.path.join(folder, n), pause), todo):
                pass
        # A state with no file of this kind (Delaware has no elementary school districts): an empty folder, which
        # the build reports as "ok (0 in this region)".
        os.makedirs(folder, exist_ok=True)
        out.update(ok=True, path=folder, date=datetime.date.today().isoformat())
        return out
    if method == "overpass":
        # One Overpass query for the region's box ({south},{west},{north},{east} in the entry's "query").
        out["version"] = datetime.date.today().strftime("%Y-%m")
        if fingerprint:
            out["ok"] = True
            return out
        from placepacks.regions import query_boxes
        target = os.path.join(folder, entry["id"] + ".json")
        os.makedirs(folder, exist_ok=True)
        merged = None
        for west, south, east, north in query_boxes(region):
            # One query per box of the region; the answers' elements are put together.
            body = urllib.parse.urlencode({"data": f["query"].format(south=south, west=west, north=north,
                                                                      east=east)}).encode()
            with request(url, "POST", body, {"Content-Type": "application/x-www-form-urlencoded"}, timeout=400) as r:
                answer = json.loads(r.read().decode("utf-8"))
            if merged is None:
                merged = answer
            else:
                merged.setdefault("elements", []).extend(answer.get("elements", []))
            time.sleep(pause)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(merged or {"elements": []}, fh)
        out.update(ok=True, path=target, date=datetime.date.today().isoformat())
        return out
    if method == "gtfs":
        return fetch_gtfs(entry, region, url, folder, pause, fingerprint)
    if method == "socrata":
        return fetch_socrata(entry, folder, fingerprint)
    if method == "wfs":
        return fetch_wfs(entry, folder, fingerprint)
    if method == "arcgis":
        return fetch_arcgis(entry, region, folder, fingerprint)
    if method == "ckan_sql":
        return fetch_ckan_sql(entry, folder, fingerprint)
    # http
    if fingerprint:
        if f.get("no_head"):
            # A host that does not answer HEAD (the FDIC's API): the source changes with the month.
            out.update(ok=True, version=datetime.date.today().strftime("%Y-%m"))
            return out
        with request(url, "HEAD") as r:
            out.update(ok=True, version=version_of(r.headers))
        return out
    target = os.path.join(folder, f.get("file") or os.path.basename(urllib.parse.urlsplit(url).path))
    version, date = download(url, target, pause)
    if f.get("no_head"):
        version = datetime.date.today().strftime("%Y-%m")     # the same version as the plan's fingerprint
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
        state = catalogue.parent_values(region).get("name") or region["name"]      # a sub-region: its state's
        if (row.get("location.subdivision_name") or "").lower() != state.lower():
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
    from placepacks.status import one_line
    if got.get("status") == "ok":
        rows = got.get("rows", rows)
        count = (got["note"] if got.get("note") else f"{rows} rows") if rows is not None else None
        bits = [one_line(got.get("version", ""), 80) or "no version"] + ([count] if count else [])
        return f"{source}: ok ({', '.join(bits)})"
    return f"{source}: {got.get('status', 'failed')} ({one_line(got.get('reason', ''))})"


FETCH_WORKERS = 4                # sources fetched at the same time in one region's job
HOST_LIMIT = 2                   # at most this many of them against the same host
HOST_LIMITS = {"query.wikidata.org": 1, "overpass-api.de": 1, "overpass-api.openhistoricalmap.org": 1,
               "download.geofabrik.de": 1}
TIME_LIMIT_MIN = 20              # minutes a source may take (its "time_limit_min" in sources.json)
FINGERPRINT_LIMIT_MIN = 5        # minutes for a fingerprint (the plan job only asks versions)


def host_of(entry, values=None):
    """The host a source mostly talks to (for the per-host limit)."""
    f = entry["fetch"]
    for key in ("url", "metadata", "listing", "domain"):
        text = f.get(key)
        if text:
            text = text if "//" in text else "https://" + text
            try:
                return urllib.parse.urlsplit(text.format(**(values or {}))).hostname or ""
            except (KeyError, IndexError, ValueError):
                return urllib.parse.urlsplit(text).hostname or ""
    return f.get("method", "")


def _limit_seconds(entry, fingerprint):
    """The wall-clock limit of one source, in seconds."""
    if fingerprint:
        return 60 * FINGERPRINT_LIMIT_MIN
    return 60 * float(entry.get("time_limit_min", TIME_LIMIT_MIN))


def _fetch_one(entry, region, cat, work, national, fingerprint):
    """fetch_source with its errors as a failed result (run in a child process)."""
    values = catalogue.settings_for(cat, region)
    try:
        return fetch_source(entry, region, values, work, national, fingerprint)
    except SourceUnavailable as e:
        return {"ok": False, "version": "", "path": "", "status": "skipped", "reason": str(e)}
    except Exception as e:  # noqa: BLE001 - recorded; the build leaves the source out
        return {"ok": False, "version": "", "path": "", "error": str(e)[:300], "status": "failed",
                "reason": str(e)[:300]}


def _child(queue, entry, region, cat, work, national, fingerprint):
    """The body of a source's process: its result goes back through the queue."""
    t = time.time()
    got = _fetch_one(entry, region, cat, work, national, fingerprint)
    got["seconds"] = round(time.time() - t, 1)
    queue.put((entry["id"], got))


def _too_long(entry, seconds):
    """The result of a source stopped at its time limit."""
    minutes = seconds / 60
    text = f"took longer than {minutes:.0f} min" if minutes >= 1 else f"took longer than {seconds:.0f} s"
    return {"ok": False, "version": "", "path": "", "status": "failed", "reason": text, "error": text,
            "seconds": seconds}


def run_with_limit(entry, region, cat, work, national, fingerprint=False):
    """One source in its own process, stopped after its time limit. Returns its result."""
    return next(got for _, got in run_parallel([entry], region, cat, work, national, fingerprint, 1))


def run_parallel(entries, region, cat, work, national, fingerprint=False, workers=FETCH_WORKERS):
    """Fetch entries, workers at a time, each in a forked process with its time limit; at most HOST_LIMIT (or
    HOST_LIMITS[host]) at once against one host. Yields (entry, result) as each one ends."""
    import multiprocessing
    import queue as queue_module
    ctx = multiprocessing.get_context("fork")
    results = ctx.Queue()
    values = catalogue.settings_for(cat, region)
    waiting = list(entries)
    running = {}                                    # id -> (entry, process, started, host)
    by_id = {e["id"]: e for e in entries}
    while waiting or running:
        # Start what may start: free workers, and a host not already at its limit.
        busy = {}
        for _, _, _, host in running.values():
            busy[host] = busy.get(host, 0) + 1
        for entry in list(waiting):
            if len(running) >= max(1, workers):
                break
            host = host_of(entry, values)
            if busy.get(host, 0) >= HOST_LIMITS.get(host, HOST_LIMIT):
                continue
            proc = ctx.Process(target=_child, args=(results, entry, region, cat, work, national, fingerprint),
                               daemon=True)
            proc.start()
            running[entry["id"]] = (entry, proc, time.time(), host)
            busy[host] = busy.get(host, 0) + 1
            waiting.remove(entry)
        try:
            sid, got = results.get(timeout=1)
        except queue_module.Empty:
            sid, got = None, None
        if sid is not None and sid in running:
            entry, proc, _, _ = running.pop(sid)
            proc.join(5)
            yield by_id[sid], got
        now = time.time()
        for sid, (entry, proc, started, _) in list(running.items()):
            limit = _limit_seconds(entry, fingerprint)
            if now - started > limit:
                proc.kill()
                proc.join(5)
                running.pop(sid)
                yield entry, _too_long(entry, limit)
            elif not proc.is_alive() and proc.exitcode not in (None, 0):
                running.pop(sid)
                yield entry, {"ok": False, "version": "", "path": "", "status": "failed",
                              "reason": f"its process stopped (exit code {proc.exitcode})"}


def fetch_region(region_id, work, parts=fmt.PARTS, national=None, fingerprint=False, cat=None, only=None):
    """Fetch every source of a region's parts. Returns the fetched dict (also written to work/fetched.json)."""
    cat = cat or catalogue.load()
    region = dict(catalogue.regions()[region_id])
    os.makedirs(work, exist_ok=True)
    result = {}
    entries = [e for part in parts for e in catalogue.sources_for(region, part, cat, only)]

    def finish(entry, got):
        """Record one source's result (its status and reason filled in) and print its status line (not when
        only fingerprinting)."""
        if got.get("ok"):
            got["status"], got["reason"] = "ok", ""
        got.setdefault("status", "failed")
        got.setdefault("reason", got.get("error", "") or "nothing was downloaded")
        result[entry["id"]] = got
        if not fingerprint:
            print(status_line(entry["id"], got) + (f" [{got['seconds']:.0f} s]" if got.get("seconds") else ""),
                  flush=True)

    # OpenStreetMap first and alone: the later slices use its extract's own box.
    for entry in [e for e in entries if e["id"] == "osm"]:
        finish(entry, run_with_limit(entry, region, cat, work, national, fingerprint))
        if result["osm"].get("ok") and not fingerprint and region.get("parent"):
            result["osm"]["path"] = clip_osm(result["osm"]["path"], region)
        if result["osm"].get("ok") and not fingerprint:
            box = extract_bbox(result["osm"]["path"])
            if box and not region.get("boxes"):
                region["bbox"] = box            # the later slices use the extract's own box
                result["_bbox"] = box           # (a region with its own boxes, Alaska, keeps them)
    # The others several at a time, each in its own process with a time limit (a source that hangs is stopped and
    # reported, and the build goes on), never more than HOST_LIMIT at once against the same host.
    rest = [e for e in entries if e["id"] != "osm"]
    workers = int(os.environ.get("PLACEPACKS_FETCH_WORKERS", FETCH_WORKERS))
    for entry, got in run_parallel(rest, region, cat, work, national, fingerprint, workers):
        finish(entry, got)
    if not fingerprint:
        with open(os.path.join(work, "fetched.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    return result


def clip_osm(path, region):
    """A sub-region's part of its parent's OpenStreetMap extract (osmium extract, "smart": a street or an area that
    crosses the border is kept whole), next to the extract. When osmium-tool is not installed the whole extract is
    used: the pack writer keeps only what is in the sub-region (PackWriter clip), only more slowly."""
    import shutil
    import subprocess
    if not shutil.which("osmium"):
        print(f"  osm: osmium-tool is not installed; the whole extract of {region['parent']} is read", flush=True)
        return path
    west, south, east, north = region["bbox"]
    m = 0.05                            # a little more than the sub-region (the packs overlap at the border)
    target = os.path.join(os.path.dirname(path), "clipped.osm.pbf")
    t = time.time()
    subprocess.run(["osmium", "extract", "--bbox", f"{west - m},{south - m},{east + m},{north + m}",
                    "--strategy", "smart", "--overwrite", "--output", target, path], check=True)
    print(f"  osm: clipped to {region['id']} in {time.time() - t:.0f} s "
          f"({os.path.getsize(target) / 1e6:.0f} MB of {os.path.getsize(path) / 1e6:.0f} MB)", flush=True)
    os.remove(path)
    return target


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
        try:
            prepare_national(entry, national, catalogue.settings_for(cat, any_region))
        except Exception as e:  # noqa: BLE001 - that layer is left out this time
            print(f"{entry['id']}: not downloaded ({e})")
            # The region builds say why ("skipped (could not be downloaded: ...)"), from this note.
            folder = os.path.join(national, entry["id"])
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, FAILED), "w", encoding="utf-8") as fh:
                fh.write(str(e)[:300])


def prepare_national(entry, national, values):
    """Download a national source's files into national/<id>/ (see national_files). A file restored from the
    Actions cache is kept unless the publisher's version changed (or cannot be asked); files of an older release
    are deleted once the new one is in; "xml_records" turns the downloaded XML files into one CSV."""
    f = entry["fetch"]
    folder = os.path.join(national, entry["id"])
    files = national_files(entry, values)
    if not files:
        raise ValueError("the publisher lists no file")
    kept, failed = [], 0
    for url, name, known in files:
        target = os.path.join(folder, name)
        stamp = target + ".version"
        kept.append(name)
        if os.path.exists(target) and os.path.exists(stamp):
            now = known
            if now is None:
                try:
                    with request(url, "HEAD") as r:
                        now = version_of(r.headers)
                except Exception:  # noqa: BLE001 - the host is busy: the cached copy is used
                    now = None
            if now is None or now == open(stamp, encoding="utf-8").read():
                print(f"{entry['id']}: {name}: {os.path.getsize(target):,} bytes (the cached copy)")
                continue
        try:
            # "retry_waits": a longer back-off for a host that times out from the build machines (the Newberry).
            version, _ = download(url, target, f.get("pause", 2), waits=tuple(f.get("retry_waits", RETRY_WAITS)))
        except Exception as e:  # noqa: BLE001 - one file of many missing does not stop the others
            if len(files) == 1:
                raise
            failed += 1
            print(f"{entry['id']}: {name}: not downloaded ({str(e)[:100]})")
            continue
        if target.lower().endswith(".zip") and repair_zip(target):
            print(f"{entry['id']}: {name}: repaired (its offsets were shifted)")
        with open(stamp, "w", encoding="utf-8") as fh:
            fh.write(known or version or url)
        if len(files) <= 30:
            print(f"{entry['id']}: {name}: {os.path.getsize(target):,} bytes")
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        base = name[:-len(".version")] if name.endswith(".version") else name
        if base not in kept:
            os.remove(os.path.join(folder, name))       # an older release (NAD_r20_TXT.zip after NAD_TXT.zip)
    if f.get("convert") == "nces_history":
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        count = nces_history_to_csv(paths, os.path.join(folder, entry["id"] + ".csv"))
        for p in paths:
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        print(f"{entry['id']}: {count:,} schools closed since the oldest year")
    if f.get("convert") == "wof":
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        total = 0
        for i, p in enumerate(paths):
            db = os.path.join(folder, f"wof-{i}.db")
            bunzip(p, db)
            total += wof_to_csv(db, os.path.join(folder, f"{entry['id']}-{i}.csv"))
            os.remove(db)
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        print(f"{entry['id']}: {total:,} neighbourhoods with an open geometry source")
    if f.get("convert") == "json_records":
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        count = json_to_csv(paths, f["json_records"], os.path.join(folder, entry["id"] + ".csv"))
        for p in paths:
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        print(f"{entry['id']}: {count:,} records")
    if f.get("convert") == "atp":
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        regions = [r for r in catalogue.regions().values() if catalogue.country_code(r) in entry["countries"] and
                   not r.get("parent")]         # a sub-region's cells are inside its parent's box
        from placepacks.regions import boxes_of
        count = atp_to_csv(paths[0], os.path.join(folder, entry["id"] + ".csv"), [b for r in regions for b in boxes_of(r)])
        for p in paths:
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        print(f"{entry['id']}: {count:,} chain locations in the covered regions")
    if f.get("convert") == "light_list":
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        count = light_list_to_csv(paths, os.path.join(folder, entry["id"] + ".csv"))
        for p in paths:
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        if not count:
            raise ValueError("no lighthouse was found in the Light List files")
        print(f"{entry['id']}: {count:,} lighthouses from {len(paths)} files")
    if f.get("xml_records"):
        paths = [os.path.join(folder, n) for n in kept if os.path.exists(os.path.join(folder, n))]
        count = xml_to_csv(paths, f["xml_records"], os.path.join(folder, entry["id"] + ".csv"))
        for p in paths:
            os.remove(p)
            if os.path.exists(p + ".version"):
                os.remove(p + ".version")
        print(f"{entry['id']}: {count:,} records from {len(paths)} files ({failed} not downloaded)")


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
    p.add_argument("--part", default="all", choices=fmt.PARTS + ("all",))
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
        from placepacks.regions import expand, leaves
        # The regions packs are made for: a parent typed (England, Texas) is its children.
        ids = [c for r in a.fingerprint_all.replace(",", " ").split() for c in expand(r)] or leaves()
        prints = {r: fingerprint(fetch_region(r, os.path.join("work", r), fmt.PARTS, a.national, True))
                  for r in ids}
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(prints, f, indent=1)
        return 0
    parts = fmt.PARTS if a.part == "all" else (a.part,)
    result = fetch_region(a.region, a.dir or os.path.join("work", a.region), parts, a.national, a.fingerprint,
                          only=set(a.only.split(",")) if a.only else None)
    print(json.dumps({k: {"ok": v.get("ok"), "version": v.get("version", "")[:80], "error": v.get("error", "")}
                      for k, v in result.items() if not k.startswith("_")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
