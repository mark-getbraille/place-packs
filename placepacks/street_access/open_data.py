"""Accessible pedestrian signals and curb ramps from US cities', counties' and state transportation departments'
open data (queue item Q4 of the owner's list of 27 November 2026, notes/helper-rules.txt). Found AUTOMATICALLY each
month, like the city facilities (placepacks/directories/city_facilities.py, whose catalogue helpers are reused), so
every government that publishes such a layer is covered, not a fixed list.

What is an accessible pedestrian signal (APS)? A crosswalk signal that tells a blind pedestrian when the walk phase
is on: a sound or a spoken message, a vibrating arrow on the push button, often a "locator tone" that ticks so the
button can be found. New York City's DOT publishes about 4,500 of them with their installation dates; Charlotte,
Seattle, Atlanta, New Orleans, Ann Arbor, Utah's DOT and others publish theirs.

1. Discovery (discover(): the workflow's plan job, once a month, a few hundred requests):
   - the Socrata catalogue and ArcGIS Hub's search are asked for every word of APS_KEYWORDS and RAMP_KEYWORDS;
   - a candidate is kept when its title names signals or curb ramps (kind_of_title) and nothing of EXCLUDE_TITLE
     (plans, requests, crash data, statistics, "missing curb ramps" ...), or when it is a traffic-signal layer with
     a field that says whether each signal is accessible (an "APS" column: only its "yes" rows are read);
   - its publisher is a government (government(): a city, county, town, a state or city transportation or public
     works department, a regional planning body; never a university, a company, a consultant's or a person's own
     account) and a US one (one record is read: its position must be in a US state);
   - it has point positions and no people fields (a staff list is never read);
   - its fields are mapped automatically (map_fields: the intersection's name or its two streets, the install
     date, the status, locator tone, vibrotactile arrow, push button, the APS flag; for curb ramps the condition,
     ADA compliance, detectable warning surface and the year built);
   - the result is street-access-layers.json, stored in the release "street-access" as layers-street-access.json
     beside the month's set, so what was picked is on record.
2. Collection (collect(), units "signals" and "curb-ramps-1".."-N"): each layer through its own API (ArcGIS REST
   with resultOffset paging; Socrata SODA with $limit/$offset), asking ONLY for the mapped fields (free-text
   comments, inspectors' and requesters' names, e-mails are never asked for). A name with a person's name added
   ("N TRYON ST_OLD CONCORD RD- Alice Example") loses it (clean_name). Rows the layer marks as planned, pending,
   removed or not accessible are left out. A layer that refuses (403, an anti-bot page) is recorded as blocked and
   left; the unit goes on.

The rows are the street-access CSV (placepacks/street_access FIELDS: the site features columns plus installed,
tags, layer, publisher): kind "accessible pedestrian signal" or "curb ramp", the intersection's name, the
position, a short note ("installed 2023-12-16; locator tone; vibrating arrow button") and the facts as JSON tags
for the navigation part ({"installed": "2023-12-16", "locator_tone": "yes", "vibration": "yes"}).
In the packs: the signals become site features of the extra part (source "street-access": downloaded by default,
so `features_near(lat, lon, "accessible pedestrian signal")` answers without the navigation part) AND features of
the navigation part (source "street-access-navigation": crossing_here says "the city lists an accessible pedestrian
signal here, installed ..."); the curb ramps, being very many (a big city lists 100,000 or more), go only to the
navigation part, which is downloaded on request.
Only the Python standard library is used.
"""

import datetime
import functools
import json
import os
import re
import urllib.parse

from placepacks.chains.polite import Blocked, NotFound, RequestFailed
from placepacks.directories import city_facilities as cf

USER_AGENT = "place-packs-street-access/1 (+https://github.com/mark-getbraille/place-packs)"
LIST_FILE = "street-access-layers.json"
RELEASE_LIST = "layers-street-access.json"
APS = "accessible pedestrian signal"
RAMP = "curb ramp"
RAMP_SHARDS = 4
PAGE = 1000
CATALOG_PAGES = 3
# The most records read from one layer: an APS layer is a few thousand at most (New York City about 4,500); a big
# city's curb ramp inventory can be 200,000 (a layer larger than that is something else, such as every sidewalk
# panel).
MAX_RECORDS = {APS: 30000, RAMP: 250000}
APS_KEYWORDS = ["accessible pedestrian signal", "accessible pedestrian signals", "audible pedestrian signal",
                "audible signal", "APS signal", "pedestrian push button", "accessible signal"]
RAMP_KEYWORDS = ["curb ramp", "curb ramps", "curb ramp inventory", "pedestrian ramp", "ADA ramp", "curb cut"]
TITLE_APS = re.compile(r"accessible (pedestrian )?signal|audible (pedestrian )?signal|\baps\b|accessible ped|"
                       r"pedestrian push ?button|ped(estrian)? (signal )?push ?button|signal button", re.I)
TITLE_RAMP = re.compile(r"curb[ _-]?ramp|kerb[ _-]?ramp|curb[ _-]?cut|pedestrian[ _-]ramp|ada[ _-]ramp|"
                        r"\bramps?\b.*(inventory|ada)|ada.*\bramps?\b", re.I)
TITLE_SIGNALS = re.compile(r"traffic[ _-]?signal|signali[sz]ed intersection|pedestrian signal", re.I)
EXCLUDE_TITLE = re.compile(r"plan(ned)?\b|proposed|future|request|candidate|priorit|eval|analysis|study|crash|"
                           r"collision|maintenance|work ?order|inspection report|survey|statistic|accumulat|built or|"
                           r"improved|count|budget|cost|missing|\bno[ _-]curb|needed|needs|deficien|project|"
                           r"permit|complaint|311|sample|test|training|demo|copy|backup|archive|historic", re.I)
GOV_WORDS = re.compile(r"\bstate of\b|department of transportation|\bdept\.? of transportation|\bdot\b|"
                       r"transportation (cabinet|department|agency)|public works|commonwealth|metropolitan planning|"
                       r"\bmpo\b|\btpo\b|council of governments|regional (planning|commission|council)|uplan", re.I)
# Federal research portals and dashboards: statistics, not places.
NOT_PORTAL = re.compile(r"(^|\.)(datahub\.transportation\.gov|performance\.[a-z.]+|.*\.edu)$", re.I)

FIELD_PATTERNS = {
    "name": [r"^(location|intersection|intersect|int_?name|intersection_?name|int_?desc|loc_?desc|location_?desc|"
             r"descriptio|description|unitdesc|site_?name|name|address|location_?name|crossing)$"],
    "street1": [r"^(street_?1|st_?1|first_?intersect\w*|primary_?st\w*|on_?street|main_?st\w*|firstroad|"
                r"street_?a|road_?1|onst\w*|from_?street)$"],
    "street2": [r"^(street_?2|st_?2|second_?intersect\w*|cross_?st\w*|secondroad|street_?b|road_?2|at_?street|"
                r"atst\w*|xstreet\w*)$"],
    "installed": [r"^(date_?insta\w*|install\w*_?date|date_?install\w*|instdate|inst_?date|installed|"
                  r"year_?install\w*|yearinstalled|install_?year|installation\w*|year_?built|yr_?built|"
                  r"constructi\w*|const_?year|year)$"],
    "status": [r"^(status|current_?status|aps_?status|condition_?status|lifecycle\w*|active)$"],
    "aps": [r"^(aps|has_?aps|aps_?yn|aps_?present|accessible_?pedestrian_?signal\w*|audible_?signal|audible|"
            r"aps_?installed|accessible_?signal)$"],
    "aps_type": [r"^(aps_?type|aps_?det\w*|device_?type|locationtype|location_?type|aps_?model)$"],
    "locator": [r"locator"],
    "vibration": [r"vibro|vibrat|tactile_?arrow"],
    "button": [r"^(push_?button\w*|pedbuttons|ped_?button\w*|ped_?pb|pushbutton)$"],
    "speech": [r"^(?!.*request)(.*speech.*|.*voice.*|.*verbal.*|.*spoken.*)$"],
    "condition": [r"^(condition|cond|overall_?condition|ramp_?condition|rating|condition_?rating)$"],
    "compliant": [r"^(ada_?compliant|compliant|compliance|ada_?compliance|meets_?ada|ada_?status|ada)$"],
    "warning": [r"^(detectable_?warning\w*|dws\w*|dw_?present|truncated_?dome\w*|domes|tactile\w*|"
                r"detect_?warn\w*)$"],
    "ramp_type": [r"^(ramp_?type|type|curb_?ramp_?type|ramp_?style)$"],
}
# Never mapped: people, free text, internal bookkeeping (a person's name, a comment, an editor's account).
NEVER_FIELD = re.compile(r"fax|e_?mail|phone|manager|inspector|requester|requestor|contact|owner_?name|first_?name|"
                         r"last_?name|comment|remark|notes?$|created|edited|_user$|user_|globalid_?\d|shape|"
                         r"gmaps|http|url|photo|image", re.I)
ID_FIELD = re.compile(r"^(globalid|global_?id|facilityid|facility_?id|unitid|unit_?id|compkey|ramp_?id|aps_?id|"
                      r"sig_?id|objectid|object_?id|fid)$", re.I)
YES = re.compile(r"^(y|yes|true|t|1|present|existing|exists|installed|active|in ?service|insvc|complete|"
                 r"completed|audible|vibrotactile|both)$", re.I)
NO = re.compile(r"^(n|no|false|f|0|none|absent|missing|not present|n/a|na)$", re.I)
# The crossing types some layers give, in plain words.
TYPE_WORDS = {"rrfb": "at a crossing with flashing beacons (RRFB)", "phb": "at a pedestrian hybrid beacon (HAWK)",
              "hawk": "at a pedestrian hybrid beacon (HAWK)", "signal": "at a traffic signal",
              "traffic signal": "at a traffic signal", "audible": "audible", "audible ": "audible",
              "vibrotactile": "vibrating arrow button"}
NOT_THERE = re.compile(r"plann|pending|propos|future|design|removed|abandon|inactive|retired|demolish|"
                       r"out of service|not installed|request|candidate|programmed|funded", re.I)


# ------------------------------------------------------------------------------------------------ small helpers

def us_state(lat, lon):
    """The two-letter code of the US state a position is in, or "" (outside the US). Unlike a box test, a position
    in Toronto is not in New York and one in Portland, Oregon not in Washington (placepacks.regions.regions_for,
    which knows the borders). Worked out once per square of about a kilometre (a big layer has 200,000 records)."""
    return _us_state(round(float(lat), 2), round(float(lon), 2))


@functools.lru_cache(maxsize=200000)
def _us_state(lat, lon):
    """us_state of a rounded position."""
    from placepacks import catalogue
    from placepacks.regions import parent_of, regions_for
    try:
        found = [r for r in regions_for(lat, lon) if r.startswith("us-")]
    except (TypeError, ValueError):
        return ""
    if not found:
        return ""
    rid = parent_of(found[0]) or found[0]
    return (catalogue.regions().get(rid) or {}).get("code", "") or cf.state_of(lat, lon)


def map_fields(names):
    """{what: the layer's field} from its field names, by FIELD_PATTERNS (the first pattern that matches a field
    not yet used; never a field of NEVER_FIELD); "id": its own record id."""
    out, used = {}, set()
    for what, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            rx = re.compile(pattern, re.I)
            hit = next((n for n in names if n not in used and rx.search(n) and not NEVER_FIELD.search(n)), None)
            if hit:
                out[what] = hit
                used.add(hit)
                break
    ident = sorted((n for n in names if ID_FIELD.match(n)),
                   key=lambda n: (not n.lower().startswith(("global", "facility", "unit", "comp", "ramp", "aps")), n))
    if ident:
        out["id"] = ident[0]
    return out


def kind_of_title(title, fields=None):
    """The kind a layer holds by its title ("accessible pedestrian signal" or "curb ramp"), or "" when it is
    neither or is a plan, a request list or a statistic (EXCLUDE_TITLE). A traffic-signal layer counts as signals
    only when its fields have an APS flag (fields: map_fields' result)."""
    title = " ".join(str(title or "").replace("_", " ").split())
    if not title or EXCLUDE_TITLE.search(title):
        return ""
    if TITLE_APS.search(title):
        return APS
    if TITLE_RAMP.search(title):
        return RAMP
    if TITLE_SIGNALS.search(title) and fields and fields.get("aps"):
        return APS
    return ""


def government(publisher):
    """True when a publisher's name is a US government's: a city, county, town ... (as the city facilities), or a
    state or city transportation or public works department, a regional planning body. Never a university, a
    company, a consultant or a person's own account (an e-mail address, a bare user name)."""
    publisher = " ".join(str(publisher or "").split())
    if not publisher or "@" in publisher or cf.NOT_GOV.search(publisher):
        return False
    return bool(cf.GOV_PUBLISHER.search(publisher) or GOV_WORDS.search(publisher))


def yes_no(value):
    """"yes", "no", or the value's own short words (lower case), or "" for nothing."""
    text = " ".join(str(value if value is not None else "").split())
    if not text:
        return ""
    if YES.match(text):
        return "yes"
    if NO.match(text):
        return "no"
    return text.lower()[:40]


def date_text(value, ftype=""):
    """A date as "YYYY-MM-DD" (or "YYYY" for a year alone), from an ArcGIS date (milliseconds since 1970), a
    Socrata date ("2023-12-16T00:00:00.000"), "12/16/2023" or a year; "" when it is not a plausible date."""
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) and (ftype == "esriFieldTypeDate" or abs(value) > 10 ** 10):
        try:
            d = datetime.datetime.fromtimestamp(value / 1000, datetime.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return ""
        return d.isoformat() if 1950 <= d.year <= 2100 else ""
    text = str(value).strip()
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if 1950 <= int(m.group(1)) <= 2100 else ""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if 1950 <= int(m.group(3)) <= 2100 else ""
    m = re.match(r"^(\d{4})(\.0)?$", text)
    if m and 1950 <= int(m.group(1)) <= 2100:
        return m.group(1)
    return ""


def _title_case(text):
    """"2ND AVE AND BROAD ST" -> "2nd Ave and Broad St" (only for a name written all in capitals)."""
    if not text.replace("_", " ").isupper():
        return text

    def word(m):
        """One word in title case ("and", "at", "of" and "4TH" in lower case)."""
        low = m.group(0).lower()
        return low if low in ("and", "at", "of") or low[0].isdigit() else low.capitalize()
    return re.sub(r"[A-Za-z0-9']+", word, text)


def clean_name(text):
    """An intersection's name made plain: a part that is a person's name is taken out ("N TRYON ST_OLD CONCORD RD-
    Alice Example" -> "N Tryon St and Old Concord Rd"), "_" and "/" and "&" between two streets become "and",
    capitals become title case. "" when nothing is left. (The New York City names, "Courtlandt Avenue and East 150
    Street", stay as they are.)"""
    from placepacks.person import PERSON
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r"\s*-\s+|\s+-\s*", text) if p.strip()]
    # Only an ADDED part can be a person's name: "Grant Street" alone is a street, even though Grant is a first name.
    parts = parts[:1] + [p for p in parts[1:] if not PERSON.match(p) and not PERSON.match(p.title())]
    text = _title_case(" - ".join(parts))
    if text.count("_") == 1:
        text = text.replace("_", " and ")
    if " and " not in text.lower():                     # "Park Avenue East S/R and East 179 Street" keeps its "/"
        text = re.sub(r"\s*[/&]\s*", " and ", text)
    text = " ".join(text.split())
    return text.strip(" -,;")


def street_name(values):
    """The intersection's name of a record: its name field, else "street1 and street2", else ""."""
    name = clean_name(values.get("name", ""))
    if not name:
        a, b = clean_name(values.get("street1", "")), clean_name(values.get("street2", ""))
        name = f"{a} and {b}" if a and b else a or b
    return name


def present(values, kind):
    """False when a record says the thing is not there yet or any more: an APS flag that is "no", a status of
    planned, pending, removed ... (NOT_THERE)."""
    status = " ".join(str(values.get("status", "")).split())
    if status and NOT_THERE.search(status):
        return False
    flag = values.get("aps", "")
    if kind == APS and flag != "" and flag is not None:
        word = yes_no(flag)
        if word == "no" or (word not in ("yes",) and NOT_THERE.search(word)):
            return False
        if word not in ("yes",) and not re.search(r"audib|vibr|tactil|speech|voice|accessib|aps|pushbutton|push",
                                                  word):
            return False
    return True


def make_row(layer, kind, ref, values, lat, lon, dates=None):
    """One record as a street-access row (placepacks/street_access FIELDS), or None (no position, outside the US,
    not there). values: {what: raw value} by map_fields' names; dates: {what: ArcGIS field type} for the date
    fields."""
    if lat is None or lon is None or not us_state(lat, lon) or not present(values, kind):
        return None
    tags, bits = {}, []
    installed = date_text(values.get("installed"), (dates or {}).get("installed", ""))
    if installed:
        tags["installed"] = installed
        bits.append(("installed " if kind == APS else "built ") + installed)
    if kind == APS:
        for what, label, word in (("locator", "locator_tone", "locator tone"),
                                  ("vibration", "vibration", "vibrating arrow button"),
                                  ("button", "button", "push button"), ("speech", "speech", "speech message")):
            v = yes_no(values.get(what))
            if v:
                tags[label] = v
                if v == "yes":
                    bits.append(word)
                elif v == "no":
                    bits.append("no " + word)
        t = " ".join(cf._text(values.get("aps_type")).split()).lower()
        if t and not NOT_THERE.search(t):
            tags["type"] = t[:40]
            bits.append(TYPE_WORDS.get(t, "type: " + t[:40]))
    else:
        for what, label, word in (("compliant", "compliant", "ADA compliant"),
                                  ("warning", "detectable_warning", "detectable warning surface")):
            v = yes_no(values.get(what))
            if v:
                tags[label] = v
                bits.append(f"{word}: {v}")
        c = yes_no(values.get("condition"))
        if c and c not in ("yes", "no"):
            tags["condition"] = c
            bits.append("condition: " + c)
        t = " ".join(cf._text(values.get("ramp_type")).split())
        if t:
            tags["type"] = t.lower()[:40]
    status = " ".join(cf._text(values.get("status")).split()).lower()
    if status and kind == APS:
        tags["status"] = status[:30]
    who = layer.get("publisher", "")
    tags["source"] = who[:80]
    note = (("Accessible pedestrian signal" if kind == APS else "Curb ramp") + (f" ({who})" if who else "")
            + ("; " + "; ".join(bits) if bits else ""))
    return {"key": f"{layer['id']}:{ref}", "kind": kind, "name": street_name(values), "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}", "notes": note[:400], "installed": installed,
            "tags": json.dumps(tags, ensure_ascii=False, separators=(",", ":")), "layer": layer["id"],
            "publisher": who, "vendor": "open-data"}


# ------------------------------------------------------------------------------------------------ discovery

def socrata_candidates(client, keywords, pages=CATALOG_PAGES):
    """The Socrata datasets the catalogue finds for the keywords whose title gives a kind (kind_of_title), on a
    US government portal, with point positions and no people fields: [layer dict] without "state" yet."""
    found = {}
    for word in keywords:
        for page in range(pages):
            url = cf.SOCRATA_CATALOG + "?" + urllib.parse.urlencode(
                {"q": word, "only": "dataset", "limit": 100, "offset": 100 * page})
            results = cf._json(client, url).get("results") or []
            for r in results:
                res, meta = r.get("resource") or {}, r.get("metadata") or {}
                domain, dataset = meta.get("domain", ""), res.get("id", "")
                if not domain or not dataset or cf.NOT_US_DOMAIN.search(domain) or NOT_PORTAL.search(domain):
                    continue
                names = [n for n in res.get("columns_field_name") or [] if not n.startswith(":")]
                types = [str(t).lower() for t in res.get("columns_datatype") or []]
                all_names = res.get("columns_field_name") or []
                if cf.people_layer(names):
                    continue
                geo = next((n for n, t in zip(all_names, types) if t == "point"), "") or \
                    next((n for n, t in zip(all_names, types) if t == "location"), "")
                fields = map_fields([n for n in names if n != geo])
                kind = kind_of_title(res.get("name"), fields)
                lat = next((n for n in names if re.fullmatch(r"lat(itude)?|y|point_?y", n, re.I)), "")
                lon = next((n for n in names if re.fullmatch(r"lon(g|gitude)?|x|point_?x", n, re.I)), "")
                if not kind or not (geo or (lat and lon)):
                    continue
                if geo:
                    fields["point"] = geo
                else:
                    fields["lat"], fields["lon"] = lat, lon
                lid = cf.layer_id("socrata", f"{domain}/{dataset}")
                found.setdefault(lid, {"id": lid, "platform": "socrata", "domain": domain, "dataset": dataset,
                                       "title": res.get("name", ""), "publisher": domain, "kind": kind,
                                       "licence": meta.get("license", ""), "fields": fields,
                                       "url": f"https://{domain}/d/{dataset}"})
            if len(results) < 100:
                break
    return list(found.values())


def hub_candidates(client, keywords, pages=CATALOG_PAGES):
    """The ArcGIS Hub feature layers the search finds for the keywords whose publisher is a government (the title
    is checked again with the fields by arcgis_check): [layer dict] without fields or state yet."""
    found = {}
    for word in keywords:
        for page in range(pages):
            url = cf.HUB_SEARCH + "?" + urllib.parse.urlencode({"q": word, "limit": 100, "startindex": 1 + 100 * page})
            features = cf._json(client, url).get("features") or []
            for f in features:
                p = f.get("properties") or {}
                if p.get("type") != "Feature Service" or not p.get("url") or p.get("access") not in (None, "public"):
                    continue
                publisher = p.get("source") or p.get("orgName") or ""
                title = p.get("title") or ""
                if not government(publisher) or EXCLUDE_TITLE.search(title) or not (
                        TITLE_APS.search(title) or TITLE_RAMP.search(title) or TITLE_SIGNALS.search(title)):
                    continue
                layer = cf._layer_url(p["url"])
                lid = cf.layer_id("arcgis", layer)
                found.setdefault(lid, {"id": lid, "platform": "arcgis", "url": layer, "title": title,
                                       "publisher": " ".join(publisher.split()),
                                       "licence": p.get("licenseInfo") or p.get("license") or ""})
            if len(features) < 100:
                break
    return list(found.values())


def arcgis_check(client, layer):
    """One request to an ArcGIS layer (its first record and fields, in longitude/latitude): adds "fields", "dates"
    (the date fields' types), "kind" and "state", or None when the layer is not usable (not points, people
    fields, no kind, outside the US, an error)."""
    url = layer["url"] + "/query?" + urllib.parse.urlencode(
        {"where": "1=1", "outFields": "*", "resultRecordCount": 1, "returnGeometry": "true", "outSR": 4326,
         "f": "json"})
    answer = cf._json(client, url)
    if answer.get("geometryType") not in ("esriGeometryPoint", "esriGeometryMultipoint"):
        return None
    info = answer.get("fields") or []
    names = [f.get("name", "") for f in info]
    if cf.people_layer(names):
        return None
    fields = map_fields(names)
    kind = kind_of_title(layer.get("title"), fields)
    if not kind:
        return None
    types = {f.get("name"): f.get("type", "") for f in info}
    feats = answer.get("features") or []
    geom = (feats[0].get("geometry") or {}) if feats else {}
    if "points" in geom and geom["points"]:
        geom = {"x": geom["points"][0][0], "y": geom["points"][0][1]}
    try:
        state = us_state(float(geom["y"]), float(geom["x"]))
    except (KeyError, TypeError, ValueError):
        return None
    if not state:
        return None
    dates = {what: types.get(field, "") for what, field in fields.items() if what == "installed"}
    return {**layer, "fields": fields, "dates": dates, "kind": kind, "state": state}


def socrata_check(client, layer):
    """One request to a Socrata dataset (its first record): adds "state", or None (no position, outside the US)."""
    f = layer["fields"]
    cols = [f["point"]] if f.get("point") else [f["lat"], f["lon"]]
    url = f"https://{layer['domain']}/resource/{layer['dataset']}.json?" + urllib.parse.urlencode(
        {"$select": ",".join(cols), "$limit": 1, "$where": " AND ".join(f"{c} IS NOT NULL" for c in cols)})
    try:
        rows = json.loads(client.fetch(url))
    except (ValueError, NotFound, RequestFailed):
        return None
    at = cf.socrata_position(rows[0], f) if isinstance(rows, list) and rows else None
    state = us_state(*at) if at else ""
    return {**layer, "state": state} if state else None


def discover(client, keywords=None, pages=CATALOG_PAGES, log=print):
    """The month's layer list: [{"id", "platform", "url", "title", "publisher", "licence", "kind", "fields",
    "dates", "state", and "domain"/"dataset" for Socrata}], sorted by kind, state and id."""
    keywords = keywords or (APS_KEYWORDS + RAMP_KEYWORDS)
    candidates = socrata_candidates(client, keywords, pages) + hub_candidates(client, keywords, pages)
    log(f"street-access: {len(candidates)} candidate layers")
    out, seen = [], set()
    for layer in candidates:
        if layer["id"] in seen:
            continue
        seen.add(layer["id"])
        try:
            checked = socrata_check(client, layer) if layer["platform"] == "socrata" else arcgis_check(client, layer)
        except Blocked as e:
            log(f"  blocked {layer['id']}: {e}")
            continue
        if checked:
            out.append(checked)
    out.sort(key=lambda l: (l["kind"], l["state"], l["id"]))
    log(f"street-access: {sum(l['kind'] == APS for l in out)} signal layers, "
        f"{sum(l['kind'] == RAMP for l in out)} curb ramp layers")
    return out


def write_list(layers, path):
    """Write the layer list (JSON) through a .partial file."""
    with open(path + ".partial", "w", encoding="utf-8") as f:
        json.dump({"layers": layers}, f, indent=1, sort_keys=True)
    os.replace(path + ".partial", path)


def read_list(client=None, path=None):
    """The layer list: the file the plan job wrote (path, else $STREET_ACCESS_LIST), else discovered now (a unit
    run on its own)."""
    path = path or os.environ.get("STREET_ACCESS_LIST") or ""
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("layers") or []
    if client is None:
        return []
    return discover(client)


# ------------------------------------------------------------------------------------------------ collection

def arcgis_records(client, layer, limit):
    """(ref, values, lat, lon) of an ArcGIS layer's records: pages of PAGE (resultOffset), only the mapped
    fields asked for. More than limit records: cf.TooBig (nothing of the layer is kept)."""
    f = layer["fields"]
    wanted = list(dict.fromkeys(v for k, v in f.items() if k not in ("point", "lat", "lon")))
    offset = 0
    while offset <= limit:
        url = layer["url"] + "/query?" + urllib.parse.urlencode(
            {"where": "1=1", "outFields": ",".join(wanted) or "*", "returnGeometry": "true", "outSR": 4326,
             "resultOffset": offset, "resultRecordCount": PAGE, "orderByFields": f.get("id", ""), "f": "json"})
        answer = json.loads(client.fetch(url))
        if not isinstance(answer, dict) or "error" in answer:
            raise RequestFailed(f"the layer answered an error: {str(answer.get('error'))[:120]}")
        feats = answer.get("features") or []
        for i, feat in enumerate(feats):
            attrs, geom = feat.get("attributes") or {}, feat.get("geometry") or {}
            if "points" in geom and geom["points"]:
                geom = {"x": geom["points"][0][0], "y": geom["points"][0][1]}
            values = {k: attrs.get(v) for k, v in f.items() if k != "id"}
            ref = cf._text(attrs.get(f.get("id"))) if f.get("id") else str(offset + i)
            try:
                lat, lon = float(geom["y"]), float(geom["x"])
            except (KeyError, TypeError, ValueError):
                lat = lon = None
            yield ref, values, lat, lon
        if len(feats) < PAGE and not answer.get("exceededTransferLimit"):
            return
        if not feats:
            return
        offset += len(feats)
    raise cf.TooBig(f"more than {limit} records")


def socrata_records(client, layer, limit):
    """(ref, values, lat, lon) of a Socrata dataset's records: pages of PAGE ($limit/$offset), only the mapped
    fields asked for."""
    f = layer["fields"]
    cols = list(dict.fromkeys([":id"] + [v for k, v in f.items() if k != "id"]))
    offset = 0
    while offset <= limit:
        url = f"https://{layer['domain']}/resource/{layer['dataset']}.json?" + urllib.parse.urlencode(
            {"$select": ",".join(cols), "$limit": PAGE, "$offset": offset, "$order": ":id"})
        records = json.loads(client.fetch(url))
        if not isinstance(records, list):
            raise RequestFailed("the dataset did not answer a list of records")
        for rec in records:
            values = {k: rec.get(v) for k, v in f.items() if k not in ("id", "point", "lat", "lon")}
            at = cf.socrata_position(rec, f)
            yield cf._text(rec.get(":id")), values, *(at or (None, None))
        if len(records) < PAGE:
            return
        offset += PAGE
    raise cf.TooBig(f"more than {limit} records")


def layer_rows(client, layer, stats):
    """The rows of one layer (all of it, or an exception and none of it)."""
    kind = layer["kind"]
    reader = socrata_records if layer["platform"] == "socrata" else arcgis_records
    rows = []
    for ref, values, lat, lon in reader(client, layer, MAX_RECORDS[kind]):
        values = {k: (v if isinstance(v, (int, float)) and k == "installed" else cf._text(v))
                  for k, v in values.items()}
        row = make_row(layer, kind, ref, values, lat, lon, layer.get("dates"))
        if row:
            rows.append(row)
        else:
            stats["left_out"] = stats.get("left_out", 0) + 1
    return rows


def units_for(unit, layers):
    """The layers a unit reads: "signals" every APS layer; "curb-ramps-2" every RAMP_SHARDS-th curb ramp layer
    from the second."""
    if unit == "signals":
        return [l for l in layers if l.get("kind") == APS]
    index = int(unit.rsplit("-", 1)[1]) - 1
    ramps = [l for l in layers if l.get("kind") == RAMP]
    return [l for i, l in enumerate(ramps) if i % RAMP_SHARDS == index]


def collect(client, unit, stats):
    """Yield the rows of one unit's layers. A layer that refuses or fails is recorded in stats ("blocked",
    "failed") and left; the others go on."""
    layers = units_for(unit, read_list(client))
    stats.update(layers=len(layers), left_out=0, blocked=[], failed=[], read=[], may_be_empty=True)
    seen = set()
    for layer in layers:
        try:
            rows = layer_rows(client, layer, stats)
        except Blocked as e:
            stats["blocked"].append(f"{layer['id']}: {str(e)[:120]}")
            continue
        except (NotFound, RequestFailed, ValueError) as e:
            stats["failed"].append(f"{layer['id']}: {str(e)[:120]}")
            continue
        stats["read"].append(f"{layer['id']}: {len(rows)}")
        for row in rows:
            if row["key"] not in seen:
                seen.add(row["key"])
                yield row


def main(argv=None):
    """python -m placepacks.street_access.open_data discover --out street-access-layers.json: the month's layer
    list (the workflow's plan job)."""
    import argparse
    from placepacks.chains.polite import Polite
    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("action", choices=["discover"])
    p.add_argument("--out", default=LIST_FILE)
    p.add_argument("--budget", type=int, default=2500)
    a = p.parse_args(argv)
    client = Polite(a.budget, cf.PAUSE, agent=USER_AGENT)
    layers = discover(client)
    write_list(layers, a.out)
    print(f"{len(layers)} layers written to {a.out} ({client.used} requests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
