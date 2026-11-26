"""Burger King (US): the chain's own GraphQL store API (the one its app and bk.com use), asked around points of a
US grid. Endpoint and query from All The Places' burger_king spider (github.com/alltheplaces/alltheplaces,
locations/spiders/burger_king.py, MIT), trimmed to the fields kept here (no e-mail, no franchisee name).

Checked 26 November 2026 from a test machine: 3 requests, all answered (JSON); a 128 km search around Atlanta gave
176 restaurants in one answer (totalCount 176, no next page). The API host has no robots.txt.
"""

from placepacks.chains import hours as oh
from placepacks.chains.base import make_row, us_grid

ENDPOINT = "https://use1-prod-bk-gateway.rbictg.com/graphql"
SPACING_KM = 170                  # grid spacing; each search reaches RADIUS_M around its point
RADIUS_M = 128000
TAGS = {"amenity": "fast_food", "cuisine": "burger"}
QUERY = ("query GetRestaurants($input: RestaurantsInput) { restaurants(input: $input) { pageInfo { hasNextPage "
         "endCursor } totalCount nodes { _id storeId latitude longitude phoneNumber physicalAddress { address1 "
         "city stateProvinceShort postalCode country } diningRoomHours { monOpen monClose tueOpen tueClose wedOpen "
         "wedClose thrOpen thrClose friOpen friClose satOpen satClose sunOpen sunClose } } } }")
_DAYS = (("mon", "Mo"), ("tue", "Tu"), ("wed", "We"), ("thr", "Th"), ("fri", "Fr"), ("sat", "Sa"), ("sun", "Su"))


def body(lat, lon):
    """The GraphQL request for the restaurants within RADIUS_M of (lat, lon)."""
    return {"operationName": "GetRestaurants", "query": QUERY, "variables": {"input": {
        "filter": "NEARBY", "coordinates": {"userLat": lat, "userLng": lon, "searchRadius": RADIUS_M},
        "first": 20000}}}


def hours_of(h):
    """OSM hours of the dining room's monOpen/monClose ... sunOpen/sunClose ("06:00:00"), or ""."""
    if not isinstance(h, dict):
        return ""
    days = {}
    for key, day in _DAYS:
        got = oh.span(h.get(f"{key}Open"), h.get(f"{key}Close"))
        if got:
            days[day] = [got]
    return oh.week(days)


def row_of(node):
    """One restaurant of the API as a row, or None."""
    a = node.get("physicalAddress") or {}
    if str(a.get("country") or "USA").upper() not in ("USA", "US", "UNITED STATES"):
        return None
    store_id = str(node.get("_id") or "").replace("restaurant_", "")
    return make_row("burger-king", node.get("storeId") or store_id, "Burger King", TAGS, node.get("latitude"),
                    node.get("longitude"), brand="Burger King", brand_wikidata="Q177054",
                    phone=node.get("phoneNumber"),
                    website=f"https://www.bk.com/store-locator/store/{store_id}" if store_id else "",
                    opening_hours=hours_of(node.get("diningRoomHours")), street=a.get("address1"),
                    city=str(a.get("city") or "").title(), state=a.get("stateProvinceShort"),
                    postcode=a.get("postalCode"))


def collect(client, stats):
    """Yield every US restaurant once (searches overlap)."""
    seen = set()
    points = us_grid(SPACING_KM)
    stats.update(searches=len(points))
    for lat, lon in points:
        data = client.json(ENDPOINT, body(lat, lon), {"x-ui-language": "en", "x-ui-region": "US"})
        found = ((data.get("data") or {}).get("restaurants") or {})
        if (found.get("pageInfo") or {}).get("hasNextPage"):
            stats["cut_off"] = stats.get("cut_off", 0) + 1     # never seen: "first" is far above any count
        for node in found.get("nodes") or []:
            row = row_of(node)
            if row and row["key"] not in seen:
                seen.add(row["key"])
                yield row
