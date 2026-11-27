"""Tourism boards' visitor listings on the Simpleview platform (the source "simpleview-listings"; the monthly
simpleview-listings workflow).

What: state tourism offices and city tourism boards (destination marketing organisations) that run Simpleview list
the restaurants, shops, attractions, hotels and venues of their area. Research of 26 November 2026 (notes/
US-LOCAL-BUSINESS-DIRECTORIES.md) found 11 state sites on Simpleview that answered without a challenge (DE, FL, IN,
KS, NM, NY, PA, RI, TX, VA, WY) and tested Visit Denver; SITES lists them. The 20 state sites that answered with an
anti-bot challenge (Cloudflare, Incapsula) are not collected (BLOCKED), and never tried another way.

How, per site (collect()):
  1. robots.txt (obeyed: every listing page is checked; its Crawl-delay is kept, at least 2 and at most 5 seconds
     between requests, PAUSE when it names none);
  2. the sitemap (robots.txt's Sitemap line, else /sitemap.xml; a sitemap index is followed into the sitemaps whose
     address names listings, or all of them): every "/listing/<name>/<number>/" page;
  3. each listing page: its schema.org JSON-LD (the LocalBusiness object: name, telephone, PostalAddress, geo) and
     the page's embedded listing data ("var data = {...}": recid, title, latitude, longitude, address1, phone,
     weburl, primaryCategory, and the amenity groups, of which only the hours and the accessibility fields are
     read). Never kept: the e-mail, the description, photos, social links, reviews, the booking links, the
     account's own fields.
A listing is left out when it has no street address (a tour operator or a home business: common.home_business), a
name that is a person's, or no position in the US. Its category gives its OpenStreetMap-style tags (common.tags_of)
and so its class and fine type in the packs; hours that read as OpenStreetMap syntax become its opening hours,
other hours text and the accessibility fields its note ("Hours: ...; Accessibility: ADA Accessible Rooms 5").

In the packs (businesses part): a new place, unless another business source already lists it, matched by the same
phone number within 500 m first, then the same name within 75 m (dedupe_phone, dedupe_m 75, dedupe_carry): then
the listing's phone, website, hours and note go to that place instead (PackWriter.drop_duplicates).
Only the Python standard library is used.
"""

import html
import re

from placepacks.chains import hours as oh
from placepacks.chains import jsonld
from placepacks.chains.base import FIELDS as CHAIN_FIELDS
from placepacks.chains.base import make_row
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.directories.common import Robots, home_business, no_email, tags_of

FIELDS = CHAIN_FIELDS + ["category", "note"]
USER_AGENT = "place-packs-simpleview/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
PAUSE = 3.0                     # seconds between requests when robots.txt names no Crawl-delay
MIN_PAUSE, MAX_PAUSE = 2.0, 5.0
LISTING = re.compile(r"/listing/[^/?#]+/(\d+)/?$")
_DATA = re.compile(r"var\s+data\s*=\s*")
HOURS_LABEL = re.compile(r"^(hours|hours of operation|operating hours|business hours|opening hours)$", re.I)
ACCESS_LABEL = re.compile(r"\bada\b|accessib|wheelchair|hearing loop|braille|service animal", re.I)


def _site(title, home, expected, timeout_min=300):
    """One entry of SITES: the site's name, its home address, about how many listings were seen, the job's time."""
    return {"title": title, "home": home, "expected": expected, "budget": int(expected * 1.5) + 200,
            "timeout": timeout_min}


# The sites (checked 26 November 2026: the platform seen on the homepage; listing numbers where the sitemap was read).
SITES = {
    "visitdelaware": _site("Visit Delaware", "https://www.visitdelaware.com", 800),
    "visitflorida": _site("Visit Florida", "https://www.visitflorida.com", 1725),
    "visitindiana": _site("Visit Indiana", "https://visitindiana.com", 1500),
    "travelks": _site("Travel Kansas", "https://www.travelks.com", 1500),
    "newmexico": _site("New Mexico True", "https://www.newmexico.org", 1500),
    "iloveny": _site("I LOVE NY", "https://www.iloveny.com", 2000),
    "visitpa": _site("Visit Pennsylvania", "https://www.visitpa.com", 2000),
    "visitrhodeisland": _site("Visit Rhode Island", "https://www.visitrhodeisland.com", 1000),
    "traveltexas": _site("Travel Texas", "https://www.traveltexas.com", 480),
    "virginia": _site("Virginia Is For Lovers", "https://www.virginia.org", 2000),
    "travelwyoming": _site("Travel Wyoming", "https://travelwyoming.com", 1000),
    "visitdenver": _site("Visit Denver", "https://visitdenver.com", 1833),
}
# State tourism sites that answered with an anti-bot challenge or a plain 403 (26 November 2026): not collected.
BLOCKED = {"travelalaska.com": "Cloudflare", "visitarizona.com": "Cloudflare", "colorado.com": "Cloudflare",
           "exploregeorgia.org": "Cloudflare", "gohawaii.com": "Cloudflare", "visitidaho.org": "Cloudflare",
           "explorelouisiana.com": "Cloudflare", "visitmaine.com": "Cloudflare", "visitmaryland.org": "Cloudflare",
           "visitma.com": "Cloudflare", "michigan.org": "Cloudflare", "exploreminnesota.com": "Cloudflare",
           "visitmississippi.org": "plain 403", "visitnebraska.com": "Cloudflare", "travelnevada.com": "Cloudflare",
           "visitnh.gov": "Cloudflare", "visitnj.org": "Incapsula", "ndtourism.com": "Cloudflare",
           "travelsouthdakota.com": "Cloudflare", "ohio.org": "404 to programs"}


def listing_data(page):
    """The embedded listing data of a page ("var data = {...}"), or {}."""
    m = _DATA.search(page or "")
    if not m:
        return {}
    value = jsonld.loads(page[m.end():])
    return value if isinstance(value, dict) else {}


def amenities(data):
    """(hours text, [accessibility facts]) of a listing's amenity groups. Only fields labelled as hours, and fields
    whose label or group names accessibility (ADA, accessible, wheelchair ...), are read; a "No" is left out."""
    hours, access = "", []
    for tab in data.get("amenityTree") or []:
        for group in (tab or {}).get("groups") or []:
            group_name = str(group.get("amenitygroupname") or "")
            for field in group.get("fields") or []:
                label = " ".join(str(field.get("label") or "").split())
                value = " ".join(str(((field.get("doc") or {}).get("value_string")) or "").split())
                if not label or not value or value.lower() in ("no", "false", "0"):
                    continue
                if HOURS_LABEL.match(label) and not hours:
                    hours = value
                elif ACCESS_LABEL.search(label) or ACCESS_LABEL.search(group_name):
                    access.append(label if value.lower() in ("yes", "true") else f"{label} {value}")
    return hours, access


def listing(page, site, url):
    """One listing page as a row (FIELDS), or None (see the module docstring)."""
    data = listing_data(page)
    found = {}
    for thing in jsonld.find(page, {"LocalBusiness", "Hotel", "Restaurant", "TouristAttraction", "Store",
                                    "LodgingBusiness", "FoodEstablishment", "Museum", "ProfessionalService",
                                    "ArtGallery", "EntertainmentBusiness", "SportsActivityLocation", "Place"}):
        if "#localbusiness" in str(thing.get("@id") or "") or not found:
            found = jsonld.store(thing, need_position=False) or {}
    m = LISTING.search(url)
    recid = str(data.get("recid") or (m.group(1) if m else ""))
    name = html.unescape(str(data.get("title") or found.get("name") or ""))
    street = str(data.get("address1") or found.get("street") or "")
    cat = data.get("primaryCategory") or {}
    category = " / ".join(str(cat.get(k)) for k in ("catname", "subcatname") if cat.get(k))
    if not recid or home_business(name, street, category):
        return None
    lat = data.get("latitude") if data.get("latitude") not in (None, "", 0) else found.get("lat")
    lon = data.get("longitude") if data.get("longitude") not in (None, "", 0) else found.get("lon")
    hours_text, access = amenities(data)
    hours = oh.from_text(hours_text) if hours_text else ""
    tags = tags_of(str(cat.get("subcatname") or ""), str(cat.get("catname") or ""))
    phone = data.get("phone") or found.get("phone") or ""
    website = str(data.get("weburl") or "").strip()
    row = make_row(site, recid, name, tags, lat, lon, phone=phone, website=website, opening_hours=hours,
                   street=street, city=found.get("city") or data.get("city") or "",
                   state=found.get("state") or data.get("state") or "",
                   postcode=found.get("postcode") or data.get("zip") or "")
    if row is None:
        return None
    if not row["type"] and cat.get("subcatname"):
        row["type"] = " ".join(str(cat["subcatname"]).lower().split())
    note = []
    if hours_text and not hours:
        note.append(f"Hours: {hours_text[:200]}")
    if access:
        note.append("Accessibility: " + ", ".join(access)[:600])
    row["category"] = category
    row["note"] = no_email("; ".join(note))
    return row


def listing_pages(client, robots, home):
    """The listing page addresses of a site's sitemap(s), each once, in sitemap order."""
    from placepacks.chains.base import sitemap
    maps = robots.sitemaps() or [home.rstrip("/") + "/sitemap.xml"]
    found, seen, todo, read = [], set(), list(maps), set()
    while todo and len(read) < 30:
        url = todo.pop(0)
        if url in read:
            continue
        read.add(url)
        try:
            locs = sitemap(client, url)
        except NotFound:
            continue
        children = [u for u in locs if re.search(r"\.xml(\.gz)?(\?|$)", u)]
        if children and len(children) == len(locs):            # a sitemap index
            named = [u for u in children if "listing" in u.lower()]
            todo += named or children
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
