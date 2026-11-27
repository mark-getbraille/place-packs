"""Yellow Pages LOOKUPS: the phone number, website and opening hours of businesses ALREADY in the packs that lack
them, looked up one by one on yellowpages.com (the source "yp-lookups"; the job is tools/yp_lookup.py).

The owner's decision (26 November 2026, notes/helper-rules.txt): Yellow Pages is used only to LOOK UP details for
businesses we already have from other sources, never to copy its directory. Only facts are taken (phone, website,
hours); never a review, a rating, a description, a photo, an e-mail address or a person's name. One-person and home
businesses are skipped. The lookups are slow (one request every 3 to 4 seconds, at most DAY_LIMIT a day) and stop
at once on any refusal or anti-bot page (placepacks/chains/polite.py: Blocked): no CAPTCHA, no browser, no other
connection is ever used to get past one. yellowpages.com's robots.txt disallows "/search*" for every program; the
owner decided to make these lookups all the same (his decision and risk), so this is recorded in sources.json.

One lookup (lookup()):
  1. skip the business when its name is a person's or its type an individual's own office (contact.allowed), or
     when no town is known for it (the search needs one);
  2. ONE search: SEARCH_URL with the business's name and "<town>, <state>";
  3. read the results page (parse_results): its schema.org JSON-LD list of LocalBusiness objects (name, street
     address, telephone, openingHours, the listing's page) and each result card's "Website" link;
  4. accept a result only if its name is like ours (name_similarity >= NAME_MIN) AND its street address is one of
     the addresses within 75 m of our place (normalised: "184 Main Street" = "184 MAIN ST"), or, when Yellow Pages
     gives the result's coordinates, they are within MATCH_M metres of ours. A result without a street address (a
     home or service-area business) or with a person's name is never taken. Two different phone numbers both
     matching is no answer (ambiguous);
  5. take its phone, website (social-media pages are dropped by contact.website) and hours. Only when the result
     has no hours and the day's detail budget allows (DETAIL_SHARE of the searches) is the listing's own page read
     for them (parse_detail).
The answer is one row of placepacks/details.py's DETAIL_FIELDS: key, lat, lon, phone, website, opening_hours,
matched_on ("name+address", "name+distance", or why nothing was taken: "no match", "no results", "ambiguous",
"skipped: ...") and checked (the date).
Only the Python standard library is used.
"""

import datetime
import html
import re
import urllib.parse

from placepacks import contact
from placepacks.chains import hours as oh
from placepacks.chains import jsonld
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.directories.common import name_similarity, person_name, same_street_address

SEARCH_URL = "https://www.yellowpages.com/search?search_terms={name}&geo_location_terms={where}"
SITE = "https://www.yellowpages.com"
NAME_MIN = 0.85                 # names at least this alike may be the same business
MATCH_M = 75                    # a result's coordinates within this many metres of ours
DAY_LIMIT = 25000               # requests a day at most
PAUSE = 3.0                     # seconds between two requests at least (plus up to a second more, tools/yp_lookup)
DETAIL_SHARE = 0.25             # listing pages read for hours: at most this share of the day's searches
USER_AGENT = "place-packs-yp-lookup/1 (+https://github.com/mark-getbraille/place-packs)"
_CARD = re.compile(r'<div class="result" id="lid-(\d+)"')
_WEBSITE = re.compile(r'<a[^>]*class="[^"]*track-visit-website[^"]*"[^>]*href="([^"]+)"', re.I)
_WEBSITE_ALT = re.compile(r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*track-visit-website[^"]*"', re.I)
_YPID = re.compile(r"-(\d+)/?(?:\?.*)?$")


def search_url(name, town, state):
    """The search address for a business's name in "<town>, <state>"."""
    return SEARCH_URL.format(name=urllib.parse.quote_plus(" ".join(name.split())),
                             where=urllib.parse.quote_plus(f"{town}, {state}"))


def _websites(page):
    """{listing id: the "Website" link of its result card} of a results page."""
    found = {}
    starts = [(m.start(), m.group(1)) for m in _CARD.finditer(page)]
    for i, (start, ypid) in enumerate(starts):
        card = page[start:starts[i + 1][0] if i + 1 < len(starts) else len(page)]
        m = _WEBSITE.search(card) or _WEBSITE_ALT.search(card)
        if m:
            found[ypid] = html.unescape(m.group(1))
    return found


def parse_results(page):
    """The results of a search page: [{"name", "street", "city", "state", "postcode", "phone", "opening_hours",
    "url", "website", "lat", "lon"}]. Only these facts are read: never a rating, a review, a description, a photo
    or an e-mail."""
    sites = _websites(page)
    out = []
    for thing in jsonld.find(page, {"LocalBusiness"}):
        got = jsonld.store(thing, need_position=False)
        if not got or not got.get("name"):
            continue
        url = got.get("website") or ""
        m = _YPID.search(url)
        out.append({"name": got["name"], "street": got["street"], "city": got["city"], "state": got["state"],
                    "postcode": got["postcode"], "phone": got["phone"], "opening_hours": got["opening_hours"],
                    "url": urllib.parse.urljoin(SITE, url) if url else "",
                    "website": sites.get(m.group(1), "") if m else "", "lat": got["lat"], "lon": got["lon"]})
    return out


def parse_detail(page):
    """(opening hours, (lat, lon) or None) of a listing's own page, from its schema.org data."""
    hours, at = "", None
    for value in jsonld.blocks(page):
        for thing in jsonld.things(value):
            if not hours and (thing.get("openingHoursSpecification") or thing.get("openingHours")):
                hours = (jsonld.store(thing, need_position=False) or {}).get("opening_hours", "")
            at = at or jsonld.position(thing)
    return hours, at


def choose(record, results):
    """(the result that is the record's business, how it matched) or (None, why not) (see the module docstring).
    record: {"name", "lat", "lon", "addresses": ["184 Main St", ...]}."""
    from placepacks.fmt import metres
    if not results:
        return None, "no results"
    found = []
    for r in results:
        if not r.get("street") or person_name(r["name"]):
            continue                    # a home or service-area business, or a person
        likeness = name_similarity(record["name"], r["name"])
        if likeness < NAME_MIN:
            continue
        how = ""
        if any(same_street_address(r["street"], a) for a in record.get("addresses") or []):
            how = "name+address"
        elif r.get("lat") is not None and r.get("lon") is not None and \
                metres(record["lat"], record["lon"], r["lat"], r["lon"]) <= MATCH_M:
            how = "name+distance"
        if how:
            found.append((likeness, how, r))
    if not found:
        return None, "no match"
    found.sort(key=lambda f: -f[0])
    phones = {contact.phone_digits(f[2].get("phone")) for f in found if f[2].get("phone")}
    if len(phones) > 1:
        return None, "ambiguous"
    return found[0][2], found[0][1]


def lookup(client, record, state, allow_detail=True, today=None):
    """Look one business up (see the module docstring). record: {"key", "name", "type", "brand", "lat", "lon",
    "town", "addresses"}; state: its two-letter state. Returns (row, requests used for the listing page: 0 or 1).
    Raises Blocked (stop the day), BudgetSpent."""
    checked = (today or datetime.date.today()).isoformat()
    row = {"key": record["key"], "lat": f"{record['lat']:.6f}", "lon": f"{record['lon']:.6f}", "phone": "",
           "website": "", "opening_hours": "", "matched_on": "", "checked": checked}
    if not contact.allowed("yp-lookups", record["name"], record.get("type"), record.get("brand")):
        return {**row, "matched_on": "skipped: a person's name or office"}, 0
    if not record.get("town"):
        return {**row, "matched_on": "skipped: no town known"}, 0
    try:
        page = client.fetch(search_url(record["name"], record["town"], state))
    except NotFound:
        return {**row, "matched_on": "no results"}, 0
    except RequestFailed:
        return {**row, "matched_on": "failed"}, 0
    best, how = choose(record, parse_results(page))
    if best is None:
        return {**row, "matched_on": how}, 0
    hours, extra = best.get("opening_hours", ""), 0
    if not hours and allow_detail and best.get("url", "").startswith(SITE + "/"):
        try:
            extra = 1
            hours, _ = parse_detail(client.fetch(best["url"]))
        except (NotFound, RequestFailed):
            hours = ""
    got = contact.clean("yp-lookups", record["name"], record.get("type"), best.get("phone"), best.get("website"),
                        oh.from_text(hours) or hours, brand=record.get("brand"))
    return {**row, **got, "matched_on": how}, extra
