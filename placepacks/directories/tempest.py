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
     reviews, the board's own entry. Many boards leave the position, the address or the telephone out of the
     JSON-LD (found on the first GitHub run, 27 November 2026): then the listing's map button
     (data-marker-lat/-lng), its "maps?q=<lat>,<lon>" link, its detail address block or "Contact Information"
     list, the first telephone link after that address and the "Website" button are read (listing()).
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
# "/directory/<name>/" on Tempest; "/listing/<name>" on boards that moved to DestinationCore, the same Craft base
# (Providence, seen 27 November 2026: section "businessDirectory").
LISTING = re.compile(r"/(?:directory|listing)/([^/?#]+)/?$")
PARTNER_MAP = re.compile(r"partner|section-(directory|listings?|businessDirectory)-\d", re.I)   # not "blogDirectory"
_ATTR = re.compile(r'data-dms-(listing-id|partner-id|category-name)="([^"]*)"')
_AMENITIES = re.compile(r'<ul[^>]*class="[^"]*detail__amenities[^"]*"[^>]*>(.*?)</ul>', re.S | re.I)
_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
# Fallbacks for boards whose JSON-LD leaves things out (found on the first GitHub run, 27 November 2026: Albany,
# Louisville, Salem, Baton Rouge, Jackson and others give no latitude/longitude in the JSON-LD, some no address and no
# telephone; Louisville types its listings "TouristInformationCenter"): the map button of the listing
# (data-marker-lat / data-marker-lng / data-marker-title), the detail address block (class "detail__address" or
# "detail__info-block") and the first telephone link after that block.
_MARKER_TAG = re.compile(r"<[^>]*\bdata-marker-lat=[^>]*>", re.S)
# The start of an address block: the detail block (class "detail__address", else "detail__info-block"); the
# address is read from the next WINDOW characters (blocks nest divs: Pittsburgh's starts with the business's name).
_DETAIL_BLOCKS = [re.compile(r'class="(?:[^"]*\s)?detail__%s(?:\s[^"]*)?"[^>]*>' % c, re.I)
                  for c in ("address", "info-block")]
_BLOCK_END = re.compile(r"<(?:ul|h\d|button|footer|script)\b", re.I)
WINDOW = 1200
_BR = re.compile(r"<br\s*/?>|</(?:span|p|li|div)>", re.I)            # line ends inside an address block
_MAPS_Q = re.compile(r"maps\?(?:[^\"'<>]*&(?:amp;)?)?q=(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)")
_TEL = re.compile(r'href="tel:([^"]+)"', re.I)
# The listing's "Website" button: <a ... href="http://example.com" ... data-dms-partner-detail-website-click>.
_WEBSITE = re.compile(r'<a\b(?=[^>]*\bdata-dms-partner-detail-website-click)[^>]*\bhref="(https?://[^"]+)"', re.I)
_CONTACT = re.compile(r"Contact Information\s*</h\d>\s*<ul[^>]*>(.*?)</ul>", re.S | re.I)
_TO_ZIP = re.compile(r"^(.*?[A-Za-z.]\s+\d{5}(?:-\d{4})?)\b")    # up to the state's ZIP (not a house number)
_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\s*$")
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
    # id, title, home, state, expected listings (the partner-directory sitemaps' count on 27 November 2026, plus
    # a tenth: it sets the site's request budget and its share of the group's time; the first run gave every site
    # 800, and Detroit and Pittsburgh, with over 2,400 listings each, ran out of requests)
    ('visitdallas', 'Dallas, TX tourism board (visitdallas.com)', 'https://www.visitdallas.com', 'TX', 800),
    ('visitlongbeach', 'Long Beach, CA tourism board (visitlongbeach.com)', 'https://www.visitlongbeach.com', 'CA', 450),
    ('visitspokane', 'Spokane, WA tourism board (visitspokane.com)', 'https://www.visitspokane.com', 'WA', 1500),
    ('visitindy', 'Indianapolis, IN tourism board (visitindy.com)', 'https://www.visitindy.com', 'IN', 3550),
    ('visitdetroit', 'Detroit, MI tourism board (visitdetroit.com)', 'https://visitdetroit.com', 'MI', 2650),
    ('minneapolis', 'Minneapolis, MN tourism board (minneapolis.org)', 'https://www.minneapolis.org', 'MN', 1150),
    ('visitsaintpaul', 'Saint Paul, MN tourism board (visitsaintpaul.com)', 'https://www.visitsaintpaul.com', 'MN', 750),
    ('littlerock', 'Little Rock, AR tourism board (littlerock.com)', 'https://www.littlerock.com', 'AR', 1700),
    ('gotolouisville', 'Louisville, KY tourism board (gotolouisville.com)', 'https://www.gotolouisville.com', 'KY', 1300),
    ('visitbatonrouge', 'Baton Rouge, LA tourism board (visitbatonrouge.com)', 'https://www.visitbatonrouge.com', 'LA', 1300),
    ('visitjackson', 'Jackson, MS tourism board (visitjackson.com)', 'https://www.visitjackson.com', 'MS', 750),
    ('visitjacksonville', 'Jacksonville, FL tourism board (visitjacksonville.com)', 'https://www.visitjacksonville.com', 'FL', 2450),
    ('visitpittsburgh', 'Pittsburgh, PA tourism board (visitpittsburgh.com)', 'https://www.visitpittsburgh.com', 'PA', 3600),
    ('visitsyracuse', 'Syracuse, NY tourism board (visitsyracuse.com)', 'https://www.visitsyracuse.com', 'NY', 1400),
    ('albany', 'Albany, NY tourism board (albany.org)', 'https://www.albany.org', 'NY', 650),
    ('goprovidence', 'Providence, RI tourism board (goprovidence.com)', 'https://www.goprovidence.com', 'RI', 400),
    ('discoverlancaster', 'Lancaster, PA tourism board (discoverlancaster.com)', 'https://www.discoverlancaster.com', 'PA', 850),
    ('visitsouthbend', 'South Bend, IN tourism board (visitsouthbend.com)', 'https://www.visitsouthbend.com', 'IN', 700),
    ('visitcasper', 'Casper, WY tourism board (visitcasper.com)', 'https://www.visitcasper.com', 'WY', 450),
    ('visitcos', 'Colorado Springs, CO tourism board (visitcos.com)', 'https://www.visitcos.com', 'CO', 1200),
    ('visitgalveston', 'Galveston, TX tourism board (visitgalveston.com)', 'https://www.visitgalveston.com', 'TX', 850),
    ('visitmesa', 'Mesa, AZ tourism board (visitmesa.com)', 'https://www.visitmesa.com', 'AZ', 450),
    ('travelsalem', 'Salem, OR tourism board (travelsalem.com)', 'https://www.travelsalem.com', 'OR', 550),
    ('visitogden', 'Ogden, UT tourism board (visitogden.com)', 'https://www.visitogden.com', 'UT', 650),
    ('visitpensacola', 'Pensacola, FL tourism board (visitpensacola.com)', 'https://www.visitpensacola.com', 'FL', 1000),
    ('floridashistoriccoast', 'St. Augustine, FL tourism board (floridashistoriccoast.com)', 'https://www.floridashistoriccoast.com', 'FL', 650),
]
SITES = {i: _site(t, h, st, n) for i, t, h, st, n in SITES_TABLE}
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


def _path(url):
    """The path of an address or of a site-relative path, with one slash at the end ("/directory/x/")."""
    path = str(url or "").split("#")[0].split("?")[0]
    path = re.sub(r"^https?://[^/]+", "", path)
    return path.rstrip("/") + "/" if path else ""


def _business(page, url=""):
    """The page's JSON-LD object that is the listing (never the board's own "#identity" entry): the object whose
    mainEntityOfPage (or url) is this page, whatever its type (Louisville types its listings
    "TouristInformationCenter"); else the first business-like object."""
    things = [t for v in jsonld.blocks(page) for t in jsonld.things(v)
              if not re.search(r"#(identity|creator)", str(t.get("@id") or "")) and t.get("name")]
    here, chosen = _path(url), {}
    if here:
        chosen = next((t for t in things if here in (_path(t.get("mainEntityOfPage")), _path(t.get("url")))), {})
    if not chosen:                      # the sitemap's address redirected to a new one: any listing entry
        chosen = next((t for t in things if LISTING.search(_path(t.get("mainEntityOfPage")).rstrip("/"))), {})
    if not chosen:
        chosen = next((t for t in things if jsonld.types_of(t) & {
            "LocalBusiness", "Restaurant", "Hotel", "Store", "TouristAttraction", "LodgingBusiness",
            "FoodEstablishment", "Museum", "Place"}), {})
    if chosen and not (chosen.get("address") and (chosen.get("geo") or chosen.get("latitude"))):
        # DestinationCore pages (Providence) give the page's entry without an address and a second entry of the
        # same name with the address, telephone and position: the missing fields are taken from it.
        merged = dict(chosen)
        for other in things:
            if other is not chosen and _plain(other.get("name")) == _plain(chosen.get("name")):
                for key in ("address", "geo", "latitude", "longitude", "telephone"):
                    if not merged.get(key) and other.get(key):
                        merged[key] = other[key]
        chosen = merged
    return chosen


def _host(url):
    """The host of an address without "www." ("" for a relative path)."""
    m = re.match(r"^https?://(?:www\.)?([^/:?#]+)", str(url or "").strip(), re.I)
    return m.group(1).lower() if m else ""


def _plain(text):
    """Text for comparing names: entities undone (twice: "&amp;#039;"), lower case, single spaces."""
    return " ".join(html.unescape(html.unescape(str(text or ""))).lower().split())


def marker(page, name=""):
    """(lat, lon) of the listing's map button (data-marker-lat / data-marker-lng): the one titled with the
    listing's name, else the first; None when the page has none. Related events further down have their own
    buttons, so the title is checked first."""
    found = []
    for tag in _MARKER_TAG.findall(page or ""):
        lat = re.search(r'data-marker-lat="(-?[\d.]+)"', tag)
        lon = re.search(r'data-marker-lng="(-?[\d.]+)"', tag)
        title = re.search(r'data-marker-title="([^"]*)"', tag)
        if lat and lon:
            found.append((float(lat.group(1)), float(lon.group(1)), _plain(title.group(1) if title else "")))
    if not found:
        return None
    for lat, lon, title in found:
        if name and title == _plain(name):
            return lat, lon
    return found[0][:2]


def address_text(raw):
    """The one-line address of an address block's HTML, from its house number to the state and ZIP ("Amped Airsoft
    Arena<br>2250 Noblestown Rd.<br>Pittsburgh, Pennsylvania 15205" -> "2250 Noblestown Rd., Pittsburgh,
    Pennsylvania 15205"): the business's name before it, e-mail addresses and anything after the ZIP (a telephone)
    are left out. "" when the block holds no such address."""
    text = " ".join(html.unescape(_TAGS.sub(" ", _BR.sub(", ", raw or ""))).split())
    parts = [p.strip() for p in text.split(",") if p.strip() and "@" not in p]
    first = next((i for i, p in enumerate(parts) if re.match(r"\d", p)), None)
    if first is None:
        return ""
    m = _TO_ZIP.match(", ".join(parts[first:]))
    return m.group(1) if m else ""


def detail_address(page):
    """(street, city, state code, ZIP, where the block starts) of the listing's address block, or None: the
    detail block (class "detail__address" or "detail__info-block": "501 S Pacific HWY 99W<br>Rickreall, Oregon
    97371"), else the list under the page's "Contact Information" heading (Minneapolis)."""
    page = page or ""
    for rx in _DETAIL_BLOCKS:
        for m in rx.finditer(page):
            window = page[m.end():m.end() + WINDOW]
            cut = _BLOCK_END.search(window)
            text = address_text(window[:cut.start()] if cut else window)
            if text:
                return split_address(text) + (m.start(),)
    for m in _CONTACT.finditer(page):
        text = address_text(m.group(1))
        if text:
            return split_address(text) + (m.start(),)
    return None


def detail_phone(page, start, skip=""):
    """The first telephone link after position start (the detail block) and before the page footer, not the
    board's own number (skip); "" when there is none."""
    end = page.find("<footer", start)
    own = re.sub(r"\D", "", str(skip or ""))[-10:]
    for m in _TEL.finditer(page, start, end if end > 0 else len(page)):
        number = html.unescape(m.group(1)).strip()
        digits = re.sub(r"\D", "", number)
        if len(digits) >= 10 and (not own or digits[-10:] != own):
            return number
    return ""


def _board_phone(page):
    """The telephone of the board's own "#identity" JSON-LD entry ("" when none)."""
    for value in jsonld.blocks(page):
        for thing in jsonld.things(value):
            if "identity" in str(thing.get("@id") or ""):
                return str(thing.get("telephone") or "")
    return ""


def accessibility(page):
    """The accessibility items of a listing's amenity list ("Wheelchair Accessible", "ADA Restrooms")."""
    m = _AMENITIES.search(page or "")
    if not m:
        return []
    items = [" ".join(html.unescape(_TAGS.sub(" ", li)).split()) for li in _LI.findall(m.group(1))]
    return [i for i in items if i and ACCESS_LABEL.search(i)]


def listing(page, site, url):
    """One listing page as a row (simpleview.FIELDS), or None (see the module docstring)."""
    thing = _business(page, url)
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
        # Some boards (Colorado Springs) write "street", "city", "region" instead of the schema.org names.
        street = str(address.get("streetAddress") or address.get("street") or "")
        city = str(address.get("addressLocality") or address.get("city") or "")
        state = str(address.get("addressRegion") or address.get("region") or "")
        postcode = str(address.get("postalCode") or address.get("zip") or "")
        if not city and _ZIP.search(street):               # the whole address in streetAddress (Providence)
            street, city, state, postcode = split_address(street)
    else:
        street, city, state, postcode = split_address(address) if address else ("", "", "", "")
    if sum(ch.isdigit() for ch in city) >= 7:
        city = ""                       # a telephone number in the city field (seen at Colorado Springs)
    block = detail_address(page)
    if block and not street:
        street, city, state, postcode = block[:4]
    category = attrs.get("category-name", "")
    kinds = " ".join(sorted(jsonld.types_of(thing)))          # "LodgingBusiness": tags when there is no category
    if not ref or home_business(name, street, category):
        return None
    lat, lon = thing.get("latitude"), thing.get("longitude")
    if lat in (None, "") or lon in (None, ""):
        at = jsonld.position(thing) or marker(page, name)
        if not at:                      # the listing's "maps?q=<lat>,<lon>" directions link (Syracuse)
            q = _MAPS_Q.search(page)
            at = (float(q.group(1)), float(q.group(2))) if q else None
        lat, lon = at if at else (None, None)
    phone = str(thing.get("telephone") or "")
    if not phone and block:
        phone = detail_phone(page, block[4], _board_phone(page))
    website = str(thing.get("url") or "").strip()
    if _host(website) == _host(url):
        website = ""                # the board's own listing page, not the business's website
    if not website:
        link = _WEBSITE.search(page)
        website = html.unescape(link.group(1)).strip() if link else ""
    if len(state) > 2:
        state = STATE_CODES.get(state.strip().lower(), state)
    row = make_row(site, ref, name, tags_of(category, kinds), lat, lon, phone=phone,
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
