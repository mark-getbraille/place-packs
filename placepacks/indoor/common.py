"""What the mall and airport directory collectors share (placepacks/indoor): the rows they write, the privacy
filters, opening hours, and the readers of the page shapes their websites use.

The rows (FIELDS): the site features CSV of placepacks/features.py (FEATURE_FIELDS: key, kind, name, site,
site_name, place_key, ..., level, lat, lon, notes, phone, website, opening_hours, ...) plus five columns for the
businesses part:
  business     "1" when a store or restaurant row also becomes a business of its own in the businesses part (it has
               its own phone number or its own opening hours, the owner's rule of 27 November 2026), else ""
  main_value   the OpenStreetMap-style main tag value of the row's category ("restaurant", "clothes", "yes"), for
               the build's class and fine type (placepacks/directories/common.py tags_of)
  type         a fine type phrase when the category gives none ("shoe store"); may be empty
  category     the directory's own category words, as they are ("Women's Apparel, Shoes")
  unit         the store's unit or suite ("Suite 690"), kept for checking by hand
A store's position is its own when the directory gives one (an Atrius airport map), else the mall's (most mall
directories give a level and a unit but no position): its site, level and note say where it is.

Privacy (the owner's limits, notes/helper-rules.txt): facts only: names of stores and services, category, floor or
level, unit, hours, phone, website, gates, desks, restrooms and accessibility features. Never an e-mail address
(taken out of every text), never a person's name (a store named like a person, "Alice Example", is left out; a
note never keeps a sentence naming a person: person_in), never a description, review, rating or photo.
Only the Python standard library is used.
"""

import html
import json
import re
import urllib.parse

from placepacks import contact as contacts
from placepacks import features
from placepacks.chains import hours as oh

FIELDS = features.FEATURE_FIELDS + ["business", "main_value", "type", "category", "unit"]
EMAIL = features.EMAIL
NOTE = 300                      # the longest note a store, desk or amenity keeps
# A sentence naming a person: a title and a capitalised name, or "contact <Name Name>". Such a sentence is never
# kept in a note (a manager's or a volunteer's name).
PERSON_WORDS = re.compile(r"\b(Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+|\b(contact|ask for|manager|coordinator|director)"
                          r"\s+[A-Z][a-z]+\s+[A-Z][a-z]+")


# ------------------------------------------------------------------------------------------------ text

def plain(text):
    """Text without HTML tags or entities, spaces made single."""
    t = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", str(text or ""))
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return " ".join(html.unescape(t).replace("\xa0", " ").split())


def person_in(text):
    """True when a text names a person (PERSON_WORDS)."""
    return bool(PERSON_WORDS.search(str(text or "")))


def note(text, limit=NOTE):
    """A short, safe note: plain text, no e-mail address, nothing when it names a person, at most limit
    characters (features.clean_note)."""
    t = plain(text)
    if not t or person_in(t):
        return ""
    return features.clean_note(t, limit)


def store_name(name):
    """A store's or service's name made plain, or "" when it cannot be used: empty, an e-mail address in it, or a
    person's name (placepacks/contact.py PERSON_NAME: a person's details are never kept)."""
    t = plain(name).strip(" -|,")
    if not t or "@" in t or len(t) > 120:
        return ""
    if contacts.PERSON_NAME.match(t):
        return ""
    return t


def phone(value):
    """A phone number made plain (placepacks/contact.py phone: "302-555-0100"), or ""."""
    return contacts.phone(value) if value else ""


def website(value, base=""):
    """A website made plain (placepacks/contact.py website), relative addresses joined to base; "" for none."""
    if not value:
        return ""
    try:
        url = urllib.parse.urljoin(base, str(value).strip()) if base else str(value).strip()
    except ValueError:                  # a broken address ("http://[x")
        return ""
    return contacts.website(url)


def slug(text):
    """A key part from a name: lower case, letters and digits joined by "-"."""
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:60]


# ------------------------------------------------------------------------------------------------ hours

def hours_of_days(items, day="day", opens="open", closes="close"):
    """OSM opening hours from a list of {day, open, close} dicts (keys given by name; "day" may be a day's name or a
    number with 0 = Sunday), or "". A day marked closed (no times) is left out."""
    days = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        d = item.get(day)
        if isinstance(d, int) or (isinstance(d, str) and d.isdigit()):
            d = ("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")[int(d) % 7]
        else:
            d = oh.day_of(d)
        got = oh.span(item.get(opens), item.get(closes))
        if d and got:
            days.setdefault(d, []).append(got)
    return oh.week(days)


def hours_of_text_days(items, day="day", text="hours"):
    """OSM opening hours from [{day: "Monday", hours: "10:00AM - 9:00PM"}], or ""."""
    days = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        d = oh.day_of(item.get(day))
        pieces = re.split(r"\s*(?:-|–|\bto\b)\s*", str(item.get(text) or "").strip())
        got = oh.span(pieces[0], pieces[1]) if d and len(pieces) == 2 else None
        if got:
            days.setdefault(d, []).append(got)
    return oh.week(days)


# ------------------------------------------------------------------------------------------------ rows

def site_row(key, name, lat, lon, place_key="", website_url="", phone_number="", opening_hours="", notes="", org="",
             vendor=""):
    """The row of a site itself (a mall or an airport: kind "site"), or None without a position."""
    try:
        lat, lon = round(float(lat), 7), round(float(lon), 7)
    except (TypeError, ValueError):
        return None
    return {"key": key, "kind": "site", "site": key, "name": name, "site_name": name, "place_key": place_key or "",
            "lat": lat, "lon": lon, "website": website(website_url), "phone": phone(phone_number),
            "opening_hours": opening_hours or "", "notes": note(notes, 600), "org": org or name, "vendor": vendor}


def feature_row(site, key, kind, name, lat, lon, site_name="", level="", building="", notes="", phone_number="",
                website_url="", opening_hours="", category="", unit="", vendor="", map_id="", business=True):
    """One feature of a site (a store, a restaurant, a desk, a restroom ...), or None (no usable name for a store
    or restaurant, no position, an unknown kind). A store or restaurant with its own phone or own hours is marked
    as a business too (business "1"), unless business is False; its main_value and type come from its category."""
    from placepacks.directories.common import tags_of
    if kind not in features.KINDS or kind == "site":
        return None
    shown = store_name(name) if kind in ("store", "dining") else plain(name)
    if kind in ("store", "dining") and not shown:
        return None
    try:
        lat, lon = round(float(lat), 7), round(float(lon), 7)
    except (TypeError, ValueError):
        return None
    tel, hours = phone(phone_number), opening_hours or ""
    row = {"key": key, "kind": kind, "name": shown, "site": site, "site_name": site_name, "level": plain(level),
           "building": building or "", "lat": lat, "lon": lon, "notes": note(notes), "phone": tel,
           "website": website(website_url), "opening_hours": hours, "vendor": vendor, "map_id": map_id,
           "category": plain(category)[:200], "unit": plain(unit)[:40], "business": "", "main_value": "",
           "type": ""}
    if business and kind in ("store", "dining") and (tel or hours):
        parts = [c for c in re.split(r"\s*[,;/|]\s*", row["category"]) if c]
        tags = tags_of(*parts, shown) or ({"amenity": "restaurant"} if kind == "dining" else {"shop": "yes"})
        row.update(business="1", main_value=next(iter(tags.values())),
                   type=" ".join(row["category"].lower().split(",")[0].split())[:60] if row["category"] else "")
    return row


def where_note(site_name, level="", unit="", near="", extra=""):
    """The note of a store inside a site: "In Christiana Mall, level 2, suite 1455, near Macy's"."""
    bits = [f"In {site_name}" if site_name else ""]
    if level:
        bits.append(level if re.match(r"(?i)(level|floor|lower|upper|ground|mezz|terminal|concourse)", level)
                    else f"level {level}")
    if unit:
        bits.append(unit if re.match(r"(?i)(suite|unit|space|ste)", unit) else f"unit {unit}")
    if near:
        bits.append(f"near {near}")
    if extra:
        bits.append(extra)
    return ", ".join(b for b in bits if b)


# ------------------------------------------------------------------------------------------------ page shapes

def next_data(page):
    """The JSON of a Next.js page's __NEXT_DATA__ script, or {}."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except ValueError:
        return {}


def rsc_text(page):
    """The text of a Next.js app-router page's streamed data (its self.__next_f.push([1, "..."]) chunks joined),
    or ""."""
    out = []
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page or "", re.S):
        try:
            out.append(json.loads('"' + chunk + '"'))
        except ValueError:
            continue
    return "".join(out)


def rsc_refs(text):
    """The numbered parts of a streamed page ({"71": value}), for resolving "$71" references; parts that are not
    JSON are left out."""
    refs = {}
    for m in re.finditer(r'(?m)(?:^|\n)([0-9a-f]{1,4}):(?=[\[{"])', text):
        try:
            refs[m.group(1)] = json.JSONDecoder().raw_decode(text, m.end())[0]
        except ValueError:
            continue
    return refs


def objects_with(text, first_key):
    """Every JSON object in a text that starts with {"first_key": (read leniently, each once)."""
    out = []
    for m in re.finditer(r'\{"' + re.escape(first_key) + '":', text or ""):
        try:
            out.append(json.JSONDecoder().raw_decode(text, m.start())[0])
        except ValueError:
            continue
    return out


def js_assigned(page, name):
    """The JSON value assigned to a global in a page's script ("Fusion.contentCache=" {...}), or None."""
    i = (page or "").find(name + "=")
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(page, i + len(name) + 1)[0]
    except ValueError:
        return None


def heading_sections(page, levels="h2|h3|h4"):
    """A page's sections: [(heading text, the plain text after it up to the next heading)], for pages that list
    services or amenities under headings."""
    body = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)\b.*?</\1>", " ", page or "")
    parts = re.split(rf"(?is)<({levels})\b[^>]*>(.*?)</\1>", body)
    out = []
    for i in range(1, len(parts) - 2, 3):
        title = plain(parts[i + 1])
        if title:
            out.append((title, plain(parts[i + 2])[:1500]))
    return out


# What the visitor and accessibility pages of malls and airports say they offer: (kind, label, pattern). A
# sentence that matches gives one amenity feature of that kind, named by the label, with the sentence as its note
# (where it is: "Wheelchairs are available at Guest Services on Level 1 near Macy's").
AMENITIES = [
    ("accessibility service", "Wheelchairs", r"wheel ?chairs?\b(?![- ]accessib)[^.]{0,100}\b(available|loan|"
                                             r"loaned|borrow|rent|"
                                             r"rental|complimentary|free of charge|at no (cost|charge))"),
    ("accessibility service", "Mobility scooters", r"(electric|motori[sz]ed|mobility) scooters?|\bscooters?\b[^.]{0,60}"
                                                    r"\b(available|rent|rental|loan)"),
    ("accessibility service", "Wheelchair assistance", r"wheel ?chair (assistance|service|escort)|request (a )?"
                                                       r"wheel ?chair"),
    ("accessibility service", "TSA Cares", r"\btsa cares\b"),
    ("accessibility service", "Hidden Disabilities Sunflower", r"sunflower (lanyard|program|programme)|hidden "
                                                               r"disabilities sunflower"),
    ("accessibility service", "Sensory room", r"sensory (room|space|suite)|quiet room"),
    ("accessibility service", "Sign language interpreting", r"(american sign language|\basl\b)[^.]{0,60}"
                                                            r"(interpret|available|video)"),
    ("accessibility service", "Assistive listening", r"assistive listening|hearing loop|induction loop"),
    ("restroom", "Restrooms", r"(?<!family )(?<!accessible )\brestrooms?\b[^.?]{0,80}\b(located|are (by|near|in|on|"
                              r"at))"),
    ("family restroom", "Family restrooms", r"(family|companion[- ]care|all[- ]gender|unisex) (restroom|restrooms|"
                                            r"bathroom|bathrooms|toilet)"),
    ("accessible restroom", "Accessible restrooms", r"(accessible|ada|wheelchair[- ]accessible) (restroom|restrooms|"
                                                    r"bathroom|bathrooms|toilets?)"),
    ("accessible parking", "Accessible parking", r"(accessible|handicap\w*|disabled|ada|disability)\s+(parking|"
                                                 r"spaces|stalls)"),
    ("accessible entrance", "Accessible entrances", r"(accessible|wheelchair[- ]accessible|ada|automatic)\s+"
                                                    r"(entrance|entrances|doors?)"),
    ("pet relief area", "Service animal relief areas", r"(animal|pet|dog)s? relief|relief area"),
    ("service desk", "Guest services", r"guest services?|customer service (center|desk|booth)|concierge"),
    ("information desk", "Information desks", r"information (desk|desks|booth|booths|counter|center)"),
    ("restroom", "Nursing rooms", r"nursing (room|rooms|suite|pod|pods|station)|lactation|mamava"),
    ("service desk", "Security office", r"security (office|desk)"),
]
_AMENITIES = [(k, label, re.compile(p, re.I)) for k, label, p in AMENITIES]


def sentences(text):
    """A text cut into sentences (at ". ", "! ", "? ", bullets and spaced dashes), each without a heading in
    capitals before it ("AMENITIES Are wheelchairs ..." -> "Are wheelchairs ...")."""
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\s+[•·|]\s+|\s+[–—]\s+", text or ""):
        s = re.sub(r"^(?:(?:[A-Z][A-Z'/-]{3,}|&|[A-Z]{2,3}\s+[A-Z]{2,})\s+)+(?=[A-Z][a-z])", "", s.strip())
        if s:
            out.append(s)
    return out


def amenities_of(texts):
    """The amenities pages' texts say there are: [(kind, label, note)], each label once (its first sentence), in
    AMENITIES order. A question ("Are wheelchairs available to rent?", the FAQ pages of many malls) is read with
    its answer: an answer that starts with "No" means the amenity is NOT there (left out); otherwise the note is
    the answer ("Yes, wheelchairs are available ... at the public safety office near JCPenney"). A sentence naming
    a person is not used."""
    found, refused = {}, set()
    for text in texts:
        parts = sentences(text)
        for i, s in enumerate(parts):
            if len(s) > 600 or person_in(s):
                continue
            answer = parts[i + 1] if s.endswith("?") and i + 1 < len(parts) else ""
            for kind, label, rx in _AMENITIES:
                if label in found or label in refused or not rx.search(s):
                    continue
                if answer and re.match(r"(?i)no\b", answer):
                    refused.add(label)
                    continue
                found[label] = (kind, label, answer if answer and not person_in(answer) else s)
    return [found[label] for _, label, _ in AMENITIES if label in found]


def amenity_rows(site, site_name, lat, lon, found, prefix):
    """Amenity features (feature_row) of a site from amenities_of: at the site's position (the page gives no
    other), named by the amenity's label, the sentence as the note."""
    rows = []
    for kind, label, sentence in found:
        row = feature_row(site, f"{prefix}:{slug(label)}", kind, label, lat, lon, site_name=site_name,
                          notes=sentence, business=False)
        if row:
            rows.append(row)
    return rows


def link_score(text, href, words):
    """The best score of a link's text and address among [(pattern, score)], or 0."""
    joined = f"{plain(text)} {urllib.parse.urlsplit(href).path}"
    return max((s for rx, s in words if rx.search(joined)), default=0)


_A = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def own_links(page, base, words, limit):
    """A site's own pages worth reading, best first: [(url, score)] (at most limit), from the page's links whose
    text or address matches words; never a data: address, a file (PDF, picture, document) or another site's page."""
    from placepacks.mapvendors import registry
    from placepacks.mapvendors.discover import same_site
    scored = {}
    for m in _A.finditer(page or ""):
        raw = html.unescape(m.group(1).strip())
        if raw.startswith(("data:", "mailto:", "tel:", "javascript:")):
            continue
        href = registry.join(base, raw)          # "" for a broken link ("http://[x")
        if not href.startswith("http") or not same_site(href, base) or re.search(r"\.(pdf|jpe?g|png|gif|docx?|xlsx?)"
                                                                                 r"($|\?)", href, re.I):
            continue
        score = link_score(m.group(2), href, words)
        if score:
            scored[href] = max(score, scored.get(href, 0))
    return sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))[:limit]
