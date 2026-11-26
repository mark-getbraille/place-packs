"""schema.org JSON-LD on store pages: finding it and reading a store out of it (name, position, address, phone,
web page, hours), as All The Places' StructuredDataSpider and LinkedDataParser do (github.com/alltheplaces/
alltheplaces, locations/structured_data_spider.py and linked_data_parser.py, MIT; rewritten here).

Store pages are written by hand or by templates and are often not quite valid JSON: a comma before "}", an extra
"}" at the end (seen on Jack in the Box's pages, November 2026). blocks() forgives those; a block that still cannot
be read is skipped.
"""

import html
import json
import re

from placepacks.chains import hours as oh

_SCRIPT = re.compile(r"<script[^>]*type\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>", re.S | re.I)
_MAP_Q = re.compile(r"[?&](?:q|ll|query|destination)=(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")


def loads(text):
    """One JSON value from text that may have trailing commas or junk after the value; None when unreadable."""
    text = (text or "").strip().lstrip("﻿")
    if text.startswith("<!--"):
        text = text[4:].rsplit("-->", 1)[0]
    for attempt in (text, re.sub(r",\s*([}\]])", r"\1", text)):
        try:
            return json.JSONDecoder(strict=False).raw_decode(attempt)[0]
        except ValueError:
            continue
    return None


def blocks(page):
    """Every JSON-LD value of an HTML page (each script block, read leniently)."""
    found = []
    for raw in _SCRIPT.findall(page or ""):
        value = loads(raw)
        if value is not None:
            found.append(value)
    return found


def things(value):
    """Every schema.org object in a JSON-LD value: the value itself, the items of a list or of "@graph"."""
    if isinstance(value, list):
        for item in value:
            yield from things(item)
    elif isinstance(value, dict):
        yield value
        for item in value.get("@graph") or []:
            yield from things(item)


def types_of(thing):
    """The @type names of an object, as a set."""
    t = thing.get("@type")
    return {str(x) for x in (t if isinstance(t, list) else [t]) if x}


def find(page, wanted):
    """The objects of a page whose @type is one of wanted (a set of names such as {"Restaurant", "AutoRental"})."""
    return [t for v in blocks(page) for t in things(v) if types_of(t) & set(wanted)]


def _text(value):
    """A plain one-line text of a JSON-LD value (a string, a number, or {"name": ...}); HTML entities undone."""
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or ""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, (str, int, float))), "")
    return " ".join(html.unescape(str(value or "")).split())


def _number(value):
    """A float, or None."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def position(thing):
    """(lat, lon) of a store: its "geo" (GeoCoordinates), else the "?q=lat,lon" of its "hasMap" or "map" link."""
    geo = thing.get("geo")
    if isinstance(geo, list):
        geo = geo[0] if geo else None
    if isinstance(geo, dict):
        lat, lon = _number(geo.get("latitude")), _number(geo.get("longitude"))
        if lat is not None and lon is not None:
            return lat, lon
    for key in ("hasMap", "map"):
        m = _MAP_Q.search(str(thing.get(key) or ""))
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def store(thing, need_position=True):
    """A store read from one schema.org object: {"name", "lat", "lon", "identifier", "street", "city", "state",
    "postcode", "country", "phone", "website", "opening_hours"} (missing ones are ""), or None without a position
    (unless need_position is False: then lat and lon are None). The phone may be the object's or its address's
    "telephone" (Budget puts it there). E-mail is never read."""
    at = position(thing)
    if not at and need_position:
        return None
    at = at or (None, None)
    address = thing.get("address")
    if isinstance(address, list):
        address = address[0] if address else {}
    address = address if isinstance(address, dict) else {}
    hours = ""
    if thing.get("openingHoursSpecification"):
        hours = oh.from_spec(thing["openingHoursSpecification"])
    if not hours and thing.get("openingHours"):
        value = thing["openingHours"]
        hours = oh.from_text("; ".join(value) if isinstance(value, list) else value)
    ident = thing.get("identifier")
    ident = ident.get("value") if isinstance(ident, dict) else ident
    return {"name": _text(thing.get("name")), "lat": at[0], "lon": at[1], "identifier": _text(ident),
            "street": _text(address.get("streetAddress")), "city": _text(address.get("addressLocality")),
            "state": _text(address.get("addressRegion")), "postcode": _text(address.get("postalCode")),
            "country": _text(address.get("addressCountry")),
            "phone": _text(thing.get("telephone") or address.get("telephone")),
            "website": _text(thing.get("url") or address.get("mainEntityOfPage")), "opening_hours": hours}
