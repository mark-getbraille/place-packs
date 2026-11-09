"""Fine place types: a short, lower-case English phrase for each record ("pizza restaurant", "hardware store",
"catholic church", "lighthouse"), beside its coarse class (cls). The phrases come from each source's own type field
through the tables in types.json (data, not code):

  osm(tags)                    OpenStreetMap or OpenHistoricalMap tags: amenity, shop, cuisine, craft, tourism,
                               leisure, healthcare, man_made, historic, religion and denomination
  naics(code)                  a NAICS code (the longest prefix in the table): business licences
  table(name, value)           a value of one of the tables ("gnis", "fsa")
  humanise(text)               a category as the source writes it ("pizza_restaurant", "Dining > Pizzeria"),
                               made a phrase (Overture, Foursquare, Wikidata, licence and inspection categories)
  most_specific(phrases)       of several phrases for one place, the most specific (a generic "restaurant" loses to
                               "pizza restaurant")
In a pack the phrases are kept once in the "types" table, and each typed point or area points to one (FORMAT.md).
"""

import json
import os
import re

_TABLES = None


def tables():
    """The tables of types.json (read once)."""
    global _TABLES
    if _TABLES is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "types.json"), encoding="utf-8") as f:
            _TABLES = json.load(f)
    return _TABLES


def humanise(text):
    """A phrase from a category as a source writes it: the last part of "A > B > C", underscores and runs of
    spaces made single spaces, lower case, at most 60 characters; "" for nothing useful."""
    text = str(text or "").split(">")[-1]
    text = re.sub(r"[_\s]+", " ", text).strip().lower()
    if not text or text in ("..", "na", "n/a", "none", "other", "unknown", "yes"):
        return ""
    return text[:60]


def _lookup(table, value):
    """The phrase of value in a key -> phrase table ("*" with "{}" for any other value), or ""."""
    if not value:
        return ""
    if value in table:
        return table[value]
    if "*" in table:
        return table["*"].format(humanise(value))
    return ""


def osm(tags):
    """The type phrase of an OpenStreetMap (or OpenHistoricalMap) object's tags, or ""."""
    t = tables()
    amenity = tags.get("amenity", "")
    if amenity == "place_of_worship" or tags.get("building") in ("church", "chapel", "cathedral"):
        denomination = tags.get("denomination", "")
        found = t["denomination"].get(denomination) if denomination else None
        if not found and tags.get("religion") == "christian" and denomination:
            found = f"{humanise(denomination)} church"
        return found or _lookup(t["religion"], tags.get("religion", "")) or "place of worship"
    if amenity in ("restaurant", "fast_food", "cafe") and tags.get("cuisine"):
        cuisine = tags["cuisine"].split(";")[0].strip().lower()
        found = _lookup(t["cuisine"], cuisine)
        if found:
            return found
    for key in ("amenity", "shop", "craft", "healthcare", "tourism", "leisure", "man_made", "historic", "railway",
                "aeroway", "landuse", "natural", "waterway"):
        value = tags.get(key)
        if value and value != "no" and key in t["osm"]:
            found = _lookup(t["osm"][key], value)
            if found:
                return found
    return ""


def naics(code):
    """The phrase of a NAICS code (the longest prefix in the table), or ""."""
    code = re.sub(r"\D", "", str(code or ""))
    table = tables()["naics"]
    for n in range(len(code), 1, -1):
        if code[:n] in table:
            return table[code[:n]]
    return ""


def table(name, value):
    """A value's phrase in one of the tables ("gnis", "fsa", "naics", "cuisine"): the value as it is, else in lower
    case with underscores (the table's "*" pattern for any other value, where it has one), or ""."""
    if name == "naics":
        return naics(value)
    t = tables().get(name, {})
    value = str(value or "").strip()
    return t.get(value) or _lookup(t, value.lower().replace(" ", "_")) if value else ""


def of(spec, value):
    """The phrase of a value by an entry's "type_map": a table name ("naics", "gnis", "fsa", "cuisine"), "humanise", or a
    template such as "{} restaurant" (the value humanised in its place)."""
    if not spec or spec == "humanise":
        return humanise(value)
    if "{}" in spec:
        word = humanise(value)
        return spec.format(word) if word else ""
    return table(spec, value)


def specificity(phrase):
    """How specific a phrase is: 0 for none, 1 for a generic one ("restaurant"), else 2 plus its number of words."""
    if not phrase:
        return 0
    if phrase in set(tables()["generic"]):
        return 1
    return 2 + len(phrase.split())


def most_specific(phrases):
    """The most specific of several phrases for one place ("" when there is none); the first wins a tie."""
    best = ""
    for p in phrases:
        if specificity(p) > specificity(best):
            best = p
    return best
