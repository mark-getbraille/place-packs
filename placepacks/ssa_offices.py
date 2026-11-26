"""Social Security field offices with their address, telephone number and weekday hours (convert "ssa_offices",
called by placepacks/gov_details.py in the prepare job).

The source is an ArcGIS copy of the Social Security Administration's own field office list (about 1,170 offices),
published by Esri's health GIS staff without a licence: the facts are the SSA's (a federal agency), and ssa.gov
itself refuses every program, so this copy is used by the owner's decision of 26 November 2026 (licence
"government-facts" in sources.json). The layer also carries internal figures of each office (costs, staff numbers,
lease dates, waiting times, local demographics, fax numbers). They are never asked for: the query names only the
columns in KEPT, and the converter writes only FIELDS.

Each office becomes one place:
  name   "Social Security office, Augusta" (the office's own name is a code such as "AUGUSTA ME")
  note   "Address: 68 Sewall St, Ste 209, Augusta, ME 04330" (the line "SOCIAL SECURITY" the list puts first is a
         mail heading, not part of the address)
  phone  the office's public number
  hours  in OpenStreetMap's syntax ("Mo-Fr 09:00-16:00"; days with other hours are written apart)
The layer's own point is the position; an office without one is left out (all had one in November 2026).
"""

import os
import re
import time

from placepacks import gov_details, hours

# The only columns asked for.
KEPT = ["OFFICE_CODE", "OFFICE_NAME", "ADDRESS_LINE_1", "ADDRESS_LINE_2", "ADDRESS_LINE_3", "CITY", "STATE",
        "ZIP_CODE", "PHONE"] + [f"{d}_{w}_TIME" for d in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY")
                                for w in ("OPEN", "CLOSE")]
WEEKDAYS = {"Mo": ("MONDAY_OPEN_TIME", "MONDAY_CLOSE_TIME"), "Tu": ("TUESDAY_OPEN_TIME", "TUESDAY_CLOSE_TIME"),
            "We": ("WEDNESDAY_OPEN_TIME", "WEDNESDAY_CLOSE_TIME"), "Th": ("THURSDAY_OPEN_TIME", "THURSDAY_CLOSE_TIME"),
            "Fr": ("FRIDAY_OPEN_TIME", "FRIDAY_CLOSE_TIME")}
PAGE = 1000


FLOOR = re.compile(r"\d+(ST|ND|RD|TH)?\s+(FL|FLR|FLOOR)\b", re.I)
ORDINAL = re.compile(r"\d+(ST|ND|RD|TH)", re.I)


def _case(line):
    """An address line in ordinary capitals ("68 SEWALL ST" -> "68 Sewall St"), where a word holding a digit keeps
    its capitals ("STE 1A" -> "Ste 1A"), except an ordinal ("2ND" -> "2nd")."""
    from placepacks.readers.tabular import smart_case
    return " ".join(o if re.search(r"\d", o) and not ORDINAL.fullmatch(o) else w
                    for o, w in zip(line.split(), smart_case(line).split()))


def address_of(attrs):
    """"68 Sewall St, Ste 209, Augusta, ME 04330" from an office's address lines (the street line first, then a
    suite or floor line; a line that only says "Social Security" is left out), city, state and ZIP code."""
    from placepacks.readers.tabular import smart_case
    lines = [" ".join(str(attrs.get(f"ADDRESS_LINE_{i}") or "").split()) for i in (1, 2, 3)]
    lines = [x for x in lines if x and x.upper() not in ("SOCIAL SECURITY", "SOCIAL SECURITY ADMINISTRATION", "SSA")]
    # The street line starts with a house number ("68 SEWALL ST"); "2ND FL" is a floor, not a street.
    streets = [x for x in lines if re.match(r"\d+[A-Z]?\s", x, re.I) and not FLOOR.match(x)]
    others = [x for x in lines if x not in streets]
    parts = [_case(x) for x in streets + others]
    city = smart_case(str(attrs.get("CITY") or "").strip())
    zip_code = str(attrs.get("ZIP_CODE") or "").strip()
    if zip_code.isdigit():
        zip_code = zip_code.zfill(5)
    tail = " ".join(x for x in (str(attrs.get("STATE") or "").strip(), zip_code) if x)
    return ", ".join(x for x in parts + [city, tail] if x)


def office_row(attrs, geometry):
    """One office's CSV row (gov_details.FIELDS), or None without a position or a city. Only the columns of KEPT
    are read."""
    from placepacks.readers.tabular import smart_case
    attrs = {k: attrs.get(k) for k in KEPT}
    city = smart_case(str(attrs.get("CITY") or "").strip())
    try:
        lon, lat = float(geometry["x"]), float(geometry["y"])
    except (TypeError, KeyError, ValueError):
        return None
    if not city or not (-90 <= lat <= 90 and -180 <= lon <= 180) or lat == lon == 0:
        return None
    text = {k: str(v) if v is not None else "" for k, v in attrs.items()}
    return {"key": text["OFFICE_CODE"].strip(), "name": f"Social Security office, {city}",
            "kind": "social security office", "type": "social security office",
            "state": text["STATE"].strip().upper(), "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
            "phone": text["PHONE"].strip(), "website": "",
            "opening_hours": hours.weekday_table(text, WEEKDAYS),
            "note": gov_details.note_of([("Address", address_of(attrs))])}


def offices(answer_pages):
    """The rows of the layer's answer pages (each an ArcGIS query answer: {"features": [{"attributes",
    "geometry"}]})."""
    for page in answer_pages:
        for feat in page.get("features") or []:
            row = office_row(feat.get("attributes") or {}, feat.get("geometry"))
            if row:
                yield row


def pages(entry, sleep=time.sleep):
    """The layer's answer pages, PAGE offices at a time, asking only for the KEPT columns."""
    from placepacks import fetch
    f = entry["fetch"]
    url = f["url"].rstrip("/") + "/query"
    start = 0
    while True:
        answer = fetch.post_json(url, {"where": "1=1", "outFields": ",".join(KEPT), "returnGeometry": "true",
                                       "outSR": "4326", "orderByFields": "OFFICE_CODE", "resultOffset": start,
                                       "resultRecordCount": PAGE, "f": "json"}, sleep=sleep,
                                 pause=f.get("pause", 2))
        yield answer
        got = len(answer.get("features") or [])
        if not answer.get("exceededTransferLimit") and got < PAGE:
            break
        start += got
        if not got or start > 20000:
            break


def prepare(entry, folder, sleep=time.sleep):
    """Write <folder>/<id>.csv of every office (see the module docstring). Returns the number written."""
    count = gov_details.write_rows(os.path.join(folder, entry["id"] + ".csv"), offices(pages(entry, sleep)))
    if not count:
        raise ValueError("the layer gave no office (has it moved?)")
    return count
