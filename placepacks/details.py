"""The "details only" sources: phone numbers, websites and opening hours for businesses ALREADY in the packs, found
by a key, never new places (FORMAT.md, "Business contact details"):

  yp-lookups          Yellow Pages lookups (tools/yp_lookup.py, run by the owner's helper, slowly, from a cloud
                      session): one search per business that lacks a phone or hours; the release "uploaded-sources",
                      files "yp-lookups-<YYYYMMDD>.csv.gz"
  business-websites   the business's own homepage, its schema.org data (placepacks/directories/websites.py, the
                      monthly web-details workflow): the release "web-details", files "web-details-<YYYYMMDD>.csv.gz"

Each file holds the whole set so far (each new file is the previous one with the new rows merged in), with the
columns DETAIL_FIELDS: key (the place's key in the packs, "overture-places:08f2..."), lat and lon (the place's
position, so the national file is cut per region like the others), phone, website, opening_hours (OpenStreetMap
syntax), matched_on (how the details were tied to the place: "name+address", "homepage json-ld" ...) and checked
(the date the lookup was made). A row whose phone, website and hours are all empty says "looked up, nothing
found", so the next run does not ask again too soon; the build skips it.

The pack build:
  - fetch method "release_latest": the newest file of the release whose name is "<prefix>-<YYYYMMDD>.csv.gz"
    (newest(); version "<release>/<file name>"); the prepare job downloads it once (prepare()) into
    national/<id>/<id>.csv, which placepacks.split cuts per region by lat and lon ("split_box"). No file yet: the
    source is skipped ("waiting for the first ... file") and the build goes on;
  - reader "details" (read()): for each row, PackWriter.fill_details gives the place listed now under the key the
    details it lacks. The place's own sources always come first: a details-only source fills only empty fields.
    The build reads these sources after every other source of the part (placepacks/build.py), so the places are
    there. A key that is not in this month's pack (the place has closed) is passed over.
Privacy: the details are cleaned by placepacks/contact.py as for any business source: never an e-mail, never for a
name that is a person's or an individual's own office (insurance agent, lawyer ...).
Only the Python standard library is used (gh is run through placepacks.uploaded.run_gh, as for the other release
sources).
"""

import csv
import gzip
import os
import re
import shutil
import tempfile
import time

from placepacks.readers import reader

DETAIL_FIELDS = ["key", "lat", "lon", "phone", "website", "opening_hours", "matched_on", "checked"]


def file_pattern(prefix):
    """The pattern of a details file's name: "<prefix>-<YYYYMMDD>.csv.gz" (group 1: the date)."""
    return re.compile(rf"^{re.escape(prefix)}-(\d{{8}})\.csv\.gz$")


def waiting(entry):
    """The skip reason while a release has no file yet."""
    f = entry["fetch"]
    return f"waiting for the first {f['prefix']} file in the release \"{f['release']}\""


def newest(entry, names=None):
    """The name of the newest details file of the entry's release (see file_pattern). Raises uploaded.Waiting when
    there is none (or the release cannot be read)."""
    from placepacks import uploaded
    f = entry["fetch"]
    try:
        names = uploaded.assets(f["release"]) if names is None else names
    except uploaded.Waiting:
        raise uploaded.Waiting(waiting(entry)) from None
    pattern = file_pattern(f["prefix"])
    found = sorted((n for n in names if pattern.match(n)), reverse=True)
    if not found:
        raise uploaded.Waiting(waiting(entry))
    return found[0]


def version(entry):
    """The source's version, "uploaded-sources/yp-lookups-20261201.csv.gz". Raises uploaded.Waiting."""
    return f"{entry['fetch']['release']}/{newest(entry)}"


def prepare(entry, national, sleep=time.sleep):
    """Download the newest file into national/<id>/<id>.csv (rows that carry at least one detail and a position).
    Returns the number of rows. Raises uploaded.Waiting (no file yet) or RuntimeError (the download failed)."""
    from placepacks import uploaded
    name = newest(entry)
    folder = os.path.join(national, entry["id"])
    os.makedirs(folder, exist_ok=True)
    scratch = tempfile.mkdtemp(prefix=f"{entry['id']}-", dir=os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        path = uploaded.download(entry["fetch"]["release"], name, scratch, sleep=sleep)
        target = os.path.join(folder, entry["id"] + ".csv")
        count = 0
        with gzip.open(path, "rt", newline="", encoding="utf-8") as f, \
                open(target + ".partial", "w", newline="", encoding="utf-8") as out:
            w = csv.DictWriter(out, fieldnames=DETAIL_FIELDS, extrasaction="ignore")
            w.writeheader()
            for row in csv.DictReader(f):
                if not (row.get("key") and row.get("lat") and row.get("lon")):
                    continue
                if not any((row.get(k) or "").strip() for k in ("phone", "website", "opening_hours")):
                    continue                # "looked up, nothing found": nothing for the packs
                w.writerow(row)
                count += 1
        os.replace(target + ".partial", target)
        with open(target + ".version", "w", encoding="utf-8") as fh:
            fh.write(f"{entry['fetch']['release']}/{name}")
        print(f"{entry['id']}: {count:,} places with details from {entry['fetch']['release']}/{name}", flush=True)
        return count
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


@reader("details")
def read(path, entry, region, writer):
    """Give the places of the pack the details of a details-only source (see the module docstring). Returns the
    number of places that got something."""
    from placepacks.readers.tabular import _get, rows_of
    cols = entry.get("contact_columns") or {"phone": "phone", "website": "website", "opening_hours": "opening_hours"}
    count = 0
    for row in rows_of(path, entry, region):
        key = _get(row, entry["columns"].get("key", "key"))
        contact = {field: _get(row, column) for field, column in cols.items()}
        if key and any(contact.values()) and writer.fill_details(entry["id"], key, contact):
            count += 1
    return count


# ------------------------------------------------------------------------------------------------ the files

def read_rows(path):
    """{key: row} of a details .csv.gz file (DETAIL_FIELDS); {} when path is None or missing."""
    if not path or not os.path.exists(path):
        return {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        return {r["key"]: {k: r.get(k, "") or "" for k in DETAIL_FIELDS} for r in csv.DictReader(f) if r.get("key")}


def merge(old, new):
    """The previous set's rows with this run's merged in ({key: row} each): a key looked up again takes its new
    row, except that a new row with nothing found never wipes out details found before (the site may have been
    down that day); then only its checked date moves on."""
    out = dict(old)
    for key, row in new.items():
        before = out.get(key)
        found = any(row.get(k) for k in ("phone", "website", "opening_hours"))
        if before and not found and any(before.get(k) for k in ("phone", "website", "opening_hours")):
            out[key] = {**before, "checked": row.get("checked") or before.get("checked", "")}
        else:
            out[key] = row
    return out


def write_rows(path, rows):
    """Write {key: row} as a .csv.gz file (DETAIL_FIELDS, sorted by key), through a .partial file. Returns the
    number of rows."""
    with gzip.open(path + ".partial", "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS, extrasaction="ignore")
        w.writeheader()
        for key in sorted(rows):
            w.writerow({k: rows[key].get(k, "") for k in DETAIL_FIELDS})
    os.replace(path + ".partial", path)
    return len(rows)
