"""The registry of map, indoor-map and campus-map vendors, with the fingerprints that show an organisation's website
uses one (the owner's decision of 27 November 2026, notes/helper-rules.txt: "keep a registry of map/indoor-map/
directory vendors with fingerprints (script/embed domains, iframe URLs, API hosts)").

Each vendor in VENDORS has:
  name         the vendor's and product's name, as said in reports
  hosts        the host names whose appearance in a page (a script, an iframe, a link, an API call) shows the vendor;
               a host matches itself and its sub-domains
  ids          regular expressions whose first group is the organisation's map id in a URL or a script's text
               (Concept3D's "map.concept3d.com/?id=1130", Mazemap's "campusid=1"); a vendor may have none
  collector    the module in placepacks/mapvendors that reads the vendor's public data, or "" (none yet)
  data         what is known about the vendor's public data: "public" (an open endpoint that answers without a
               login or key and that robots.txt allows), "robots-disallowed" (it answers, but its robots.txt asks
               programs not to read it: nothing is published until the owner decides), "login" (needs an account or
               a customer key), "unknown" (not looked at yet)
  marks        regular expressions of the vendor's own map page (its script or title), for a vendor whose maps are
               served from the customer's own host ("maps.<airport>.com" for Atrius); a page with a mark is that
               vendor's map, the page's own address its "url" (optional)
  showcase     public pages of the vendor listing its customers' maps (a discovery seed), may be empty
  verified     False for a fingerprint written from the vendor's public documentation or product pages but not yet
               seen on an organisation's page (the first discovery run confirms or corrects it)

fingerprints(text, base) finds every vendor (and map id) in a page; unknown_embeds(text, base) finds the map embeds
of vendors not in the registry (iframes and scripts on map pages from hosts the registry and GENERIC_HOSTS do not
know), which discovery appends to notes/new-map-vendors.txt so a collector can be written.
Only the Python standard library is used.
"""

import re
import urllib.parse

VENDORS = {
    "concept3d": {
        "name": "Concept3D (interactive campus maps)",
        "hosts": ["concept3d.com"],
        "ids": [r"map\.concept3d\.com/?\??[^\"'\s<>]*?[?&#]id=(\d+)", r"concept3d\.com/map/[^\"'\s<>]*?[?&#]id=(\d+)",
                r"api\.concept3d\.com/[^\"'\s<>]*?[?&]map=(\d+)"],
        "collector": "concept3d",
        "data": "robots-disallowed",
        "data_note": "The web maps read https://api.concept3d.com/ (locations, categories) with a public key built "
                     "into Concept3D's own web map, but that host's robots.txt says \"User-agent: * Disallow: /\" "
                     "(checked 27 November 2026). By the standing rule (robots.txt obeyed for what is published, "
                     "except chain store locators and government websites) nothing is read from it until the owner "
                     "decides; the collector is ready and records the organisations as blocked by robots.txt.",
        "showcase": ["https://concept3d.com/sitemap_index.xml"],
        "verified": True,
    },
    "mazemap": {
        "name": "MazeMap (indoor maps and wayfinding)",
        "hosts": ["mazemap.com"],
        "ids": [r"mazemap\.com/[^\"'\s<>]*?[?&#](?:v=\d+&)?campusid=(\d+)", r"mazemap\.com/[^\"'\s<>]*?campuses=(\d+)",
                r"[\"']?campuses[\"']?\s*:\s*[\"']?(\d+)"],
        "collector": "mazemap",
        "data": "public",
        "data_note": "https://api.mazemap.com/api/campus/<id>/, /api/buildings/?campusid=<id> and "
                     "/api/campus/<id>/pois/ answer without a key; the host has no robots.txt (404: allowed). "
                     "Checked 27 November 2026.",
        "showcase": ["https://www.mazemap.com/sitemap.xml"],
        "verified": True,
    },
    "campusbird": {
        "name": "Nuvo / CampusBird (campus maps)",
        "hosts": ["campusbird.com", "nuvo.cloud", "nuvoinc.com"],
        "ids": [r"campusbird\.com/(?:map/)?(?:#!/)?([a-z0-9-]+)"],
        "collector": "",
        "data": "unknown",
        "showcase": [],
        "verified": False,
    },
    "rave": {
        "name": "Rave Mobile Safety (campus safety maps)",
        "hosts": ["ravemobilesafety.com", "getrave.com"],
        "ids": [],
        "collector": "",
        "data": "login",
        "data_note": "Rave's facility maps sit inside its safety apps for signed-in users.",
        "showcase": [],
        "verified": False,
    },
    "mappedin": {
        "name": "Mappedin (malls, airports, hospitals)",
        "hosts": ["mappedin.com", "mappedin.cloud"],
        "ids": [r"app\.mappedin\.com/map/([0-9a-f]{24})", r"mappedin\.com/[^\"'\s<>]*?[?&]venue=([a-z0-9-]+)"],
        "collector": "",
        "data": "login",
        "data_note": "Mappedin's data API needs a customer key. Queue item Q3 looked again (27 November 2026): the "
                     "malls' Mappedin Web maps (Macerich, Brookfield, Tanger) read api-gateway.mappedin.com with "
                     "the customer's key; no public endpoint, so nothing is read (the maps are recorded).",
        "showcase": [],
        "verified": False,
    },
    "locuslabs": {
        "name": "Atrius / LocusLabs (airport maps)",
        "hosts": ["locuslabs.com", "atrius.com", "atriusmaps.com"],
        "ids": [r"locuslabs\.com/[^\"'\s<>]*?venueId=([a-z0-9-]+)", r"[?&]vid=([a-z0-9-]+)"],
        "marks": [r"LocusLabsMaps", r"<title>\s*Atrius Maps"],
        "collector": "atrius",
        "data": "public",
        "data_note": "An airport's public Atrius map (maps.<its site>/?vid=<venue>) names its account and venue in "
                     "its own config.json; the map then reads the venue's files from a.locuslabs.com without a "
                     "login or key (placepacks/mapvendors/atrius.py; checked 27 November 2026, queue item Q3).",
        "showcase": [],
        "verified": True,
    },
    "mapsindoors": {
        "name": "MapsIndoors by MapsPeople",
        "hosts": ["mapsindoors.com", "mapspeople.com"],
        "ids": [r"mapsindoors\.com/[^\"'\s<>]*?(?:apiKey|solutionId)=([a-z0-9]+)"],
        "collector": "",
        "data": "login",
        "data_note": "Each customer's solution has its own API key in its page (queue item Q3).",
        "showcase": [],
        "verified": False,
    },
    "pointr": {
        "name": "Pointr (indoor maps)",
        "hosts": ["pointr.tech", "pointr.cloud"],
        "ids": [],
        "collector": "",
        "data": "login",
        "showcase": [],
        "verified": False,
    },
    "jibestream": {
        "name": "Jibestream (indoor maps, now part of Inpixon)",
        "hosts": ["jibestream.com", "inpixon.com"],
        "ids": [],
        "collector": "",
        "data": "login",
        "showcase": [],
        "verified": False,
    },
    "esri-indoors": {
        "name": "ArcGIS Indoors viewer (Esri)",
        "hosts": [],
        "ids": [r"/apps/indoorviewer/index\.html\?[^\"'\s<>]*?appid=([0-9a-f]{32})",
                r"/apps/instant/indoors/index\.html\?[^\"'\s<>]*?appid=([0-9a-f]{32})"],
        "collector": "",
        "data": "unknown",
        "data_note": "A public Indoors viewer reads public ArcGIS layers (Units, Levels, Facilities); the "
                     "campus-gis collector reads public building layers found through ArcGIS Hub.",
        "showcase": [],
        "verified": True,
    },
    "mapwize": {
        "name": "Mapwize (indoor maps)",
        "hosts": ["mapwize.io"],
        "ids": [r"mapwize\.io/[^\"'\s<>]*?(?:venueId|venue)=([0-9a-f]{24})"],
        "collector": "",
        "data": "unknown",
        "showcase": [],
        "verified": False,
    },
    "mapsted": {
        "name": "Mapsted (indoor maps)",
        "hosts": ["mapsted.com"],
        "ids": [],
        "collector": "",
        "data": "unknown",
        "showcase": [],
        "verified": False,
    },
}

# Hosts of general map services and of page furniture that are never a campus-map vendor (their embeds are not
# "unknown vendors"): plain street maps, video, analytics, fonts, consent banners, CDNs.
GENERIC_HOSTS = ("google.com", "googleapis.com", "gstatic.com", "googletagmanager.com", "google-analytics.com",
                 "bing.com", "virtualearth.net", "apple.com", "openstreetmap.org", "mapbox.com", "mapquest.com",
                 "here.com", "youtube.com", "youtube-nocookie.com", "vimeo.com", "facebook.com", "facebook.net",
                 "twitter.com", "x.com", "instagram.com", "linkedin.com", "doubleclick.net", "cloudflare.com",
                 "jsdelivr.net", "unpkg.com", "jquery.com", "fontawesome.com", "typekit.net", "hotjar.com",
                 "onetrust.com", "cookielaw.org", "hubspot.com", "siteimproveanalytics.com", "addtoany.com",
                 "sharethis.com", "recaptcha.net", "hcaptcha.com", "arcgis.com", "esri.com", "leafletjs.com",
                 "cartocdn.com", "stamen.com", "maptiler.com", "thunderforest.com", "tiles.mapbox.com")
# Words of a map embed's address or of the page around it (an iframe or script is an embed of interest only when
# its address says map, or the page it is on is a map page).
MAP_WORDS = re.compile(r"map|wayfind|indoor|floor[-_ ]?plan", re.I)
_EMBED = re.compile(r"<(iframe|script|embed)\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_URL = re.compile(r"https?://[a-z0-9.-]+(?::\d+)?(?:/[^\s\"'<>)\\]*)?", re.I)


def host_of(url):
    """The lower-case host of a URL, or ""."""
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def host_matches(host, names):
    """True when host is one of names or a sub-domain of one ("map.concept3d.com" matches "concept3d.com")."""
    return any(host == n or host.endswith("." + n) for n in names)


def known_host(host):
    """The vendor id whose hosts include host, or ""."""
    for vid, v in VENDORS.items():
        if v["hosts"] and host_matches(host, v["hosts"]):
            return vid
    return ""


def fingerprints(text, base=""):
    """Every vendor seen in a page's text: [{"vendor", "map_id" ("" when no id), "url" (the address that showed
    it)}], each (vendor, map id) once. base: the page's own address (for relative embeds)."""
    found, seen = [], set()
    text = str(text or "")
    urls = [urllib.parse.urljoin(base, m.group(2)) for m in _EMBED.finditer(text)] + _URL.findall(text)
    for vid, v in VENDORS.items():
        ids = []
        for pattern in v["ids"]:
            for m in re.finditer(pattern, text, re.I):
                ids.append((m.group(1), m.group(0)))
        hit = next((u for u in urls if v["hosts"] and host_matches(host_of(u), v["hosts"])), "")
        if not ids and not hit and base and any(re.search(m, text, re.I) for m in v.get("marks") or []):
            ids, hit = [("", base)], base       # the vendor's own map page, on the customer's host
        if not ids and not hit:
            continue
        if vid == "locuslabs" and not hit:
            continue                    # "vid=" alone is too common a parameter to mean LocusLabs
        if vid == "mazemap" and not hit:
            ids = [i for i in ids if "mazemap" in i[1].lower()]
            if not ids:
                continue
        for map_id, where in ids or [("", hit)]:
            if (vid, map_id) in seen:
                continue
            seen.add((vid, map_id))
            url = where if where.startswith("http") else (hit or base)
            found.append({"vendor": vid, "map_id": map_id, "url": url})
    return found


def unknown_embeds(text, base="", page_is_map=False):
    """The map embeds of vendors not in the registry: [{"host", "url"}] of iframes, scripts and embeds whose host is
    neither a registered vendor's, nor generic (GENERIC_HOSTS), nor the page's own site, and whose address (or, for
    a map page, the page itself) speaks of maps. Each host once."""
    own = host_of(base)
    own_root = ".".join(own.split(".")[-2:]) if own else ""
    out, seen = [], set()
    for m in _EMBED.finditer(str(text or "")):
        url = urllib.parse.urljoin(base, m.group(2))
        host = host_of(url)
        if not host or host in seen or known_host(host) or host_matches(host, GENERIC_HOSTS):
            continue
        if own_root and host_matches(host, [own_root]):
            continue
        if m.group(1).lower() == "script" and not MAP_WORDS.search(url):
            continue                    # a script is counted only when its own address speaks of maps
        if not (MAP_WORDS.search(url) or (page_is_map and m.group(1).lower() == "iframe")):
            continue
        seen.add(host)
        out.append({"host": host, "url": url[:300]})
    return out


def collectors():
    """{vendor id: collector module name} of the vendors that have one."""
    return {vid: v["collector"] for vid, v in VENDORS.items() if v["collector"]}
