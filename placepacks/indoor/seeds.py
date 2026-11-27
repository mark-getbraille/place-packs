"""Where the malls and airports are: the lists the indoor directory collectors start from (placepacks/indoor), each
with a position, a website and the key of its place in the packs.

  malls     Wikidata's US shopping malls (and outlet malls) with an official website and a position (place_key
            "wikidata:Q..."), and OpenStreetMap's US shop=mall places with a website (place_key "n123", "w123",
            "r123": the core part's keys), asked once from the Overpass API; an operator's mall (Tanger, Macerich,
            Brookfield, Westfield, CBL) is tied to one of these by its website's host, else by its name
            (match_mall), which gives it its position and its place in the packs.
  airports  OurAirports' US airports with scheduled passenger service (public domain; the FAA identifier gives
            the place_key "faa-airports:<id>"), large airports first, their websites from Wikidata (official website
            of the item with the airport's IATA code) or else OurAirports' home_link.
Every request goes through the polite client (placepacks/chains/polite.py). A list that cannot be read is empty
(the collector then records why); nothing is ever got round.
Only the Python standard library is used.
"""

import csv
import io
import re
import urllib.parse

from placepacks.chains.polite import Blocked, NotFound, RequestFailed

OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_QUERY = ('[out:json][timeout:240];area["ISO3166-1"="US"][admin_level=2]->.us;'
                  'nwr["shop"="mall"]["name"](area.us);out center tags;')
AIRPORT_TYPES = ("large_airport", "medium_airport", "small_airport", "seaplane_base", "heliport")


def host_root(url):
    """The last two labels of a website's host without "www" ("https://www.shopmadeup.com/x" -> "shopmadeup.com"),
    or ""; for a shared host (westfield.com/<mall>) the first path part is added ("westfield.com/valleyfair")."""
    try:
        parts = urllib.parse.urlsplit(url if "://" in str(url) else f"https://{url}")
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if not host:
        return ""
    root = ".".join(host.split(".")[-2:])
    if root in SHARED_HOSTS:
        first = [p for p in parts.path.split("/") if p and p not in ("en", "united-states", "mall")]
        return f"{root}/{first[0].lower()}" if first else root
    return root


# Hosts shared by many malls (the mall is in the address's path).
SHARED_HOSTS = ("westfield.com", "simon.com", "tanger.com", "brookfieldproperties.com", "kimcorealty.com")


def wikidata_malls(client):
    """Wikidata's US shopping malls: [{"org", "homepage", "place_key", "lat", "lon"}] (placepacks/mapvendors/
    discover.py wikidata_orgs, kind "shopping mall")."""
    from placepacks.mapvendors.discover import wikidata_orgs
    return wikidata_orgs(client, ("shopping mall",))


def overpass_malls(client):
    """OpenStreetMap's US malls with a name, from one Overpass query: [{"org", "homepage", "place_key", "lat",
    "lon"}]; [] when Overpass does not answer (it is a shared service: one query, never repeated)."""
    try:
        text = client.fetch(OVERPASS, data=urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
        import json
        answer = json.loads(text)
    except (Blocked, NotFound, RequestFailed, ValueError) as e:
        print(f"Overpass: {e}", flush=True)
        return []
    out = []
    for el in answer.get("elements") or []:
        tags = el.get("tags") or {}
        at = el.get("center") or el
        if "lat" not in at or not tags.get("name"):
            continue
        out.append({"org": tags["name"], "homepage": tags.get("website") or tags.get("contact:website") or "",
                    "place_key": f"{el['type'][0]}{el['id']}", "lat": str(at["lat"]), "lon": str(at["lon"]),
                    "state": tags.get("addr:state", "")})
    return out


def match_mall(name, homepage, seeds, state=""):
    """The seed of an operator's mall: the one with the same website host (host_root), else the one with nearly
    the same name (directories/common.py name_similarity >= 0.9; in the same state when both say), else None."""
    from placepacks.directories.common import name_similarity
    root = host_root(homepage) if homepage else ""
    if root:
        for s in seeds:
            if s.get("homepage") and host_root(s["homepage"]) == root:
                return s
    best, score = None, 0.0
    for s in seeds:
        if state and s.get("state") and s["state"].upper() != state.upper():
            continue
        got = name_similarity(name, s.get("org", ""))
        if got > score:
            best, score = s, got
    return best if score >= 0.9 else None


def ourairports(text):
    """The US airports with scheduled service of OurAirports' airports.csv (text): [{"org", "iata", "faa",
    "place_key", "lat", "lon", "homepage", "type"}], large airports first, then by name."""
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        if r.get("iso_country") != "US" or r.get("scheduled_service") != "yes":
            continue
        faa = (r.get("local_code") or r.get("gps_code") or "").strip()
        if not faa:
            continue
        out.append({"org": " ".join((r.get("name") or "").split()), "iata": (r.get("iata_code") or "").strip(),
                    "faa": faa, "place_key": f"faa-airports:{faa}", "lat": r.get("latitude_deg", ""),
                    "lon": r.get("longitude_deg", ""), "homepage": (r.get("home_link") or "").strip(),
                    "type": r.get("type", "")})
    rank = {t: i for i, t in enumerate(AIRPORT_TYPES)}
    return sorted(out, key=lambda a: (rank.get(a["type"], 9), a["org"]))


def wikidata_airport_sites(client):
    """{IATA code: official website} of US airports in Wikidata (one query); {} when it cannot be read."""
    from placepacks.mapvendors.discover import WDQS
    query = ("SELECT ?iata ?site WHERE { ?item wdt:P238 ?iata; wdt:P17 wd:Q30; wdt:P856 ?site. "
             "?item wdt:P31/wdt:P279* wd:Q1248784. }")
    url = WDQS + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
    try:
        answer = client.json(url, headers={"Accept": "application/sparql-results+json"})
    except (Blocked, NotFound, RequestFailed) as e:
        print(f"Wikidata airports: {e}", flush=True)
        return {}
    out = {}
    for b in (answer.get("results") or {}).get("bindings") or []:
        code = b.get("iata", {}).get("value", "").strip().upper()
        site = b.get("site", {}).get("value", "").strip()
        if re.fullmatch(r"[A-Z0-9]{3}", code) and site and code not in out:
            out[code] = site
    return out


def airports(client):
    """The airports to read (ourairports), each with its best website: Wikidata's when it has one, else
    OurAirports' home_link; airports with neither are kept (counted, never read)."""
    try:
        text = client.fetch(OURAIRPORTS)
    except (Blocked, NotFound, RequestFailed) as e:
        print(f"OurAirports: {e}", flush=True)
        return []
    found = ourairports(text)
    sites = wikidata_airport_sites(client)
    for a in found:
        if a["iata"] and sites.get(a["iata"].upper()):
            a["homepage"] = sites[a["iata"].upper()]
    return found


# ------------------------------------------------------------------------------------------------ the plan job

def read_file(variable):
    """The seed list saved by the workflow's plan job in the file named by an environment variable (MALL_SEEDS,
    AIRPORT_SEEDS), or None when there is none (each unit then asks for the list itself)."""
    import json
    import os
    path = os.environ.get(variable, "")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    """Save a seed list once for all of a workflow's units:
        python -m placepacks.indoor.seeds malls --out mall-seeds.json
        python -m placepacks.indoor.seeds airports --out airport-seeds.json"""
    import argparse
    import json
    import time
    from placepacks import indoor
    from placepacks.chains.polite import Polite
    p = argparse.ArgumentParser()
    p.add_argument("which", choices=["malls", "airports"])
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    client = Polite(20, indoor.PAUSE, agent=indoor.USER_AGENT, waits=(30,), deadline=time.monotonic() + 1500)
    found = (wikidata_malls(client) + overpass_malls(client)) if a.which == "malls" else airports(client)
    if not found:
        print(f"no {a.which} found: nothing saved (each unit will ask for the list itself)")
        return 1
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(found, f)
    print(f"{len(found)} {a.which} saved in {a.out} ({client.used} requests)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
