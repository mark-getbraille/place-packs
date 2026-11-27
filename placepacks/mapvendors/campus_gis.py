"""Universities' and colleges' own open campus GIS layers: their buildings with names (and addresses where given),
found through ArcGIS Hub's search like the cities' public places (placepacks/directories/city_facilities.py), the
owner's second source for campus buildings (27 November 2026, notes/helper-rules.txt). Run as the unit "campus-gis"
of the monthly map-vendors workflow.

Discovery: ArcGIS Hub's dataset search for each of KEYWORDS ("campus buildings", "university buildings" ...); a
result is kept when it is a public feature service, its title speaks of buildings or facilities (GOOD_TITLE, not
EXCLUDE_TITLE: no energy use, room inventories, floor plans of offices, work orders or staff directories) and its
publisher is a US university or college (UNIVERSITY). One record (check_layer) tells its fields: it needs a name
field and no people fields (placepacks/directories/city_facilities.py people_layer), and a position in the US.

Reading: at most MAX_RECORDS records per layer, only the name, address and id fields, with positions in longitude
and latitude (a polygon's middle, features.centroid). Each building becomes a row of kind "building", keyed
"campusgis:<layer id>:<record id>", with its address as the note ("Address: ...") and the publisher as "org". No
site key: the pack build gives each building the campus area holding it (features.read, SiteResolver).
Politeness as for every collector: identified, paced, a refusal stops that layer ("blocked"), the others go on.
"""

import json
import re
import urllib.parse

from placepacks import features
from placepacks.chains.polite import Blocked, NotFound, RequestFailed

HUB_SEARCH = "https://hub.arcgis.com/api/search/v1/collections/dataset/items"
KEYWORDS = ["campus buildings", "university buildings", "college buildings", "campus facilities",
            "campus building footprints", "university facilities"]
PAGES = 3
MAX_LAYERS = 120
MAX_RECORDS = 4000
PAGE = 1000
GOOD_TITLE = re.compile(r"building|facilit|structure|footprint|campus map|bldg", re.I)
EXCLUDE_TITLE = re.compile(r"energy|utility|utilities|meter|consumption|room|floor ?plan|work ?order|staff|"
                           r"employee|people|directory|inspection|permit|projects?|construction|hvac|steam|"
                           r"sewer|storm|water|electric|telecom|fiber|asbestos|lease|deferred|condition", re.I)
UNIVERSITY = re.compile(r"universit|college|\bcampus\b|institute of technology|\bstate u\b|polytechnic", re.I)


def candidates(client, keywords=KEYWORDS, pages=PAGES):
    """The Hub layers whose title and publisher pass (see the module docstring): [{"id", "url", "title",
    "publisher"}]."""
    from placepacks.directories.city_facilities import _json, _layer_url, layer_id
    found = {}
    for word in keywords:
        for page in range(pages):
            url = HUB_SEARCH + "?" + urllib.parse.urlencode({"q": word, "limit": 100, "startindex": 1 + 100 * page})
            feats = _json(client, url).get("features") or []
            for f in feats:
                p = f.get("properties") or {}
                if p.get("type") != "Feature Service" or not p.get("url") or p.get("access") not in (None, "public"):
                    continue
                publisher = " ".join(str(p.get("source") or p.get("orgName") or "").split())
                title = " ".join(str(p.get("title") or "").split())
                if not GOOD_TITLE.search(title) or EXCLUDE_TITLE.search(title) or not UNIVERSITY.search(publisher) \
                        or "@" in publisher:
                    continue
                layer = _layer_url(p["url"])
                found.setdefault(layer_id("arcgis", layer), {"id": layer_id("arcgis", layer), "url": layer,
                                                             "title": title, "publisher": publisher})
            if len(feats) < 100:
                break
    return sorted(found.values(), key=lambda x: x["id"])[:MAX_LAYERS]


def check_layer(client, layer):
    """One record of a layer: adds "fields" ({"name", "address", "id"}) and "geometry", or None when the layer is
    not usable (no name field, people fields, not points or polygons, outside the US, an error)."""
    from placepacks.directories.city_facilities import _json, map_fields, people_layer, state_of
    url = layer["url"] + "/query?" + urllib.parse.urlencode(
        {"where": "1=1", "outFields": "*", "resultRecordCount": 1, "returnGeometry": "true", "outSR": 4326,
         "f": "json"})
    answer = _json(client, url)
    geometry = answer.get("geometryType")
    if geometry not in ("esriGeometryPoint", "esriGeometryPolygon"):
        return None
    names = [f.get("name", "") for f in answer.get("fields") or []]
    if people_layer(names):
        return None
    mapped = map_fields(names)
    if "name" not in mapped:
        return None
    feats = answer.get("features") or []
    at = position((feats[0].get("geometry") or {}) if feats else {})
    if not at or not state_of(*at):
        return None
    return {**layer, "geometry": geometry, "fields": {k: mapped[k] for k in ("name", "address", "id") if k in mapped}}


def position(geom):
    """(lat, lon) of an ArcGIS point or polygon (its first ring's middle), or None."""
    try:
        if "x" in geom:
            return float(geom["y"]), float(geom["x"])
        if geom.get("rings"):
            return features.centroid([[(float(p[1]), float(p[0])) for p in geom["rings"][0]]])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    return None


def layer_rows(client, layer, stats):
    """The building rows of one checked layer (pages of PAGE records, at most MAX_RECORDS)."""
    f = layer["fields"]
    wanted = ",".join(dict.fromkeys(v for v in f.values()))
    offset = 0
    while offset < MAX_RECORDS:
        url = layer["url"] + "/query?" + urllib.parse.urlencode(
            {"where": "1=1", "outFields": wanted, "returnGeometry": "true", "outSR": 4326, "resultOffset": offset,
             "resultRecordCount": PAGE, "f": "json", "geometryPrecision": 6})
        answer = json.loads(client.fetch(url))
        if not isinstance(answer, dict) or "error" in answer:
            raise RequestFailed(f"the layer answered an error: {str(answer.get('error'))[:120]}")
        feats = answer.get("features") or []
        for i, feat in enumerate(feats):
            attrs = feat.get("attributes") or {}
            name = " ".join(str(attrs.get(f["name"]) or "").split())
            at = position(feat.get("geometry") or {})
            if not name or not at or name.lower() in ("null", "none", "unknown", "n/a"):
                continue
            ref = str(attrs.get(f.get("id")) if f.get("id") else offset + i)
            address = " ".join(str(attrs.get(f["address"]) or "").split()) if f.get("address") else ""
            stats["buildings"] = stats.get("buildings", 0) + 1
            yield {"key": f"campusgis:{layer['id'][7:]}:{ref}", "kind": "building", "name": name,
                   "lat": round(at[0], 7), "lon": round(at[1], 7),
                   "notes": f"Address: {address}" if address and address.lower() not in ("null", "none") else "",
                   "org": layer["publisher"], "vendor": "campus-gis", "map_id": layer["url"][:200]}
        if len(feats) < PAGE or not answer.get("exceededTransferLimit", len(feats) == PAGE):
            break
        offset += len(feats)


def collect(client, unit, stats, listing=None):
    """Find the layers and read each (see the module docstring). A layer that refuses or fails is left out (counted
    in stats); the others go on."""
    layers = candidates(client)
    stats["candidates"] = len(layers)
    stats.setdefault("blocked_layers", [])
    stats["layers"] = 0
    for layer in layers:
        try:
            checked = check_layer(client, layer)
            if not checked:
                continue
            stats["layers"] += 1
            yield from layer_rows(client, checked, stats)
        except Blocked as e:
            stats["blocked_layers"].append(f"{layer['url']}: {str(e)[:120]}")
        except (NotFound, RequestFailed, ValueError) as e:
            stats["failed_layers"] = stats.get("failed_layers", 0) + 1
            print(f"campus-gis {layer['url']}: {str(e)[:120]}", flush=True)
