"""Hospitals' own "patients and visitors" and accessibility pages: which accessibility services a hospital says
it offers (the owner's request of 27 November 2026, notes/helper-rules.txt; part of source "health-access"; the
owner approved reading hospitals' websites where needed, stopping at any block).

The hospitals: US hospitals with an official website and a position in Wikidata (placepacks/mapvendors/discover.py
wikidata_orgs; place_key "wikidata:Q..."), shared between the units hospital-pages-1 .. -N. For each: robots.txt
first (obeyed), its homepage, then up to MAX_LINKS of its own pages whose link speaks of accessibility,
disabilities, ADA, interpreters, language services or patients and visitors.

What is kept is a list of FACTS, never the page's text: each fact of FACTS whose words appear in a sentence of
those pages ("wheelchairs available", "sign language interpreters", "braille materials", "large print materials",
"service animals welcome", "TTY or relay service", "accessible parking", "accessible entrance", "assistive
listening devices" ...), and the phone number written in a sentence about accessibility, disability services or
interpreters (the accessibility desk's line; a person's name next to it is never kept). The note reads
"Accessibility (hospital's website): wheelchairs available; sign language interpreters; ...; accessibility services
phone 802-555-0100; page https://...". Each hospital becomes one "site" row (features.FEATURE_FIELDS), which the
pack build ties to the hospital already in the pack (its Wikidata key, else the same name nearby).
Never: an e-mail address, a person's name, a review; a site that refuses (403, a challenge page) is recorded as
blocked and left; no login, no CAPTCHA, no headless browser.
"""

import re
import urllib.parse

from placepacks import contact, features
from placepacks.chains.polite import Blocked, NotFound, RequestFailed

SHARDS = 4
MAX_LINKS = 3
LINK = [(re.compile(r"accessib|disabilit|\bada\b|section 504|1557|non-?discrimination", re.I), 3),
        (re.compile(r"interpret|language (services|assistance|access)|deaf|hard of hearing|blind|low vision", re.I), 2),
        (re.compile(r"patients?\s*(&|and|-)\s*visitors|visitor (info|guide|information)|for patients|patient guide|"
                    r"patient (rights|services)", re.I), 1)]
FACTS = [
    ("wheelchairs available", r"wheel ?chairs?\b[^.]{0,80}\b(available|loan|loaned|borrow|provided|at (each|the main)"
                              r"|offer)"),
    ("sign language interpreters", r"(american sign language|\basl\b|sign language)[^.]{0,40}interpret|interpret"
                                   r"[^.]{0,60}(american sign language|\basl\b|sign language)"),
    ("language interpreters", r"interpret(er|ers|ing|ation)[^.]{0,40}(available|provided|free|no cost|at no charge)|"
                              r"(free|no[- ]cost)[^.]{0,20}interpret"),
    ("video remote interpreting", r"video remote interpret|\bvri\b"),
    ("TTY or relay service", r"\btty\b|\btdd\b|relay service|\bdial 711\b|\b711\b"),
    ("braille materials", r"\bbraille\b"),
    ("large print materials", r"large[- ]print"),
    ("audio or electronic formats", r"audio (recording|format)|accessible electronic format|screen reader"),
    ("assistive listening devices", r"assistive listening|hearing loop|pocket ?talker|amplified (phone|telephone)"),
    ("service animals welcome", r"service (animal|animals|dog|dogs)\b"),
    ("accessible parking", r"(accessible|handicap\w*|disabled|ada|disability)\s+(parking|spaces)"),
    ("accessible entrance", r"(accessible|wheelchair[- ]accessible|ada)\s+(entrance|entrances|entry|door|doors)"),
    ("accessible restrooms", r"accessible (restroom|restrooms|bathroom|bathrooms|toilet)"),
    ("accessible exam rooms and equipment", r"accessible (exam|examination) (room|rooms|table|tables)|"
                                           r"(height[- ]adjustable|lift) (exam )?tables?|patient lifts?"),
    ("escort or wheelchair assistance at the entrance", r"(escort|transport|volunteer)[^.]{0,40}wheelchair|"
                                                         r"wheelchair (escort|assistance)"),
]
_FACTS = [(label, re.compile(p, re.I)) for label, p in FACTS]
PHONE_CONTEXT = re.compile(r"accessib|disabilit|\bada\b|section 504|interpret|language (services|assistance)|"
                           r"\btty\b|deaf", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?[2-9]\d\d\)?[\s.-]?[2-9]\d\d[\s.-]?\d{4}(?!\d)")
_A = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def page_text(html):
    """A page's visible text: scripts, styles and tags taken out, spaces made single."""
    t = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", html or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&rsquo;", "'")
    return " ".join(t.split())


def sentences(text):
    """A text cut into sentences (at ". ", "! ", "? " and bullet-like breaks)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\s+[•·|]\s+", text) if s.strip()]


def facts_of(texts):
    """(facts, accessibility phone) of pages' texts: the FACTS labels seen (in FACTS order) and the first phone
    number in a sentence about accessibility (PHONE_CONTEXT), written "802-555-0100", or ""."""
    seen, phone = set(), ""
    for text in texts:
        for s in sentences(text):
            for label, rx in _FACTS:
                if label not in seen and rx.search(s):
                    seen.add(label)
            if not phone and PHONE_CONTEXT.search(s):
                m = PHONE.search(s)
                if m:
                    phone = contact.phone(m.group(0))
    return [label for label, _ in FACTS if label in seen], phone


def access_links(page, base, home):
    """The hospital's own pages worth reading, best first (at most MAX_LINKS)."""
    from placepacks.mapvendors.discover import same_site
    scored = {}
    for m in _A.finditer(page or ""):
        href = urllib.parse.urljoin(base, m.group(1).strip())
        if not href.startswith("http") or not same_site(href, home) or re.search(r"\.(pdf|jpe?g|png|docx?)$", href,
                                                                                  re.I):
            continue
        words = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split()) + " " + urllib.parse.urlsplit(href).path
        score = max((s for rx, s in LINK if rx.search(words)), default=0)
        if score:
            scored[href] = max(score, scored.get(href, 0))
    return [u for u, _ in sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))[:MAX_LINKS]]


def scan_hospital(client, org):
    """The "site" row of one hospital, or None (nothing found, robots.txt disallows, the site refused or failed:
    status in the second value)."""
    from placepacks.directories.common import Robots
    home = org["homepage"]
    parts = urllib.parse.urlsplit(home)
    try:
        robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent="place-packs-health-access")
        if not robots.allowed(home + "/"):
            return None, "robots"
        first = client.fetch(home + ("/" if not parts.path else ""))
        texts, pages = [], []
        for url in access_links(first, home, home):
            if robots.allowed(url):
                try:
                    texts.append(page_text(client.fetch(url)))
                    pages.append(url)
                except NotFound:
                    continue
    except Blocked:
        return None, "blocked"
    except (NotFound, RequestFailed):
        return None, "failed"
    found, phone = facts_of(texts)
    if not found and not phone:
        return None, "nothing"
    note = "Accessibility (hospital's website): " + "; ".join(
        found + ([f"accessibility services phone {phone}"] if phone else []) + ([f"page {pages[0]}"] if pages else []))
    key = f"hospital-pages:{org['place_key'].split(':')[-1]}"
    return {"key": key, "kind": "site", "site": key, "name": org["org"], "site_name": org["org"],
            "place_key": org["place_key"], "lat": org["lat"], "lon": org["lon"], "website": home,
            "notes": features.clean_note(note, 500), "org": org["org"], "vendor": "hospital-pages"}, "ok"


def collect(client, unit, stats):
    """The hospitals of one shard ("hospital-pages-2": every SHARDS-th from the second)."""
    from placepacks.mapvendors.discover import wikidata_orgs
    index = int(unit.rsplit("-", 1)[1]) - 1
    orgs = [o for i, o in enumerate(wikidata_orgs(client, ("hospital",))) if i % SHARDS == index]
    stats.update(hospitals=len(orgs), ok=0, blocked=0, robots=0, failed=0, nothing=0)
    stats["may_be_empty"] = True
    for org in orgs:
        row, status = scan_hospital(client, org)
        stats[status] = stats.get(status, 0) + 1
        if row:
            yield row
