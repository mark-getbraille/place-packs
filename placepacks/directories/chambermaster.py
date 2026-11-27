"""Chambers of commerce's public member directories on the OLDER ChamberMaster platform (GrowthZone's "classic"
public directory), found through the US Chamber of Commerce's directory (the source "chambermaster-listings"; the
monthly chambermaster-listings workflow, one job per state).

Research of 26 November 2026 (notes/US-LOCAL-BUSINESS-DIRECTORIES.md): classic ChamberMaster directories answer
programs and are consistent HTML with schema.org microdata; the newer GrowthZone v2 directories answer with a
Cloudflare challenge, so they are never asked for a directory page at all: their robots.txt (exactly 51 bytes,
"Disallow: /", no sitemap) tells them apart cheaply, and they are recorded as "v2" and left.

One state (collect()):
  1. the US Chamber's directory page of the state (www.uschamber.com/co/chambers/<state>, found from its chamber-
     directory sitemap): every chamber's name and website (used only for finding chambers; nothing of the page
     goes into the packs);
  2. each chamber's homepage (one request): a link to its directory host ("business.<chamber>/list",
     "members.<chamber>/list", "<x>.chambermaster.com/list"); a growthzoneapp.com link is v2 and left;
  3. the directory host's robots.txt (one request): classic only when it does not disallow /list/ and names its
     SiteMap.xml; 51 bytes or "Disallow: /" for everything: left (v2, or closed to programs);
  4. its SiteMap.xml: the public-facing "quick link" groups (PUBLIC_QL: restaurants, shopping, lodging, health
     care, automotive, personal services, arts and entertainment, sports and recreation, home and garden, pets),
     else, when a chamber has no quick links, its own categories whose names are public-facing (at most
     MAX_CATEGORIES); never the search pages (robots.txt disallows /list/search);
  5. each of those pages (5 to 10 seconds apart on the host): the member cards (data-memid): name
     (itemprop="name"), street (itemprop="streetAddress"), city, state and ZIP, phone (tel: link) and website.
Never read: representatives' names, e-mail forms, descriptions, logos, member levels. Left out: members without a
street address or with a post office box only, names that are a person's, individuals' offices (insurance and
estate agents, lawyers, accountants), the "Individuals" and "Government-education-individuals" groups, and the
chamber's own entry. Cards carry no coordinates: the pack build places each address with the offline NAD geocoder
(a home address, which the NAD marks residential, is left out: geocode "skip_homes").
A chamber's site that refuses (403, a challenge page) is recorded as blocked and left; the state's job goes on
with the next chamber. Only a refusal of the US Chamber's own page stops the state.
Only the Python standard library is used.
"""

import html
import re
import urllib.parse

from placepacks.chains.base import sitemap
from placepacks.chains.polite import Blocked, NotFound, RequestFailed
from placepacks.contact import PERSONAL_TYPES, phone_digits
from placepacks.directories.common import Robots, home_business, name_similarity, plain_name, tags_of

FIELDS = ["key", "name", "main_key", "main_value", "type", "phone", "website", "opening_hours", "street", "city",
          "state", "postcode", "category", "chamber"]
USER_AGENT = "place-packs-chambermaster/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
PAUSE = 6.0                     # seconds between two requests to one host (5 to 10 s, the research's advice)
DIRECTORY = "https://www.uschamber.com/co/sitemap/chamber-directory"
STATE_PAGE = "https://www.uschamber.com/co/chambers/{slug}"
MAX_CATEGORIES = 120            # a chamber's own category pages read at most, when it has no quick links
# The public-facing quick-link groups, by the number every classic directory gives them, with their tags.
PUBLIC_QL = {3: {"tourism": "attraction"}, 4: {"shop": "car_repair"}, 11: {"amenity": "clinic"},
             12: {"shop": "garden_centre"}, 15: {"tourism": "hotel"}, 17: {"shop": "beauty"},
             18: {"amenity": "veterinary"}, 22: {"amenity": "restaurant"}, 23: {"shop": "yes"},
             24: {"leisure": "sports_centre"}}
_QL = re.compile(r"/list/QL/[^/]*?-(\d+)\.htm$", re.I)
_CATEGORY = re.compile(r"/list/category/([^/?#]+?)(?:-\d+)?/?$", re.I)
_CARD = re.compile(r'<div[^>]*data-memid="(\d+)"', re.I)
_DIR_LINK = re.compile(r"https?://((?:business|members|directory|web)\.[a-z0-9.-]+|[a-z0-9-]+\.chambermaster\.com)"
                       r"(/list\b[^\"'<\s]*)?", re.I)
_V2_LINK = re.compile(r"https?://[a-z0-9-]+\.growthzoneapp\.com", re.I)
_TAGS = re.compile(r"<[^>]+>")


def _state(name, code):
    """One entry of STATES."""
    return {"title": name, "code": code, "slug": re.sub(r"[^a-z]+", "-", name.lower()).strip("-"),
            "expected": 0, "budget": 4000, "timeout": 300}


def _states():
    """The states, DC and Puerto Rico of regions.json, by their two-letter code in lower case."""
    from placepacks import catalogue
    out = {}
    for r in sorted(catalogue.regions().values(), key=lambda r: r.get("code", "")):
        if r.get("cc") == "US" and not r.get("parent") and r.get("code"):
            out[r["code"].lower()] = _state(r["name"], r["code"])
    return out


STATES = _states()


def _text(fragment):
    """The plain text of an HTML fragment."""
    return " ".join(html.unescape(_TAGS.sub(" ", fragment or "")).split())


def chambers(page):
    """[(name, website)] of a US Chamber state page's chamber cards (li data-cy="chamber-card")."""
    out = []
    for card in page.split('data-cy="chamber-card"')[1:]:
        name = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.S)
        site = re.search(r"Website</p>\s*<a[^>]*href=\"([^\"]+)\"", card, re.S)
        if name and site and site.group(1).startswith("http"):
            out.append((_text(name.group(1)), html.unescape(site.group(1)).strip()))
    return out


def directory_hosts(page):
    """(classic candidates: ["https://business.example.org"], v2 links found: True/False) of a chamber homepage."""
    hosts = []
    for m in _DIR_LINK.finditer(page or ""):
        host = m.group(1).lower()
        if host.endswith(".chambermaster.com") and host.startswith("www."):
            continue                                # the vendor's own site, not a directory
        if not host.endswith(".chambermaster.com") and not m.group(2):
            continue                                # a "members." host without a /list link: not a directory
        base = f"https://{host}"
        if base not in hosts:
            hosts.append(base)
    return hosts, bool(_V2_LINK.search(page or ""))


def classify(robots):
    """"classic", "v2" or "closed" from a directory host's robots.txt (see the module docstring, step 3)."""
    text = (robots.text or "").strip()
    has_map = bool(re.search(r"(?im)^\s*sitemap\s*:\s*\S*sitemap\.xml", text))
    raw = (robots.text or "").encode("utf-8")
    if not has_map and (len(raw) == 51 or "tellafriend" in text.lower()):
        return "v2"                     # GrowthZone v2's robots.txt: "Disallow: /", "Disallow: */TellAFriend"
    if not robots.allowed(robots.base + "/list/") or not has_map:
        return "closed"
    return "classic"


def pages_to_read(locs, robots):
    """The directory pages of a chamber's sitemap to read: its public-facing quick links, else its public-facing
    categories (at most MAX_CATEGORIES). [(url, category words, tags)]."""
    quick = []
    for loc in locs:
        m = _QL.search(loc)
        if m and int(m.group(1)) in PUBLIC_QL and robots.allowed(loc):
            words = re.sub(r"-\d+\.htm$", "", loc.rsplit("/", 1)[-1]).replace("-", " ")
            quick.append((loc, words, PUBLIC_QL[int(m.group(1))]))
    if quick or any(_QL.search(loc) for loc in locs):
        return quick
    cats = []
    for loc in locs:
        m = _CATEGORY.search(loc)
        if not m or not robots.allowed(loc):
            continue
        words = urllib.parse.unquote(m.group(1)).replace("-", " ")
        tags = tags_of(words)
        if tags and not PERSONAL_TYPES.search(words):
            cats.append((loc, words, tags))
    return cats[:MAX_CATEGORIES]


def cards(page):
    """The member cards of a directory page: [{"memid", "name", "street", "city", "state", "postcode", "phone",
    "website"}]. Nothing else of a card is read."""
    out = []
    starts = [(m.start(), m.group(1)) for m in _CARD.finditer(page or "")]
    for i, (start, memid) in enumerate(starts):
        card = page[start:starts[i + 1][0] if i + 1 < len(starts) else len(page)]
        name = re.search(r'itemprop="name"[^>]*>(.*?)</h5>', card, re.S)
        street = re.search(r'itemprop="streetAddress"[^>]*>(.*?)</span>', card, re.S)
        place = re.search(r'gz-address-city"[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>\s*<span[^>]*>(.*?)</span>',
                          card, re.S)
        phone = re.search(r'gz-card-phone.*?href="tel:([^"]+)"', card, re.S)
        site = re.search(r'gz-card-website.*?href="(https?://[^"]+)"', card, re.S)
        out.append({"memid": memid, "name": _text(name.group(1)) if name else "",
                    "street": _text(street.group(1)) if street else "",
                    "city": _text(place.group(1)) if place else "", "state": _text(place.group(2)) if place else "",
                    "postcode": _text(place.group(3)) if place else "",
                    "phone": html.unescape(phone.group(1)) if phone else "",
                    "website": html.unescape(site.group(1)) if site else ""})
    return out


def member_row(card, host, chamber, category, tags, code):
    """A member card as a row (FIELDS), or None when it is left out (see the module docstring)."""
    from placepacks import types as place_types
    from placepacks.readers.osm import main_tag
    name = card["name"]
    if not name or home_business(name, card["street"], category) or PERSONAL_TYPES.search(name):
        return None
    if "chamber" in name.lower() or name_similarity(name, chamber) >= 0.85:
        return None                                 # the chamber's own entry (or another chamber)
    if card["state"] and card["state"].upper() != code:
        return None                                 # a member's office in another state
    own = tags_of(name) or tags                     # "Joe's Pizza" in "Restaurants, Food & Beverages": pizza
    text = {k: str(v) for k, v in own.items()}
    found = main_tag(text)
    host_id = re.sub(r"[^a-z0-9]+", "-", urllib.parse.urlsplit(host).hostname or "").strip("-")
    return {"key": f"{host_id}:{card['memid']}", "name": name, "main_key": found[0] if found else "",
            "main_value": found[1] if found else "", "type": place_types.osm(text) or category.lower(),
            "phone": card["phone"], "website": card["website"], "opening_hours": "", "street": card["street"],
            "city": card["city"], "state": code, "postcode": card["postcode"], "category": category,
            "chamber": chamber}


def state_page(client, spec):
    """The US Chamber's directory page of a state ("" when it has none)."""
    url = STATE_PAGE.format(slug=spec["slug"])
    try:
        listing = client.fetch(DIRECTORY)
        found = [u for u in re.findall(r"https://www\.uschamber\.com/co/chambers/[a-z-]+", listing)
                 if u.rsplit("/", 1)[-1] == spec["slug"]]
        url = found[0] if found else url
    except (NotFound, RequestFailed):
        pass
    try:
        return client.fetch(url)
    except NotFound:
        return ""


def collect(client, unit, stats):
    """Yield the member rows of one state's classic ChamberMaster chambers (see the module docstring). stats gets
    the counts: chambers, classic, v2, closed, blocked, other, pages, members, left_out."""
    spec = STATES[unit]
    client.pause = PAUSE
    stats.update(chambers=0, classic=0, v2=0, closed=0, blocked=0, other=0, pages=0, members=0, left_out=0,
                 may_be_empty=True)
    page = state_page(client, spec)                 # a refusal here stops the state (Blocked)
    found = chambers(page)
    stats["chambers"] = len(found)
    seen_hosts, seen = set(), set()
    for name, site in found:
        try:
            hosts, v2 = directory_hosts(client.fetch(site))
        except Blocked:
            stats["blocked"] += 1
            continue
        except (NotFound, RequestFailed):
            stats["other"] += 1
            continue
        hosts = [h for h in hosts if h not in seen_hosts]
        if not hosts:
            stats["v2" if v2 else "other"] += 1
            continue
        for host in hosts[:1]:
            seen_hosts.add(host)
            try:
                robots = Robots(client, host, ROBOTS_AGENT)
                kind = classify(robots)
                if kind != "classic":
                    stats[kind] += 1
                    continue
                maps = robots.sitemaps()
                locs = sitemap(client, maps[0] if maps else host + "/SiteMap.xml")
                stats["classic"] += 1
                for url, words, tags in pages_to_read(locs, robots):
                    stats["pages"] += 1
                    for card in cards(client.fetch(url)):
                        row = member_row(card, host, name, words, tags, spec["code"])
                        dedupe = (phone_digits(card["phone"]) or plain_name(card["name"]) + card["street"].lower())
                        if row is None or row["key"] in seen or dedupe in seen:
                            stats["left_out"] += 1
                            continue
                        seen.update({row["key"], dedupe})
                        stats["members"] += 1
                        yield row
            except Blocked:
                stats["blocked"] += 1
            except (NotFound, RequestFailed):
                stats["other"] += 1
