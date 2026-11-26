"""What every chain collector shares: the row it writes, the US test, the search grid and sitemap reading.

A row has the shape of the All The Places CSV the build already reads (fetch.ATP_FIELDS and ATP_CONTACT_FIELDS), so
the existing readers give the chain stores their class, fine type, brand, contact details and history unchanged:
  key "<chain>:<the chain's own store number>", spider (the chain's id), name, branch, brand, brand_wikidata,
  main_key / main_value / type (from OpenStreetMap-style tags, as for All The Places), lat, lon, first, last (empty),
  phone, website (the store's own page), opening_hours (OpenStreetMap syntax),
then the address (street, city, state, postcode), kept for checking by hand; the packs do not use it.
Only the Python standard library is used.
"""

import math
import re

from placepacks.contact import is_brand_name
from placepacks.fetch import _PERSON, ATP_CONTACT_FIELDS, ATP_FIELDS, ATP_PERSONAL

FIELDS = ATP_FIELDS + ATP_CONTACT_FIELDS + ["street", "city", "state", "postcode"]

# Where US stores can be (the search grid's areas): the 48 states, Alaska's mainland, Hawaii's main islands and
# Puerto Rico (west, south, east, north). The rows are also checked against the states' own boxes (in_us).
GRID_BOXES = [(-124.8, 24.4, -66.9, 49.4), (-170.0, 54.0, -130.0, 71.5), (-160.6, 18.8, -154.7, 22.3),
              (-67.3, 17.9, -65.2, 18.6)]
_US_BOXES = []


def us_boxes():
    """The boxes of the US regions of regions.json (states, DC, Puerto Rico), read once."""
    if not _US_BOXES:
        from placepacks import catalogue
        from placepacks.regions import boxes_of
        for r in catalogue.regions().values():
            if catalogue.country_code(r) == "US" and not r.get("parent"):
                _US_BOXES.extend(boxes_of(r))
    return _US_BOXES


def in_us(lat, lon, margin=0.0):
    """True when (lat, lon) is inside the box of a US state, DC or Puerto Rico (within margin degrees)."""
    return any(w - margin <= lon <= e + margin and s - margin <= lat <= n + margin for w, s, e, n in us_boxes())


def us_grid(spacing_km):
    """Search points about spacing_km apart over GRID_BOXES, kept only where a US state's box is near: a radius
    search of spacing_km * 0.75 around each point covers the US without gaps (half the square's diagonal is
    spacing_km * 0.71). Returns [(lat, lon)], south to north."""
    points = []
    step_lat = spacing_km / 111.0
    for west, south, east, north in GRID_BOXES:
        lat = south + step_lat / 2
        while lat < north + step_lat / 2:
            step_lon = spacing_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
            lon = west + step_lon / 2
            while lon < east + step_lon / 2:
                if in_us(lat, lon, margin=max(step_lat, step_lon) / 2):
                    points.append((round(lat, 4), round(lon, 4)))
                lon += step_lon
            lat += step_lat
    return points


def make_row(chain, ref, name, tags, lat, lon, brand="", brand_wikidata="", branch="", phone="", website="",
             opening_hours="", street="", city="", state="", postcode=""):
    """One store as a row (FIELDS), or None when it cannot be used: no store number, no position or one outside
    the US, an individual's own office (ATP_PERSONAL), or no name or a name that is a person's (not the brand's). tags are the
    store's OpenStreetMap-style tags ({"amenity": "fast_food", "cuisine": "burger"}) that give its class and type."""
    from placepacks import types as place_types
    from placepacks.readers.osm import main_tag
    ref = " ".join(str(ref or "").split())
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not ref or (lat == 0 and lon == 0) or not in_us(lat, lon):
        return None
    if any(tags.get(k) in v for k, v in ATP_PERSONAL.items()):
        return None
    name = " ".join(str(name or brand or "").split())
    if not name or (_PERSON.match(name) and not is_brand_name(name, brand)):
        return None                                 # a person's name (a chain's own brand is not one)
    text = {k: str(v) for k, v in tags.items()}
    found = main_tag(text)
    row = {"key": f"{chain}:{ref}", "spider": chain, "name": name, "branch": " ".join(str(branch or "").split()),
           "brand": brand, "brand_wikidata": brand_wikidata, "main_key": found[0] if found else "",
           "main_value": found[1] if found else "", "type": place_types.osm(text), "lat": f"{lat:.6f}",
           "lon": f"{lon:.6f}", "first": "", "last": "",
           "phone": " ".join(str(phone or "").split())[:100], "website": str(website or "").strip()[:400],
           "opening_hours": " ".join(str(opening_hours or "").split())[:255],
           "street": " ".join(str(street or "").split()), "city": " ".join(str(city or "").split()),
           "state": " ".join(str(state or "").split()), "postcode": " ".join(str(postcode or "").split())}
    return row


_LOC = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)\s*(?:\]\]>)?\s*</loc>", re.I)


def sitemap(client, url):
    """The page addresses (<loc>) of one sitemap file (a .gz one too). A sitemap index gives its sitemaps'
    addresses: the collector chooses which of them to read."""
    import html
    return [html.unescape(u) for u in _LOC.findall(client.fetch(url))]
