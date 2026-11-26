"""Recreation.gov's RIDB full export (the Recreation Information Database of every federal land agency): campgrounds,
day-use sites, visitor centers, recreation areas and permit entry points with their telephone number, reservable
flag, ADA access and coordinates (convert "ridb", called by placepacks/gov_details.py in the prepare job).

Licence: RIDB was rejected before (Recreation.gov's API agreement keeps the vendor's rights in its materials and no
licence is on recreation.gov itself). The owner decided on 26 November 2026 to include it regardless of those terms
(licence "government-facts" in sources.json): only facts about federal places are taken, politely.

The export (ridb.recreation.gov/downloads/RIDBFullExport_V1_CSV.zip, about 250 MB, refreshed by Recreation.gov) is
a .zip whose files are stored without compression. Only the members in MEMBERS (about 32 MB) are read, each with one
HTTP range request at the place the .zip's directory gives (zip_members); a server that ignores range requests is
handled by downloading the whole file once instead. About ten requests a month, PAUSE seconds apart.

Kept (gov_details.FIELDS):
  - facilities of the types in FACILITY_TYPES (campgrounds, visitor centers, day-use and other recreation sites,
    memorials, museums, libraries, fish hatcheries); tickets, passes, tree permits, timed entries and venue bookings
    are not places and are left out;
  - recreation areas (their point, typed "recreation area");
  - permit entrances that are entry points or trailheads with a position.
  phone: the facility's or area's public number; website: the Recreation.gov booking page of a reservable
  campground; note: "Managed by: US Army Corps of Engineers; Reservations: yes, on Recreation.gov; ADA access: yes;
  Accessibility: <the facility's accessibility text>; About: <the description's first sentence, at most 200
  characters>". Never kept: e-mail addresses, contact names, photos, links, the full descriptions and directions.
Places without coordinates are left out. A place the Forest Service, the National Park Service, BLM, Reclamation or
TVA layers already have (the same name within the entry's "dedupe_m" metres) is not added again: the build keeps the
agency's own point and gives it these details (writer.PackWriter.drop_duplicates with "dedupe_carry").
"""

import csv
import io
import os
import struct
import time
import zipfile

from placepacks import gov_details

URL = "https://ridb.recreation.gov/downloads/RIDBFullExport_V1_CSV.zip"
MEMBERS = ("Facilities_API_v1.csv", "RecAreas_API_v1.csv", "OrgEntities_API_v1.csv", "Organizations_API_v1.csv",
           "PermitEntrances_API_v1.csv")
PAUSE = 2
# RIDB's facility types that are places, with their kind (the class map) and fine type.
FACILITY_TYPES = {"Campground": "campground", "Visitor Center": "visitor center", "Facility": "recreation site",
                  "Cemetery and Memorial": "memorial", "Museum": "museum", "Library": "library",
                  "Archives": "archives", "National Fish Hatchery": "fish hatchery"}
ENTRANCE_TYPES = {"entry point": "permit entry point", "trailhead": "trailhead"}
ADA = {"y": "yes", "yes": "yes", "n": "no", "no": "no"}


# ------------------------------------------------------------------------------------------- reading the .zip

def _get_range(url, start, end, sleep, opener):
    """Bytes start..end (inclusive) of url, by one range request; raises ValueError when the server sends the
    whole file instead (it ignores range requests)."""
    from placepacks import fetch
    open_url = opener or (lambda u, h: fetch.request(u, headers=h))
    for attempt, wait in enumerate((0,) + tuple(fetch.RETRY_WAITS)):
        if wait:
            sleep(wait)
        try:
            with open_url(url, {"Range": f"bytes={start}-{end}"}) as r:
                if getattr(r, "status", 206) != 206:
                    raise ValueError("the server does not answer range requests")
                data = r.read()
            break
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001 - a busy host is tried again
            if gov_details.is_blocked(e) or not fetch.retryable(e) or attempt == len(fetch.RETRY_WAITS):
                raise
    sleep(PAUSE)
    return data


def zip_members(url, size, names, sleep=time.sleep, opener=None):
    """{name: bytes} of the named members of a remote .zip of size bytes, read with range requests: the end of the
    file (the directory's last record), the directory, then each member's local header and data. Only members
    stored without compression (method 0) or deflated (8) are read."""
    import zlib
    tail_start = max(0, size - 65536)
    tail = _get_range(url, tail_start, size - 1, sleep, opener)
    at = tail.rfind(b"PK\x05\x06")
    if at < 0:
        raise ValueError("no .zip directory at the end of the file")
    cd_size, cd_offset = struct.unpack("<II", tail[at + 12:at + 20])
    if cd_offset == 0xFFFFFFFF:
        raise ValueError("a ZIP64 file (not expected for this export)")
    if cd_offset >= tail_start:
        directory = tail[cd_offset - tail_start:cd_offset - tail_start + cd_size]
    else:
        directory = _get_range(url, cd_offset, cd_offset + cd_size - 1, sleep, opener)
    found, p = {}, 0
    while p + 46 <= len(directory) and directory[p:p + 4] == b"PK\x01\x02":
        method, = struct.unpack("<H", directory[p + 10:p + 12])
        csize, = struct.unpack("<I", directory[p + 20:p + 24])
        nlen, xlen, clen = struct.unpack("<HHH", directory[p + 28:p + 34])
        offset, = struct.unpack("<I", directory[p + 42:p + 46])
        name = directory[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        found[name] = (offset, csize, method)
        p += 46 + nlen + xlen + clen
    out = {}
    for name in names:
        if name not in found:
            raise ValueError(f"{name} is not in the export")
        offset, csize, method = found[name]
        head = _get_range(url, offset, offset + 29, sleep, opener)
        nlen, xlen = struct.unpack("<HH", head[26:30])
        start = offset + 30 + nlen + xlen
        data = _get_range(url, start, start + csize - 1, sleep, opener) if csize else b""
        if method == 8:
            data = zlib.decompress(data, -15)
        elif method != 0:
            raise ValueError(f"{name} uses a compression this reader does not know ({method})")
        out[name] = data
    return out


def read_export(folder, sleep=time.sleep, opener=None):
    """{member name: its rows (dicts)} of MEMBERS: by range requests, or from the whole file downloaded once into
    folder (and deleted) when the server will not answer range requests."""
    from placepacks import fetch
    texts = None
    try:
        with (opener or (lambda u, h: fetch.request(u, method="HEAD", headers=h)))(URL, {}) as r:
            size = int(r.headers.get("Content-Length") or 0)
        sleep(PAUSE)
        if size:
            texts = zip_members(URL, size, MEMBERS, sleep, opener)
    except ValueError as e:
        print(f"  RIDB: reading the whole export ({e})", flush=True)
    if texts is None:
        path = os.path.join(folder, "ridb-export.zip")
        fetch.download(URL, path, PAUSE)
        try:
            with zipfile.ZipFile(path) as z:
                texts = {n: z.read(n) for n in MEMBERS}
        finally:
            os.remove(path)
    return {n: list(csv.DictReader(io.StringIO(data.decode("utf-8-sig", "replace")))) for n, data in texts.items()}


# ------------------------------------------------------------------------------------------- converting

def _position(lat, lon):
    """(lat, lon) as numbers, or None for a missing or zero position."""
    try:
        y, x = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if y == 0 or x == 0 or not (-90 <= y <= 90 and -180 <= x <= 180):
        return None
    return y, x


def ada_text(value):
    """"yes" or "no" from RIDB's ADA access field ("Y", "No", "YES"); other words are kept as plain text (at most
    150 characters); "" when empty or "undefined"."""
    from placepacks.hours import plain_text
    v = plain_text(value)
    if not v or v.lower() in ("undefined", "null", "n/a", "unknown"):
        return ""
    return ADA.get(v.lower(), v[:150])


def _row(key, name, kind, kind_type, at, phone, website, parts):
    """A CSV row (gov_details.FIELDS)."""
    return {"key": key, "name": " ".join((name or "").split()), "kind": kind, "type": kind_type, "state": "",
            "lat": f"{at[0]:.6f}", "lon": f"{at[1]:.6f}", "phone": phone, "website": website, "opening_hours": "",
            "note": gov_details.note_of(parts)}


def convert(tables):
    """The CSV rows of the export's tables ({member name: rows}; see the module docstring)."""
    from placepacks.hours import plain_text
    orgs = {r.get("OrgID"): (r.get("OrgName") or "").strip() for r in tables.get("Organizations_API_v1.csv", [])}
    owner = {r.get("EntityID"): orgs.get(r.get("OrgID"), "") for r in tables.get("OrgEntities_API_v1.csv", [])}
    for r in tables.get("Facilities_API_v1.csv", []):
        kind = FACILITY_TYPES.get((r.get("FacilityTypeDescription") or "").strip())
        at = _position(r.get("FacilityLatitude"), r.get("FacilityLongitude"))
        if not kind or not at or (r.get("Enabled") or "true").lower() == "false" or not r.get("FacilityName"):
            continue
        fid = (r.get("FacilityID") or "").strip()
        reservable = (r.get("Reservable") or "").lower() == "true"
        website = (f"https://www.recreation.gov/camping/campgrounds/{fid}" if reservable and kind == "campground"
                   else "")
        yield _row(f"facility:{fid}", r["FacilityName"], kind, kind, at, (r.get("FacilityPhone") or "").strip(),
                   website, [("Managed by", owner.get(fid, "")),
                             ("Reservations", "yes, on Recreation.gov" if reservable else "no"),
                             ("ADA access", ada_text(r.get("FacilityAdaAccess"))),
                             ("Accessibility", plain_text(r.get("FacilityAccessibilityText"))[:400]),
                             ("About", gov_details.first_sentence(r.get("FacilityDescription")))])
    for r in tables.get("RecAreas_API_v1.csv", []):
        at = _position(r.get("RecAreaLatitude"), r.get("RecAreaLongitude"))
        if not at or (r.get("Enabled") or "true").lower() == "false" or not r.get("RecAreaName"):
            continue
        rid = (r.get("RecAreaID") or "").strip()
        yield _row(f"area:{rid}", r["RecAreaName"], "recreation area", "recreation area", at,
                   (r.get("RecAreaPhone") or "").strip(), "",
                   [("Managed by", owner.get(rid, "")),
                    ("About", gov_details.first_sentence(r.get("RecAreaDescription")))])
    for r in tables.get("PermitEntrances_API_v1.csv", []):
        kind = ENTRANCE_TYPES.get((r.get("PermitEntranceType") or "").strip().lower())
        at = _position(r.get("Latitude"), r.get("Longitude"))
        if not kind or not at or not r.get("PermitEntranceName"):
            continue
        accessible = (r.get("PermitEntranceAccessible") or "").lower() == "true"
        yield _row(f"entrance:{(r.get('PermitEntranceID') or '').strip()}", r["PermitEntranceName"], kind, kind, at,
                   "", "", [("Managed by", owner.get((r.get("FacilityID") or "").strip(), "")),
                            ("Accessible", "yes" if accessible else ""),
                            ("About", gov_details.first_sentence(r.get("PermitEntranceDescription")))])


def prepare(entry, folder, sleep=time.sleep, opener=None):
    """Write <folder>/<id>.csv from the export (see the module docstring). Returns the number written."""
    tables = read_export(folder, sleep, opener)
    count = gov_details.write_rows(os.path.join(folder, entry["id"] + ".csv"), convert(tables))
    if not count:
        raise ValueError("the export gave no place (has its layout changed?)")
    return count
