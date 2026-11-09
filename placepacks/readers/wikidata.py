"""Wikidata (CC0): named landmarks, buildings, monuments and institutions with coordinates, and their dates.

Only the item id, the English label, the coordinates, the class of the item and its dates are used, never any
description text (Wikipedia's text is CC BY-SA and is not used). Dates: inception (P571) or start time (P580) start
the record; dissolved, abolished or demolished (P576) or end time (P582) close it, so a pack knows that a building
was there from 1923 to 1998. fetch.py asks the Wikidata Query Service once per region, by bounding box, with a
User-Agent that names the project, and saves the answer (SPARQL JSON); this reader reads that file.
"""

import json

from placepacks import fmt
from placepacks.readers import reader

QUERY = """SELECT ?item ?itemLabel ?coord ?class ?start ?end WHERE {{
  SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({west} {south})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({east} {north})"^^geo:wktLiteral . }}
  ?item wdt:P31 ?class .
  VALUES ?class {{ {classes} }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }} OPTIONAL {{ ?item wdt:P580 ?started . }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved . }} OPTIONAL {{ ?item wdt:P582 ?ended . }}
  BIND(COALESCE(?inception, ?started) AS ?start) BIND(COALESCE(?dissolved, ?ended) AS ?end)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
# Wikidata classes kept, and the pack class of each.
CLASSES = {"Q41176": "building", "Q4989906": "landmark", "Q33506": "landmark", "Q570116": "landmark",
           "Q16970": "landmark", "Q22698": "park", "Q3918": "campus", "Q16917": "campus", "Q7075": "landmark",
           "Q1248784": "business", "Q55488": "transit", "Q12280": "landmark", "Q839954": "landmark",
           "Q483110": "landmark", "Q24398318": "landmark"}


def query_for(region):
    """The SPARQL query for a region's bounding box (Alaska's box spans the 180th meridian: the whole width)."""
    west, south, east, north = region["bbox"]
    classes = " ".join(f"wd:{q}" for q in CLASSES)
    return QUERY.format(west=west, south=south, east=east, north=north, classes=classes)


@reader("wikidata")
def read(path, entry, region, writer):
    """Add the items of a saved SPARQL JSON answer. Returns the number of items."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    count, seen = 0, set()
    for b in data.get("results", {}).get("bindings", []):
        item = b.get("item", {}).get("value", "").rsplit("/", 1)[-1]
        name = b.get("itemLabel", {}).get("value", "")
        coord = b.get("coord", {}).get("value", "")
        if not item.startswith("Q") or not name or name == item or item in seen or not coord.startswith("Point("):
            continue
        try:
            lon, lat = (float(v) for v in coord[6:-1].split())
        except ValueError:
            continue
        cls = CLASSES.get(b.get("class", {}).get("value", "").rsplit("/", 1)[-1], "landmark")
        first = fmt.parse_month(b.get("start", {}).get("value", ""))
        last = fmt.parse_month(b.get("end", {}).get("value", ""))
        seen.add(item)
        writer.add_point(f"wikidata:{item}", entry["id"], name, cls, f"wikidata={item}", lat, lon, first, last)
        count += 1
    return count
