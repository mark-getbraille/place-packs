"""Amtrak station accessibility (queue item Q4, notes/helper-rules.txt), from Great American Stations
(greatamericanstations.com), Amtrak's public station-information site: for each station the accessibility list
("Accessible platform", "Accessible restrooms", "Accessible ticket office", "Accessible waiting room", "High
platform", "Wheelchair available", "No wheelchair lift"), the station building's features (elevator, restrooms,
ticket office), and the hours of the waiting room, the ticket office and passenger assistance (when someone is
there to help).

amtrak.com itself answers 403 to programs (checked 27 November 2026; never got round), so its station pages are not
read. Great American Stations' robots.txt allows reading station pages and asks for 10 seconds between requests
(Crawl-delay: 10), which is obeyed: about 530 stations, one page each, once a month (about an hour and a half).
The station's position comes from the Bureau of Transportation Statistics' Amtrak station layer (the source
ntad-amtrak, public domain; one or two requests), by its three-letter code.

Kept: only the listed facts and the hours (never the page's other text, the regional contact's name or e-mail, the
history or the ridership). Each station becomes one "site" row tied to the station already in the pack (place_key
"ntad-amtrak:<code>"): its note "Accessibility (Amtrak station information): accessible platform; accessible
restrooms; high platform; wheelchair available; no wheelchair lift; elevator; ticket office Mo-Su 05:00-23:30;
passenger assistance Mo-Su 05:30-23:30" and the waiting room's hours as its opening hours; and features at the
station's position for an elevator, accessible restrooms, a wheelchair or a wheelchair lift (kinds "elevator",
"accessible restroom", "accessibility service").
Only the Python standard library is used.
"""

import re
import urllib.parse

from placepacks import features
from placepacks.chains.polite import NotFound, RequestFailed

SITE = "https://www.greatamericanstations.com"
SITEMAP = SITE + "/stations-sitemap.xml"
NTAD = ("https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Amtrak_Stations/FeatureServer/0/"
        "query")
AGENT = "place-packs-street-access"
# The accessibility list's lines kept (lower case -> the note's words). Any other line is left out.
ACCESS_WORDS = {
    "accessible platform": "accessible platform", "accessible restrooms": "accessible restrooms",
    "accessible ticket office": "accessible ticket office", "accessible waiting room": "accessible waiting room",
    "accessible water fountain": "accessible water fountain", "high platform": "high platform",
    "low platform": "low platform", "wheelchair available": "wheelchair available",
    "wheelchair lift available": "wheelchair lift", "wheelchair lift": "wheelchair lift",
    "no wheelchair lift": "no wheelchair lift", "no wheelchair available": "no wheelchair",
    "accessible parking": "accessible parking", "tty available": "TTY",
}
HOURS_TABLES = (("stationHours", "waiting room"), ("ticketHours", "ticket office"),
                ("meetAndAssistHours", "passenger assistance"))
_LI = re.compile(r"<li>(.*?)</li>", re.S | re.I)


def _plain(html):
    """Text of an HTML snippet: tags out, entities of the common kinds turned back, spaces made single."""
    t = re.sub(r"<[^>]+>", " ", html or "")
    t = t.replace("&amp;", "&").replace("&#8217;", "'").replace("&#8211;", "-").replace("&nbsp;", " ")
    return " ".join(t.split())


def section(page, title):
    """The list items of the accordion section whose heading is title ("Accessibility", "Features"), as text."""
    m = re.search(r"</i>\s*" + re.escape(title) + r"\s*</a>\s*</h3>\s*<div[^>]*>(.*?)</div>", page or "", re.S | re.I)
    return [_plain(li) for li in _LI.findall(m.group(1))] if m else []


def _clock(text):
    """"05:30 am" -> "05:30", "11:59 pm" -> "24:00" (the end of the day), "12:00 am" -> "00:00"; "" if unreadable."""
    m = re.match(r"^(\d{1,2}):(\d\d)\s*(am|pm)$", text.strip(), re.I)
    if not m:
        return ""
    h, mins, half = int(m.group(1)) % 12, int(m.group(2)), m.group(3).lower()
    h += 12 if half == "pm" else 0
    if (h, mins) == (23, 59):
        return "24:00"
    return f"{h:02d}:{mins:02d}"


def day_hours(text):
    """OpenStreetMap hours of one day's cell: "05:00 am - 11:30 pm" -> "05:00-23:30"; several ranges joined by
    commas ("00:00-01:00,04:00-24:00"); "CLOSED" -> "off"; "" when a range cannot be read."""
    text = " ".join(text.split())
    if re.fullmatch(r"closed\.?", text, re.I):
        return "off"
    ranges = re.findall(r"(\d{1,2}:\d\d\s*[ap]m)\s*-\s*(\d{1,2}:\d\d\s*[ap]m)", text, re.I)
    out = []
    for a, b in ranges:
        start, end = _clock(a), _clock(b)
        if not start or not end:
            return ""
        out.append(f"{start}-{end}")
    if out and out[0] == "00:00-24:00" and len(out) == 1:
        return "00:00-24:00"
    return ",".join(out)


def hours_table(page, table_id):
    """OpenStreetMap hours of one of the page's hours tables ("stationHours"): "Mo-Su 05:00-23:30", "off" when it
    is closed every day, or "" (no table, a day that cannot be read)."""
    from placepacks import hours as oh
    from placepacks.directories.city_facilities import oh_day
    m = re.search(r'id="' + re.escape(table_id) + r'"[^>]*>(.*?)</table>', page or "", re.S | re.I)
    if not m:
        return ""
    days = {}
    for day, text in re.findall(r"<tr>\s*<td>\s*(\w+)\s*</td>\s*<td>(.*?)</td>\s*</tr>", m.group(1), re.S | re.I):
        d = oh_day(day)
        got = day_hours(_plain(text.replace("<br/>", " ").replace("<br>", " ")))
        if d and not got:
            return ""
        if d:
            days[d] = got
    if days and all(v == "off" for v in days.values()):
        return "off"
    return oh.weekly(days) if days else ""


def station_code(url):
    """The three-letter code at the end of a station page's address (".../providence-ri-pvd/" -> "PVD"), or ""."""
    m = re.search(r"-([a-z]{3})/?$", urllib.parse.urlsplit(url).path, re.I)
    return m.group(1).upper() if m else ""


def parse_station(page, code, where, url=""):
    """The rows of one station page: [site row, feature rows]; [] when the station's position is not known.
    where: {code: (lat, lon, city)} from the BTS layer; url: the page's address (the station's website)."""
    if code not in where:
        return []
    lat, lon, city = where[code]
    access = [ACCESS_WORDS[t.lower()] for t in section(page, "Accessibility") if t.lower() in ACCESS_WORDS]
    feats = [t.lower() for t in section(page, "Features")]
    has_elevator = any(t.startswith("elevator") for t in feats)
    facts = list(dict.fromkeys(access + (["elevator"] if has_elevator else [])))
    hours = {label: hours_table(page, tid) for tid, label in HOURS_TABLES}
    bits = facts + [f"{label} closed" if h == "off" else f"{label} {h}" for label, h in hours.items()
                    if h and label != "waiting room"]
    if hours.get("waiting room") == "off":
        hours["waiting room"] = ""
    if not bits and not hours.get("waiting room"):
        return []
    key = f"amtrak-station:{code}"
    name = f"{city} Amtrak station" if city else f"Amtrak station {code}"
    note = "Accessibility (Amtrak station information): " + "; ".join(bits) if bits else ""
    rows = [{"key": key, "kind": "site", "site": key, "name": name, "site_name": name,
             "place_key": f"ntad-amtrak:{code}", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
             "notes": features.clean_note(note, 500), "opening_hours": hours.get("waiting room", ""),
             "website": url, "org": "Amtrak", "vendor": "great-american-stations"}]
    for fact, kind, label in (("elevator", "elevator", "Elevator"),
                              ("accessible restrooms", "accessible restroom", "Accessible restrooms"),
                              ("wheelchair available", "accessibility service", "Wheelchair available"),
                              ("wheelchair lift", "accessibility service", "Wheelchair lift")):
        if fact in facts:
            rows.append({"key": f"{key}:{kind.replace(' ', '-')}:{label.lower().replace(' ', '-')}", "kind": kind,
                         "name": label, "site": key, "site_name": name, "place_key": f"ntad-amtrak:{code}",
                         "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "notes": f"At the {name}",
                         "org": "Amtrak", "vendor": "great-american-stations"})
    return rows


def ntad_positions(client):
    """{code: (lat, lon, city)} of Amtrak's train stations from the BTS layer (two pages of 1,000 at most)."""
    out, offset = {}, 0
    while offset < 4000:
        url = NTAD + "?" + urllib.parse.urlencode(
            {"where": "StnType = 'TRAIN'", "outFields": "Code,City", "returnGeometry": "true", "outSR": 4326,
             "resultOffset": offset, "resultRecordCount": 1000, "f": "json"})
        answer = client.json(url)
        feats = answer.get("features") or []
        for f in feats:
            a, g = f.get("attributes") or {}, f.get("geometry") or {}
            try:
                out[str(a.get("Code", "")).upper()] = (float(g["y"]), float(g["x"]), (a.get("City") or "").strip())
            except (KeyError, TypeError, ValueError):
                continue
        if len(feats) < 1000:
            break
        offset += 1000
    return out


def collect(client, unit, stats, limit=None):
    """Every station page of the sitemap (limit: the first few, for a test run). robots.txt is read first; its
    Crawl-delay is obeyed (the client's pause is raised to it). A refusal (Blocked) stops the unit."""
    from placepacks.directories.common import Robots
    robots = Robots(client, SITE, agent=AGENT)
    delay = robots.crawl_delay() or 10
    client.pause = max(client.pause, float(delay))
    where = ntad_positions(client)
    urls = re.findall(r"<loc>([^<]+)</loc>", client.fetch(SITEMAP))
    urls = [u for u in urls if "/stations/" in u and robots.allowed(u)][:limit]
    stats.update(pages=len(urls), stations=0, not_found=0, no_position=0, may_be_empty=False)
    for url in urls:
        code = station_code(url)
        if code not in where:
            stats["no_position"] += 1
            continue
        try:
            page = client.fetch(url)
        except (NotFound, RequestFailed):
            stats["not_found"] += 1
            continue
        rows = parse_station(page, code, where, url)
        if rows:
            stats["stations"] += 1
            yield from rows

