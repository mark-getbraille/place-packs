"""Cities' and counties' own lists of public places: city halls, libraries, community, recreation and senior
centers, pools, police and fire stations and other municipal buildings, from their open-data portals (the source
"city-facilities"; the monthly city-facilities workflow). Found and read AUTOMATICALLY, so every US city or county
that publishes such a layer is covered, not a fixed list.

The owner's decisions: government data may be used regardless of its licence (26 November 2026); cover ALL US
cities and towns that publish facilities data, with a monthly discovery step and a manual override list (27
November 2026). Staff and people directories are never read.

1. Discovery (discover(): the workflow's "discover" job, once a month, a few hundred requests to two catalogues and
   one small request per candidate layer):
   - the Socrata catalogue (api.us.socrata.com/api/catalog/v1) and ArcGIS Hub's search (hub.arcgis.com/api/search/
     v1), each asked for every word of KEYWORDS (facilities, community centers, libraries, city hall ...);
   - a candidate is kept only when (good_title) its title names public places and nothing of EXCLUDE_TITLE
     (inspections, energy use, permits, 311 requests, budgets, staff, employees ...); its publisher is a US
     government (Socrata: a US portal; ArcGIS: an organisation named as a city, town, village, county, borough,
     township, parish or municipal government, never a university or a person's own account); it has a name
     field and point positions; and it has no people fields (first or last names, job titles) -- a staff directory;
   - its fields are mapped automatically (map_fields: NAME / FACILITY / FAC_NAME -> name, ADDRESS, CITY, ZIP,
     PHONE, HOURS, TYPE, WEBSITE ...), and one record is read to find its state and to check it lies in the US;
   - OVERRIDES (placepacks/data/city_facilities_overrides.json, kept by hand) adds layers, skips layers, and fixes
     field mappings;
   - the result, the layer list, is a JSON file (city-facilities-layers.json) that the collect jobs read and the
     publish job stores in the release "city-facilities" (as layers-city-facilities.json) beside the month's set,
     so what was picked is on record; when discovery fails, the workflow uses last month's list from there.
2. Collection (collect(): one matrix job per state): every layer of the state, read through its own API (ArcGIS
   REST query with resultOffset paging, at most MAX_RECORDS records; Socrata SODA with $limit/$offset), asking ONLY
   for the mapped fields (a layer's other columns, such as a manager's name or an e-mail, are never requested).
   Each record becomes one row: the name; the kind of place (kind_of: from the type field, else the name), as
   OpenStreetMap-style tags; the position; the public phone number, website and opening hours (hours that read as
   OpenStreetMap syntax, or that placepacks/hours.py can turn into it; other hours text becomes the note); the street
   address. A layer that refuses (403, an anti-bot page) is recorded as blocked and left; the state's job goes on.
In the packs (extra part): a public place of its own (class "public", or "park"/"landmark" for parks, pools and
museums), with its phone, website and opening hours (placepacks/contact.py treats "city-facilities" as a
government source).
Only the Python standard library is used.
"""

import json
import os
import re
import urllib.parse

from placepacks.chains.polite import Blocked, NotFound, RequestFailed

FIELDS = ["key", "name", "main_key", "main_value", "type", "lat", "lon", "first", "last", "phone", "website",
          "opening_hours", "street", "city", "state", "postcode", "note", "layer", "publisher"]
USER_AGENT = "place-packs-city-facilities/1 (+https://github.com/mark-getbraille/place-packs)"
PAUSE = 1.5                     # seconds between two requests to one host
MAX_RECORDS = 5000              # a "facilities" layer with more records is something else (address points ...)
PAGE = 1000
LIST_FILE = "city-facilities-layers.json"
RELEASE_LIST = "layers-city-facilities.json"   # the list's name in the release (not a dated set's name)
OVERRIDES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                         "city_facilities_overrides.json")
SOCRATA_CATALOG = "https://api.us.socrata.com/api/catalog/v1"
HUB_SEARCH = "https://hub.arcgis.com/api/search/v1/collections/dataset/items"
KEYWORDS = ["facilities", "city facilities", "public facilities", "municipal facilities", "points of interest",
            "community centers", "recreation centers", "libraries", "city hall", "municipal buildings",
            "parks facilities", "senior centers", "public buildings", "government buildings"]
CATALOG_PAGES = 5               # pages of 100 results read per keyword and catalogue at most
# A title that names public places ...
GOOD_TITLE = re.compile(r"facilit|points? of interest|\bpoi\b|community cent|recreation|\brec\b|librar|city hall|"
                        r"town hall|village hall|municipal|civic|senior|public (building|place|site)|"
                        r"government (building|location|office)|county (building|office)|cultural cent|"
                        r"neighbou?rhood cent|aquatic|\bpools?\b|fire stations?|police stations?|landmarks?", re.I)
# ... and nothing of these (measurements, permits, requests, people, plans).
EXCLUDE_TITLE = re.compile(r"inspection|energy|utility|consumption|usage|\buse\b|emission|permit|licen[cs]|"
                           r"request|311|budget|expend|cost|payroll|salar|staff|employee|personnel|contact list|"
                           r"violation|complaint|incident|crime|arrest|census|discharge|cleanliness|survey|"
                           r"proposed|planned|future|capital project|historic(al)? data|footprint|parcel|zoning|"
                           r"storage tank|waste|sewer|water main|hydrant|cooling|warming|shelter|polling|voting|"
                           r"nursing|child ?care|daycare|hospital|health facilit|clinic|school|universit|college|"
                           r"assessment|condition|maintenance|work order|lease|insurance|risk|evacuation|"
                           r"\bcare\b|x-?ray|acute|assisted|treatment|correction|jail|prison|mobile home|radiation|"
                           r"laborator|dental|pharmac|medical|licensed|regulated|solid waste|wastewater", re.I)
# Publishers that are US local governments (ArcGIS organisation names) ...
GOV_PUBLISHER = re.compile(r"\b(city|town|village|county|borough|township|parish|municipal|municipality|"
                           r"metro(politan)? government|consolidated government|unified government)\b", re.I)
# ... and never these.
NOT_GOV = re.compile(r"universit|college|school|student|academy|institute|esri|\bgis lab|class|course|"
                     r"chamber of commerce|foundation|united way|\binc\b|llc|company", re.I)
# Socrata portals outside the US (the US catalogue lists a few), and portals that are not a city's or a county's:
# state portals ("data.ny.gov", "health.data.ny.gov", "data.texas.gov"), federal agencies' and universities'
# (their facility lists are licences, inspections and statistics, read elsewhere if at all).
NOT_US_DOMAIN = re.compile(r"\.(ca|uk|au|nz|mx|ie|fr|de|nl|es|it|br|in)$", re.I)
STATES_WORDS = (r"[a-z]{2}|alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|"
                r"hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|"
                r"michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|newhampshire|newjersey|newmexico|"
                r"newyork|northcarolina|northdakota|ohio|oklahoma|oregon|pennsylvania|rhodeisland|southcarolina|"
                r"southdakota|tennessee|texas|utah|vermont|virginia|washington|westvirginia|wisconsin|wyoming")
NOT_LOCAL_DOMAIN = re.compile(r"^(?:[a-z-]+\.)?(?:data|opendata|datahub)\.(?:" + STATES_WORDS +
                              r")\.gov$|\.(?:cdc|hhs|transportation|cms|medicaid|usda|energy|nasa|ed|va|census|"
                              r"epa|nih|fda|dol|doi|hud|treasury|commerce|state)\.gov$|\.edu$", re.I)
# Fields that show a layer lists people: such a layer is a staff directory and is never read.
# (An e-mail field alone does not: many facility layers give the building's own address; it is never requested.)
PEOPLE_FIELD = re.compile(r"^(first_?name|last_?name|fname|lname|given_?name|surname|middle_?name|"
                          r"employee\w*|staff\w*|title_?position|job_?title|position_?title)$", re.I)

# Field names -> what they hold, the first matching pattern of each list wins (map_fields).
FIELD_PATTERNS = {
    "name": [r"^(name|facility|facility_?name|fac_?name|facname|site_?name|location_?name|loc_?name|place_?name|"
             r"common_?name|building_?name|bldg_?name|center_?name|park_?name|library|library_?name|label|"
             r"facility_?nm|name1|full_?name|feat_?name|poi_?name|title)$",
             r"(^|_)name($|_)"],
    "address": [r"^(address|addr|full_?address|fulladdr|street_?address|site_?address|location_?address|"
                r"address1|address_?1|add1|st_?address|street|location_?1|physical_?address|situs_?address)$",
                r"address"],
    "city": [r"^(city|municipality|town|post_?city|city_?name|mail_?city|addr_?city|community)$"],
    "zip": [r"^(zip|zip_?code|zipcode|zip5|postal|postal_?code|postcode|addr_?zip)$"],
    "phone": [r"^(phone|phone_?number|phone_?num|phonenumber|telephone|tel|main_?phone|phone1|phone_?1|"
              r"office_?phone|public_?phone|phone_?no|contact_?phone)$", r"phone"],
    "hours": [r"^(hours|hours_?of_?operation|operating_?hours|open_?hours|hours_?open|hrs|business_?hours|"
              r"schedule|opening_?hours)$", r"hours"],
    "type": [r"^(type|facility_?type|fac_?type|factype|category|facility_?category|use_?type|building_?type|"
             r"bldg_?type|subtype|sub_?type|feat_?type|feature_?type|site_?type|place_?type|class|"
             r"facility_?class|facility_?group|use|department|dept)$", r"type$"],
    "website": [r"^(website|url|web|web_?site|weburl|web_?url|link|webpage|web_?page|homepage|more_?info|"
                r"website_?url|info_?url)$", r"(website|url)$"],
}
# Fields of one weekday's hours ("HOURS_MONDAY", "MON_HOURS", "Tuesday"): read together as a week (week_hours).
DAY_FIELD = re.compile(r"(^|_)(mon|tue|wed|thu|fri|sat|sun)[a-z]*($|_)", re.I)
# A mapped field is never one of these (a person's details, an internal code).
NEVER_FIELD = re.compile(r"fax|cell|mobile|e_?mail|manager|director|supervisor|contact_?name|owner|"
                         r"first_?name|last_?name|user|created|edited|globalid_?\d|shape|objectid|street_?name$|"
                         r"street_?type|street_?dir|street_?num|house|st_?num|_id$", re.I)
ID_FIELD = re.compile(r"^(globalid|global_?id|facility_?id|facilityid|fac_?id|site_?id|poi_?id|objectid|fid|"
                      r"object_?id)$", re.I)

# The kinds of place, from the type field or the name (kind_of): the first that matches gives the tags.
KINDS = [
    (r"\blibrar", {"amenity": "library"}),
    (r"senior|older adult|aging", {"amenity": "social_centre", "social_facility:for": "senior"}),
    (r"community cent|neighbou?rhood cent|recreation cent|\brec(reation)? cent|civic cent|community house|"
     r"community building|activity cent|teen cent|youth cent", {"amenity": "community_centre"}),
    (r"city hall|town hall|village hall|municipal (building|center|complex|offices?)|government cent|"
     r"county (building|courthouse|administration|office)|civic (building|offices?)|borough hall",
     {"amenity": "townhall"}),
    (r"court ?house|\bcourts?\b", {"amenity": "courthouse"}),
    (r"police", {"amenity": "police"}),
    (r"fire (station|house|dept|department)|\bfire\b", {"amenity": "fire_station"}),
    (r"\bpools?\b|aquatic|natatorium|splash pad|spray ?ground", {"leisure": "swimming_pool"}),
    (r"museum|historic (site|house)", {"tourism": "museum"}),
    (r"cultural cent|arts? cent|theat(er|re)|performing arts|auditorium|amphithea", {"amenity": "arts_centre"}),
    (r"golf", {"leisure": "golf_course"}),
    (r"ice rink|skating rink|ice arena", {"leisure": "ice_rink"}),
    (r"gym|fitness", {"leisure": "fitness_centre"}),
    (r"stadium|sports complex|athletic (complex|field)|ball ?field|ballpark", {"leisure": "sports_centre"}),
    (r"nature cent|visitor cent|interpretive", {"tourism": "information"}),
    (r"\bparks?\b|playground|garden|plaza|greenway", {"leisure": "park"}),
    (r"post office", {"amenity": "post_office"}),
    (r"recycl|transfer station|drop.?off", {"amenity": "recycling"}),
    (r"animal shelter|animal services", {"amenity": "animal_shelter"}),
    (r"marina|boat (launch|ramp)", {"leisure": "slipway"}),
    (r"cemetery", {"landuse": "cemetery"}),
    (r"parking (garage|lot|deck)", {"amenity": "parking"}),
]
_KINDS = [(re.compile(p, re.I), t) for p, t in KINDS]


# ------------------------------------------------------------------------------------------------ mapping

def map_fields(names):
    """{"name", "address", "city", "zip", "phone", "hours", "type", "website", "id": the layer's field for each}
    from its field names, by FIELD_PATTERNS (exact names first, then looser ones; never a field of NEVER_FIELD
    and never one field for two things). Fields not found are left out. "id" is the record's own id."""
    out, used = {}, set()
    for what, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            rx = re.compile(pattern, re.I)
            hit = next((n for n in names if n not in used and rx.search(n) and not NEVER_FIELD.search(n)
                        and not (what != "name" and n == out.get("name"))), None)
            if hit:
                out[what] = hit
                used.add(hit)
                break
    days = {}
    for n in names:
        m = DAY_FIELD.search(n)
        if m and (re.search(r"hour|hrs|open|time", n, re.I) or re.fullmatch(r"[a-z]+day", n, re.I)) \
                and not re.search(r"close|end", n, re.I):
            days.setdefault(oh_day(m.group(2)), n)
    if len(days) >= 5:
        out["days"] = days
        if out.get("hours") in days.values():
            del out["hours"]                            # "HOURS_SUNDAY" is one day, not the week
    ident = sorted((n for n in names if ID_FIELD.match(n)), key=lambda n: (not n.lower().startswith(("global",
                                                                                                   "fac", "site")), n))
    if ident:
        out["id"] = ident[0]
    return out


def oh_day(word):
    """OpenStreetMap's two letters of a day's name or its start ("monday", "Tue" -> "Mo", "Tu")."""
    from placepacks.hours import DAY_WORDS
    return DAY_WORDS.get(word.lower()[:3], DAY_WORDS.get(word.lower(), ""))


def week_hours(values):
    """OpenStreetMap hours from one text per day ({"Mo": "9:00 AM - 5:00 PM", "Sa": "Closed", ...}); "" when a
    day's text cannot be read (no wrong time is ever written)."""
    from placepacks import hours as oh
    days = {}
    for day, text in values.items():
        text = " ".join(str(text or "").split())
        if not text:
            continue
        if re.fullmatch(r"closed\.?", text, re.I):
            days[day] = "off"
            continue
        got = oh.from_text(text)
        if not got or " " in got:                       # one time range only
            return ""
        days[day] = "00:00-24:00" if got == "24/7" else got
    return oh.weekly(days)


def people_layer(names):
    """True when a layer's fields show it lists people (a staff directory): never read."""
    return any(PEOPLE_FIELD.match(n) for n in names)


def good_title(title):
    """True when a dataset's title names public places and nothing of EXCLUDE_TITLE."""
    title = " ".join(str(title or "").replace("_", " ").split())
    return bool(GOOD_TITLE.search(title)) and not EXCLUDE_TITLE.search(title)


def government(publisher):
    """True when an ArcGIS organisation's name is a US local government's ("City of Seattle", "Harris County")."""
    publisher = " ".join(str(publisher or "").split())
    return bool(GOV_PUBLISHER.search(publisher)) and not NOT_GOV.search(publisher) and "@" not in publisher


def kind_of(type_text, name, title=""):
    """The OpenStreetMap-style tags of a place, from its type field, else its name, else its layer's title
    ("Senior Centers") ({} when none tells)."""
    for text in (type_text, name, title):
        for pattern, tags in _KINDS:
            if text and pattern.search(str(text)):
                return dict(tags)
    return {}


def state_of(lat, lon):
    """The two-letter code of the US state whose box holds a position (the smallest box when several do), or ""
    (outside the US). Only used to choose which state's job reads a layer; the pack build places each record by
    its own position."""
    from placepacks import catalogue
    best = None
    for r in catalogue.regions().values():
        if r.get("cc") != "US" or r.get("parent") or not r.get("code") or not r.get("bbox"):
            continue
        w, s, e, n = r["bbox"]
        if w <= lon <= e and s <= lat <= n:
            area = (e - w) * (n - s)
            if best is None or area < best[0]:
                best = (area, r["code"])
    return best[1] if best else ""


def layer_id(platform, where):
    """A short stable id of a layer: its platform and a cleaned form of its address (Socrata: domain and dataset;
    ArcGIS: the layer's URL)."""
    text = re.sub(r"^https?://", "", where.lower())
    text = re.sub(r"/arcgis/rest/services/|/rest/services/|featureserver|mapserver", "/", text)
    return platform + ":" + re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:120]


# ------------------------------------------------------------------------------------------------ discovery

def _json(client, url):
    """The JSON answer of url (a dict), or {} when it is not JSON or is an error."""
    try:
        value = json.loads(client.fetch(url))
    except (ValueError, NotFound, RequestFailed):
        return {}
    return value if isinstance(value, dict) and "error" not in value else {}


def socrata_candidates(client, keywords=KEYWORDS, pages=CATALOG_PAGES):
    """The Socrata datasets the catalogue finds for the keywords that pass good_title, a US portal, a name field,
    point positions and no people fields: [layer dict] (see discover) without "state" yet."""
    found = {}
    for word in keywords:
        for page in range(pages):
            url = SOCRATA_CATALOG + "?" + urllib.parse.urlencode(
                {"q": word, "only": "dataset", "limit": 100, "offset": 100 * page})
            results = _json(client, url).get("results") or []
            for r in results:
                res, meta = r.get("resource") or {}, r.get("metadata") or {}
                domain, dataset = meta.get("domain", ""), res.get("id", "")
                if not domain or not dataset or NOT_US_DOMAIN.search(domain) or NOT_LOCAL_DOMAIN.search(domain) \
                        or not good_title(res.get("name")):
                    continue
                names = res.get("columns_field_name") or []
                types = [str(t).lower() for t in res.get("columns_datatype") or []]
                if people_layer(names):
                    continue
                geo = next((n for n, t in zip(names, types) if t == "point"), "") or \
                    next((n for n, t in zip(names, types) if t == "location"), "")
                fields = map_fields([n for n in names if not n.startswith(":") and n != geo])
                lat = next((n for n in names if re.fullmatch(r"lat(itude)?|y", n, re.I)), "")
                lon = next((n for n in names if re.fullmatch(r"lon(g|gitude)?|x", n, re.I)), "")
                if "name" not in fields or not (geo or (lat and lon)):
                    continue
                if geo:
                    fields["point"] = geo
                else:
                    fields["lat"], fields["lon"] = lat, lon
                lid = layer_id("socrata", f"{domain}/{dataset}")
                found.setdefault(lid, {"id": lid, "platform": "socrata", "domain": domain, "dataset": dataset,
                                       "title": res.get("name", ""), "publisher": domain,
                                       "licence": meta.get("license", ""), "fields": fields,
                                       "url": f"https://{domain}/d/{dataset}"})
            if len(results) < 100:
                break
    return list(found.values())


def _layer_url(url):
    """An ArcGIS item's URL as a layer's (a service's root gets "/0")."""
    url = url.rstrip("/")
    return url + "/0" if re.search(r"/(FeatureServer|MapServer)$", url, re.I) else url


def hub_candidates(client, keywords=KEYWORDS, pages=CATALOG_PAGES):
    """The ArcGIS Hub feature layers the search finds for the keywords whose title passes good_title and whose
    publisher is a US local government: [layer dict] without fields or state yet (arcgis_check adds them)."""
    found = {}
    for word in keywords:
        for page in range(pages):
            url = HUB_SEARCH + "?" + urllib.parse.urlencode({"q": word, "limit": 100, "startindex": 1 + 100 * page})
            features = _json(client, url).get("features") or []
            for f in features:
                p = f.get("properties") or {}
                if p.get("type") != "Feature Service" or not p.get("url") or p.get("access") not in (None, "public"):
                    continue
                publisher = p.get("source") or p.get("orgName") or ""
                if not good_title(p.get("title")) or not government(publisher):
                    continue
                layer = _layer_url(p["url"])
                lid = layer_id("arcgis", layer)
                found.setdefault(lid, {"id": lid, "platform": "arcgis", "url": layer, "title": p.get("title", ""),
                                       "publisher": " ".join(publisher.split()),
                                       "licence": p.get("licenseInfo") or p.get("license") or ""})
            if len(features) < 100:
                break
    return list(found.values())


def arcgis_check(client, layer):
    """One request to an ArcGIS layer (its first record, with its fields, in longitude/latitude): adds "fields"
    (map_fields) and "state", or returns None when the layer is not usable (not points, no name field, people
    fields, outside the US, an error)."""
    url = layer["url"] + "/query?" + urllib.parse.urlencode(
        {"where": "1=1", "outFields": "*", "resultRecordCount": 1, "returnGeometry": "true", "outSR": 4326,
         "f": "json"})
    answer = _json(client, url)
    if answer.get("geometryType") not in ("esriGeometryPoint", "esriGeometryMultipoint"):
        return None
    names = [f.get("name", "") for f in answer.get("fields") or []]
    if people_layer(names):
        return None
    fields = map_fields(names)
    feats = answer.get("features") or []
    geom = (feats[0].get("geometry") or {}) if feats else {}
    if "points" in geom and geom["points"]:
        geom = {"x": geom["points"][0][0], "y": geom["points"][0][1]}
    try:
        state = state_of(float(geom["y"]), float(geom["x"]))
    except (KeyError, TypeError, ValueError):
        return None
    if "name" not in fields or not state:
        return None
    return {**layer, "fields": fields, "state": state}


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
    if not isinstance(rows, list) or not rows:
        return None
    at = socrata_position(rows[0], f)
    state = state_of(*at) if at else ""
    return {**layer, "state": state} if state else None


def load_overrides(path=OVERRIDES):
    """The manual override list: {"add": [layer dicts], "skip": {layer id or address part: why}, "fields": {layer
    id: {what: field}}}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    return {"add": data.get("add") or [], "skip": data.get("skip") or {}, "fields": data.get("fields") or {}}


def skipped(layer, skip):
    """The reason a layer is skipped by the override list (by its id, or a part of its address), or ""."""
    where = layer.get("url", "") + " " + layer.get("id", "")
    for key, why in skip.items():
        if key == layer.get("id") or key in where:
            return str(why) or "skipped by the override list"
    return ""


def discover(client, overrides=None, keywords=KEYWORDS, pages=CATALOG_PAGES, log=print):
    """The month's layer list (see the module docstring): [{"id", "platform", "url", "title", "publisher",
    "licence", "fields", "state", and "domain"/"dataset" for Socrata}], sorted by state and id. A catalogue that
    refuses (Blocked) stops discovery: the workflow then keeps last month's list."""
    overrides = overrides if overrides is not None else load_overrides()
    out, seen = [], set()
    candidates = socrata_candidates(client, keywords, pages) + hub_candidates(client, keywords, pages)
    for layer in overrides["add"]:
        layer = dict(layer)
        layer.setdefault("id", layer_id(layer.get("platform", "arcgis"), layer.get("url") or
                                        f"{layer.get('domain')}/{layer.get('dataset')}"))
        candidates.append(layer)
    log(f"city-facilities: {len(candidates)} candidate layers")
    for layer in candidates:
        if layer["id"] in seen:
            continue
        seen.add(layer["id"])
        why = skipped(layer, overrides["skip"])
        if why:
            log(f"  skip {layer['id']}: {why}")
            continue
        try:
            if layer.get("state") and layer.get("fields"):
                checked = layer                              # an added layer with everything given
            elif layer["platform"] == "socrata":
                checked = socrata_check(client, layer)
            else:
                checked = arcgis_check(client, layer)
        except Blocked as e:
            log(f"  blocked {layer['id']}: {e}")
            continue
        if checked:
            checked["fields"] = {**checked["fields"], **overrides["fields"].get(checked["id"], {})}
            out.append(checked)
    out.sort(key=lambda l: (l["state"], l["id"]))
    log(f"city-facilities: {len(out)} layers kept in {len({l['state'] for l in out})} states")
    return out


def write_list(layers, path):
    """Write the layer list (JSON) through a .partial file."""
    with open(path + ".partial", "w", encoding="utf-8") as f:
        json.dump({"layers": layers}, f, indent=1, sort_keys=True)
    os.replace(path + ".partial", path)


def read_list(path=None):
    """The layer list written by discover (path, else $CITY_FACILITIES_LIST, else LIST_FILE)."""
    path = path or os.environ.get("CITY_FACILITIES_LIST") or LIST_FILE
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("layers") or []


# ------------------------------------------------------------------------------------------------ collection

class TooBig(RequestFailed):
    """A layer has more than MAX_RECORDS records: it is not a list of public places (address points, a city-wide
    asset inventory), so none of it is kept."""


def socrata_position(record, fields):
    """(lat, lon) of a Socrata record (its point or location column, or its latitude and longitude), or None."""
    try:
        if fields.get("point"):
            value = record.get(fields["point"]) or {}
            if isinstance(value, str):
                value = json.loads(value)
            if value.get("coordinates"):
                lon, lat = value["coordinates"][:2]
            else:
                lat, lon = value.get("latitude"), value.get("longitude")
        else:
            lat, lon = record.get(fields["lat"]), record.get(fields["lon"])
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError, AttributeError, KeyError):
        return None
    return (lat, lon) if (lat or lon) else None


def _text(value):
    """A field's value as plain one-line text ("" for none)."""
    if value is None:
        return ""
    if isinstance(value, dict):                       # a Socrata URL column {"url": ...} or location column
        if value.get("human_address"):
            try:
                value = json.loads(value["human_address"]).get("address") or ""
            except (ValueError, AttributeError):
                value = ""
        else:
            value = value.get("url") or ""
    return " ".join(str(value).split())


def make(layer, ref, values, lat, lon):
    """One record as a row (FIELDS), or None (no name, no position or one outside the US). values: {what: text}
    by map_fields' names."""
    from placepacks import hours as oh
    from placepacks.contact import hours as osm_hours
    from placepacks.readers.osm import main_tag
    from placepacks import types as place_types
    name = values.get("name", "")
    if not name or not ref or lat is None or lon is None or not state_of(lat, lon):
        return None
    tags = kind_of(values.get("type", ""), name, layer.get("title", "")) or {"amenity": "public_building"}
    found = main_tag({k: str(v) for k, v in tags.items()})
    hours_text = values.get("hours", "")
    hours = oh.from_text(hours_text) if hours_text else ""
    if not hours_text and values.get("days"):
        hours = week_hours(values["days"])
        hours_text = "" if hours else "; ".join(f"{d} {t}" for d, t in values["days"].items() if t)
    if hours_text and not hours and re.match(r"^(Mo|Tu|We|Th|Fr|Sa|Su|24/7)", hours_text):
        hours = osm_hours(hours_text)                  # already in OpenStreetMap's syntax
    note = f"Hours: {hours_text[:200]}" if hours_text and not hours else ""
    kind = place_types.osm({k: str(v) for k, v in tags.items()}) or " ".join(values.get("type", "").lower().split())
    return {"key": f"{layer['id']}:{ref}", "name": name, "main_key": found[0] if found else "",
            "main_value": found[1] if found else "", "type": kind, "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
            "first": "", "last": "", "phone": values.get("phone", "")[:100],
            "website": values.get("website", "") if values.get("website", "").startswith("http") else "",
            "opening_hours": hours, "street": values.get("address", ""), "city": values.get("city", ""),
            "state": state_of(lat, lon), "postcode": values.get("zip", ""), "note": note, "layer": layer["id"],
            "publisher": layer.get("publisher", "")}


def arcgis_rows(client, layer, stats):
    """The rows of an ArcGIS layer: pages of PAGE records (resultOffset), only the mapped fields asked for."""
    f = layer["fields"]
    wanted = [v for k, v in f.items() if k not in ("point", "lat", "lon", "days")] + list((f.get("days") or {}).values())
    offset, count = 0, 0
    while offset < MAX_RECORDS:
        url = layer["url"] + "/query?" + urllib.parse.urlencode(
            {"where": "1=1", "outFields": ",".join(dict.fromkeys(wanted)), "returnGeometry": "true", "outSR": 4326,
             "resultOffset": offset, "resultRecordCount": PAGE, "orderByFields": f.get("id", ""), "f": "json"})
        answer = json.loads(client.fetch(url))
        if not isinstance(answer, dict) or "error" in answer:
            raise RequestFailed(f"the layer answered an error: {str(answer.get('error'))[:120]}")
        feats = answer.get("features") or []
        for i, feat in enumerate(feats):
            attrs, geom = feat.get("attributes") or {}, feat.get("geometry") or {}
            if "points" in geom and geom["points"]:
                geom = {"x": geom["points"][0][0], "y": geom["points"][0][1]}
            values = {k: _text(attrs.get(v)) for k, v in f.items() if k not in ("id", "days")}
            values["days"] = {d: _text(attrs.get(v)) for d, v in (f.get("days") or {}).items()}
            ref = _text(attrs.get(f.get("id"))) if f.get("id") else str(offset + i)
            try:
                lat, lon = float(geom["y"]), float(geom["x"])
            except (KeyError, TypeError, ValueError):
                lat = lon = None
            row = make(layer, ref, values, lat, lon)
            if row:
                count += 1
                yield row
            else:
                stats["left_out"] += 1
        if len(feats) < PAGE or not answer.get("exceededTransferLimit", len(feats) == PAGE):
            break
        offset += len(feats)
    else:
        raise TooBig(f"more than {MAX_RECORDS} records: not a list of public places")
    stats["records"] += count


def socrata_rows(client, layer, stats):
    """The rows of a Socrata dataset: pages of PAGE records ($limit/$offset), only the mapped fields asked for."""
    f = layer["fields"]
    cols = list(dict.fromkeys([":id"] + [v for k, v in f.items() if k not in ("id", "days")]
                              + list((f.get("days") or {}).values())))
    offset, count = 0, 0
    while offset < MAX_RECORDS:
        url = f"https://{layer['domain']}/resource/{layer['dataset']}.json?" + urllib.parse.urlencode(
            {"$select": ",".join(cols), "$limit": PAGE, "$offset": offset, "$order": ":id"})
        records = json.loads(client.fetch(url))
        if not isinstance(records, list):
            raise RequestFailed("the dataset did not answer a list of records")
        for rec in records:
            values = {k: _text(rec.get(v)) for k, v in f.items() if k not in ("id", "point", "lat", "lon", "days")}
            values["days"] = {d: _text(rec.get(v)) for d, v in (f.get("days") or {}).items()}
            at = socrata_position(rec, f)
            row = make(layer, _text(rec.get(":id")), values, *(at or (None, None)))
            if row:
                count += 1
                yield row
            else:
                stats["left_out"] += 1
        if len(records) < PAGE:
            break
        offset += PAGE
    else:
        raise TooBig(f"more than {MAX_RECORDS} records: not a list of public places")
    stats["records"] += count


def collect(client, unit, stats):
    """Yield the rows of one state's layers (unit: the state's code in lower case; the layer list from read_list).
    A layer that refuses or fails is recorded in stats ("blocked", "failed") and left; the others go on."""
    layers = [l for l in read_list() if l.get("state", "").lower() == unit]
    stats.update(layers=len(layers), records=0, left_out=0, blocked=[], failed=[], may_be_empty=True)
    seen = set()
    for layer in layers:
        reader = socrata_rows if layer["platform"] == "socrata" else arcgis_rows
        try:
            rows = list(reader(client, layer, stats))           # all of a layer, or none of it
        except Blocked as e:
            stats["blocked"].append(f"{layer['id']}: {str(e)[:120]}")
            continue
        except (NotFound, RequestFailed, ValueError) as e:
            stats["failed"].append(f"{layer['id']}: {str(e)[:120]}")
            continue
        for row in rows:
            if row["key"] not in seen:
                seen.add(row["key"])
                yield row


def units():
    """The matrix units: the states, DC and Puerto Rico (as for the chambers)."""
    from placepacks.directories.chambermaster import _states
    out = {}
    for code, spec in _states().items():
        out[code] = {**spec, "expected": 0, "budget": 3000, "timeout": 120}
    return out


STATES = units()


def states_with_layers(path=None):
    """The state codes (lower case, space-separated) that have layers in the list: the matrix of the month."""
    return " ".join(sorted({l["state"].lower() for l in read_list(path) if l.get("state")}))


def main(argv=None):
    """python -m placepacks.directories.city_facilities discover --out city-facilities-layers.json: the month's
    layer list (the workflow's discover job); ... states --list city-facilities-layers.json: its states."""
    import argparse
    from placepacks.chains.polite import Polite
    p = argparse.ArgumentParser(description=main.__doc__)
    p.add_argument("action", choices=["discover", "states"])
    p.add_argument("--out", default=LIST_FILE)
    p.add_argument("--list", default=LIST_FILE)
    p.add_argument("--budget", type=int, default=4000)
    a = p.parse_args(argv)
    if a.action == "states":
        print(states_with_layers(a.list))
        return 0
    client = Polite(a.budget, PAUSE, agent=USER_AGENT)
    layers = discover(client)
    write_list(layers, a.out)
    print(f"{len(layers)} layers written to {a.out} ({client.used} requests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
