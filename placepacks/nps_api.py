"""The National Park Service's Data API (developer.nps.gov): parks, visitor centers, campgrounds and places with
their hours, telephone and TTY numbers, web pages, accessibility and amenities (convert "nps_api", called by
placepacks/gov_details.py in the prepare job).

A free key is needed: the owner signs up at nps.gov/subjects/developer (the key arrives by e-mail) and stores it as
the repository secret NPS_API_KEY, which only the prepare step of build-packs.yml sees. It is sent in the X-Api-Key
header, never in an address, and never printed. Without it the source is skipped ("needs the NPS_API_KEY secret")
and everything else builds. The API allows 1,000 requests an hour; a whole run is about 25 (ENDPOINTS, PAGE records
a request, PAUSE seconds apart).

Licence: the API's data is a work of the US government (public domain; nps.gov's disclaimer). Only facts are
taken: names, positions, telephone numbers, web pages, hours, accessibility fields and amenities. Photos (often
credited to others), long descriptions, e-mail addresses and anything with a credit line are never read.

Each record becomes one row (gov_details.FIELDS):
  hours  the first "operatingHours" entry in OpenStreetMap's syntax, with its exceptions that have not ended
         (placepacks.hours.nps_hours: "Mo-Su 09:00-17:00; 2026 Nov 01-2027 Apr 30 off"); when a day's words are
         not plain hours, its description is kept in the note instead ("Hours: Open daily in summer ...")
  phone  the first voice number; the TTY number goes into the note ("TTY: 207-555-0100")
  note   hours that could not be written, TTY, accessibility (campgrounds: wheelchair access, ADA information,
         access roads, RV and trailer lengths), amenities and the number of reservable sites
The rows are matched to the National Park Service's own points (nps-poi) when the pack is built: the same name
within the entry's "dedupe_m" metres is one place, which keeps the nps-poi point and takes these details
(writer.PackWriter.drop_duplicates with "dedupe_carry"); anything else is added as a place of its own.
"""

import datetime
import os
import time
import urllib.parse

from placepacks import gov_details, hours

BASE = "https://developer.nps.gov/api/v1/"
ENDPOINTS = ("parks", "visitorcenters", "campgrounds", "places")
PAGE = 500
PAUSE = 2
MAX_PAGES = 60                  # a safety stop (about 30,000 records an endpoint)
KIND = {"parks": "park", "visitorcenters": "visitor center", "campgrounds": "campground", "places": "place"}


class NeedsKey(Exception):
    """The NPS_API_KEY secret is not set: the source is skipped this month."""


def _phones(record):
    """(the first voice number, the first TTY number) of a record's contacts (fax numbers are never kept)."""
    voice = tty = ""
    for p in ((record.get("contacts") or {}).get("phoneNumbers") or []):
        number, kind = (p.get("phoneNumber") or "").strip(), (p.get("type") or "").strip().lower()
        if not number:
            continue
        if kind == "tty" and not tty:
            tty = number
        elif kind in ("voice", "") and not voice:
            voice = number
    return voice, tty


def _state(record):
    """The state of a record: its physical address's state, else the first of the park's states."""
    for a in record.get("addresses") or []:
        if (a.get("type") or "").lower() == "physical" and a.get("stateCode"):
            return a["stateCode"].upper()
    return (record.get("states") or "").split(",")[0].strip().upper()


def _yes(value):
    """True for the API's "1", "Yes", "true"."""
    return str(value or "").strip().lower() in ("1", "yes", "true", "y")


def _amenities(record):
    """The amenities of a record as plain text: a list of names (visitor centers, places) or the campgrounds'
    object of lists ("Toilets: Flush Toilets - year round; Potable Water: Yes - seasonal; Showers: None")."""
    a = record.get("amenities")
    if isinstance(a, list):
        return ", ".join(str(x).strip() for x in a if str(x).strip())
    if isinstance(a, dict):
        parts = []
        for k, v in a.items():
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v if str(x).strip())
            v = str(v or "").strip()
            if v and v.lower() not in ("no", "none", "0", "false", "unknown"):
                label = "".join(" " + c.lower() if c.isupper() else c for c in k).strip().capitalize()
                parts.append(f"{label}: {v}")
        return "; ".join(parts)
    return ""


def _accessibility(record):
    """A campground's accessibility facts as plain text, or ""."""
    a = record.get("accessibility") or {}
    if not isinstance(a, dict):
        return ""
    parts = [hours.plain_text(a.get("wheelchairAccess")), hours.plain_text(a.get("adaInfo"))]
    roads = ", ".join(x for x in (a.get("accessRoads") or []) if x)
    if roads:
        parts.append(f"access roads: {roads}")
    if _yes(a.get("rvAllowed")):
        parts.append("RVs allowed" + (f" up to {a['rvMaxLength']} ft" if str(a.get("rvMaxLength") or "0") not in
                                      ("", "0") else ""))
    if _yes(a.get("trailerAllowed")):
        parts.append("trailers allowed" + (f" up to {a['trailerMaxLength']} ft" if str(
            a.get("trailerMaxLength") or "0") not in ("", "0") else ""))
    return "; ".join(p for p in parts if p)


def row_of(endpoint, record, today=None):
    """One API record's CSV row (gov_details.FIELDS), or None without a name or a position (see the module
    docstring)."""
    name = (record.get("fullName") if endpoint == "parks" else record.get("title") if endpoint == "places"
            else record.get("name")) or ""
    name = " ".join(name.split())
    try:
        lat, lon = float(record.get("latitude")), float(record.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not name or lat == lon == 0 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if endpoint == "places" and str(record.get("isOpenToPublic", "1")).strip().lower() in ("0", "false", "no"):
        return None                         # a place the park says is not open to the public
    operating = record.get("operatingHours") or []
    osm = hours.nps_hours(operating, today)
    text = ""
    if operating and not osm:
        first = operating[0] or {}
        text = hours.plain_text(first.get("description")) or hours.plain_text(first.get("name"))
    voice, tty = _phones(record)
    reservable = str(record.get("numberOfSitesReservable") or "").strip()
    note = gov_details.note_of([("Hours", text[:400]), ("TTY", tty), ("Accessibility", _accessibility(record)),
                                ("Amenities", _amenities(record)[:500]),
                                ("Reservable sites", reservable if reservable not in ("", "0") else "")])
    kind = KIND[endpoint]
    kind_type = (" ".join((record.get("designation") or "").split()).lower() or "national park unit") \
        if endpoint == "parks" else ("point of interest" if endpoint == "places" else kind)
    url = (record.get("url") or "").strip()
    return {"key": f"{endpoint}:{record.get('id') or record.get('parkCode')}", "name": name, "kind": kind,
            "type": kind_type, "state": _state(record), "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "phone": voice,
            "website": url if url.startswith(("http://", "https://")) else "", "opening_hours": osm, "note": note}


def records(endpoint, key, sleep=time.sleep, opener=None):
    """Every record of one endpoint, PAGE at a time (the API's "start" and "total")."""
    start = 0
    for _ in range(MAX_PAGES):
        url = BASE + endpoint + "?" + urllib.parse.urlencode({"limit": PAGE, "start": start})
        answer = gov_details.get_json(url, {"X-Api-Key": key}, PAUSE, sleep, opener)
        data = answer.get("data") or []
        yield from data
        start += len(data)
        try:
            total = int(answer.get("total") or 0)
        except ValueError:
            total = 0
        if not data or len(data) < PAGE or (total and start >= total):
            break


def prepare(entry, folder, sleep=time.sleep, opener=None, today=None):
    """Write <folder>/<id>.csv of every endpoint's records. Raises NeedsKey without the NPS_API_KEY secret (the
    prepare job then records the source as skipped). Returns the number written."""
    key = os.environ.get(entry["fetch"].get("key_env", "NPS_API_KEY"), "").strip()
    if not key:
        raise NeedsKey("needs the NPS_API_KEY secret (a free key from nps.gov/subjects/developer; see SOURCES.md)")
    today = today or datetime.date.today()

    def rows():
        """The rows of every endpoint, one place once (an id seen twice is kept once)."""
        seen = set()
        for endpoint in ENDPOINTS:
            for rec in records(endpoint, key, sleep, opener):
                row = row_of(endpoint, rec, today)
                if row and row["key"] not in seen:
                    seen.add(row["key"])
                    yield row
    return gov_details.write_rows(os.path.join(folder, entry["id"] + ".csv"), rows())
