"""Buick and GMC dealers: General Motors' own dealer-locator API (the "quantum" locator its brand sites use), asked
around points of a US grid, as All The Places' cadillac_us spider does for Cadillac (github.com/alltheplaces/
alltheplaces, locations/spiders/cadillac_us.py, MIT). Make codes: Buick 004, GMC 012 (Chevrolet 001 and Cadillac
006 are already in All The Places).

The API gives at most CAP dealers an answer; a search that comes back full is asked again as four smaller searches
(half the distance, one in each quarter of its square), down to MAX_DEPTH times.

Checked 26 November 2026: 3 requests (Buick 004 near Montpelier VT: 5 dealers; GMC 048: none; GMC 012: 16), each
with the dealer's number, name, address, position, phone, web site and hours. robots.txt of www.buick.com has no
rule for /bypass/.
"""

from placepacks.chains import hours as oh
from placepacks.chains.base import make_row, us_grid

URL = ("https://{host}/bypass/pcf/quantum-dealer-locator/v1/getDealers?desiredCount=1000&distance={miles}"
       "&makeCodes={make}&latitude={lat}&longitude={lon}&searchType=latLongSearch")
HEADERS = {"clientapplicationid": "quantum", "locale": "en-US"}
MAKES = {"buick-dealers": ("www.buick.com", "004", "Buick", "Q27415"),
         "gmc-dealers": ("www.gmc.com", "012", "GMC", "Q28993")}
MILES = 75                       # the first searches' distance; the grid spacing makes it cover every point
SPACING_KM = 160
CAP, MAX_DEPTH = 50, 3
_DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")       # dayOfWeek 1 is Monday


def hours_of(items):
    """OSM hours of the API's generalOpeningHour ([{"dayOfWeek": [1, 2], "openFrom": "08:00 AM", ...}]), or ""."""
    days = {}
    for item in items or []:
        got = oh.span(item.get("openFrom"), item.get("openTo"))
        for d in item.get("dayOfWeek") or []:
            if got and isinstance(d, int) and 1 <= d <= 7:
                days.setdefault(_DAYS[d - 1], []).append(got)
    return oh.week(days)


def search(client, host, make, lat, lon, miles, side_km, depth, stats):
    """The dealers within miles of (lat, lon); a full answer is split into four smaller searches."""
    import math
    url = URL.format(host=host, miles=miles, make=make, lat=round(lat, 4), lon=round(lon, 4))
    dealers = ((client.json(url, headers=HEADERS).get("payload") or {}).get("dealers")) or []
    yield from dealers
    if len(dealers) >= CAP:
        if depth >= MAX_DEPTH:
            stats["cut_off"] = stats.get("cut_off", 0) + 1
            return
        step = side_km / 4
        for dy in (-step, step):
            for dx in (-step, step):
                yield from search(client, host, make, lat + dy / 111.0,
                                  lon + dx / (111.0 * max(0.2, math.cos(math.radians(lat)))),
                                  max(5, miles // 2), side_km / 2, depth + 1, stats)


def tidy(text):
    """A name in capitals made readable ("ST. JOHNSBURY GMC LLC" -> "St. Johnsbury GMC LLC")."""
    import re
    from placepacks.readers.tabular import smart_case
    return re.sub(r"\b(Gmc|Llc|Usa)\b", lambda m: m.group(1).upper(), smart_case(text or ""))


def row_of(chain, dealer):
    """One dealer as a row, or None."""
    _host, _make, brand, wikidata = MAKES[chain]
    a = dealer.get("address") or {}
    if str(a.get("countryIso") or "US").upper() != "US":
        return None
    geo = dealer.get("geolocation") or {}
    tags = {"shop": "car", "brand": brand}
    return make_row(chain, dealer.get("dealerCode") or dealer.get("bac"), tidy(dealer.get("dealerName")), tags,
                    geo.get("latitude"), geo.get("longitude"), brand=brand, brand_wikidata=wikidata,
                    phone=(dealer.get("generalContact") or {}).get("phone1"), website=dealer.get("dealerUrl"),
                    opening_hours=hours_of(dealer.get("generalOpeningHour")),
                    street=tidy(a.get("addressLine1")), city=tidy(a.get("cityName")),
                    state=a.get("countrySubdivisionCode"), postcode=a.get("postalCodeFormatted") or a.get("postalCode"))


def collector(chain):
    """The collect function of one make (MAKES)."""
    host, make, _brand, _wd = MAKES[chain]

    def collect(client, stats):
        """Yield every US dealer of the make once."""
        seen = set()
        points = us_grid(SPACING_KM)
        stats.update(searches=len(points))
        for lat, lon in points:
            for dealer in search(client, host, make, lat, lon, MILES, SPACING_KM, 0, stats):
                row = row_of(chain, dealer)
                if row and row["key"] not in seen:
                    seen.add(row["key"])
                    yield row
    return collect
