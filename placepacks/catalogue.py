"""The source catalogue (sources.json) and the regions (regions.json): loading, checking and choosing.

check() is what the tests and the build run first: every accepted source has a licence from ALLOWED (open, allows
redistribution), an attribution, a licence address, a part ("core" or "extra") and a reader; every licence with a
text has its file in LICENSES/; every rejection says why. sources_for(region, part) gives the sources of a pack.
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Licences a source may have to be in a pack (each allows redistribution; none is non-commercial or no-derivatives).
# ODbL is share-alike, so only OpenStreetMap's own layer has it (see LICENSES.md: each pack is a collective database).
# NYC-Open-Data and OPEN-NY are the terms of New York City's and New York State's portals: by law (NYC Admin. Code
# 23-502(d)) and by their terms, the data is free to use and redistribute without licence, attribution or share-alike
# requirements (see sources.json "licences").
ALLOWED = {"ODbL-1.0", "CDLA-Permissive-2.0", "Apache-2.0", "OGL-Canada-2.0", "OGL-UK-3.0", "CC0-1.0", "CC-BY-4.0",
           "US-Government-Work", "etalab-2.0", "per-feed-open", "per-source-open", "PDDL-1.0", "ODC-By-1.0",
           "NYC-Open-Data", "OPEN-NY", "public-domain-marked", "Newberry-open"}
SHARE_ALIKE = {"ODbL-1.0"}


def load(path=None):
    """The catalogue (dict)."""
    with open(path or os.path.join(ROOT, "sources.json"), encoding="utf-8") as f:
        return json.load(f)


def regions(path=None):
    """{region id: region dict} of regions.json."""
    with open(path or os.path.join(ROOT, "placepacks", "regions.json"), encoding="utf-8") as f:
        return {r["id"]: r for r in json.load(f)["regions"]}


def country_code(region):
    """The two-letter country of a region ("US", "CA", "GB", ...)."""
    return region.get("cc") or {"United States": "US", "Canada": "CA"}.get(region.get("country"), "")


def check(cat=None):
    """[problems] of the catalogue (empty when it is right)."""
    cat = cat or load()
    problems, ids = [], set()
    licences = cat.get("licences", {})
    known = regions()
    for e in cat.get("accepted", []):
        where = e.get("id", "?")
        if where in ids:
            problems.append(f"{where}: the id is used twice")
        ids.add(where)
        for field in ("id", "name", "short", "part", "licence", "attribution", "url", "reader", "fetch", "history",
                      "countries"):
            if not e.get(field):
                problems.append(f"{where}: no {field}")
        if e.get("licence") not in ALLOWED:
            problems.append(f"{where}: the licence {e.get('licence')} is not one of the allowed open licences")
        if e.get("licence") in SHARE_ALIKE and where != "osm":
            problems.append(f"{where}: a share-alike licence outside the OpenStreetMap layer")
        if e.get("licence") not in licences:
            problems.append(f"{where}: the licence {e.get('licence')} is not described in licences")
        if e.get("part") not in ("core", "extra"):
            problems.append(f"{where}: the part must be core or extra")
        for rid in e.get("regions", []):
            if rid not in known:
                problems.append(f"{where}: the region {rid} is not in regions.json")
    for lid, lic in licences.items():
        if not lic.get("url"):
            problems.append(f"licence {lid}: no address")
        if lic.get("file") and not os.path.exists(os.path.join(ROOT, lic["file"])):
            problems.append(f"licence {lid}: {lic['file']} is missing")
    for r in cat.get("rejected", []):
        if not r.get("name") or not r.get("reason") or not r.get("licence"):
            problems.append(f"rejected {r.get('name', '?')}: name, licence and reason are needed")
    return problems


def settings_for(cat, region, extra=None):
    """The placeholders of a region's addresses and filters (the catalogue's settings and the region's fields)."""
    values = dict(cat.get("settings", {}))
    # A seed run builds as of an older release: PLACEPACKS_SETTINGS='{"tiger_year": "2011"}'.
    if os.environ.get("PLACEPACKS_SETTINGS"):
        values.update(json.loads(os.environ["PLACEPACKS_SETTINGS"]))
    values.update({k: v for k, v in region.items() if isinstance(v, str)})
    values.update(extra or {})
    return values


def sources_for(region, part, cat=None, only=None):
    """The accepted sources of a region's part (the region's country is in the source's countries and, for a source
    of one city or state, the region is in its "regions")."""
    cat = cat or load()
    cc = country_code(region)
    return [e for e in cat["accepted"] if e["part"] == part and cc in e["countries"] and
            (not e.get("regions") or region["id"] in e["regions"]) and (only is None or e["id"] in only)]
