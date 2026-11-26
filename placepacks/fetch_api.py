"""The "json_api" fetch method: a public web API that answers with pages of JSON records, read for one region at a
time and written as one CSV that the tabular reader reads (the VA's Facilities API; the CMS data API, which serves the
Provider of Services files the same way, was checked with it).

The catalogue entry's "fetch" says how:
  "url":      the API's address ("https://data.cms.gov/data-api/v1/dataset/<id>/data")
  "params":   the query, {name: value}; the values may hold the region's placeholders ("{code}": its postal code),
              so each region asks only for its own state ({"filter[state_cd]": "{code}"})
  "paging":   how the pages are asked for: {"style": "offset", "size": "size", "offset": "offset"} (the record to
              start from, CMS) or {"style": "page", "size": "per_page", "page": "page", "first": 1} (a page number,
              the VA); "page_size": records a page (the last page is the first one with fewer records)
  "records":  where the list of records is in the answer: "" for an answer that is the list itself (CMS), or a key,
              dotted for a nested one ("data", the VA's JSON:API answer)
  "fields":   the columns written, each a key of the record, dotted for a nested one ("attributes.name"); "a|b" is
              the first of a or b that is not empty (an API that renamed a key), and the column is named after a
              (dots and other punctuation made "_")
  "key_env" and "key_header": an API that needs a key: the key is read from the environment variable key_env (a
              GitHub secret given to the build's fetch step, such as VA_API_KEY) and sent in the header key_header,
              never in the address and never printed. Without it the source is skipped ("needs the VA_API_KEY
              secret"), and the build goes on without it.
  "pause":    seconds to wait between requests (politeness)
The version is the month: these APIs give no cheap version number, so the source is read again every month.
"""

import csv
import datetime
import json
import os
import re
import time
import urllib.parse

MAX_PAGES = 200           # a safety stop: an API that never sends a short page is not asked for ever


def column_name(field):
    """The CSV column of a field spec: its first alternative, with dots and other punctuation made "_"
    ("attributes.name|attributes.title" -> "attributes_name")."""
    return re.sub(r"[^0-9A-Za-z]+", "_", field.split("|")[0]).strip("_")


def value_of(record, field):
    """The value of a field spec in one JSON record: a dotted key ("attributes.address.physical.zip"), a number for
    an item of a list, and "a|b" for the first alternative that is not empty. Lists and objects that are left are
    written as JSON; a missing value is ""."""
    for option in field.split("|"):
        v = record
        for part in option.split("."):
            if isinstance(v, list) and part.isdigit():
                v = v[int(part)] if int(part) < len(v) else None
            elif isinstance(v, dict):
                v = v.get(part)
            else:
                v = None
        if v is None or v == "":
            continue
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v).strip()
    return ""


def records_of(answer, where):
    """The list of records of one JSON answer ("" for an answer that is the list itself, else a dotted key)."""
    data = answer
    for part in [p for p in (where or "").split(".") if p]:
        data = data.get(part) if isinstance(data, dict) else None
    return data if isinstance(data, list) else []


def page_url(f, values, number):
    """The address of page number (0 for the first page) of the entry's API, with the region's placeholders filled
    in the parameters."""
    params = {k: str(v).format(**values) for k, v in (f.get("params") or {}).items()}
    paging = f.get("paging") or {}
    size = int(paging.get("page_size", 1000))
    if paging.get("style") == "page":
        params[paging.get("page", "page")] = str(int(paging.get("first", 1)) + number)
        params[paging.get("size", "per_page")] = str(size)
    elif paging:
        params[paging.get("offset", "offset")] = str(number * size)
        params[paging.get("size", "size")] = str(size)
    url = f["url"].format(**values)
    return url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params) if params else url


def api_key(f):
    """{header: key} for an API that needs a key (read from the environment variable "key_env"); {} when it needs
    none. Raises KeyError naming the variable when the key is needed but not set."""
    if not f.get("key_env"):
        return {}
    key = os.environ.get(f["key_env"], "").strip()
    if not key:
        raise KeyError(f["key_env"])
    return {f.get("key_header", "apikey"): key}


def fetch_json_api(entry, values, folder, fingerprint, opener=None, sleep=time.sleep):
    """Fetch one region's records of a json_api source into <folder>/<id>.csv (see the module docstring). Returns
    the fetched.json entry. opener(url, headers) -> a file-like answer may replace the network (tests)."""
    from placepacks import fetch
    f = entry["fetch"]
    version = datetime.date.today().strftime("%Y-%m")
    if fingerprint:
        return {"ok": True, "version": version, "path": "", "date": ""}
    try:
        headers = api_key(f)
    except KeyError as e:
        raise fetch.SourceUnavailable(f"needs the {e.args[0]} secret (a free key; see SOURCES.md)") from None
    open_url = opener or (lambda url, hdrs: fetch.request(url, headers={"Accept": "application/json", **hdrs}))
    size = int((f.get("paging") or {}).get("page_size", 1000))
    fields = f["fields"]
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, entry["id"] + ".csv")
    rows = 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow([column_name(x) for x in fields])
        for number in range(MAX_PAGES):
            url = page_url(f, values, number)
            answer = None
            for attempt, wait in enumerate((0,) + tuple(fetch.RETRY_WAITS)):
                if wait:
                    sleep(wait)
                try:
                    with open_url(url, headers) as r:
                        answer = json.loads(r.read().decode("utf-8"))
                    break
                except Exception as e:  # noqa: BLE001 - a busy host is tried again, anything else stops
                    if not fetch.retryable(e) or attempt == len(fetch.RETRY_WAITS):
                        raise
            found = records_of(answer, f.get("records", ""))
            for rec in found:
                w.writerow([value_of(rec, x) for x in fields])
            rows += len(found)
            if len(found) < size or not f.get("paging"):
                break
            sleep(f.get("pause", 1))
    os.replace(target + ".partial", target)
    # No record in the region (a state without any) is an empty file: the build says "ok (0 in this region)".
    return {"ok": True, "version": version, "path": target, "date": datetime.date.today().isoformat()}
