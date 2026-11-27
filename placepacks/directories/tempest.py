"""City and county tourism boards' partner listings on the TEMPEST platform (formerly iDSS; the source
"tempest-listings"; the monthly tempest-listings workflow).

What: many city and county tourism boards (destination marketing organisations) run their website on Tempest, a
Craft CMS platform for tourism boards. Their "partner directory" lists the restaurants, shops, attractions, hotels
and venues of the area. Research of 27 November 2026 (notes/US-LOCAL-BUSINESS-DIRECTORIES.md): one robots.txt per
board told the platforms apart; Tempest sites name a Craft "sitemaps-1-sitemap.xml" index whose
"section-partnerDirectory" sitemaps list every listing ("/directory/<name>/"), and each listing page carries a
schema.org JSON-LD LocalBusiness (name, address, latitude, longitude, telephone, website) and the listing's
category in its page data (data-dms-category-name). SITES lists the boards that answered; boards that refused
(Cloudflare, a plain 403) are in BLOCKED and are never tried another way.

How, per site (collect()):
  1. robots.txt (obeyed: every listing page is checked; its Crawl-delay kept, at least 2 and at most 5 seconds
     between requests, PAUSE when it names none);
  2. the sitemap index (robots.txt's Sitemap line, else /sitemaps-1-sitemap.xml) and its partner-directory
     sitemaps (their address names "partner", or the section "directory" or "listings"; never the blog's); a site without them
     is not (or no longer) on Tempest: the run fails with that reason, and the site is checked by a person;
  3. each listing page: the JSON-LD LocalBusiness that is not the board's own entry, the page's listing id and
     category (data-dms-listing-id, data-dms-category-name), and, from its amenity list, only the accessibility
     items (wheelchair, ADA, accessible ...). Never kept: the description, the e-mail, photos, social links,
     reviews, the board's own entry.
A listing is left out when it has no street address (a tour operator or a home business: common.home_business), a
name that is a person's, or no position in the US. Its category gives its OpenStreetMap-style tags
(common.tags_of), and so its class and fine type in the packs.

In the packs (businesses part): a new place, unless another business source already lists it (the same phone
number within 500 m first, then the same name within 75 m): then the listing's phone, website and note go to that
place instead (PackWriter.drop_duplicates), as for the Simpleview listings.
Only the Python standard library is used.
"""

import html
import re

from placepacks.chains import jsonld
from placepacks.chains.base import make_row, sitemap
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.directories.common import Robots, home_business, no_email, tags_of
from placepacks.directories.simpleview import ACCESS_LABEL, FIELDS  # noqa: F401  (the same CSV columns)

USER_AGENT = "place-packs-tempest/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
PAUSE = 3.0                     # seconds between requests when robots.txt names no Crawl-delay
MIN_PAUSE, MAX_PAUSE = 2.0, 5.0
LISTING = re.compile(r"/directory/([^/?#]+)/?$")
PARTNER_MAP = re.compile(r"partner|section-(directory|listings?)-", re.I)   # not "blogDirectory"
_ATTR = re.compile(r'data-dms-(listing-id|partner-id|category-name)="([^"]*)"')
_AMENITIES = re.compile(r'<ul[^>]*class="[^"]*detail__amenities[^"]*"[^>]*>(.*?)</ul>', re.S | re.I)
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
# "101 West Georgia Street Indianapolis, Indiana 46225": street and town run together before the first comma; the
# street ends at its last street-type word (and a suite after it).
_ADDRESS = re.compile(r"^(?P<head>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]+?)\.?\s+(?P<zip>\d{5})(?:-\d{4})?\s*$")
_STREET_END = re.compile(
    r"^(?P<street>.*\b(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|way|lane|ln|parkway|pkwy|place|pl|"
    r"court|ct|circle|cir|highway|hwy|square|sq|terrace|ter|trail|trl|plaza|pike|alley|row|loop|broadway|"
    r"[nsew]|north|south|east|west)\.?(?:\s+(?:suite|ste|unit|#|bldg|building|floor|fl)\.?\s*[\w-]+)?)\s+"
    r"(?P<city>[A-Z][A-Za-z.' -]+)$", re.I)
STATE_CODES = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
               "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL",
               "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
               "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
               "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
               "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
               "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
               "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
               "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
               "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
               "wyoming": "WY"}


class NotTempest(RuntimeError):
    """The site has no partner-directory sitemaps: it is not (or no longer) on Tempest."""


def _site(title, home, state, expected=800):
    """One entry of SITES: the board's name, its home address, its state, about how many listings it has, the
    job's time (a site runs inside a matrix group: placepacks/directories/run.py)."""
    return {"title": title, "home": home, "state": state, "expected": expected,
            "budget": int(expected * 1.5) + 200, "timeout": 300}


# The boards found on Tempest (one robots.txt each, 27 November 2026: a Craft "sitemaps-1-sitemap.xml" index; Visit
# Indy's partner directory and one listing were read as the sample). A board whose index has no partner-directory
# sitemap fails with NotTempest and is checked by a person.
SITES_TABLE = [
    # id, title, home, state
    ('visitdallas', 'Dallas, TX tourism board (visitdallas.com)', 'https://www.visitdallas.com', 'TX'),
    ('visitlongbeach', 'Long Beach, CA tourism board (visitlongbeach.com)', 'https://www.visitlongbeach.com', 'CA'),
    ('visitspokane', 'Spokane, WA tourism board (visitspokane.com)', 'https://www.visitspokane.com', 'WA'),
    ('visitindy', 'Indianapolis, IN tourism board (visitindy.com)', 'https://www.visitindy.com', 'IN'),
    ('visitdetroit', 'Detroit, MI tourism board (visitdetroit.com)', 'https://visitdetroit.com', 'MI'),
    ('minneapolis', 'Minneapolis, MN tourism board (minneapolis.org)', 'https://www.minneapolis.org', 'MN'),
    ('visitsaintpaul', 'Saint Paul, MN tourism board (visitsaintpaul.com)', 'https://www.visitsaintpaul.com', 'MN'),
    ('littlerock', 'Little Rock, AR tourism board (littlerock.com)', 'https://www.littlerock.com', 'AR'),
    ('gotolouisville', 'Louisville, KY tourism board (gotolouisville.com)', 'https://www.gotolouisville.com', 'KY'),
    ('visitbatonrouge', 'Baton Rouge, LA tourism board (visitbatonrouge.com)', 'https://www.visitbatonrouge.com', 'LA'),
    ('visitjackson', 'Jackson, MS tourism board (visitjackson.com)', 'https://www.visitjackson.com', 'MS'),
    ('visitjacksonville', 'Jacksonville, FL tourism board (visitjacksonville.com)', 'https://www.visitjacksonville.com', 'FL'),
    ('visitpittsburgh', 'Pittsburgh, PA tourism board (visitpittsburgh.com)', 'https://www.visitpittsburgh.com', 'PA'),
    ('visitsyracuse', 'Syracuse, NY tourism board (visitsyracuse.com)', 'https://www.visitsyracuse.com', 'NY'),
    ('albany', 'Albany, NY tourism board (albany.org)', 'https://www.albany.org', 'NY'),
    ('goprovidence', 'Providence, RI tourism board (goprovidence.com)', 'https://www.goprovidence.com', 'RI'),
    ('discoverlancaster', 'Lancaster, PA tourism board (discoverlancaster.com)', 'https://www.discoverlancaster.com', 'PA'),
    ('visitsouthbend', 'South Bend, IN tourism board (visitsouthbend.com)', 'https://www.visitsouthbend.com', 'IN'),
    ('visitcasper', 'Casper, WY tourism board (visitcasper.com)', 'https://www.visitcasper.com', 'WY'),
    ('visitcos', 'Colorado Springs, CO tourism board (visitcos.com)', 'https://www.visitcos.com', 'CO'),
    ('visitgalveston', 'Galveston, TX tourism board (visitgalveston.com)', 'https://www.visitgalveston.com', 'TX'),
    ('visitmesa', 'Mesa, AZ tourism board (visitmesa.com)', 'https://www.visitmesa.com', 'AZ'),
    ('travelsalem', 'Salem, OR tourism board (travelsalem.com)', 'https://www.travelsalem.com', 'OR'),
    ('visitogden', 'Ogden, UT tourism board (visitogden.com)', 'https://www.visitogden.com', 'UT'),
    ('visitpensacola', 'Pensacola, FL tourism board (visitpensacola.com)', 'https://www.visitpensacola.com', 'FL'),
    ('floridashistoriccoast', 'St. Augustine, FL tourism board (floridashistoriccoast.com)', 'https://www.floridashistoriccoast.com', 'FL'),
]
SITES = {i: _site(t, h, st) for i, t, h, st in SITES_TABLE}
# Boards that answered our one robots.txt request with an anti-bot challenge or a plain 403 are listed with the
# Simpleview ones (simpleview.CITY_BLOCKED): the robots.txt request could not tell their platform.


def split_address(text):
    """(street, city, state code, ZIP) of a one-line address ("101 West Georgia Street Indianapolis, Indiana
    46225" -> ("101 West Georgia Street", "Indianapolis", "IN", "46225")); a part that cannot be told apart is ""
    (the whole head stays the street)."""
    text = " ".join(html.unescape(str(text or "")).split())
    m = _ADDRESS.match(text)
    if not m:
        return text.split(",")[0].strip(), "", "", ""
    head, state = m.group("head").strip(), m.group("state").strip()
    code = state.upper() if len(state) == 2 else STATE_CODES.get(state.lower(), "")
    if "," in head:                                             # "184 Main St, Burlington"
        street, city = (p.strip() for p in head.rsplit(",", 1))
    else:
        s = _STREET_END.match(head)
        street, city = (s.group("street"), s.group("city")) if s else (head, "")
    return street, city, code, m.group("zip")


def _business(page):
    """The page's LocalBusiness JSON-LD object that is the listing (not the board's own "#identity" entry)."""
    for value in jsonld.blocks(page):
        for thing in jsonld.things(value):
            if "identity" in str(thing.get("@id") or ""):
                continue
            if any(t in ("LocalBusiness", "Restaurant", "Hotel", "Store", "TouristAttraction", "LodgingBusiness",
                         "FoodEstablishment", "Museum", "Place") for t in jsonld.types_of(thing)):
                return thing
    return {}


def accessibility(page):
    """The accessibility items of a listing's amenity list ("Wheelchair Accessible", "ADA Restrooms")."""
    m = _AMENITIES.search(page or "")
    if not m:
        return []
    items = [" ".join(html.unescape(_TAGS.sub(" ", li)).split()) for li in _LI.findall(m.group(1))]
    return [i for i in items if i and ACCESS_LABEL.search(i)]


def listing(page, site, url):
    """One listing page as a row (simpleview.FIELDS), or None (see the module docstring)."""
    thing = _business(page)
    if not thing:
        return None
    attrs = {}
    for k, v in _ATTR.findall(page):
        attrs.setdefault(k, html.unescape(v))
    m = LISTING.search(url)
    ref = attrs.get("listing-id") or attrs.get("partner-id") or (m.group(1) if m else "")
    name = html.unescape(str(thing.get("name") or ""))
    address = thing.get("address")
    if isinstance(address, dict):
        street = str(address.get("streetAddress") or "")
        city, state = str(address.get("addressLocality") or ""), str(address.get("addressRegion") or "")
        postcode = str(address.get("postalCode") or "")
    else:
        street, city, state, postcode = split_address(address)
    category = attrs.get("category-name", "")
    if not ref or home_business(name, street, category):
        return None
    lat, lon = thing.get("latitude"), thing.get("longitude")
    if lat in (None, "") or lon in (None, ""):
        at = jsonld.position(thing)
        lat, lon = at if at else (None, None)
    website = str(thing.get("url") or "").strip()
    row = make_row(site, ref, name, tags_of(category), lat, lon, phone=str(thing.get("telephone") or ""),
                   website=website if website.startswith("http") else "", street=street, city=city, state=state,
                   postcode=postcode)
    if row is None:
        return None
    if not row["type"] and category:
        row["type"] = " ".join(category.lower().split())
    access = accessibility(page)
    row["category"] = category
    row["note"] = no_email("Accessibility: " + ", ".join(access)[:600]) if access else ""
    return row


def listing_pages(client, robots, home):
    """The listing page addresses of a site's partner-directory sitemaps, each once, in sitemap order. Raises
    NotTempest when the site has none."""
    maps = robots.sitemaps() or [home.rstrip("/") + "/sitemaps-1-sitemap.xml"]
    found, seen, partner = [], set(), []
    for url in maps[:5]:
        try:
            locs = sitemap(client, url)
        except NotFound:
            continue
        children = [u for u in locs if re.search(r"\.xml(\.gz)?(\?|$)", u)]
        partner += [u for u in children if PARTNER_MAP.search(u.rsplit("/", 1)[-1])]
    if not partner:
        raise NotTempest("no partner-directory sitemap (is the site still on Tempest?)")
    for url in partner[:60]:
        try:
            locs = sitemap(client, url)
        except NotFound:
            continue
        for loc in locs:
            if LISTING.search(loc) and loc not in seen and robots.allowed(loc):
                seen.add(loc)
                found.append(loc)
    return found


def collect(client, unit, stats):
    """Yield the rows of one site (see the module docstring). client: a polite client (its pause is set from
    robots.txt here); stats gets "listings", "gone", "left_out" and "failed" counts."""
    spec = SITES[unit]
    robots = Robots(client, spec["home"], ROBOTS_AGENT)
    delay = robots.crawl_delay()
    client.pause = max(MIN_PAUSE, min(MAX_PAUSE, delay if delay else PAUSE))
    pages = listing_pages(client, robots, spec["home"])
    stats.update(listings=len(pages), gone=0, left_out=0, failed=0)
    seen = set()
    for url in pages:
        try:
            page = client.fetch(url)
        except NotFound:
            stats["gone"] += 1
            continue
        except RequestFailed:
            stats["failed"] += 1
            if stats["failed"] > max(20, len(pages) // 20):
                raise
            continue
        row = listing(page, unit, url)
        if row is None or row["key"] in seen:
            stats["left_out"] += 1
            continue
        seen.add(row["key"])
        yield row
