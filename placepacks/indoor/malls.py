"""Mall directories: the stores of US shopping malls and outlet centres (name, category, level, unit, hours, phone,
website) and their amenities (guest services, wheelchair and scooter loans, family and accessible restrooms,
accessible parking and entrances, nursing rooms, security office), from the malls' own websites (the owner's
decision of 27 November 2026, notes/helper-rules.txt: queue item Q3; source "mall-directories" in the extra part,
"mall-directories-businesses" in the businesses part).

One unit per operator (OPERATORS), each reading its malls' directories the way its websites publish them (all
checked 27 November 2026 with one or two requests per site):
  tanger      Tanger outlet centres: tanger.com/<centre>/stores is a Next.js page whose __NEXT_DATA__ holds the
              centre (name, phone, weekly hours) and its store cards (name, categories, suite, own hours); the
              centres are the /<centre>/stores pages of tanger.com's sitemap; /<centre>/visitor-info gives amenities
  macerich    Macerich malls: macerich.com's sitemap lists /leasing/<mall> pages, each linking the mall's own site;
              its /Directory page lists every store (name, level, phone, category words) and the mall's regular
              hours, /Services its amenities under headings
  brookfield  Brookfield Properties' malls: brookfieldproperties.com's property sitemap; each retail property page
              links the mall's own site, whose /en/directory/ page carries the store list as JSON
              (Fusion.contentCache "brookfield-store": name, phone, website, categories, level, "near" anchor
              store, own hours) and the mall's weekly hours ("brookfield-mall-info"); /en/visit/ its FAQ
  westfield   Westfield (URW) US centres: the US sitemap index names the centres; /retailers and /restaurants are
              streamed Next.js pages holding the centre (name, position, phone) and each store (name, categories,
              level, own trading hours when they differ from the centre's); /services the service cards
              (wheelchairs, ADA services, family lounge, security office ...), with the accessibility ones' own
              page read for its description
  cbl         CBL Properties' malls: cblproperties.com/portfolio, each property page linking the mall's own site;
              its /directory page names every store, the mall's phone and the coming week's hours
  simon, preit, washington-prime, federal-realty, kimco
              not read: Simon answers 403 to programs and its robots.txt forbids automated collection; PREIT's
              property pages answer 403; Washington Prime's site cannot be reached securely (its TLS certificate
              does not verify); Federal Realty's and Kimco's centre lists are script-only applications with no
              directory in their pages. Each month one request checks whether that is still so; the unit is
              recorded as "blocked" (or "failed" with a note when the site now answers, so a collector can be
              written). Their centres that have their own websites are read by the independent units.
  independent-1 .. -N
              every other mall with a website from Wikidata and OpenStreetMap (placepacks/indoor/seeds.py): its
              homepage and up to MAX_PAGES of its own directory, visitor and amenity pages: schema.org data (the
              mall's hours and phone, Store and Restaurant items), the store links of a directory page, and the
              amenities the pages name; map vendors are fingerprinted (placepacks/mapvendors/registry.py: Mappedin
              and the others needing a customer key are recorded, not read).
Positions: Westfield gives the centre's; every other mall takes the position (and the place key) of the Wikidata
or OpenStreetMap mall with the same website host, else the same name (seeds.match_mall); a mall matching neither
is counted as "no position" and left out. Stores and amenities take the mall's position (no directory here gives
store positions); their level, unit and "near" say where.
Politeness: robots.txt of every host read first and obeyed; an identified User-Agent; PAUSE seconds between
requests to one host; a refusal (401, 403, 429, an anti-bot page) stops that operator's unit at once ("blocked"),
or, in the independent units, that mall; no login, no CAPTCHA, no headless browser, no other address.
Only the Python standard library is used.
"""

import re
import urllib.parse

from placepacks.chains import jsonld
from placepacks.chains.polite import Blocked, BudgetSpent, NotFound, RequestFailed
from placepacks.directories.tempest import STATE_CODES
from placepacks.indoor import common, seeds
from placepacks.mapvendors import registry

INDEPENDENT_SHARDS = 3
MAX_PAGES = 4
AGENT = "place-packs-indoor-directories"
# Operators whose malls are read by their own unit: an independent mall on one of these hosts, or whose homepage
# carries one of these marks, is left to that unit.
OPERATOR_HOSTS = ("simon.com", "westfield.com", "tanger.com", "brookfieldproperties.com", "macerich.com",
                  "cblproperties.com", "preit.com", "wpgus.com")
OPERATOR_MARKS = re.compile(r"macerichepicenter\.com|Fusion\.contentCache|brookfield-mall-info|cblproperties\.com|"
                            r"tanger\.com/|westfield\.com/en/united-states", re.I)
LINK_WORDS = [
    (re.compile(r"director(y|ies)|stores?\b|shops?\b|shopping|tenants?|retailers?", re.I), 3),
    (re.compile(r"dining|restaurants?|food", re.I), 2),
    (re.compile(r"visit|amenit|services|guest|accessib|hours|info", re.I), 2),
]
FOOD = re.compile(r"\b(food|foods|dining|restaurants?|eats?|eatery|drinks?|cafe|caf\xe9|coffee|tea|treats|snacks?|"
                  r"bars?|grill|pizza|bakery|dessert|ice cream|food court)\b", re.I)


def kind_of_store(*categories):
    """"dining" when a store's categories speak of food and drink, else "store"."""
    return "dining" if any(FOOD.search(str(c or "")) for c in categories) else "store"


# What a mall's services or amenity title is (Westfield's service cards, a services page's headings).
SERVICE_KINDS = [
    (r"wheel ?chair|scooter|mobility|\bada\b|accessib|sunflower|sensory|hearing", "accessibility service"),
    (r"family (lounge|restroom|bathroom)|companion", "family restroom"),
    (r"nursing|lactation|mamava|mothers? room", "restroom"),
    (r"(pet|animal|dog)s?.{0,10}relief", "pet relief area"),
    (r"accessible parking|handicap\w* parking|disabled parking", "accessible parking"),
    (r"guest services|concierge|customer service|security (office|desk)|lost (and|&) found|management office",
     "service desk"),
    (r"information|directory kiosk", "information desk"),
    (r"taxi|rideshare|ride share|shuttle|bus stop|transit", "ground transport"),
    (r"restroom|toilet|bathroom", "restroom"),
    (r"elevator", "elevator"),
]
_SERVICE = [(re.compile(p, re.I), k) for p, k in SERVICE_KINDS]


def service_kind(title):
    """The kind of a mall service's title ("Wheelchairs" -> "accessibility service"), or "" (ATMs, Wi-Fi ...)."""
    return next((k for rx, k in _SERVICE if rx.search(str(title or ""))), "")


class Mall:
    """One mall being read: its site key, name, position, place key, website and the rows found."""

    def __init__(self, key, name, lat, lon, place_key="", homepage="", operator=""):
        """See the class docstring."""
        self.key, self.name, self.lat, self.lon = key, name, lat, lon
        self.place_key, self.homepage, self.operator = place_key, homepage, operator
        self.phone, self.hours, self.rows, self.texts = "", "", [], []

    def store(self, ident, name, category="", level="", unit="", near="", phone="", website="", hours="",
              kind=None):
        """Add one store or restaurant (common.feature_row; its note says where in the mall it is)."""
        row = common.feature_row(self.key, f"{self.key}:store:{common.slug(ident) or common.slug(name)}",
                                 kind or kind_of_store(category), name, self.lat, self.lon, site_name=self.name,
                                 level=level, notes=common.where_note(self.name, level, unit, near),
                                 phone_number=phone, website_url=website, opening_hours=hours, category=category,
                                 unit=unit, vendor=self.operator)
        if row:
            self.rows.append(row)

    def service(self, title, kind, notes="", level=""):
        """Add one amenity or service of the mall (a desk, wheelchairs, a family restroom ...)."""
        row = common.feature_row(self.key, f"{self.key}:service:{common.slug(title)}", kind, title, self.lat,
                                 self.lon, site_name=self.name, level=level, notes=notes, vendor=self.operator,
                                 business=False)
        if row:
            self.rows.append(row)

    def finish(self):
        """The mall's rows: its site row (phone, hours, a note), its stores and services, then the amenities its
        pages' texts name that no service row has given yet."""
        have = {r["kind"] for r in self.rows}
        extra = [r for r in common.amenity_rows(self.key, self.name, self.lat, self.lon,
                                                common.amenities_of(self.texts), f"{self.key}:amenity")
                 if not (r["kind"] in have and r["kind"] != "restroom")]
        site = common.site_row(self.key, self.name, self.lat, self.lon, place_key=self.place_key,
                               website_url=self.homepage, phone_number=self.phone, opening_hours=self.hours,
                               notes="Store directory from the mall's own website", vendor=self.operator)
        if site is None:
            return []
        seen, out = set(), [site]
        for r in self.rows + extra:
            if r["key"] not in seen:
                seen.add(r["key"])
                out.append(r)
        return out


def _robots(client, url):
    """The robots.txt of url's host (placepacks/directories/common.py Robots)."""
    from placepacks.directories.common import Robots
    parts = urllib.parse.urlsplit(url)
    return Robots(client, f"{parts.scheme}://{parts.netloc}", agent=AGENT)


def _get(client, robots, url):
    """A page robots.txt allows, or "" (disallowed or gone)."""
    if not robots.allowed(url):
        return ""
    try:
        return client.fetch(url)
    except NotFound:
        return ""


def _locs(text):
    """The <loc> addresses of a sitemap."""
    return re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", text or "")


def _place(name, homepage, mall_seeds, state=""):
    """(lat, lon, place_key) of an operator's mall from the seeds (seeds.match_mall), or None."""
    s = seeds.match_mall(name, homepage, mall_seeds, state)
    return (s["lat"], s["lon"], s.get("place_key", "")) if s else None


def _mall_site(page, own):
    """The mall's own website linked from an operator's property page: the first https://www.<x>.<com|net> address
    that is not the operator's, a social site or a service, or ""."""
    for url in re.findall(r"https?://(?:www\.)?[a-z0-9-]+\.(?:com|net|org)/?(?=[\"'<\s])", page or ""):
        host = seeds.host_root(url)
        if host and own not in host and not re.search(
                r"google|facebook|instagram|twitter|linkedin|youtube|vimeo|tiktok|pinterest|onetrust|mpulse|"
                r"flipsnack|ggp\.com|box\.com|quikspace|contentstack|imgix|cloudfront|apple|gmpg|mapbox|w3|"
                r"schema|jquery|community\.com|vipholidayphotos|stackoverflow|macerichepicenter", host):
            return url.rstrip("/")
    return ""


# ------------------------------------------------------------------------------------------------ Tanger

TANGER = "https://www.tanger.com"


def tanger_centres(client):
    """The Tanger centre slugs of tanger.com's sitemap (the /<slug>/stores pages)."""
    robots = _robots(client, TANGER)
    index = _get(client, robots, f"{TANGER}/sitemap.xml")
    slugs = []
    for sub in [u for u in _locs(index) if u.endswith(".xml")][:4]:
        for url in _locs(_get(client, robots, sub)):
            m = re.match(rf"{re.escape(TANGER)}/([a-z0-9-]+)/stores/?$", url)
            if m and m.group(1) not in slugs:
                slugs.append(m.group(1))
    return robots, slugs


def tanger_mall(client, robots, slug, mall_seeds, stats):
    """The rows of one Tanger centre, or [] (not in the US, no position)."""
    page = _get(client, robots, f"{TANGER}/{slug}/stores")
    data = common.next_data(page)
    centre = ((data.get("props") or {}).get("pageProps") or {}).get("center") or {}
    if not centre:
        return []
    address = (centre.get("fullAddressCS") or [{}])[0]
    if address.get("country") and address["country"] != "United States":
        return []
    # "Tanger Outlets Riverhead", as Wikidata and OpenStreetMap name the centres (the first GitHub run named them
    # "Tanger Riverhead", which matched no seed: 33 of 36 centres had no position); the state (the address's
    # "county" field holds the state's name) keeps a same-named centre in another state out.
    own = str(centre.get("name") or slug).strip()
    name = own if own.lower().startswith("tanger") else f"Tanger Outlets {own}"
    state = str(address.get("county") or address.get("state") or "").strip()
    state = state.upper() if len(state) == 2 else STATE_CODES.get(state.lower(), "")
    where = _place(name, f"{TANGER}/{slug}", mall_seeds, state)
    if not where:
        stats["no_position"] = stats.get("no_position", 0) + 1
        return []
    mall = Mall(f"mall:tanger:{slug}", name, where[0], where[1], where[2], f"{TANGER}/{slug}", "tanger")
    mall.phone = centre.get("centerPhoneNumber") or centre.get("contactTelephoneNumber") or ""
    mall.hours = common.hours_of_days([{**h, "day": ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")[int(h["day_index"])
                                                                                                 % 7]}
                                       for h in centre.get("hours") or [] if "day_index" in h])
    for card in centre.get("storeCards") or []:
        cats = ", ".join(card.get("categories") or [])
        mall.store(str(card.get("cardId") or card.get("heading")), card.get("heading"), category=cats,
                   unit=card.get("storeSuite") or "", hours=common.hours_of_text_days(card.get("storeHours")))
    info = _get(client, robots, f"{TANGER}/{slug}/visitor-info")
    mall.texts.append(common.plain(info))
    return mall.finish()


def collect_tanger(client, stats, mall_seeds):
    """Every Tanger centre."""
    robots, slugs = tanger_centres(client)
    stats["malls"] = len(slugs)
    for slug in slugs:
        yield from tanger_mall(client, robots, slug, mall_seeds, stats)


# ------------------------------------------------------------------------------------------------ Macerich

MACERICH = "https://www.macerich.com"
_RESULT = re.compile(r'<div class="result-item"[^>]*data-filter="([^"]*)"[^>]*data-filter-sub="([^"]*)"(.*?)'
                     r'(?=<div class="result-item"|$)', re.S)


def macerich_directory(page):
    """The stores of a Macerich mall's /Directory page: [{"id", "name", "level", "phone", "category"}]."""
    out = []
    for m in _RESULT.finditer(page or ""):
        block = m.group(3)
        name = re.search(r'class="result-description[^"]*"[^>]*>(.*?)</h\d>', block, re.S)
        ident = re.search(r'/Directory/Details/(\d+)', block)
        details = re.search(r'class="search-result-details"[^>]*>(.*?)</span>\s*(?:</span>)?', block, re.S)
        text = common.plain(details.group(1)) if details else ""
        level = re.search(r"((?:Level|Floor)\s*\w+|Lower Level|Upper Level|Ground Level)", text, re.I)
        tel = re.search(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
        if name:
            out.append({"id": ident.group(1) if ident else "", "name": common.plain(name.group(1)),
                        "level": level.group(1) if level else "", "phone": tel.group(0) if tel else "",
                        "category": m.group(1).replace("-", " ")})
    return out


def regular_hours(text):
    """OSM hours from a page's "REGULAR HOURS Monday: 10 AM - 8 PM Tuesday: ..." text, or ""."""
    from placepacks.chains import hours as oh
    m = re.search(r"REGULAR HOURS(.*?)(?:See All Hours|$)", text or "", re.I | re.S)
    block = m.group(1) if m else ""
    pairs = re.findall(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*:\s*(\d{1,2}(?::\d\d)?\s*[AP]M)\s*-\s*(\d{1,2}(?::\d\d)?"
                       r"\s*[AP]M)", block, re.I)
    days = {}
    for d, a, b in pairs:
        got = oh.span(a.replace(" ", "").lower(), b.replace(" ", "").lower())
        if got and oh.day_of(d) not in days:
            days[oh.day_of(d)] = [got]
    return oh.week(days)


def macerich_malls(client):
    """[(mall name, its own website)] from macerich.com's /leasing/<mall> pages."""
    robots = _robots(client, MACERICH)
    out = []
    for url in _locs(_get(client, robots, f"{MACERICH}/sitemap.xml")):
        m = re.match(rf"{re.escape(MACERICH)}/leasing/([a-z0-9-]+)$", url)
        if not m or m.group(1) in ("properties", "contact", "specialty", "brand-opportunities"):
            continue
        page = _get(client, robots, url)
        site = _mall_site(page, "macerich")
        title = re.search(r"<title>(.*?)</title>", page or "", re.S)
        name = common.plain(title.group(1)).split("|")[0].strip() if title else m.group(1).replace("-", " ").title()
        if site:
            out.append((name, site))
    return out


def macerich_mall(client, name, site, mall_seeds, stats):
    """The rows of one Macerich mall, or []."""
    where = _place(name, site, mall_seeds)
    if not where:
        stats["no_position"] = stats.get("no_position", 0) + 1
        return []
    robots = _robots(client, site)
    page = _get(client, robots, f"{site}/Directory")
    if not page:
        return []
    mall = Mall(f"mall:macerich:{seeds.host_root(site).split('.')[0]}", name, where[0], where[1], where[2], site,
                "macerich")
    text = common.plain(page)
    mall.hours = regular_hours(text)
    tel = re.search(r"Visit Us .{0,120}?(\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4})", text)
    mall.phone = tel.group(1) if tel else ""
    for s in macerich_directory(page):
        mall.store(s["id"] or s["name"], s["name"], category=s["category"], level=s["level"], phone=s["phone"])
    services = _get(client, robots, f"{site}/Services")
    for title, body in common.heading_sections(services):
        kind = service_kind(title)
        if kind:
            mall.service(title, kind, notes=body[:300])
    mall.texts.append(common.plain(services))
    return mall.finish()


def collect_macerich(client, stats, mall_seeds):
    """Every Macerich mall."""
    malls = macerich_malls(client)
    stats["malls"] = len(malls)
    for name, site in malls:
        yield from macerich_mall(client, name, site, mall_seeds, stats)


# ------------------------------------------------------------------------------------------------ Brookfield

BROOKFIELD = "https://www.brookfieldproperties.com"
RETAIL = re.compile(r"mall|center|centre|galleria|fashion|place|square|plaza|commons|market|crossing|village|"
                    r"town|shoppes|park-meadows|oakbrook|ala-moana|tysons|water-tower|natick|quarter", re.I)
NOT_RETAIL = re.compile(r"logistic|office|tower|metro-center|residen|apartment|industrial|warehouse|distribution|"
                        r"business|techspace|financial|commerce-center|airport-center|allen-center|east-end|"
                        r"first-canadian|bay-adelaide|brookfield-place", re.I)


def brookfield_malls(client):
    """[(mall name, its own website)] of Brookfield's retail property pages (each links the mall's site)."""
    robots = _robots(client, BROOKFIELD)
    out = []
    xml = _get(client, robots, f"{BROOKFIELD}/arc/outboundfeeds/sitemap-properties/?outputType=xml")
    for url in _locs(xml):
        m = re.search(r"/our-properties/([a-z0-9-]+)/?$", url)
        if not m or not RETAIL.search(m.group(1)) or NOT_RETAIL.search(m.group(1)):
            continue
        page = _get(client, robots, url)
        site = _mall_site(page, "brookfieldproperties")
        title = re.search(r"<title>(.*?)</title>", page or "", re.S)
        name = common.plain(title.group(1)).split("|")[0].strip() if title else ""
        if site and name:
            out.append((name, site))
    return out


def brookfield_mall(client, name, site, mall_seeds, stats):
    """The rows of one Brookfield mall, or []."""
    where = _place(name, site, mall_seeds)
    if not where:
        stats["no_position"] = stats.get("no_position", 0) + 1
        return []
    robots = _robots(client, site)
    page = _get(client, robots, f"{site}/en/directory/")
    cache = common.js_assigned(page, "Fusion.contentCache") or {}
    if not cache:
        return []
    info = {}
    for v in (cache.get("brookfield-mall-info") or {}).values():
        content = ((v or {}).get("data") or {}).get("content") or {}
        if isinstance(content, dict) and content.get("regMallHours") is not None:
            info = content
            break
    mall = Mall(f"mall:brookfield:{seeds.host_root(site).split('.')[0]}", info.get("name") or name, where[0],
                where[1], where[2], site, "brookfield")
    mall.hours = common.hours_of_days(info.get("regMallHours"), opens="openTime", closes="closeTime")
    for entry in (cache.get("brookfield-store") or {}).values():
        for item in entry.get("data") or []:
            s = (item or {}).get("content") or {}
            if not s.get("displayName") or (s.get("leaseStatus") and s["leaseStatus"] != "Open") or \
                    s.get("temporarilyClosed") == "Yes":
                continue
            cats = ", ".join(c.get("description", "") for c in s.get("categories") or [] if isinstance(c, dict))
            near = s.get("zoneName") if (s.get("zoneOrientation") or "near") == "near" else ""
            hours = s.get("storeHoursOverride") or s.get("storeHours") or ""
            mall.store(str(s.get("storeId") or s["displayName"]), s["displayName"], category=cats,
                       level=s.get("level") or "", near=near or "", phone=s.get("phoneNumber") or "",
                       website=s.get("tenantWebsite") or "",
                       hours=hours if isinstance(hours, str) and re.match(r"^(Mo|Tu|We|Th|Fr|Sa|Su)", hours) else "")
    visit = _get(client, robots, f"{site}/en/visit/")
    text = common.plain(visit)
    tel = re.search(r"phone number is\s*(\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})", text)
    mall.phone = tel.group(1) if tel else ""
    mall.texts.append(text)
    return mall.finish()


def collect_brookfield(client, stats, mall_seeds):
    """Every Brookfield mall."""
    malls = brookfield_malls(client)
    stats["malls"] = len(malls)
    for name, site in malls:
        yield from brookfield_mall(client, name, site, mall_seeds, stats)


# ------------------------------------------------------------------------------------------------ Westfield

WESTFIELD = "https://www.westfield.com"


def westfield_centres(client):
    """(robots, the US centre slugs) from Westfield's US sitemap index."""
    robots = _robots(client, WESTFIELD)
    index = _get(client, robots, f"{WESTFIELD}/sitemap/sitemap-us-index.xml")
    slugs = [m.group(1) for m in re.finditer(r"/sitemap-us-([a-z0-9]+)\.xml", index)]
    return robots, slugs


def westfield_trading(hours, refs):
    """OSM hours of a Westfield store's own "standard_trading" schedule (its days resolved through the page's
    numbered parts; day_of_week 0 is Sunday), or "" (none, or the centre's own schedule)."""
    std = (hours or {}).get("standard_trading") if isinstance(hours, dict) else None
    if not isinstance(std, dict) or "Centre" in str(std.get("name") or ""):
        return ""
    days = std.get("days_of_week")
    days = refs.get(days[1:]) if isinstance(days, str) and days.startswith("$") else days
    items = []
    for d in days or []:
        d = refs.get(d[1:]) if isinstance(d, str) and d.startswith("$") else d
        if isinstance(d, dict) and d.get("type") == "open":
            items.append({"day": int(d.get("day_of_week", 0)), "open": d.get("starts_at"), "close": d.get("ends_at")})
    return common.hours_of_days(items)


def westfield_mall(client, robots, slug, mall_seeds, stats):
    """The rows of one Westfield centre, or []."""
    base = f"{WESTFIELD}/en/united-states/{slug}"
    mall, cats = None, {}
    for part in ("retailers", "restaurants"):
        text = common.rsc_text(_get(client, robots, f"{base}/{part}"))
        if not text:
            continue
        refs = common.rsc_refs(text)
        if mall is None:
            centre = next(iter(common.objects_with(text, "centre_id")), {})
            if not centre.get("latitude"):
                stats["no_position"] = stats.get("no_position", 0) + 1
                return []
            seed = seeds.match_mall(centre.get("name", ""), f"{WESTFIELD}/{slug}", mall_seeds, centre.get("state", ""))
            mall = Mall(f"mall:westfield:{slug}", centre.get("name") or slug, centre["latitude"],
                        centre["longitude"], seed.get("place_key", "") if seed else "", base, "westfield")
            mall.phone = centre.get("phone_number") or ""
        cats.update({str(c.get("category_id")): c.get("name", "") for c in common.objects_with(text, "category_id")})
        for s in common.objects_with(text, "store_id"):
            if (s.get("status") or {}).get("state", "live") != "live":
                continue
            names = [cats.get(str(c), "") for c in s.get("category_ids") or []][:3]
            level = next((loc.get("level_description") for loc in s.get("locations") or []
                          if isinstance(loc, dict) and loc.get("level_description")), "") or s.get("store_level", "")
            mall.store(str(s.get("store_id")), s.get("name"), category=", ".join(n for n in names if n),
                       level=level, hours=westfield_trading(s.get("trading_hours"), refs),
                       kind="dining" if part == "restaurants" else None)
    if mall is None:
        return []
    services = common.rsc_text(_get(client, robots, f"{base}/services"))
    for card in common.objects_with(services, "title"):
        if card.get("__typename") != "ServiceCard" and "service_id" not in card:
            continue
        title = " ".join(str(card.get("title") or "").split())
        kind = service_kind(title)
        if not kind:
            continue
        text = ""
        if kind == "accessibility service" and card.get("slug"):
            detail = common.rsc_text(_get(client, robots, f"{base}/services/{card['slug']}"))
            found = next((o for o in common.objects_with(detail, "service_id") if o.get("description")), {})
            text = found.get("description") or ""
        mall.service(title, kind, notes=text, level=card.get("level_name") or "")
    return mall.finish()


def collect_westfield(client, stats, mall_seeds):
    """Every Westfield US centre."""
    robots, slugs = westfield_centres(client)
    stats["malls"] = len(slugs)
    for slug in slugs:
        yield from westfield_mall(client, robots, slug, mall_seeds, stats)


# ------------------------------------------------------------------------------------------------ CBL

CBL = "https://cblproperties.com"
_CBL_STORE = re.compile(r'\{name:"([^"]+)",globalName:"([^"]*)",href:"/store/([^"?]+)"\}')
_CBL_DAY = re.compile(r'dayString:"(\w+)",dayNum:\d,closed:(true|false),description:"[^"]*",shifts:\[(?:\{shift_title:'
                      r'"[^"]*",open:"([^"]+)",close:"([^"]+)"\})?')


def cbl_directory(page):
    """(stores [(name, slug)], phone, hours) of a CBL mall's /directory page (its Nuxt data). The hours are the
    coming week's: a day closed for a holiday is left out (OSM's "closed")."""
    stores, seen = [], set()
    for name, global_name, slug in _CBL_STORE.findall(page or ""):
        if slug not in seen and global_name != "Mall Management":
            seen.add(slug)
            stores.append((common.plain(name.encode().decode("unicode_escape", "ignore")
                                        if "\\u" in name else name), slug))
    tel = re.search(r'phone:\{general:"([^"]+)"', page or "")
    items = [{"day": d, "open": a, "close": b} for d, closed, a, b in _CBL_DAY.findall(page or "")
             if closed == "false" and a]
    return stores, tel.group(1) if tel else "", common.hours_of_days(items)


def cbl_malls(client):
    """[(mall name, its own website)] of CBL's portfolio pages."""
    robots = _robots(client, CBL)
    page = _get(client, robots, f"{CBL}/portfolio")
    out = []
    for slug in sorted(set(re.findall(r'href="/portfolio/([a-z0-9-]+)"', page or ""))):
        prop = _get(client, robots, f"{CBL}/portfolio/{slug}")
        site = _mall_site(prop, "cblproperties")
        if site:
            out.append((slug.replace("-", " ").title(), site))
    return out


def cbl_mall(client, name, site, mall_seeds, stats):
    """The rows of one CBL mall, or []."""
    where = _place(name, site, mall_seeds)
    if not where:
        stats["no_position"] = stats.get("no_position", 0) + 1
        return []
    robots = _robots(client, site)
    page = _get(client, robots, f"{site}/directory")
    stores, tel, hours = cbl_directory(page)
    if not stores:
        return []
    mall = Mall(f"mall:cbl:{seeds.host_root(site).split('.')[0]}", name, where[0], where[1], where[2], site, "cbl")
    mall.phone, mall.hours = tel, hours
    for store_name, slug in stores:
        mall.store(slug, store_name)
    return mall.finish()


def collect_cbl(client, stats, mall_seeds):
    """Every CBL mall."""
    malls = cbl_malls(client)
    stats["malls"] = len(malls)
    for name, site in malls:
        yield from cbl_mall(client, name, site, mall_seeds, stats)


# ------------------------------------------------------------------------------------------------ independent malls

_STORE_LINK = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#?]*/(?:stores?|directory|tenants?|shops?|retailers?)/"
                         r"[^\"'#?/]+/?)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def store_links(page, base):
    """The stores a directory page links to: [(name, url)] (each once; link texts of 2 to 60 characters that are
    not navigation words)."""
    out, seen = [], set()
    for href, text in _STORE_LINK.findall(page or ""):
        name = common.plain(text)
        url = registry.join(base, href)
        if not url or "${" in url or not 2 <= len(name) <= 60 or url in seen or re.fullmatch(
                r"(?i)(view|see|more|all|details?|learn more|read more|map|directions|shop now|visit|website|"
                r"view (all|store|details|more)|more info)\.?", name):
            continue
        seen.add(url)
        out.append((name, url))
    return out


def independent_mall(client, seed, stats, vendors):
    """The rows of one independent mall (see the module docstring), or [] with its status counted."""
    home = seed["homepage"] if re.match(r"https?://", seed["homepage"]) else "https://" + seed["homepage"]
    key = f"mall:{common.slug(seeds.host_root(home).replace('/', '-'))}"
    mall = Mall(key, seed["org"], seed["lat"], seed["lon"], seed.get("place_key", ""), home, "mall-website")
    try:
        robots = _robots(client, home)
        if not robots.allowed(home):
            stats["robots"] = stats.get("robots", 0) + 1
            return []
        page = client.fetch(home)
        if OPERATOR_MARKS.search(page[:300000]):
            stats["operator"] = stats.get("operator", 0) + 1
            return []
        pages = [(home, page)]
        for url, _ in common.own_links(page, home, LINK_WORDS, MAX_PAGES):
            if url.rstrip("/") != home.rstrip("/"):
                got = _get(client, robots, url)
                if got:
                    pages.append((url, got))
    except Blocked:
        stats["blocked"] = stats.get("blocked", 0) + 1
        return []
    except (NotFound, RequestFailed):
        stats["failed"] = stats.get("failed", 0) + 1
        return []
    for url, text in pages:
        for f in registry.fingerprints(text, url):
            vendors.append({**f, "org": seed["org"], "page": url})
        for u in registry.unknown_embeds(text, url, page_is_map=bool(re.search(r"map", url, re.I))):
            vendors.append({"vendor": "unknown", "host": u["host"], "url": u["url"], "org": seed["org"], "page": url})
        for thing in jsonld.find(text, {"ShoppingCenter"}):
            got = jsonld.store(thing, need_position=False) or {}
            mall.phone = mall.phone or got.get("phone", "")
            mall.hours = mall.hours or got.get("opening_hours", "")
        for thing in jsonld.find(text, {"Store", "Restaurant", "FoodEstablishment", "ClothingStore", "LocalBusiness"}):
            got = jsonld.store(thing, need_position=False) or {}
            if got.get("name") and common.store_name(got["name"]) != common.store_name(mall.name):
                mall.store(got["name"], got["name"], category=" ".join(jsonld.types_of(thing)),
                           phone=got.get("phone", ""), website=got.get("website", ""),
                           hours=got.get("opening_hours", ""))
        if re.search(r"director|stores|shops|tenants|retailers|dining", url, re.I):
            for name, link in store_links(text, url)[:400]:
                mall.store(link, name, kind="dining" if re.search(r"dining", url, re.I) else None)
        mall.texts.append(common.plain(text))
    rows = mall.finish()
    if len(rows) <= 1:
        stats["nothing"] = stats.get("nothing", 0) + 1
        return []
    stats["ok"] = stats.get("ok", 0) + 1
    return rows


def independent_seeds(client):
    """The independent malls with a website: Wikidata's and OpenStreetMap's (independent_only)."""
    return independent_only(seeds.wikidata_malls(client) + seeds.overpass_malls(client))


def independent_only(found):
    """The malls of a seed list with a website (each website host once, the first kept: Wikidata's), leaving out
    the operators' hosts."""
    out, hosts = [], set()
    for s in found:
        root = seeds.host_root(s.get("homepage") or "")
        if not root or root in hosts or any(root == h or root.startswith(h + "/") for h in OPERATOR_HOSTS):
            continue
        hosts.add(root)
        out.append(s)
    return out


def collect_independent(client, unit, stats, mall_seeds=None):
    """The independent malls of one unit ("independent-2": every INDEPENDENT_SHARDS-th from the second). A mall
    that fails unexpectedly is counted as "error" and the next is read; when the request budget or the time runs
    out, the unit ends with the malls read so far (stats["stopped"])."""
    index = int(unit.rsplit("-", 1)[1]) - 1
    if mall_seeds is None:
        saved = seeds.read_file("MALL_SEEDS")
        mall_seeds = independent_only(saved) if saved is not None else None
    every = independent_seeds(client) if mall_seeds is None else mall_seeds
    mine = [s for i, s in enumerate(every) if i % INDEPENDENT_SHARDS == index]
    stats.update(malls=len(mine), may_be_empty=True)
    vendors = []
    for s in mine:
        # One mall's broken page must not cost the others (the first GitHub run lost all three units to one bad
        # link); the run's request budget or time running out ends the unit with what was found so far.
        try:
            rows = independent_mall(client, s, stats, vendors)
        except BudgetSpent as e:
            stats["stopped"] = f"{e} after {stats.get('ok', 0)} malls with rows"
            break
        except Exception as e:  # noqa: BLE001 - counted and named in the summary; the next mall is read
            stats["error"] = stats.get("error", 0) + 1
            stats.setdefault("errors", []).append(f"{s.get('homepage', '')}: {type(e).__name__}: {str(e)[:150]}")
            del stats["errors"][20:]
            continue
        yield from rows
    stats["vendors"] = sorted({f"{v['vendor']}: {v.get('host') or v.get('map_id') or ''} ({v['org']})"
                               for v in vendors})[:200]


# ------------------------------------------------------------------------------------------------ the units

# Operators not read, with the address checked each month and why (see the module docstring).
NOT_READ = {
    "simon": ("https://www.simon.com/mall", "Simon answers 403 to programs, and its robots.txt says automated "
                                            "collection is prohibited (checked 27 November 2026)"),
    "preit": ("https://www.preit.com/properties/", "PREIT's property pages answer 403 (checked 27 November 2026)"),
    "washington-prime": ("https://www.wpgus.com/", "Washington Prime's website cannot be reached securely: its TLS "
                                                   "certificate does not verify (checked 27 November 2026)"),
    "federal-realty": ("https://properties.federalrealty.com/", "Federal Realty's centre list is a script-only "
                                                                "application: no directory in its pages"),
    "kimco": ("https://www.kimcorealty.com/properties", "Kimco's centre list is a script-only application: no "
                                                        "directory in its pages"),
}
READERS = {"tanger": collect_tanger, "macerich": collect_macerich, "brookfield": collect_brookfield,
           "westfield": collect_westfield, "cbl": collect_cbl}


def check_not_read(client, unit, stats):
    """The monthly check of an operator that is not read: raises Blocked when it still refuses (or cannot be
    reached securely), else raises RequestFailed saying the site now answers (a collector can be written)."""
    url, why = NOT_READ[unit]
    stats["why"] = why
    try:
        client.fetch(url)
    except (Blocked, NotFound) as e:
        raise Blocked(f"{why}; this month: {e}") from None
    except RequestFailed as e:
        raise Blocked(f"{why}; this month: {str(e)[:120]}") from None
    if unit in ("federal-realty", "kimco"):
        stats["may_be_empty"] = True
        return
    raise RequestFailed(f"{url} answered this month: the operator may now be readable (write a collector)")


def collect(client, unit, stats, mall_seeds=None):
    """One unit's rows (see the module docstring)."""
    if unit in NOT_READ:
        check_not_read(client, unit, stats)
        return
    if unit.startswith("independent-"):
        yield from collect_independent(client, unit, stats, mall_seeds)
        return
    if mall_seeds is None:
        mall_seeds = seeds.read_file("MALL_SEEDS")
    if mall_seeds is None:
        mall_seeds = seeds.wikidata_malls(client) + seeds.overpass_malls(client)
    yield from READERS[unit](client, stats, mall_seeds)
