"""Government places WITH DETAILS (phone, opening hours, web page, accessibility), read once a month by the prepare job
("national" sources with a "convert" this module knows) and written as one CSV each that the tabular reader reads:

  convert "ssa_offices"  Social Security field offices (placepacks/ssa_offices.py)
  convert "nps_api"      the National Park Service's Data API: parks, visitor centers, campgrounds, places
                         (placepacks/nps_api.py; needs the free key in the NPS_API_KEY secret)
  convert "ridb"         Recreation.gov's RIDB full export: facilities, recreation areas and permit entrances of every
                         federal agency (placepacks/ridb.py)

The Forest Service's Recreation Opportunities layer is not a place list of its own: its hours, season and
accessibility are joined to the existing Forest Service recreation sites when they are fetched
(placepacks/usfs_details.py), so no place is listed twice.

Every converter writes the same columns (FIELDS): key, name, kind, type, state, lat, lon, phone, website,
opening_hours (OpenStreetMap syntax, placepacks/hours.py) and note (a short plain-text note: the address, hours the
converter could not write in OpenStreetMap's syntax, accessibility, amenities; data only, never spoken). The
phone, web page and hours become the place's details (the pack's biz_details table, placepacks/contact.py:
GOVERNMENT_SOURCES), which the "nearest" lookups say (placepacks/local.py, placepacks/find.py).

Privacy: only facts about public offices and sites are kept. No staff or contact person's name, no e-mail address
and no internal figure (costs, staff numbers, leases, waiting times) is ever written; the converters list the
columns they keep, so anything else a source adds later is never read.

Politeness: every request names the project in its User-Agent (placepacks.fetch.request), waits the entry's "pause"
between requests and stops at a refusal (a 403, a challenge page): such a site is recorded as blocked, never worked
around. Only the Python standard library is used.
"""

import csv
import importlib
import json
import os
import re
import time

FIELDS = ["key", "name", "kind", "type", "state", "lat", "lon", "phone", "website", "opening_hours", "note"]
# The converters, by the catalogue's "convert" name: the module whose prepare(entry, folder) writes the CSV.
CONVERTERS = {"ssa_offices": "placepacks.ssa_offices", "nps_api": "placepacks.nps_api", "ridb": "placepacks.ridb"}
NOTE_LIMIT = 1200               # as the tabular reader's notes (placepacks/readers/tabular.py, NOTE_LIMIT)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


def prepare(entry, folder):
    """The prepare job's step for a source whose "convert" is one of CONVERTERS: its module writes
    <folder>/<id>.csv. Returns the number of places written."""
    module = importlib.import_module(CONVERTERS[entry["fetch"]["convert"]])
    os.makedirs(folder, exist_ok=True)
    count = module.prepare(entry, folder)
    print(f"{entry['id']}: {count:,} places with details", flush=True)
    return count


def write_rows(target, rows):
    """Write rows (dicts with FIELDS) as the CSV the tabular reader reads, through a .partial file so a failed run
    never leaves half a list. Returns the number written."""
    count = 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in FIELDS})
            count += 1
    os.replace(target + ".partial", target)
    return count


def note_of(parts):
    """A note from labelled parts [("Accessibility", "accessible toilets"), ...]: "Accessibility: accessible
    toilets; ..." for the parts that have a value; e-mail addresses are taken out, and the note is cut to
    NOTE_LIMIT characters at a word."""
    def tidy(value):
        """A part's text without a closing full stop or semicolon ("No Fee Required." -> "No Fee Required"),
        so the parts join cleanly; an ellipsis stays."""
        v = " ".join(str(value).split())
        return v if v.endswith("...") else v.rstrip(" .;")
    text = "; ".join(f"{label}: {tidy(value)}" if label else tidy(value) for label, value in parts
                     if value and tidy(value))
    text = " ".join(_EMAIL.sub("", text).split()).strip(" ;,")
    if len(text) > NOTE_LIMIT:
        text = text[:NOTE_LIMIT].rsplit(" ", 1)[0] + " ..."
    return text


def first_sentence(text, limit=200):
    """The first sentence of a description (HTML taken out), at most limit characters; "" when it would name a
    person to contact ("call", "contact", "host", "e-mail") or holds an address for e-mail: descriptions are
    trimmed to a short fact about the place."""
    from placepacks.hours import plain_text
    t = plain_text(text)
    # A heading the description starts with ("Overview", "Description") is not part of the sentence.
    t = re.sub(r"^(overview|description|about|introduction)\b\s*[:;.-]?\s*", "", t, flags=re.I)
    if not t:
        return ""
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    t = (m.group(1) if m else t).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + " ..."
    if _EMAIL.search(t) or re.search(r"\b(call|contact|host|hosts|e-?mail|phone)\b", t, re.I):
        return ""
    return t


def is_blocked(error):
    """True when an error is a site refusing programs (403 or 401, a challenge page): the source is recorded as
    blocked and never tried another way."""
    code = getattr(error, "code", None)
    return code in (401, 403) or "challenge" in str(error).lower()


def get_json(url, headers=None, pause=1, sleep=time.sleep, opener=None):
    """The JSON answer of one GET request (placepacks.fetch.request, with the project's User-Agent), tried again
    after a pause when the host is busy (429, 5xx); a refusal (403) raises at once. Waits pause seconds after."""
    from placepacks import fetch
    open_url = opener or (lambda u, h: fetch.request(u, headers=h))
    for attempt, wait in enumerate((0,) + tuple(fetch.RETRY_WAITS)):
        if wait:
            sleep(wait)
        try:
            with open_url(url, {"Accept": "application/json", **(headers or {})}) as r:
                answer = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - a busy host is tried again, anything else stops
            if is_blocked(e) or not fetch.retryable(e) or attempt == len(fetch.RETRY_WAITS):
                raise
    if pause:
        sleep(pause)
    return answer
