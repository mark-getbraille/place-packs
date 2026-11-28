"""The map vendor DISCOVERY CHAIN (the owner's decision of 27 November 2026, notes/helper-rules.txt): scan
organisations' own websites for the fingerprints of campus-map and indoor-map vendors (placepacks/mapvendors/
registry.py), and record which organisation uses which vendor, with its map id, so the vendor's collector can read
the map's buildings, entrances, elevators and parking.

The organisations scanned (each shard of the monthly map-vendors workflow takes a share):
  colleges-N   every active college, community college, trade and tribal school in IPEDS (its homepage WEBADDR,
               its UNITID: place_key "nces-postsecondary:<UNITID>", and its position), from the newest IPEDS HD file
  health-N     US hospitals with an official website and a position in Wikidata (place_key "wikidata:Q...")
  venues-N     US zoos, aquariums, museums, convention centres, stadiums, shopping malls and airports with an official
               website and a position in Wikidata
  showcase     each vendor's own public customer pages and sitemaps (registry "showcase"): map ids in their links
For each organisation: its homepage, then up to MAX_LINKS of its own pages whose link says map, campus map,
visitors, parking, directions or accessibility. Every page is fingerprinted (registry.fingerprints); embeds of
map vendors the registry does not know are kept as "unknown" (registry.unknown_embeds) and appended to
notes/new-map-vendors.txt (vendor host, example organisation, URL) so a collector can be written.

Politeness (the owner's limits): robots.txt is read first and obeyed (a page it disallows is not read); an
identified User-Agent (USER_AGENT); at least a second between two requests to one host; a refusal (401, 403, 429,
an anti-bot challenge page) ends that organisation at once, recorded as "blocked", never got round; no login, no
CAPTCHA, no headless browser, no other IP address. Only the page's addresses are looked at: no text, name or e-mail
of a page is kept.

    python -m placepacks.mapvendors.discover shards                        the workflow's matrix (JSON)
    python -m placepacks.mapvendors.discover scan --shard colleges-3 --out found/
    python -m placepacks.mapvendors.discover merge --dir found/ --previous old.json --out map-vendors-orgs.json \\
        --new-vendors new-map-vendors.txt
    python -m placepacks.mapvendors.discover notes --file new-map-vendors.txt [--notes /home/user/notes/...]
Only the Python standard library is used.
"""

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
import time
import urllib.parse
import zipfile

from placepacks.chains.polite import Blocked, BudgetSpent, NotFound, Polite, RequestFailed
from placepacks.mapvendors import registry

USER_AGENT = "place-packs-map-vendors/1 (+https://github.com/mark-getbraille/place-packs)"
PAUSE = 1.5
MAX_LINKS = 3                   # an organisation's own pages read after its homepage, at most
COLLEGE_SHARDS = 8
HEALTH_SHARDS = 3
VENUE_SHARDS = 3
SHARD_BUDGET = 6000             # requests one shard may send
SHARD_MINUTES = 340
LIST_FILE = "map-vendors-orgs.json"
NEW_VENDORS_FILE = "new-map-vendors.txt"
NOTES_FILE = "/home/user/notes/new-map-vendors.txt"
KEEP_MONTHS = 6                 # a map not seen again for this many months leaves the list
IPEDS_HD = "https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip"
WDQS = "https://query.wikidata.org/sparql"
# Wikidata classes of the organisations scanned (instance of, P31), by kind.
WIKIDATA_KINDS = {
    "hospital": ["Q16917"],
    "zoo": ["Q43501"],
    "aquarium": ["Q2281788"],
    "museum": ["Q33506", "Q207694"],
    "convention centre": ["Q1378975"],
    "stadium": ["Q483110"],
    "shopping mall": ["Q11315", "Q31374404"],
    "airport": ["Q1248784", "Q644371"],
}
HEALTH_KINDS = ("hospital",)
VENUE_KINDS = ("zoo", "aquarium", "museum", "convention centre", "stadium", "shopping mall", "airport")
WIKIDATA_LIMIT = 4000
# The words of a link worth following, best first.
LINK_WORDS = [
    (re.compile(r"campus[- ]?maps?|interactive[- ]?map|maps?\s*(&|and)\s*directions|wayfinding|floor[- ]?plans?", re.I),
     3),
    (re.compile(r"\bmaps?\b", re.I), 2),
    (re.compile(r"visit(ors?|ing)?\b|getting here|directions|parking|patients?\s*(&|and)\s*visitors|accessib", re.I), 1),
]
_A = re.compile(r"<a\b[^>]*?\bhref\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


# ------------------------------------------------------------------------------------------------ seeds

def homepage(url):
    """An organisation's homepage as a full https address ("www.madeup.edu/" -> "https://www.madeup.edu"), or ""."""
    text = " ".join(str(url or "").split())
    if not text or "@" in text:
        return ""
    if not re.match(r"https?://", text, re.I):
        text = "https://" + text.lstrip("/")
    parts = urllib.parse.urlsplit(text)
    if not parts.hostname or "." not in parts.hostname:
        return ""
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def ipeds_orgs(zip_bytes):
    """The colleges of an IPEDS HD .zip (bytes): [{"org", "kind", "homepage", "place_key", "lat", "lon"}] for the
    active institutions with a website. Only the name, website, id and position columns are read."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = io.TextIOWrapper(z.open(name), encoding="utf-8-sig", errors="replace", newline="")
        out = []
        for d in csv.DictReader(text):
            site = homepage(d.get("WEBADDR"))
            if not site or (d.get("CYACTIVE") or "1").strip() not in ("1", "3"):
                continue
            out.append({"org": " ".join((d.get("INSTNM") or "").split()), "kind": "college", "homepage": site,
                        "place_key": f"nces-postsecondary:{(d.get('UNITID') or '').strip()}",
                        "lat": (d.get("LATITUDE") or "").strip(), "lon": (d.get("LONGITUD") or "").strip()})
    return sorted(out, key=lambda o: o["place_key"])


def wikidata_query(classes, limit=WIKIDATA_LIMIT):
    """The SPARQL query of US items of the classes with an official website and a position."""
    values = " ".join(f"wd:{c}" for c in classes)
    return ("SELECT ?item ?itemLabel ?site ?coord WHERE { VALUES ?class { " + values + " } ?item wdt:P31 ?class; "
            "wdt:P17 wd:Q30; wdt:P856 ?site; wdt:P625 ?coord. SERVICE wikibase:label { bd:serviceParam "
            "wikibase:language \"en\". } } LIMIT " + str(limit))


WIKIDATA_WAITS = (60, 180, 420)     # seconds to wait after Wikidata's "too many requests" before asking again


def wikidata_orgs(client, kinds, sleep=time.sleep):
    """The organisations of the kinds from Wikidata: one query per kind (WIKIDATA_KINDS), each item once."""
    out, seen = [], set()
    for kind in kinds:
        url = WDQS + "?" + urllib.parse.urlencode({"query": wikidata_query(WIKIDATA_KINDS[kind]), "format": "json"})
        answer = None
        for wait in WIKIDATA_WAITS + (None,):
            try:
                answer = client.json(url, headers={"Accept": "application/sparql-results+json"})
                break
            except Blocked as e:
                # Several shards ask at the same moment and Wikidata says "too many requests" (429): wait as asked
                # and try again a few times; after that, or for another refusal, this kind is skipped, not the run.
                if "HTTP 429" in str(e) and wait is not None:
                    print(f"Wikidata {kind}: too many requests; waiting {wait} s", flush=True)
                    sleep(wait)
                    continue
                print(f"Wikidata {kind}: {e}", flush=True)
                break
            except (NotFound, RequestFailed) as e:
                print(f"Wikidata {kind}: {e}", flush=True)
                break
        if answer is None:
            continue
        for b in (answer.get("results") or {}).get("bindings") or []:
            qid = b["item"]["value"].rsplit("/", 1)[-1]
            m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", b.get("coord", {}).get("value", ""))
            site = homepage(b.get("site", {}).get("value"))
            if qid in seen or not m or not site:
                continue
            seen.add(qid)
            out.append({"org": b.get("itemLabel", {}).get("value", qid), "kind": kind, "homepage": site,
                        "place_key": f"wikidata:{qid}", "lat": m.group(2), "lon": m.group(1)})
    return sorted(out, key=lambda o: o["place_key"])


def shard_list():
    """The workflow's discovery matrix: [{"shard": "colleges-1"}, ...]."""
    names = ([f"colleges-{i}" for i in range(1, COLLEGE_SHARDS + 1)] + [f"health-{i}" for i in range(1, HEALTH_SHARDS + 1)]
             + [f"venues-{i}" for i in range(1, VENUE_SHARDS + 1)] + ["showcase"])
    return [{"shard": n} for n in names]


def orgs_for(shard, client, get_bytes=None):
    """The organisations of one shard ("colleges-3": every 8th college from the third), or [] for "showcase"."""
    group, _, number = shard.rpartition("-")
    if shard == "showcase":
        return []
    index = int(number) - 1
    if group == "colleges":
        get_bytes = get_bytes or _ipeds_bytes
        orgs, total = ipeds_orgs(get_bytes(client)), COLLEGE_SHARDS
    elif group == "health":
        orgs, total = wikidata_orgs(client, HEALTH_KINDS), HEALTH_SHARDS
    elif group == "venues":
        orgs, total = wikidata_orgs(client, VENUE_KINDS), VENUE_SHARDS
    else:
        raise SystemExit(f"unknown shard {shard!r}")
    return [o for i, o in enumerate(orgs) if i % total == index]


def _ipeds_bytes(client, today=None):
    """The newest IPEDS HD .zip (bytes), this year's or an earlier one's."""
    today = today or datetime.date.today()
    for year in range(today.year, today.year - 4, -1):
        try:
            return _binary(client, IPEDS_HD.format(year=year))
        except NotFound:
            continue
    raise RequestFailed("no IPEDS HD file found")


def _binary(client, url):
    """The raw bytes of url through the polite client's opener (the client's text decoding would spoil a .zip)."""
    import urllib.request
    host = urllib.parse.urlsplit(url).hostname or ""
    if client.used >= client.budget:
        raise BudgetSpent(f"the budget of {client.budget} requests is spent")
    client._wait_for(host)
    client.used += 1
    client.hosts.add(host)
    status, _, body = client.opener(urllib.request.Request(url, headers={"User-Agent": client.agent}), 120)
    client.last[host] = client.clock()
    if status in (404, 410):
        raise NotFound(url)
    if status in (401, 403, 429):
        raise Blocked(f"{host} refused the request (HTTP {status})")
    if not 200 <= status < 300:
        raise RequestFailed(f"{url}: HTTP {status}")
    return body


# ------------------------------------------------------------------------------------------------ scanning

def same_site(url, home):
    """True when url is on the organisation's own site (the same last two host labels as its homepage)."""
    a, b = registry.host_of(url), registry.host_of(home)
    return bool(a and b) and ".".join(a.split(".")[-2:]) == ".".join(b.split(".")[-2:])


def map_links(page, base, home):
    """The organisation's own pages worth reading for a map, best first: [(url, is_map_link)] (at most MAX_LINKS),
    from the page's links whose text or address says map, visitors, parking, directions or accessibility."""
    scored = {}
    for m in _A.finditer(page or ""):
        href = registry.join(base, m.group(1).strip())
        if not href.startswith("http") or not same_site(href, home) or re.search(r"\.(pdf|jpe?g|png|docx?)$", href, re.I):
            continue
        words = " ".join(_TAG.sub(" ", m.group(2)).split()) + " " + urllib.parse.urlsplit(href).path
        score = max((s for pattern, s in LINK_WORDS if pattern.search(words)), default=0)
        if score:
            scored[href] = max(score, scored.get(href, 0))
    best = sorted(scored.items(), key=lambda kv: (-kv[1], len(kv[0])))
    return [(u, s >= 2) for u, s in best[:MAX_LINKS]]


def scan_org(client, org, today):
    """Scan one organisation's site (see the module docstring). Returns {"found": [...], "unknown": [...],
    "status": "ok" | "blocked" | "failed" | "robots", "reason"}; BudgetSpent is raised (the shard stops)."""
    from placepacks.directories.common import Robots
    home = org["homepage"]
    parts = urllib.parse.urlsplit(home)
    base = f"{parts.scheme}://{parts.netloc}"
    out = {"found": [], "unknown": [], "status": "ok", "reason": ""}
    try:
        robots = Robots(client, base, agent="place-packs-map-vendors")
        if not robots.allowed(home + "/"):
            out.update(status="robots", reason="robots.txt disallows the homepage")
            return out
        page = client.fetch(home + ("/" if not parts.path else ""))
        pages = [(home, page, False)]
        for url, is_map in map_links(page, home, home):
            if robots.allowed(url):
                try:
                    pages.append((url, client.fetch(url), is_map))
                except NotFound:
                    continue
    except Blocked as e:
        out.update(status="blocked", reason=str(e)[:200])
        return out
    except (NotFound, RequestFailed) as e:
        out.update(status="failed", reason=str(e)[:200])
        return out
    seen = set()
    for url, text, is_map in pages:
        for f in registry.fingerprints(text, url):
            if (f["vendor"], f["map_id"]) in seen:
                continue
            seen.add((f["vendor"], f["map_id"]))
            out["found"].append({**{k: org.get(k, "") for k in ("org", "kind", "homepage", "place_key", "lat",
                                                                 "lon")},
                                 "vendor": f["vendor"], "map_id": f["map_id"], "url": f["url"][:300],
                                 "page": url[:300], "seen": today})
        for u in registry.unknown_embeds(text, url, page_is_map=is_map):
            out["unknown"].append({**u, "org": org.get("org", ""), "page": url[:300], "seen": today})
    return out


def showcase(client, today):
    """Map ids found on the vendors' own customer pages and sitemaps (registry "showcase"): [found records]. A
    sitemap's pages whose address speaks of customers, case studies or clients are read too (at most 40 a vendor)."""
    from placepacks.directories.common import Robots
    found = []
    for vid, v in registry.VENDORS.items():
        for start in v.get("showcase") or []:
            parts = urllib.parse.urlsplit(start)
            try:
                robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent="place-packs-map-vendors")
                if not robots.allowed(start):
                    continue
                text = client.fetch(start)
                pages = [(start, text)]
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
                subs = [u for u in locs if u.endswith(".xml")][:10]
                for sub in subs:
                    if robots.allowed(sub):
                        locs += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", client.fetch(sub))
                wanted = [u for u in locs if re.search(r"customer|case-stud|client|success|partner|campus-map", u, re.I)]
                for url in wanted[:40]:
                    if robots.allowed(url):
                        try:
                            pages.append((url, client.fetch(url)))
                        except NotFound:
                            continue
            except (Blocked, NotFound, RequestFailed) as e:
                print(f"showcase {vid}: {e}", flush=True)
                continue
            for url, page in pages:
                for f in registry.fingerprints(page, url):
                    if f["map_id"]:
                        found.append({"org": "", "kind": "", "homepage": "", "place_key": "", "lat": "", "lon": "",
                                      "vendor": f["vendor"], "map_id": f["map_id"], "url": f["url"][:300],
                                      "page": url[:300], "seen": today})
    return found


def scan_shard(shard, out_dir, client=None, today=None, get_bytes=None, log=print):
    """Scan one shard's organisations into out_dir/<shard>.json. Returns the result dict."""
    today = (today or datetime.date.today()).isoformat()
    # One short retry only: a shard visits thousands of different sites, and a site that is down is simply left.
    client = client or Polite(SHARD_BUDGET, PAUSE, agent=USER_AGENT, waits=(10,),
                              deadline=time.monotonic() + 60 * (SHARD_MINUTES - 10))
    result = {"shard": shard, "date": today, "found": [], "unknown": [], "scanned": 0, "blocked": [],
              "robots": 0, "failed": 0, "status": "ok"}
    try:
        if shard == "showcase":
            result["found"] = showcase(client, today)
        else:
            for org in orgs_for(shard, client, get_bytes):
                try:
                    got = scan_org(client, org, today)
                except BudgetSpent:
                    raise
                except Exception as e:  # noqa: BLE001 - one odd website (a bad address, a broken answer) never
                    # loses the shard: it counts as failed and the scan goes on
                    got = {"found": [], "unknown": [], "status": "failed", "reason": f"{type(e).__name__}: {e}"}
                result["scanned"] += 1
                result["found"] += got["found"]
                result["unknown"] += got["unknown"]
                if got["status"] == "blocked":
                    result["blocked"].append({"org": org["org"], "homepage": org["homepage"], "reason": got["reason"]})
                elif got["status"] in ("robots", "failed"):
                    result[got["status"]] += 1
    except BudgetSpent as e:
        result.update(status="incomplete", reason=str(e))
    result["requests"] = client.used
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{shard}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    log(f"{shard}: {result['scanned']} sites, {len(result['found'])} maps, {len(result['unknown'])} unknown embeds, "
        f"{len(result['blocked'])} blocked, {client.used} requests ({result['status']})")
    return result


# ------------------------------------------------------------------------------------------------ the list

def merge(results, previous=None, today=None):
    """The month's list from the shards' results and last month's list: each map (vendor and map id; a vendor
    seen without an id is kept per organisation) once, with first_seen and last_seen; a map not seen for
    KEEP_MONTHS months is dropped; organisation details from a scan replace a showcase's empty ones. Returns
    {"date", "maps", "unknown", "blocked"}."""
    today = today or datetime.date.today()
    cutoff = (today - datetime.timedelta(days=31 * KEEP_MONTHS)).isoformat()
    maps = {}

    def ident(m):
        """A map's identity in the list."""
        return (m["vendor"], m["map_id"] or m.get("homepage", ""))

    for m in (previous or {}).get("maps", []):
        if m.get("last_seen", "") >= cutoff:
            maps[ident(m)] = dict(m)
    for r in results:
        for m in r.get("found", []):
            key = ident(m)
            old = maps.get(key, {})
            merged = {**old, **{k: v for k, v in m.items() if v not in ("", None)}}
            merged["first_seen"] = old.get("first_seen") or m.get("seen", today.isoformat())
            merged["last_seen"] = m.get("seen", today.isoformat())
            merged.pop("seen", None)
            maps[key] = merged
    unknown = {}
    for u in (previous or {}).get("unknown", []):
        unknown[u["host"]] = u
    for r in results:
        for u in r.get("unknown", []):
            unknown.setdefault(u["host"], u)
    blocked = [b for r in results for b in r.get("blocked", [])]
    return {"date": today.isoformat(), "maps": sorted(maps.values(), key=lambda m: (m["vendor"], m["map_id"],
                                                                                    m.get("org", ""))),
            "unknown": sorted(unknown.values(), key=lambda u: u["host"]), "blocked": blocked}


def new_vendor_lines(listing, previous=None):
    """The lines for notes/new-map-vendors.txt of the hosts first seen this month: "<date> | vendor host: <host> |
    example organisation: <org> | URL: <url>"."""
    before = {u["host"] for u in (previous or {}).get("unknown", [])}
    return [f"{listing['date']} | vendor host: {u['host']} | example organisation: {u.get('org') or '?'} | "
            f"URL: {u['url']}" for u in listing.get("unknown", []) if u["host"] not in before]


def append_notes(lines, path=NOTES_FILE):
    """Append the lines to the notes file, leaving out a host already named there. Returns the lines added."""
    have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    added = [line for line in lines if f"vendor host: {line.split('vendor host: ')[1].split(' |')[0]} |" not in have]
    if added:
        with open(path, "a", encoding="utf-8") as f:
            if not have:
                f.write("# New map vendors found by place-packs' map vendor discovery (placepacks/mapvendors/"
                        "discover.py): host, example organisation, embed URL. Write a collector, then add the "
                        "vendor to placepacks/mapvendors/registry.py.\n")
            f.write("\n".join(added) + "\n")
    return added


def read_list(path=None):
    """The map list (LIST_FILE) from path or the MAP_VENDORS_LIST environment variable; {} when there is none."""
    path = path or os.environ.get("MAP_VENDORS_LIST", "")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def maps_of(vendor, listing=None):
    """The maps of one vendor in the list (with a map id), each map id once."""
    listing = read_list() if listing is None else listing
    out, seen = [], set()
    for m in listing.get("maps", []):
        if m.get("vendor") == vendor and m.get("map_id") and m["map_id"] not in seen:
            seen.add(m["map_id"])
            out.append(m)
    return out


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["shards", "scan", "merge", "notes"])
    p.add_argument("--shard", default="")
    p.add_argument("--out", default="found")
    p.add_argument("--dir", default="found")
    p.add_argument("--previous", default="")
    p.add_argument("--new-vendors", default=NEW_VENDORS_FILE)
    p.add_argument("--file", default=NEW_VENDORS_FILE)
    p.add_argument("--notes", default=NOTES_FILE)
    a = p.parse_args(argv)
    if a.command == "shards":
        print(json.dumps(shard_list(), separators=(",", ":")))
    elif a.command == "scan":
        scan_shard(a.shard, a.out)
    elif a.command == "merge":
        results = []
        if os.path.isdir(a.dir):
            for name in sorted(os.listdir(a.dir)):
                if name.endswith(".json") and name != os.path.basename(a.out):
                    with open(os.path.join(a.dir, name), encoding="utf-8") as f:
                        results.append(json.load(f))
        previous = read_list(a.previous) if a.previous else {}
        listing = merge(results, previous)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(listing, f, indent=1)
        lines = new_vendor_lines(listing, previous)
        with open(a.new_vendors, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        print(f"{len(listing['maps'])} maps ({', '.join(sorted({m['vendor'] for m in listing['maps']}))}); "
              f"{len(lines)} new vendor hosts")
    else:
        lines = [x.strip() for x in open(a.file, encoding="utf-8") if x.strip()] if os.path.exists(a.file) else []
        print(f"{len(append_notes(lines, a.notes))} new vendor hosts added to {a.notes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
