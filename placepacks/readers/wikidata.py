"""Wikidata (CC0): every named item with coordinates in the region (the "all" mode), or only the classes below, and
their dates.

The "all" mode (fetch "mode": "all") asks for every item with coordinates (P625) in the region's box, tile by tile:
a tile that times out or answers ALL_LIMIT rows is split into four (fetch.py). Each item is typed by the English
label of its class (P31); CLASSES give the pack class of the known classes and the rest are landmarks. Items of the
classes in wikidata_exclude.json are left out (trees, survey points, census tracts, list and disambiguation pages,
astronomical objects, taxa) and so are people (Q5) and private homes, unless a home has a heritage designation
(P1435). The list is data: a class is added to the file, not to the code. With "skip_gnis_copies", an item that only
copies a GNIS record (it has a GNIS id, P590, and no dates or heritage designation) is left to the GNIS layer.

Only the item id, the English label, the coordinates, the class of the item and its dates are used, never any
description text (Wikipedia's text is CC BY-SA and is not used). Dates: inception (P571) or start time (P580) start
the record; dissolved, abolished or demolished (P576) or end time (P582) close it, so a pack knows that a building
was there from 1923 to 1998. fetch.py asks the Wikidata Query Service once per region, by bounding box, with a
User-Agent that names the project, and saves the answer (SPARQL JSON); this reader reads that file.
"""

import json

from placepacks import fmt, types
from placepacks.readers import reader

QUERY = """SELECT ?item ?itemLabel ?coord ?class ?classLabel ?start ?end WHERE {{
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
           "Q483110": "landmark", "Q24398318": "landmark",
           # Lighthouses and light stations; forts, fortifications and military, air, naval and Coast Guard bases and
           # stations (with their inception and closing dates, so a 1960 picture at a base closed in 1995 gets it);
           # national cemeteries (other cemeteries come from GNIS and OpenStreetMap); state parks.
           "Q39715": "landmark", "Q27193297": "landmark", "Q1785071": "landmark", "Q57821": "landmark",
           "Q245016": "campus", "Q18691599": "campus", "Q695850": "campus", "Q1324633": "campus",
           "Q31407679": "landmark", "Q12585720": "cemetery", "Q1761072": "park",
           # Current and former railway stations; ski areas, amusement parks, theatres, cinemas, concert halls, hotels,
           # shopping centres and malls, department stores; factories, mills (grist, saw, water), mines, breweries,
           # trading posts and ghost towns: each with its opening and closing dates when Wikidata has them.
           "Q4663385": "transit", "Q106772341": "transit", "Q130003": "park", "Q3034650": "park",
           "Q194195": "park", "Q24354": "landmark", "Q41253": "business", "Q1060829": "landmark",
           "Q27686": "business", "Q11315": "business", "Q31374404": "business", "Q216107": "business",
           "Q83405": "building", "Q44494": "landmark", "Q623605": "landmark", "Q505213": "landmark",
           "Q185187": "landmark", "Q820477": "landmark", "Q131734": "business", "Q39463": "landmark",
           "Q74047": "settlement",
           # Museums of every kind, galleries, zoos, aquariums, gardens, observatories, memorials and statues,
           # viewpoints, covered bridges, historic houses, castles, national monuments, waterfalls, caves, hot springs,
           # beaches, piers, boardwalks, carousels, roller coasters, water parks, racetracks, arenas, convention centres,
           # casinos, wineries and vineyards, visitor and nature centres, academic libraries.
           "Q207694": "landmark", "Q16735822": "landmark", "Q588140": "landmark", "Q842478": "landmark",
           "Q1007870": "landmark", "Q43501": "park", "Q2281788": "landmark", "Q167346": "park", "Q272231": "park",
           "Q148319": "landmark", "Q1254933": "landmark", "Q5003624": "landmark", "Q179700": "landmark",
           "Q177305": "landmark", "Q6017969": "nature", "Q1825472": "landmark", "Q2087181": "landmark",
           "Q23413": "landmark", "Q893745": "landmark", "Q34038": "nature", "Q35509": "nature", "Q2232001": "nature",
           "Q177380": "nature", "Q40080": "water", "Q863454": "landmark", "Q11111030": "landmark",
           "Q208322": "landmark", "Q204832": "landmark", "Q740326": "park", "Q2338524": "landmark",
           "Q641226": "landmark", "Q1378975": "landmark", "Q133215": "business", "Q156362": "business",
           "Q22715": "business", "Q18411786": "public", "Q1970365": "landmark", "Q1863818": "landmark",
           "Q18704634": "landmark", "Q756102": "landmark", "Q16761700": "park", "Q856234": "public",
           # City halls, courthouses (county courthouses), police and fire stations, post offices, capitols, dead
           # malls (shopping centres and malls are above).
           "Q25550691": "public", "Q1137809": "public", "Q64037785": "public", "Q861951": "public",
           "Q1195942": "public", "Q35054": "public", "Q3284499": "public", "Q1028645": "business",
           # Drive-in theatres, diners, drive-in restaurants, motels, bowling alleys, dude ranches, horse racing venues,
           # fire lookout towers, mountain passes, historic districts, and battles (with their dates).
           "Q786922": "business", "Q1226318": "business", "Q1259350": "business", "Q216212": "business",
           "Q27106471": "business", "Q5615133": "business", "Q11822917": "landmark", "Q748998": "landmark",
           "Q133056": "nature", "Q15243209": "landmark", "Q178561": "landmark",
           # Places to eat and drink (restaurants and their kinds, cafés, bars, pubs, taverns, brewpubs, bakeries,
           # inns, nightclubs); a chain's brand (restaurant chain, Q18534542) is not a place and is not asked for.
           "Q11707": "business", "Q30022": "business", "Q187456": "business", "Q212198": "business",
           "Q274393": "business", "Q3640372": "business", "Q1751429": "business", "Q81799": "business",
           "Q1501212": "business", "Q154250": "business", "Q256020": "business", "Q622425": "business",
           "Q8463304": "business", "Q1311064": "business", "Q19316447": "business", "Q3109696": "business",
           "Q866742": "business", "Q4236467": "business", "Q3231410": "business", "Q17102985": "business",
           "Q858012": "business", "Q24439113": "business", "Q1193068": "business",
           # In the "all" mode: settlements and natural features, so they are not called landmarks.
           "Q486972": "settlement", "Q532": "settlement", "Q3957": "settlement", "Q515": "settlement",
           "Q17343829": "settlement", "Q15127012": "settlement", "Q1093829": "settlement", "Q123705": "settlement",
           "Q8502": "nature", "Q54050": "nature", "Q39816": "nature", "Q46831": "nature", "Q23442": "nature",
           "Q4022": "water", "Q23397": "water", "Q131681": "water", "Q47521": "water", "Q12284": "water",
           "Q355304": "water", "Q166620": "water", "Q187223": "water", "Q39594": "water", "Q1322134": "water",
           "Q39614": "cemetery", "Q2154459": "settlement", "Q498162": "settlement", "Q5084": "settlement",
           "Q751708": "settlement", "Q4421": "nature", "Q166735": "nature", "Q185113": "nature", "Q740445": "nature",
           "Q12719646": "water"}
# Items with a heritage designation (P1435) kept whatever their class: World Heritage Sites (Wikidata's own
# statements, CC0; UNESCO's list itself is CC BY-SA IGO and is not used).
DESIGNATIONS = {"Q9259": "landmark"}
GROUP = 12                      # classes per query, so each query stays well within the 60-second limit
BIG_BOX = 40.0                  # square degrees: a larger region (Texas, Alaska, the Prairie provinces) is asked in
                                # four tiles
DESIGNATION_QUERY = """SELECT ?item ?itemLabel ?coord ?class ?classLabel ?start ?end WHERE {{
  SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({west} {south})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({east} {north})"^^geo:wktLiteral . }}
  ?item wdt:P1435 ?class .
  VALUES ?class {{ {classes} }}
  OPTIONAL {{ ?item wdt:P571 ?inception . }} OPTIONAL {{ ?item wdt:P580 ?started . }}
  OPTIONAL {{ ?item wdt:P576 ?dissolved . }} OPTIONAL {{ ?item wdt:P582 ?ended . }}
  BIND(COALESCE(?inception, ?started) AS ?start) BIND(COALESCE(?dissolved, ?ended) AS ?end)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""


ALL_QUERY = """SELECT ?item ?itemLabel ?coord ?class ?classLabel ?start ?end ?heritage ?gnis WHERE {{
  SERVICE wikibase:box {{ ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point({west} {south})"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point({east} {north})"^^geo:wktLiteral . }}
  OPTIONAL {{ ?item wdt:P31 ?class . }}
  OPTIONAL {{ ?item wdt:P571 ?start . }} OPTIONAL {{ ?item wdt:P576 ?end . }} OPTIONAL {{ ?item wdt:P1435 ?heritage . }}
  OPTIONAL {{ ?item wdt:P590 ?gnis . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT {limit}"""
ALL_LIMIT = 50000               # rows per tile; a tile that fills it is split into four
MIN_TILE = 0.02                 # degrees: a tile this small is not split again


def all_query(box, limit=ALL_LIMIT):
    """The "all" mode query of one tile (west, south, east, north)."""
    west, south, east, north = box
    return ALL_QUERY.format(west=west, south=south, east=east, north=north, limit=limit)


ALL_TILE = 2.0                  # square degrees: the "all" mode starts with tiles this size (Vermont's 5 square
                                # degrees can pass the 60-second limit)


def first_tiles(region, most=ALL_TILE):
    """The region's box in tiles of at most most square degrees (fetch.py splits a tile further when needed)."""
    tiles, out = [tuple(region["bbox"])], []
    while tiles:
        w, s_, e, n = tiles.pop()
        if (e - w) * (n - s_) > most:
            tiles += split_tile((w, s_, e, n))
        else:
            out.append((w, s_, e, n))
    return out


def split_tile(box):
    """A tile's four quarters."""
    w, s_, e, n = box
    mx, my = (w + e) / 2, (s_ + n) / 2
    return [(w, s_, mx, my), (mx, s_, e, my), (w, my, mx, n), (mx, my, e, n)]


_EXCLUDE = None


def exclusions():
    """(classes left out, home classes left out unless designated) from wikidata_exclude.json."""
    global _EXCLUDE
    if _EXCLUDE is None:
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "wikidata_exclude.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        _EXCLUDE = (set(data["exclude"]), set(data["homes"]))
    return _EXCLUDE


def queries_for(region):
    """The SPARQL queries for a region's bounding box (four tiles for a box larger than BIG_BOX): one per group of
    GROUP classes, and one for the designations (World Heritage Sites). fetch.py sends them one after the other and
    saves their answers together (an item found twice is kept once)."""
    west, south, east, north = region["bbox"]
    boxes = [(west, south, east, north)]
    if (east - west) * (north - south) > BIG_BOX:
        mx, my = (west + east) / 2, (south + north) / 2
        boxes = [(west, south, mx, my), (mx, south, east, my), (west, my, mx, north), (mx, my, east, north)]
    ids = list(CLASSES)
    out = []
    for w, s_, e, n in boxes:
        out += [QUERY.format(west=w, south=s_, east=e, north=n, classes=" ".join(f"wd:{q}" for q in ids[i:i + GROUP]))
                for i in range(0, len(ids), GROUP)]
        out.append(DESIGNATION_QUERY.format(west=w, south=s_, east=e, north=n,
                                            classes=" ".join(f"wd:{q}" for q in DESIGNATIONS)))
    return out


def query_for(region):
    """All the region's queries as one text (for reading and the tests)."""
    return "\n\n".join(queries_for(region))


def _qid(b, field):
    """The Q id of a binding's entity field ("" when none)."""
    return b.get(field, {}).get("value", "").rsplit("/", 1)[-1]


@reader("wikidata")
def read(path, entry, region, writer):
    """Add the items of a saved SPARQL JSON answer (an item may come in several rows, one per class). Returns the
    number of items."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = {}
    for b in data.get("results", {}).get("bindings", []):
        item = _qid(b, "item")
        if not item.startswith("Q"):
            continue
        it = items.setdefault(item, {"rows": [], "classes": set(), "heritage": False, "gnis": False, "dated": False})
        it["rows"].append(b)
        it["classes"].add(_qid(b, "class"))
        it["heritage"] = it["heritage"] or bool(b.get("heritage"))
        it["gnis"] = it["gnis"] or bool(b.get("gnis"))
        it["dated"] = it["dated"] or bool(b.get("start") or b.get("end"))
    excluded, homes = exclusions()
    count = 0
    for item, it in items.items():
        if it["classes"] & excluded or (it["classes"] & homes and not it["heritage"]):
            continue                    # people, trees, survey points, ...; homes without a heritage designation
        if entry.get("skip_gnis_copies") and it["gnis"] and not it["dated"] and not it["heritage"]:
            continue                    # a copy of a GNIS record (most streams, summits, cemeteries): GNIS has it
        b = it["rows"][0]
        name = b.get("itemLabel", {}).get("value", "")
        coord = b.get("coord", {}).get("value", "")
        if not name or name == item or not coord.startswith("Point("):
            continue
        try:
            lon, lat = (float(v) for v in coord[6:-1].split())
        except ValueError:
            continue
        # The row of the most useful class: a known one first, then any with an English label.
        known = [r for r in it["rows"] if _qid(r, "class") in CLASSES or _qid(r, "class") in DESIGNATIONS]
        labelled = [r for r in it["rows"] if r.get("classLabel", {}).get("value", "") and
                    not r["classLabel"]["value"].startswith("Q")]
        best = (known or labelled or it["rows"])[0]
        qid = _qid(best, "class")
        cls = CLASSES.get(qid) or DESIGNATIONS.get(qid) or "landmark"
        first = min((m for m in (fmt.parse_month(r.get("start", {}).get("value", "")) for r in it["rows"]) if m),
                    default=None)
        last = max((m for m in (fmt.parse_month(r.get("end", {}).get("value", "")) for r in it["rows"]) if m),
                   default=None)
        # The fine type: the English label of the class the item is an instance of ("lighthouse", "fort").
        label = best.get("classLabel", {}).get("value", "")
        kind = types.humanise(label) if label and label != qid else None
        writer.add_point(f"wikidata:{item}", entry["id"], name, cls, f"wikidata={item}", lat, lon, first, last,
                         type=kind or None)
        count += 1
    return count
