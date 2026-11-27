"""Airport terminal directories: the shops, restaurants, gates, restrooms, family restrooms, service-animal relief
areas, information desks, accessibility services (wheelchair assistance, TSA Cares, the Sunflower programme,
sensory rooms) and ground transport pick-up areas of US airports with scheduled passenger service (the owner's
decision of 27 November 2026, notes/helper-rules.txt: queue item Q3; source "airport-directories" in the extra part
and "airport-directories-businesses" in the businesses part).

The airports: OurAirports' US airports with scheduled service (about 700; placepacks/indoor/seeds.py airports),
large airports first, each with its place key "faa-airports:<FAA id>" and its website (Wikidata's, else
OurAirports'). The units airports-1 .. airports-N share them (every N-th airport).

For each airport (read_airport), politely (robots.txt read first and obeyed; an identified User-Agent; at least
PAUSE seconds between requests to one host; a refusal, a 403 or an anti-bot page stops that airport at once and it
is recorded as "blocked", never got round; no login, no CAPTCHA, no headless browser, no other address):
  1. its homepage, fingerprinted for map vendors (placepacks/mapvendors/registry.py; unknown map embeds are kept
     for notes/new-map-vendors.txt);
  2. its Atrius map, when the homepage links to one (an Atrius page found by its script or title, then the map's
     config.json and Atrius' public venue files: placepacks/mapvendors/atrius.py): every gate, shop, restaurant,
     restroom, relief area, desk and elevator with its terminal, level and own position. This is the best source;
  3. up to MAX_PAGES of its own pages whose links speak of shops and dining, accessibility, amenities and services,
     maps and terminals, ground transport: schema.org data on them (Restaurant, Store, FoodEstablishment ...: name,
     hours, phone; placepacks/chains/jsonld.py), shop and restaurant cards (a heading followed by text that says
     where: terminal, concourse, gate, pre- or post-security), and the amenities they say there are
     (common.amenities_of: wheelchair assistance, TSA Cares, relief areas, family restrooms, information desks,
     sensory rooms ...), each with the sentence that says where.
Features without a position of their own (cards, amenities) take the airport's. Mappedin, MapsIndoors, Pointr and
Jibestream maps need a customer key and are not read (recorded as found).
Only the Python standard library is used.
"""

import re
import urllib.parse

from placepacks.chains import jsonld
from placepacks.chains.polite import Blocked, BudgetSpent, NotFound, RequestFailed
from placepacks.indoor import common
from placepacks.mapvendors import atrius, registry

SHARDS = 6
MAX_PAGES = 6                   # an airport's own pages read after its homepage, at most
LINK_WORDS = [
    (re.compile(r"shop|dine|dining|eat|restaurant|food|concession", re.I), 3),
    (re.compile(r"accessib|disabilit|\bada\b|wheel ?chair|special assistance|hidden disab|sunflower", re.I), 3),
    (re.compile(r"amenit|services|restroom|relief|nursing|lactation|information desk", re.I), 2),
    (re.compile(r"\bmaps?\b|terminal|concourse|gates?\b|wayfind", re.I), 2),
    (re.compile(r"ground transport|taxi|rideshare|ride share|shuttle|transit|pick[- ]?up", re.I), 1),
]
# Words of a card's text that say where in an airport something is.
# Headings of a page's furniture, never a shop's name.
NOT_CARDS = re.compile(r"(?i)\b(filter|results?|search|sort|categor(y|ies)|menu|sign ?up|newsletter|contact|related|"
                       r"share|follow|subscribe|quick links|download|alerts?|cookies?|privacy|hours|locations?|"
                       r"directions|faqs?|more information|learn more|close)\b")
WHERE = re.compile(r"\b(terminal|concourse|gate|gates|pier|pre[- ]security|post[- ]security|before security|"
                   r"after security|airside|landside|baggage claim|ticketing|level|mezzanine|food court)\b", re.I)
SHOP_TYPES = {"Store", "ClothingStore", "BookStore", "ElectronicsStore", "GiftShop", "JewelryStore", "ShoeStore",
              "ConvenienceStore", "HealthAndBeautyBusiness", "Pharmacy", "ShoppingCenter"}
DINE_TYPES = {"Restaurant", "FoodEstablishment", "CafeOrCoffeeShop", "BarOrPub", "FastFoodRestaurant", "Bakery",
              "IceCreamShop", "Winery", "Brewery"}


def page_kind(url, text=""):
    """What an airport page lists: "dining", "store" (shops and dining pages count as "store" unless they speak
    only of food), or "" for other pages."""
    words = f"{urllib.parse.urlsplit(url).path} {text[:200]}".lower()
    if re.search(r"dine|dining|eat|restaurant|food", words) and not re.search(r"shop", words):
        return "dining"
    if re.search(r"shop|retail|store", words):
        return "store"
    return ""


def gate_of(text):
    """The terminal, concourse and gate words of a card's text ("Terminal B, near Gate B12, after security"), or
    ""; at most 120 characters."""
    found = []
    for m in re.finditer(r"\b(terminal|concourse|pier)\s+([A-Z0-9]{1,3})\b|\bgates?\s+([A-Z]?\d{1,3}[A-Z]?"
                         r"(?:\s*(?:-|–|to|and|&)\s*[A-Z]?\d{1,3}[A-Z]?)?)|\b(pre[- ]security|post[- ]security|"
                         r"before security|after security|airside|landside)\b", text or "", re.I):
        found.append(" ".join(m.group(0).split()))
    out = []
    for f in found:
        if f.lower() not in (o.lower() for o in out):
            out.append(f)
    return ", ".join(out)[:120]


def cards(page, url, kind, site, site_name, lat, lon):
    """The shops or restaurants of a listing page (kind "store" or "dining") as features: each heading whose text
    after it says where (WHERE) is a card; its name is the heading, its note the where words (gate_of), its hours
    the first hours the text gives. Headings that are section titles ("Terminal B", "Shops") are not cards."""
    from placepacks.chains import hours as oh
    rows = []
    for title, text in common.heading_sections(page, "h2|h3|h4|h5"):
        section = re.fullmatch(r"(?i)(terminal|concourse|gates?|level)\s+\S+|shops?|dining|restaurants?|eat|food|"
                               r"amenities|services|pre[- ]security|post[- ]security", title.strip())
        if len(title) > 60 or NOT_CARDS.search(title) or not WHERE.search(text[:300]) or section:
            continue
        where = gate_of(text[:300])
        m = re.search(r"((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun|Daily)[^.]{0,80}?\d{1,2}(?::\d\d)?\s*[ap]\.?m\.?\s*(?:-|–|to)"
                      r"\s*\d{1,2}(?::\d\d)?\s*[ap]\.?m\.?)", text, re.I)
        hours = oh.from_text(m.group(1).replace("Daily", "Mo-Su")) if m else ""
        row = common.feature_row(site, f"{site}:card:{common.slug(title)}:{common.slug(where)}", kind, title, lat,
                                 lon, site_name=site_name, notes=common.where_note(site_name, extra=where),
                                 opening_hours=hours, vendor="airport-website")
        if row:
            rows.append(row)
    return rows


def structured(page, url, site, site_name, lat, lon):
    """The shops and restaurants an airport page describes in schema.org data (JSON-LD), as features."""
    rows = []
    for thing in jsonld.find(page, SHOP_TYPES | DINE_TYPES):
        types = set(jsonld.types_of(thing))
        if "ShoppingCenter" in types:
            continue
        got = jsonld.store(thing, need_position=False) or {}
        name = got.get("name") or ""
        kind = "dining" if types & DINE_TYPES else "store"
        where = gate_of(" ".join(str(thing.get(k) or "") for k in ("description", "address", "location"))[:400])
        row = common.feature_row(site, f"{site}:ld:{common.slug(name)}", kind, name, got.get("lat") or lat,
                                 got.get("lon") or lon, site_name=site_name,
                                 notes=common.where_note(site_name, extra=where), phone_number=got.get("phone", ""),
                                 website_url=got.get("website", ""), opening_hours=got.get("opening_hours", ""),
                                 vendor="airport-website")
        if row:
            rows.append(row)
    return rows


def _label(url):
    """The name part of a website's host ("https://maps.skyharbor.aero/x" -> "skyharbor"), for an airport whose map
    is on a sister domain."""
    host = (urllib.parse.urlsplit(url).hostname or "").split(".")
    return host[-2] if len(host) >= 2 else ""


def atrius_link(page, base):
    """The address of the airport's own map page on a "map..." host of its site (or of a sister domain with the
    same name: maps.skyharbor.aero for skyharbor.com) linked from a page, or "": Atrius maps live there
    ("maps.<site>/?vid=<venue>"); the venue parameter is kept, other parameters dropped."""
    from placepacks.mapvendors.discover import same_site
    for href in re.findall(r"href\s*=\s*[\"']([^\"']+)[\"']", page or "", re.I):
        url = urllib.parse.urljoin(base, href.replace("&amp;", "&"))
        parts = urllib.parse.urlsplit(url)
        if not (parts.hostname or "").startswith("map") or not (same_site(url, base) or _label(url) == _label(base)):
            continue
        vid = urllib.parse.parse_qs(parts.query).get("vid", [""])[0]
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path or "/", f"vid={vid}" if vid else "",
                                        ""))
    return ""


def read_airport(client, airport, stats, found_vendors=None):
    """The rows of one airport (see the module docstring). Returns (rows, status): status "ok", "blocked",
    "robots", "failed", "nothing" or "no-website". BudgetSpent is raised (the unit stops)."""
    from placepacks.directories.common import Robots
    found_vendors = found_vendors if found_vendors is not None else []
    home = airport.get("homepage") or ""
    if not home:
        return [], "no-website"
    if not re.match(r"https?://", home):
        home = "https://" + home
    site = f"airport:{airport['faa']}"
    name, lat, lon = airport["org"], airport["lat"], airport["lon"]
    rows, texts = [], []
    parts = urllib.parse.urlsplit(home)
    try:
        robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent="place-packs-indoor-directories")
        if not robots.allowed(home):
            return [], "robots"
        page = client.fetch(home)
        for f in registry.fingerprints(page, home):
            found_vendors.append({**f, "org": name, "page": home})
        map_url = atrius_link(page, home)
        if map_url:
            try:
                rows += list(atrius.from_map_page(client, map_url, site, name, airport["place_key"], stats))
            except (NotFound, RequestFailed) as e:
                stats["atrius_failed"] = stats.get("atrius_failed", 0) + 1
                print(f"{name}: Atrius map {map_url}: {e}", flush=True)
        have_map = any(r["kind"] in ("store", "dining", "gate") for r in rows)
        pages = []
        for url, _ in common.own_links(page, home, LINK_WORDS, MAX_PAGES):
            if url.rstrip("/") == home.rstrip("/") or not robots.allowed(url):
                continue
            try:
                pages.append((url, client.fetch(url)))
            except NotFound:
                continue
    except Blocked:
        return [], "blocked"
    except (NotFound, RequestFailed):
        return [], "failed"
    for url, text in pages:
        for f in registry.fingerprints(text, url):
            found_vendors.append({**f, "org": name, "page": url})
        texts.append(common.plain(text))
        if have_map:
            continue                    # the Atrius map already gives the shops with their own positions
        kind = page_kind(url)
        if kind:
            rows += structured(text, url, site, name, lat, lon) or cards(text, url, kind, site, name, lat, lon)
    rows += common.amenity_rows(site, name, lat, lon, common.amenities_of(texts), f"{site}:amenity")
    if not rows:
        return [], "nothing"
    if not any(r["kind"] == "site" for r in rows):
        site_row = common.site_row(site, name, lat, lon, place_key=airport["place_key"], website_url=home,
                                   vendor="airport-website")
        if site_row:
            rows.insert(0, site_row)
    seen, out = set(), []
    for r in rows:
        if r["key"] not in seen:
            seen.add(r["key"])
            out.append(r)
    return out, "ok"


def collect(client, unit, stats, airports=None):
    """The airports of one unit ("airports-2": every SHARDS-th airport from the second). The rows of every
    airport read; each airport's status is counted in stats, and the blocked ones are listed by name."""
    from placepacks.indoor import seeds
    index = int(unit.rsplit("-", 1)[1]) - 1
    if airports is None:
        airports = seeds.read_file("AIRPORT_SEEDS")
    every = seeds.airports(client) if airports is None else airports
    mine = [a for i, a in enumerate(every) if i % SHARDS == index]
    stats.update(airports=len(mine), ok=0, blocked=0, robots=0, failed=0, nothing=0, **{"no-website": 0})
    stats["may_be_empty"] = True
    stats["blocked_sites"] = []
    vendors = []
    for a in mine:
        try:
            rows, status = read_airport(client, a, stats, vendors)
        except BudgetSpent:
            raise
        stats[status] = stats.get(status, 0) + 1
        if status == "blocked":
            stats["blocked_sites"].append(f"{a['faa']} {a.get('homepage', '')}")
        yield from rows
    stats["vendors"] = sorted({f"{v['vendor']} ({v['org']})" for v in vendors})[:200]
