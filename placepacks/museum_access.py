"""Museum accessibility (queue item Q4 of the owner's list of 27 November 2026, notes/helper-rules.txt): what each
museum's own website says it offers visitors with disabilities: audio description and audio guides, touch and
tactile tours, braille and large print, sign language tours and interpreters, assistive listening, captions,
wheelchairs to borrow, accessible entrances, elevators and restrooms, service animals, sensory-friendly hours and
kits, free admission for a companion. Source "museum-access" (extra part; monthly workflow
.github/workflows/museum-access.yml, release "museum-access").

The museums: those already in the packs that have a website: the IMLS Museum Universe Data File (WEBURL; place_key
"imls-museums:<MID>"; historical societies left out as in the source imls-museums) and Wikidata's US museums with
an official website (place_key "wikidata:Q..."), each website once. The Smithsonian's central accessibility page
(si.edu/accessibility) answers 403 to programs (checked 27 November 2026; recorded as blocked, never got round); its
museums' own sites (naturalhistory.si.edu, airandspace.si.edu ...) come in with their Wikidata entries. The plan
job saves the list once (seeds); the units museums-1 .. museums-SHARDS each take every SHARDS-th museum.

For each museum: robots.txt first (obeyed), its homepage, then up to MAX_LINKS of its own pages whose link speaks of
accessibility, disabilities, access programs, sensory, or (last) visiting. What is kept is a list of FACTS (never
the page's text): each fact whose words appear in a sentence of those pages; only for the accessible entrance the
sentence that says where it is is kept too (cut to 300 characters, e-mail addresses and telephone numbers taken
out). Each museum becomes:
  - one "site" row tied by the pack build to the museum already in the pack (its IMLS or Wikidata key, else the
    same name within 400 m), with the note "Accessibility (museum's website): audio description; touch tours;
    braille; large print; sign language; wheelchairs available; service animals welcome; sensory-friendly
    programs; page https://..." (a museum that matches no place adds nothing: keep_unmatched_sites false);
  - features at the museum's position (site features of the museum): kind "accessibility service" for each
    service ("Audio description", "Touch tours", "Braille materials", "Large print materials", "Sign language
    tours or interpreters", "Assistive listening devices", "Wheelchairs available", "Sensory-friendly programs"),
    "accessible entrance" (with the sentence that says where), "elevator" and "accessible restroom".
Never: a person's name, an e-mail address, a review; a site that refuses (403, a challenge page) is recorded as
blocked and left; no login, no CAPTCHA, no headless browser.

    python -m placepacks.museum_access seeds --out museum-seeds.json        the plan job's list
    python -m placepacks.directories.run museumaccess --unit museums-3 --out out/
Only the Python standard library is used.
"""

import csv
import io
import json
import os
import re
import urllib.parse
import zipfile

from placepacks import features
from placepacks.chains.polite import Blocked, NotFound, RequestFailed

USER_AGENT = "place-packs-museum-access/1 (+https://github.com/mark-getbraille/place-packs)"
AGENT = "place-packs-museum-access"
PAUSE = 2.0
TAG = "museum-access"
FIELDS = features.FEATURE_FIELDS
SHARDS = 8
MAX_LINKS = 2
SEEDS_FILE = "museum-seeds.json"
IMLS_LISTING = "https://www.imls.gov/research-evaluation/data/museum-data-files"
IMLS_PATTERN = r"[^\"'\s>]*\d{4}_csv_museum_data_files\.zip"
WDQS = "https://query.wikidata.org/sparql"
# Wikidata classes: museum, art museum, history museum, science museum, natural history museum, children's museum.
WIKIDATA_CLASSES = ("Q33506", "Q207694", "Q16735822", "Q588140", "Q1970365", "Q2087181")
# Hosts that are not a museum's own site (a social network page, a listing): never read.
NOT_OWN_SITE = re.compile(r"(^|\.)(facebook|instagram|twitter|x|youtube|tripadvisor|yelp|wikipedia|google|"
                          r"linkedin|pinterest|tiktok|blogspot|wordpress\.com|squarespace\.com|eventbrite|"
                          r"meetup|nps\.gov)(\.|$)", re.I)
LINK = [(re.compile(r"accessib|disabilit|\bada\b|access (programs?|services|for all)|visitors with|"
                    r"blind|low vision|deaf|hard of hearing|sign language|\basl\b", re.I), 3),
        (re.compile(r"sensory|autism|neurodiver|inclusi", re.I), 2),
        (re.compile(r"plan (your|a) visit|visitor (info|information|guide)|visit(ing)?\b|faq", re.I), 1)]
UNIT_SERVICES = [
    # (fact, words, feature kind or "", feature name)
    ("audio description", r"audio[- ]descri|described (tour|video)|verbal descri|visual descri|descriptive tour",
     "accessibility service", "Audio description"),
    ("audio guides", r"audio (guide|tour)s?\b|audioguide", "", ""),
    ("touch tours", r"touch (tour|tours|object|objects|cart|carts|collection|gallery|table|tables)|tactile "
                    r"(tour|tours|graphic|graphics|model|models|exhibit|exhibits|map|maps|object|objects)|"
                    r"hands[- ]on tour", "accessibility service", "Touch tours"),
    ("braille", r"\bbraille\b", "accessibility service", "Braille materials"),
    ("large print", r"large[- ]print", "accessibility service", "Large print materials"),
    ("sign language", r"american sign language|\basl\b|sign language", "accessibility service",
     "Sign language tours or interpreters"),
    ("assistive listening devices", r"assistive listening|hearing loop|induction loop|\bt-?coil\b",
     "accessibility service", "Assistive listening devices"),
    ("captions", r"\bcaption(s|ed|ing)\b|\bcart (captioning|services)\b", "", ""),
    ("wheelchairs available", r"wheel ?chairs?\b[^.]{0,80}\b(available|loan|loaned|borrow|free of charge|"
                              r"complimentary|first[- ]come|check(ed)? out|reserve|provided)",
     "accessibility service", "Wheelchairs available"),
    ("wheelchair accessible", r"(fully|wheelchair)[- ]accessible|accessible (to|for) (wheelchair|visitors who use)",
     "", ""),
    ("accessible entrance", r"accessible (entrance|entrances|entry|door|doors)|(entrance|entry)[^.]{0,50}"
                            r"\b(ramp|wheelchair|step[- ]free|accessible)", "accessible entrance",
     "Accessible entrance"),
    ("elevators", r"\belevators?\b", "elevator", "Elevator"),
    ("accessible restrooms", r"accessible (restroom|restrooms|bathroom|bathrooms|toilet|toilets)|"
                             r"(family|all[- ]gender) restrooms?", "accessible restroom", "Accessible restrooms"),
    ("accessible parking", r"(accessible|handicap\w*|disabled|ada|disability)\s+(parking|spaces)", "", ""),
    ("service animals welcome", r"service (animal|animals|dog|dogs)\b", "", ""),
    ("sensory-friendly programs", r"sensory[- ]friendly|low[- ]sensory|sensory (hours|morning|mornings|kit|kits|"
                                  r"bag|bags|backpack|backpacks|map|maps|guide|guides|room)|quiet (room|hours|space)",
     "accessibility service", "Sensory-friendly programs"),
    ("programs for blind and low-vision visitors", r"\b(blind|low[- ]vision|visually impaired|vision loss)\b", "", ""),
    ("free admission for a companion", r"(caregiver|companion|personal care attendant|care partner|aide)s?[^.]{0,60}"
                                       r"\b(free|no charge|complimentary|no cost)", "", ""),
    ("portable stools or seating", r"(portable|folding|gallery) (stool|stools|seat|seats|chair|chairs)|"
                                   r"stools? (are )?available", "", ""),
]
_SERVICES = [(fact, re.compile(words, re.I), kind, name) for fact, words, kind, name in UNIT_SERVICES]
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?[2-9]\d\d\)?[\s.-]?[2-9]\d\d[\s.-]?\d{4}(?!\d)")


# ------------------------------------------------------------------------------------------------ the museums

def own_site(url):
    """A museum's homepage as a full address when it is the museum's own site (not a social network page or a
    listing), else ""."""
    from placepacks.mapvendors.discover import homepage
    site = homepage(url)
    host = urllib.parse.urlsplit(site).hostname or ""
    return "" if not site or NOT_OWN_SITE.search(host) else site


def imls_museums(zip_bytes):
    """The museums of an IMLS Museum Universe Data File .zip (bytes) that have a website: [{"org", "homepage",
    "place_key", "lat", "lon"}]. Historical societies (HSC) are left out, as in the source imls-museums. Only the
    id, name, website, discipline and position columns are read."""
    out = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in sorted(n for n in z.namelist() if n.lower().endswith(".csv")):
            text = io.TextIOWrapper(z.open(name), encoding="latin-1", newline="")
            for d in csv.DictReader(text):
                discipline = (d.get("DISCIPL") or d.get("DISCIPLINE") or "").strip()
                site = own_site((d.get("WEBURL") or "").strip())
                if discipline == "HSC" or not site:
                    continue
                try:
                    lat, lon = float(d.get("LATITUDE") or ""), float(d.get("LONGITUDE") or "")
                except ValueError:
                    continue
                org = " ".join((d.get("COMMONNAME") or d.get("LEGALNAME") or "").split()).title()
                out.append({"org": org, "homepage": site, "place_key": f"imls-museums:{(d.get('MID') or '').strip()}",
                            "lat": f"{lat:.6f}", "lon": f"{lon:.6f}"})
    return out


def wikidata_museums(client, limit=8000):
    """Wikidata's US museums with an official website and a position: [{"org", "homepage", "place_key", "lat",
    "lon"}]."""
    values = " ".join(f"wd:{c}" for c in WIKIDATA_CLASSES)
    query = ("SELECT DISTINCT ?item ?itemLabel ?site ?coord WHERE { VALUES ?class { " + values + " } ?item wdt:P31 "
             "?class; wdt:P17 wd:Q30; wdt:P856 ?site; wdt:P625 ?coord. SERVICE wikibase:label { bd:serviceParam "
             "wikibase:language \"en\". } } LIMIT " + str(limit))
    answer = client.json(WDQS + "?" + urllib.parse.urlencode({"query": query, "format": "json"}),
                         headers={"Accept": "application/sparql-results+json"})
    out = []
    for b in (answer.get("results") or {}).get("bindings") or []:
        m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
        site = own_site(b.get("site", {}).get("value"))
        if not m or not site:
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        out.append({"org": b.get("itemLabel", {}).get("value", qid), "homepage": site, "place_key": f"wikidata:{qid}",
                    "lat": m.group(2), "lon": m.group(1)})
    return out


def merge_seeds(*lists):
    """The museums of several lists, each website once (the first list's entry wins), sorted by place_key so the
    shares stay stable from month to month."""
    out, seen = [], set()
    for items in lists:
        for o in items:
            site = o["homepage"].lower().rstrip("/")
            site = re.sub(r"^https?://(www\.)?", "", site)
            if site in seen:
                continue
            seen.add(site)
            out.append(o)
    return sorted(out, key=lambda o: o["place_key"])


def make_seeds(client):
    """The month's museum list: IMLS's (the newest file found on its data page) and Wikidata's. A list that cannot
    be read is left out (the other still counts)."""
    imls, wikidata = [], []
    try:
        page = client.fetch(IMLS_LISTING)
        m = re.search(IMLS_PATTERN, page)
        if m:
            from placepacks.mapvendors.discover import _binary
            imls = imls_museums(_binary(client, urllib.parse.urljoin(IMLS_LISTING, m.group(0))))
    except (NotFound, RequestFailed, Blocked, zipfile.BadZipFile) as e:
        print(f"IMLS museum file: {e}", flush=True)
    try:
        wikidata = wikidata_museums(client)
    except (NotFound, RequestFailed, Blocked) as e:
        print(f"Wikidata museums: {e}", flush=True)
    return merge_seeds(imls, wikidata)


def load_seeds(client):
    """The museum list saved by the plan job ($MUSEUM_SEEDS), else made now."""
    path = os.environ.get("MUSEUM_SEEDS") or ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return make_seeds(client)


# ------------------------------------------------------------------------------------------------ one museum

def access_links(page, base, home):
    """The museum's own pages worth reading, best first (at most MAX_LINKS)."""
    from placepacks.health_access.hospital_pages import _A
    from placepacks.mapvendors.discover import same_site
    scored = {}
    for m in _A.finditer(page or ""):
        href = urllib.parse.urljoin(base, m.group(1).strip())
        if not href.startswith("http") or not same_site(href, home) or \
                re.search(r"\.(pdf|jpe?g|png|docx?|mp3|mp4)$", href, re.I):
            continue
        words = " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split()) + " " + urllib.parse.urlsplit(href).path
        score = max((s for rx, s in LINK if rx.search(words)), default=0)
        if score:
            scored[href] = max(score, scored.get(href, 0))
    return [u for u, _ in sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))[:MAX_LINKS]]


def facts_of(texts):
    """(facts, entrance sentence) of pages' texts: the UNIT_SERVICES facts seen (in their order), and the first
    sentence that names an accessible entrance (e-mail addresses and telephone numbers taken out, at most 300
    characters), or ""."""
    from placepacks.health_access.hospital_pages import sentences
    seen, entrance = set(), ""
    for text in texts:
        for s in sentences(text):
            if len(s) > 600:                                # a run of menu words, not a sentence
                continue
            for fact, rx, _, _ in _SERVICES:
                if fact not in seen and rx.search(s):
                    seen.add(fact)
                    if fact == "accessible entrance" and not entrance:
                        entrance = features.clean_note(PHONE.sub("", s), 300)
    return [fact for fact, *_ in UNIT_SERVICES if fact in seen], entrance


def museum_rows(org, facts, entrance, page_url):
    """The rows of one museum: its "site" row and its features (see the module docstring)."""
    key = f"museum-access:{org['place_key'].split(':')[-1]}"
    note = "Accessibility (museum's website): " + "; ".join(facts + ([f"page {page_url}"] if page_url else []))
    base = {"site": key, "site_name": org["org"], "place_key": org["place_key"], "lat": org["lat"],
            "lon": org["lon"], "org": org["org"], "vendor": "museum-pages"}
    rows = [{**base, "key": key, "kind": "site", "name": org["org"], "website": org["homepage"],
             "notes": features.clean_note(note, 600)}]
    for fact, _, kind, name in _SERVICES:
        if kind and fact in facts:
            notes = entrance if fact == "accessible entrance" else f"At {org['org']} (the museum's website)"
            rows.append({**base, "key": f"{key}:{name.lower().replace(' ', '-')}", "kind": kind, "name": name,
                         "notes": notes})
    return rows


def scan_museum(client, org):
    """(rows, status) of one museum: status "ok", "robots" (robots.txt disallows), "blocked" (403, a challenge
    page: left at once), "failed" or "nothing" (no accessibility fact found)."""
    from placepacks.directories.common import Robots
    from placepacks.health_access.hospital_pages import page_text
    home = org["homepage"]
    parts = urllib.parse.urlsplit(home)
    try:
        robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent=AGENT)
        if not robots.allowed(home + "/"):
            return [], "robots"
        first = client.fetch(home + ("/" if not parts.path else ""))
        texts, pages = [page_text(first)], []
        for url in access_links(first, home, home):
            if robots.allowed(url):
                try:
                    texts.append(page_text(client.fetch(url)))
                    pages.append(url)
                except NotFound:
                    continue
    except Blocked:
        return [], "blocked"
    except (NotFound, RequestFailed):
        return [], "failed"
    found, entrance = facts_of(texts)
    # The homepage alone often says "elevator" or "wheelchair accessible" in passing: a museum needs at least one
    # fact from an accessibility page, or two from the homepage.
    if not found or (not pages and len(found) < 2):
        return [], "nothing"
    return museum_rows(org, found, entrance, pages[0] if pages else ""), "ok"


def collect(client, unit, stats):
    """The museums of one share ("museums-3": every SHARDS-th from the third). A museum that refuses is counted as
    blocked and the share goes on; the request budget or the time running out ends the share (BudgetSpent)."""
    index = int(unit.rsplit("-", 1)[1]) - 1
    orgs = [o for i, o in enumerate(load_seeds(client)) if i % SHARDS == index]
    stats.update(museums=len(orgs), ok=0, blocked=0, robots=0, failed=0, nothing=0, may_be_empty=True)
    for org in orgs:
        rows, status = scan_museum(client, org)
        stats[status] = stats.get(status, 0) + 1
        yield from rows


UNITS = {f"museums-{i}": {"title": f"Museums' own accessibility pages ({i} of {SHARDS})", "expected": 1000,
                          "budget": 6000, "timeout": 340} for i in range(1, SHARDS + 1)}


def main(argv=None):
    """python -m placepacks.museum_access seeds --out museum-seeds.json: the month's museum list (the plan job)."""
    import argparse
    from placepacks.chains.polite import Polite
    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("action", choices=["seeds"])
    p.add_argument("--out", default=SEEDS_FILE)
    a = p.parse_args(argv)
    client = Polite(20, PAUSE, agent=USER_AGENT)
    seeds = make_seeds(client)
    if not seeds:
        raise SystemExit("no museums could be listed")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(seeds, f)
    print(f"{len(seeds)} museums written to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
