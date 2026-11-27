"""Hotfrog, a free US business directory: (1) a FALLBACK lookup for the Yellow Pages job (tools/yp_lookup.py), tried
only when Yellow Pages has no match for a business already in the packs, and (2) a monthly city-by-city collection
of business listings (the source "hotfrog-listings"; the hotfrog-listings workflow).

Research of 27 November 2026 (one polite request each: robots.txt, then one search page): of the business phone
directories the owner named, only Hotfrog answered a search without a challenge and allows it in robots.txt
(it disallows only /search/ankh/). Manta, Cylex and EZlocal answered with a Cloudflare challenge; MerchantCircle's
robots.txt disallows everything for programs; Superpages is Yellow Pages' own sister site with the same listings
(and its robots.txt disallows /search); Local.com is now an articles site, not a directory; Brownbook's search is a
JavaScript app over an internal API and its city pages are disallowed; no newspaper directory platform with
public business listings was found (TownNews BLOX sites list none in robots.txt or sitemaps). People-search and
white-pages sites are never used (personal data).

The owner's decisions (27 November 2026): look businesses up on directories that answer without a challenge, and
also collect their listings city by city, adding businesses not already in the packs; facts only (name, street
address, phone, website, category; Hotfrog's search cards show no hours), the same privacy filters as everywhere
(no people's names, no e-mails, no one-person or home businesses, a street address required), polite pacing and
request budgets, and a stop on any block. robots.txt is obeyed here.

A results page (parse_results) has one card per business ('<div class="surface entity serp">'): its name and
listing address (/company/<id>/...), its categories, its address ("42 Church St, 05401-4407" then "Burlington,
VT"), its phone (the tel: link; never the number written in the business's own description) and its website
link. Never read: the description, the tags, reviews, photos, the "claim" links.
Only the Python standard library is used.
"""

import csv
import datetime
import html
import io
import re
import urllib.parse

from placepacks import contact
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.contact import PERSONAL_TYPES
from placepacks.directories.common import Robots, home_business, tags_of

SITE = "https://www.hotfrog.com"
SEARCH_URL = SITE + "/search/{where}/{what}"
USER_AGENT = "place-packs-hotfrog/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
PAUSE = 4.0                     # seconds between two requests to Hotfrog at least
FIELDS = ["key", "name", "main_key", "main_value", "type", "phone", "website", "opening_hours", "street", "city",
          "state", "postcode", "category"]
# The towns of a state that are searched: incorporated places of at least MIN_POPULATION people, from the Census
# Bureau's population estimates (one file a month, ~7 MB, census.gov).
CITIES_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv"
MIN_POPULATION = 25000
# The public-facing kinds of business searched in each town (Hotfrog's own category words).
CATEGORIES = ["restaurants", "cafes", "bakeries", "bars", "grocery stores", "pharmacies", "hardware stores",
              "clothing stores", "gift shops", "book stores", "florists", "hair salons", "auto repair", "hotels",
              "dentists", "veterinarians", "fitness centers", "pet stores", "furniture stores", "laundromats"]
_CARD = re.compile(r'<div class="surface entity serp">')
_TITLE = re.compile(r'<h3 class="entity-title[^"]*">\s*<a href="(/company/([^/"]+)/[^"]*)">\s*(.*?)\s*</a>', re.S)
_CATS = re.compile(r'<div class="entity-categories">(.*?)</div>', re.S)
_SPAN = re.compile(r"<span[^>]*>(.*?)</span>", re.S)
_ADDRESS = re.compile(r'<p class="entity-address[^"]*">\s*<span>(.*?)</span>', re.S)
_TEL = re.compile(r'href="tel:([^"]+)"')
_WEB = re.compile(r'class="btn has-icon--website"[^>]*?href="([^"]+)"', re.S)
_NEXT = re.compile(r'<a[^>]*rel="next"[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*rel="next"')
_TAGS = re.compile(r"<[^>]+>")


def _plain(text):
    """Text of an HTML fragment: tags out, entities read, spaces tidied."""
    return " ".join(html.unescape(_TAGS.sub(" ", text or "")).split())


def search_url(what, town, state):
    """The search address for words (a business's name or a category) in "<town>, <state>"."""
    return SEARCH_URL.format(where=urllib.parse.quote(f"{town}, {state}"), what=urllib.parse.quote(" ".join(
        str(what).split())))


def split_card_address(text):
    """(street, city, state, ZIP) of a card's address ("42 Church St, 05401-4407 Burlington, VT")."""
    text = " ".join(str(text or "").split())
    m = re.match(r"^(?P<street>.*?),\s*(?P<zip>\d{5})(?:-\d{4})?\s+(?P<city>.+?),\s*(?P<state>[A-Z]{2})$", text)
    if m:
        return m.group("street"), m.group("city"), m.group("state"), m.group("zip")
    m = re.match(r"^(?P<street>.*?),\s*(?P<city>[^,]+?),\s*(?P<state>[A-Z]{2})(?:\s+(?P<zip>\d{5}))?", text)
    if m:
        return m.group("street"), m.group("city"), m.group("state"), m.group("zip") or ""
    return "", "", "", ""


def parse_results(page):
    """The business cards of a results page: [{"id", "name", "street", "city", "state", "postcode", "phone",
    "website", "categories", "lat": None, "lon": None}] (facts only; see the module docstring)."""
    out = []
    starts = [m.start() for m in _CARD.finditer(page or "")]
    for i, start in enumerate(starts):
        card = page[start:starts[i + 1] if i + 1 < len(starts) else len(page)]
        t = _TITLE.search(card)
        if not t:
            continue
        cats = _CATS.search(card)
        categories = [_plain(c) for c in _SPAN.findall(cats.group(1))] if cats else []
        a = _ADDRESS.search(card)
        street, city, state, postcode = split_card_address(_plain(a.group(1)) if a else "")
        tel = _TEL.search(card)
        web = _WEB.search(card)
        out.append({"id": t.group(2), "name": _plain(t.group(3)), "street": street, "city": city, "state": state,
                    "postcode": postcode, "phone": html.unescape(tel.group(1)) if tel else "",
                    "website": html.unescape(web.group(1)) if web else "",
                    "categories": [c for c in categories if c], "lat": None, "lon": None})
    return out


def next_page(page):
    """The address of a results page's next page (its rel="next" link), or ""."""
    m = _NEXT.search(page or "")
    return urllib.parse.urljoin(SITE, html.unescape(m.group(1) or m.group(2))) if m else ""


# ------------------------------------------------------------------------------------------------ lookups

def lookup(client, record, state, today=None):
    """Look one business up on Hotfrog (the Yellow Pages job's fallback; the same rules as
    placepacks/directories/yellowpages.py lookup and choose: the name alike AND the same street address; a result
    without a street address or with a person's name is never taken). Returns a details row (placepacks/details.py
    DETAIL_FIELDS) whose matched_on starts "hotfrog". Raises Blocked, BudgetSpent."""
    from placepacks.directories import yellowpages as yp
    checked = (today or datetime.date.today()).isoformat()
    row = {"key": record["key"], "lat": f"{record['lat']:.6f}", "lon": f"{record['lon']:.6f}", "phone": "",
           "website": "", "opening_hours": "", "matched_on": "", "checked": checked}
    if not contact.allowed("yp-lookups", record["name"], record.get("type"), record.get("brand")):
        return {**row, "matched_on": "hotfrog skipped: a person's name or office"}
    if not record.get("town"):
        return {**row, "matched_on": "hotfrog skipped: no town known"}
    try:
        page = client.fetch(search_url(record["name"], record["town"], state))
    except NotFound:
        return {**row, "matched_on": "hotfrog no results"}
    except RequestFailed:
        return {**row, "matched_on": "hotfrog failed"}
    results = [r for r in parse_results(page)
               if not any(PERSONAL_TYPES.search(c) for c in r["categories"])]
    best, how = yp.choose(record, results)
    if best is None:
        return {**row, "matched_on": f"hotfrog {how}"}
    got = contact.clean("yp-lookups", record["name"], record.get("type"), best.get("phone"), best.get("website"),
                        "", brand=record.get("brand"))
    return {**row, **got, "matched_on": f"hotfrog {how}"}


# ------------------------------------------------------------------------------------------------ collection

def _states():
    """The states, DC and Puerto Rico, as the matrix units (as for the chambers), with a request budget."""
    from placepacks.directories.chambermaster import _states as states
    return {code: {**spec, "expected": 0, "budget": 4800, "timeout": 350} for code, spec in states().items()}


STATES = _states()
_PLACE_WORDS = re.compile(r"\s+(city|town|village|borough|municipality|CDP|urban county|consolidated government|"
                          r"metropolitan government|unified government|city and borough|plantation|corporation)"
                          r"(\s*\(balance\))?$|\s*\(balance\)$|\s+(metro|metropolitan) government \(balance\)$", re.I)


def cities(text, state_name, minimum=MIN_POPULATION):
    """The town names of one state in the Census population file (incorporated places, SUMLEV 162, of at least
    `minimum` people in the newest year), biggest first: "Burlington city" -> "Burlington"."""
    reader = csv.DictReader(io.StringIO(text))
    year = None
    out = []
    for r in reader:
        if year is None:
            year = sorted(k for k in r if k.startswith("POPESTIMATE") and k[11:].isdigit())[-1]
        if r.get("SUMLEV") != "162" or r.get("STNAME") != state_name:
            continue
        try:
            people = int(r.get(year) or 0)
        except ValueError:
            continue
        name = _PLACE_WORDS.sub("", r.get("NAME", "")).strip()
        if people >= minimum and name:
            out.append((people, name))
    return [n for _, n in sorted(out, key=lambda p: (-p[0], p[1]))]


def row_of(card, category_word):
    """One card as a row (FIELDS), or None (no street address, a post office box, a person's name, an
    individual's office, or no Hotfrog id)."""
    category = card["categories"][0] if card["categories"] else category_word
    if not card["id"] or home_business(card["name"], card["street"], " ".join(card["categories"])):
        return None
    if contact.PERSON_NAME.match(card["name"]):
        return None
    tags = tags_of(category, category_word)
    from placepacks import types as place_types
    from placepacks.readers.osm import main_tag
    text = {k: str(v) for k, v in tags.items()}
    found = main_tag(text) if tags else None
    kind = (place_types.osm(text) if tags else "") or " ".join(category.lower().split())
    return {"key": f"hotfrog:{card['id']}", "name": card["name"], "main_key": found[0] if found else "",
            "main_value": found[1] if found else "", "type": kind,
            "phone": card["phone"], "website": card["website"], "opening_hours": "", "street": card["street"],
            "city": card["city"], "state": card["state"], "postcode": card["postcode"], "category": category}


def collect(client, unit, stats, categories=None, max_pages=3):
    """Yield the business rows of one state (see the module docstring): the towns of at least MIN_POPULATION
    people (the biggest first, as many as the request budget allows), every category of CATEGORIES, up to
    max_pages pages each, robots.txt obeyed. A refusal (Blocked) stops
    the state's run at once (recorded "blocked" by placepacks/directories/run.py)."""
    spec = STATES[unit]
    categories = categories or CATEGORIES
    robots = Robots(client, SITE, ROBOTS_AGENT)
    client.pause = max(client.pause, PAUSE, robots.crawl_delay() or 0)
    towns = cities(client.fetch(CITIES_URL), spec["title"])
    # The biggest towns first, as many as the state's request budget allows (about 1.3 pages per search).
    towns = towns[:max(1, int((client.budget - client.used - 5) / (len(categories) * 1.3)))]
    stats.update(towns=len(towns), pages=0, cards=0, left_out=0, may_be_empty=True)
    seen = set()
    for town in towns:
        for word in categories:
            url, pages = search_url(word, town, spec["code"]), 0
            while url and pages < max_pages and robots.allowed(url):
                try:
                    page = client.fetch(url)
                except NotFound:
                    break
                except RequestFailed:
                    stats["failed"] = stats.get("failed", 0) + 1
                    break
                pages += 1
                stats["pages"] += 1
                for card in parse_results(page):
                    stats["cards"] += 1
                    if card["state"] and card["state"] != spec["code"]:
                        continue
                    row = row_of(card, word)
                    if row is None or row["key"] in seen:
                        stats["left_out"] += 1
                        continue
                    seen.add(row["key"])
                    yield row
                url = next_page(page)
