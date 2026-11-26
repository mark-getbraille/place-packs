"""Ford and Lincoln dealers: Ford's own dealer API (ford.com/cxservices/dealer/Dealers.json), asked once per state
and make, as All The Places' ford_dealers_us spider does (github.com/alltheplaces/alltheplaces, MIT), which gave 9
US dealers in November 2026 (it reads the state list with a browser; here the list is fixed).

The API wants the "Application-id" that ford.com's own dealer page carries for every visitor (its "clientId"); it
is read from that page once per run. It is a public value of the page, not a login or a challenge token; if the
page stops giving it, the run fails (and the previous month's dealers are kept).
ford.com's robots.txt asks for 10 seconds between requests (Crawl-delay: 10), so the pause is 10 seconds.

Checked 26 November 2026: 3 requests (the dealer page; Vermont's Ford dealers twice): 13 dealers with number, name,
address, position, phone, web site and sales and service hours; one had no position (0.0) and is left out.
"""

import re

from placepacks.chains import hours as oh
from placepacks.chains.base import make_row

PAGE = "https://www.ford.com/dealerships/"
API = "https://www.ford.com/cxservices/dealer/Dealers.json?make={make}&state={state}"
MAKES = {"Ford": ("Ford", "Q44294"), "Lincoln": ("Lincoln", "Q216796")}
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
          "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR").split()
_CLIENT_ID = re.compile(r'clientId\\?"\s*:\s*\\?"([0-9a-f-]{20,})')


def hours_of(block):
    """OSM hours of {"Day": [{"name": "Monday", "open": "09:00", "close": "18:00"} or {"closed": "true"}]}, or ""."""
    days = {}
    for item in (block or {}).get("Day") or []:
        if not isinstance(item, dict) or str(item.get("closed")).lower() == "true":
            continue
        d, got = oh.day_of(item.get("name")), oh.span(item.get("open"), item.get("close"))
        if d and got:
            days.setdefault(d, []).append(got)
    return oh.week(days)


def row_of(make, dealer):
    """One dealer as a row, or None. A service-only location ("SVO") is a car repair shop, the others dealers."""
    brand, wikidata = MAKES[make]
    a = dealer.get("Address") or {}
    service_only = dealer.get("LocationType") == "SVO"
    tags = {"shop": "car_repair" if service_only else "car", "brand": brand}
    site = str(dealer.get("URL") or "").replace("www. ", "www.")
    if not site or "null" in site.lower():
        site = f"https://www.ford.com/dealerships/{dealer['urlKey']}/" if dealer.get("urlKey") else ""
    return make_row("ford-dealers", f"{dealer.get('PACode')}-{make}" if dealer.get("PACode") else "",
                    dealer.get("Name"), tags, dealer.get("Latitude"), dealer.get("Longitude"), brand=brand,
                    brand_wikidata=wikidata, phone=dealer.get("Phone"), website=site,
                    opening_hours=hours_of(dealer.get("ServiceHours" if service_only else "SalesHours")),
                    street=a.get("Street1"), city=a.get("City"), state=a.get("State"), postcode=a.get("PostalCode"))


def collect(client, stats):
    """Yield every Ford and Lincoln dealer once."""
    m = _CLIENT_ID.search(client.fetch(PAGE))
    if not m:
        raise ValueError("ford.com's dealer page no longer carries its clientId")
    headers = {"Application-id": m.group(1)}
    seen = set()
    for make in MAKES:
        for state in STATES:
            data = client.json(API.format(make=make, state=state), headers=headers)
            dealers = (data.get("Response") or {}).get("Dealer") or []
            for dealer in [dealers] if isinstance(dealers, dict) else dealers:
                row = row_of(make, dealer) if isinstance(dealer, dict) else None
                if row and row["key"] not in seen:
                    seen.add(row["key"])
                    yield row
