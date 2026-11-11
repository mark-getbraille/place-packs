"""Places from a list: read a list of places (pasted from a chat, a CSV or Excel file, a SQLite database or a .sql
file), find each place's position on this computer, and save or export lists of places.

This same file is used by two programs (Photo Location Identifier, pli/placelist.py, and the Digital Accessibility
Toolkit, app/toolkit/vision/placelist.py); keep the two copies the same. It needs only the standard library, plus
openpyxl for .xlsx files and the placepacks package for finding addresses.

Nothing here goes on the internet, and nothing is written anywhere but the files the caller names. Only a place's
name and its address or position are kept from a list: phone numbers, e-mail addresses, web addresses and people's
names are never read into a Row.

  Row                    one place of a list: name, street, city, state, zip, country, lat, lon (and metres and
                         list, for lists exported by these programs), where (e.g. "line 12"), status and why
  parse_pasted(text)     Rows from pasted text: Markdown tables, bulleted or numbered lists ("**Name**: address",
                         "Name - address", "Name, 123 Main St, Springfield, IL 62701", the name on one line and the
                         address on the next), CSV or tab-separated text, or plain lines
  split_address(text)    {"name", "street", "city", "state", "zip", "country"} from "123 Main St, Springfield, IL"
  read_file(path, table) Rows of a .csv, .tsv, .txt, .xlsx, SQLite database or .sql file (streamed)
  sqlite_tables(path)    the tables of a database (or .sql file) that hold places, best first, for a choice
  load_sql(path)         a .sql file loaded safely into an in-memory database: only CREATE TABLE and INSERT run
  Locator                finds positions for Rows without one, in the place packs (read-only): the NAD address
                         points, then the TIGER address ranges, then a name search in the town
  PlaceGrid              a grid index of positions, so finding the place near a point stays fast with 150,000 places
  find_duplicates        marks the Rows that are already in My places (or twice in the list)
  export_places          write places to a SQLite database, a .sql file or a .csv file
"""

import csv
import io
import json
import math
import os
import re
import sqlite3
import urllib.parse

LIST_RADIUS_M = 60.0            # a place from a list names a picture taken this close to it
DUPLICATE_M = 100.0             # the same name this close: the same place
EXPORT_TABLE = "my_places"
EXPORT_COLUMNS = ("name", "latitude", "longitude", "metres", "list")
SQLITE_ENDINGS = (".db", ".sqlite", ".sqlite3", ".db3")
TEXT_ENDINGS = (".csv", ".tsv", ".txt", ".tab")

# ------------------------------------------------------------------------------------------- column names

# The columns recognised (any capitals; spaces, dashes, dots, slashes and underscores count as spaces). The first
# name column found in this order is used, so "Company" wins over "Name" (which can be a person in a contacts file).
ALIASES = {
    "name": ["business name", "company name", "company", "business", "organization name", "organisation name",
             "organization", "organisation", "organization 1 name", "place name", "place", "location name",
             "school name", "school", "facility name", "facility", "venue", "store name", "store", "site name",
             "site", "branch name", "branch", "institution", "agency", "library", "name"],
    "street": ["street address", "address line 1", "address 1", "address1", "street 1", "street1", "street",
               "address", "addr", "full address", "mailing address", "physical address", "location",
               "business street", "company street"],
    "city": ["city", "town", "locality", "municipality", "business city", "company city", "city town"],
    "state": ["state", "state province", "province", "region", "st", "business state", "company state",
              "state code"],
    "zip": ["zip", "zip code", "zipcode", "postal code", "postal", "postcode", "post code", "zip postal code",
            "business postal code"],
    "country": ["country", "country region", "country code"],
    "lat": ["latitude", "lat", "y"],
    "lon": ["longitude", "lon", "lng", "long", "x"],
    "metres": ["metres", "meters", "radius", "radius m", "radius metres", "radius meters"],
    "list": ["list", "my places list"],
}
# Columns that hold a person's name: when one is there, a column called just "Name" is a person, not a place.
PERSON_COLUMNS = {"first name", "last name", "full name", "given name", "family name", "middle name", "contact name",
                  "first", "last", "surname"}


def header_key(text):
    """A column name as it is compared: "Address_Line-1" -> "address line 1"."""
    return " ".join(re.sub(r"[^0-9a-z#]+", " ", str(text or "").lower()).split())


def map_headers(headers):
    """{field: column index} of the recognised columns of a header row (see ALIASES); {} if none."""
    keys = [header_key(h) for h in headers]
    persons = any(k in PERSON_COLUMNS for k in keys)
    out = {}
    for field, names in ALIASES.items():
        for alias in names:
            if field == "name" and alias == "name" and persons:
                continue
            if alias in keys:
                i = keys.index(alias)
                if i not in out.values():
                    out[field] = i
                    break
    if "lat" in out and "lon" not in out:
        del out["lat"]
    if "lon" in out and "lat" not in out:
        del out["lon"]
    return out


def looks_like_header(headers):
    """True if a row is a header row of a list of places (a name or address column, and one more)."""
    m = map_headers(headers)
    return ("name" in m or "street" in m) and len(m) >= 2


# ------------------------------------------------------------------------------------------- a row

class Row:
    """One place of a list. Only the place's name, its address and its position are kept. status: "" (not yet
    looked at), "located", "not located" or "duplicate"; why: the reason in words; found_by: how it was located
    ("position in the list", "address point", "address range", "name in the town")."""

    __slots__ = ("name", "street", "city", "state", "zip", "country", "lat", "lon", "metres", "list", "where",
                 "status", "why", "found_by")

    def __init__(self, name="", street="", city="", state="", zip="", country="", lat=None, lon=None,  # noqa: A002
                 metres=None, list="", where=""):  # noqa: A002
        """Store the fields, tidied: spaces collapsed, Markdown removed, a position checked."""
        self.name = tidy(name)
        self.street, self.city = tidy(street), tidy(city)
        self.state, self.zip, self.country = tidy(state), tidy(zip), tidy(country)
        self.lat, self.lon = _position(lat, lon)
        self.metres = _number(metres)
        self.list = tidy(list)
        self.where = where
        self.status, self.why, self.found_by = "", "", ""

    @property
    def located(self):
        """True if the row has a position."""
        return self.lat is not None and self.lon is not None

    def address(self):
        """"123 Main St, Springfield, IL 62701" (the parts known)."""
        tail = " ".join(p for p in (self.state, self.zip) if p)
        return ", ".join(p for p in (self.street, self.city, tail) if p)

    def line(self):
        """The review list's line: "Name — address — located" (or "not located: why")."""
        where = self.address() or (f"{self.lat:.5f}, {self.lon:.5f}" if self.located else "no address")
        state = self.status or ("located" if self.located else "not located")
        if self.status == "not located" and self.why:
            state = f"not located: {self.why}"
        elif self.status == "duplicate":
            state = f"duplicate: {self.why}" if self.why else "duplicate"
        return f"{self.name or '(no name)'} — {where} — {state}"

    def __repr__(self):
        """For test messages."""
        return f"Row({self.name!r}, {self.address()!r}, {self.lat}, {self.lon}, {self.status!r})"


def _number(value):
    """A float from a cell ("36.01", 36.01, "") or None."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def _position(lat, lon):
    """(lat, lon) as floats if both are a position on the earth (not 0, 0), else (None, None)."""
    lat, lon = _number(lat), _number(lon)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None, None
    return lat, lon


# ------------------------------------------------------------------------------------------- tidying text

_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)[^\s)\]>|]+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:(?<=\s)|^|(?<=[,;:(]))(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}(?:\s*(?:x|ext\.?)"
                    r"\s*\d+)?(?!\d)")
_BOLD = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC = re.compile(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])")


def strip_markdown(text):
    """Text without Markdown bold, italics, code marks, headings, quotes and links ("[text](url)" keeps the text)."""
    text = _LINK.sub(r"\1", str(text or ""))
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC.sub(r"\2", text)
    text = text.replace("`", "")
    text = re.sub(r"^\s*(#{1,6}|>+)\s*", "", text)
    return text


def strip_contacts(text):
    """Text without web addresses, e-mail addresses and phone numbers (and the labels left before them)."""
    text = _URL.sub(" ", text)
    text = _EMAIL.sub(" ", text)
    text = _PHONE.sub(" ", text)
    text = re.sub(r"\b(phone|tel|telephone|fax|e-?mail|website|web|url|call|visit)\s*:?\s*(?=$|[,;|)\]])", " ", text,
                  flags=re.I)
    return re.sub(r"[(\[][\s,;:]*[)\]]", " ", text)


def tidy(text):
    """Text for a field: Markdown and contact details removed, spaces collapsed, stray separators trimmed."""
    text = strip_contacts(strip_markdown("" if text is None else str(text)))
    text = " ".join(text.replace(" ", " ").split())
    return text.strip(" ,;:|-–—•*\t").strip()


# ------------------------------------------------------------------------------------------- addresses

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR", "guam": "GU", "us virgin islands": "VI",
    "american samoa": "AS", "northern mariana islands": "MP",
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB", "new brunswick": "NB",
    "newfoundland and labrador": "NL", "nova scotia": "NS", "ontario": "ON", "prince edward island": "PE",
    "quebec": "QC", "saskatchewan": "SK", "northwest territories": "NT", "nunavut": "NU", "yukon": "YT",
}
STATE_CODES = set(STATES.values())
COUNTRY_WORDS = {"usa", "us", "u s", "u s a", "united states", "united states of america", "canada"}
_ZIP = r"(?:\d{5}(?:-\d{4})?|[A-Z]\d[A-Z] ?\d[A-Z]\d)"
_HOUSE = re.compile(r"^\d+[A-Za-z]?(?:[-/]\d+[A-Za-z]?)?\s+\S")
_UNIT = re.compile(r"^(suite|ste|unit|apt|apartment|#|room|rm|floor|fl|bldg|building|dept|po box|p o box)\b\.?",
                   re.I)
STREET_TYPES = {
    "street": "st", "st": "st", "str": "st", "avenue": "ave", "ave": "ave", "av": "ave", "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr", "boulevard": "blvd", "blvd": "blvd", "lane": "ln", "ln": "ln", "court": "ct",
    "ct": "ct", "place": "pl", "pl": "pl", "highway": "hwy", "hwy": "hwy", "parkway": "pkwy", "pkwy": "pkwy",
    "circle": "cir", "cir": "cir", "terrace": "ter", "ter": "ter", "trail": "trl", "trl": "trl", "way": "way",
    "square": "sq", "sq": "sq", "expressway": "expy", "expy": "expy", "freeway": "fwy", "fwy": "fwy",
    "pike": "pike", "turnpike": "tpke", "tpke": "tpke", "route": "rte", "rte": "rte", "rt": "rte", "plaza": "plz",
    "plz": "plz", "alley": "aly", "aly": "aly", "crossing": "xing", "xing": "xing", "point": "pt", "pt": "pt",
    "loop": "loop", "row": "row", "run": "run", "path": "path", "pass": "pass", "walk": "walk", "center": "ctr",
    "ctr": "ctr", "mall": "mall", "bypass": "byp", "byp": "byp", "causeway": "cswy", "estates": "est",
}
DIRECTIONS = {"north": "n", "n": "n", "south": "s", "s": "s", "east": "e", "e": "e", "west": "w", "w": "w",
              "northeast": "ne", "ne": "ne", "northwest": "nw", "nw": "nw", "southeast": "se", "se": "se",
              "southwest": "sw", "sw": "sw"}
ORDINALS = {"first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
            "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th"}
OTHER_WORDS = {"saint": "st", "mount": "mt", "fort": "ft", "us": "us", "u s": "us", "state": "state",
               "county": "co", "co": "co"}


def state_code(text):
    """"IL" for "IL", "Ill." is not known; "Illinois" -> "IL"; "" if text is not a state or province."""
    t = header_key(text).replace("#", "")
    if t.upper() in STATE_CODES and len(t) == 2:
        return t.upper()
    return STATES.get(t, "")


def _state_zip(part):
    """(state code, zip, rest before them) of the end of an address part: "IL 62701", "Illinois", "Springfield IL
    62701"; None if it does not end with a state or a ZIP code."""
    part = part.strip().rstrip(".")
    m = re.match(rf"^(?P<rest>.*?)[\s,]*(?P<zip>{_ZIP})$", part)
    zip_code, rest = "", part
    if m:
        zip_code, rest = m.group("zip"), m.group("rest").strip()
    words = rest.split()
    for n in (4, 3, 2, 1):
        if len(words) >= n:
            code = state_code(" ".join(words[-n:]))
            if code and not (n == 1 and len(words[-1]) == 2 and words[-1] != words[-1].upper() and len(words) > 1):
                return code, zip_code, " ".join(words[:-n])
    if zip_code and not rest:
        return "", zip_code, ""
    return None


def _cut_street_and_city(text):
    """("123 Main St", "Springfield") from "123 Main St Springfield" (the city after the last street-type word)."""
    words = text.split()
    for i in range(len(words) - 1, 0, -1):
        if words[i].lower().rstrip(".") in STREET_TYPES and i < len(words) - 1:
            return " ".join(words[:i + 1]), " ".join(words[i + 1:])
    return text, ""


def split_address(text):
    """The parts of a place and its address written on one line: {"name", "street", "city", "state", "zip",
    "country"} ("" for each part not found). "Springfield School, 123 Main St, Springfield, IL 62701" gives the
    name "Springfield School"; "Main Street Diner, Springfield, IL" gives a name, city and state only."""
    out = dict(name="", street="", city="", state="", zip="", country="")
    parts = [p.strip() for p in re.split(r"[,;\n]", tidy(text)) if p.strip()]
    if parts and header_key(parts[-1]) in COUNTRY_WORDS:
        out["country"] = "US" if header_key(parts[-1]) != "canada" else "CA"
        parts.pop()
    parts = [p for p in parts if not _UNIT.match(p)]
    if not parts:
        return out
    found = _state_zip(parts[-1])
    city_at = None
    if found is not None:
        out["state"], out["zip"], rest = found
        if rest:
            parts[-1] = rest
            city_at = len(parts) - 1
        else:
            parts.pop()
            city_at = len(parts) - 1 if parts else None
    street_at = next((i for i, p in enumerate(parts) if _HOUSE.match(p) and not re.match(r"^\d+\s*(st|nd|rd|th)\b", p,
                                                                                         re.I)), None)
    if street_at is None:
        street_at = next((i for i, p in enumerate(parts) if _HOUSE.match(p)), None)
    if street_at is None:
        # "Riverside Diner 9 River Road" (no comma between the name and the street): the street starts at a
        # number followed by words that end in a street type.
        for i, p in enumerate(parts):
            m = re.search(r"^(?P<name>.*?\D)\s+(?P<street>\d{1,6}[A-Za-z]?\s+[A-Za-z].*)$", p)
            if m and any(w.lower().rstrip(".") in STREET_TYPES for w in m.group("street").split()[1:]):
                parts[i:i + 1] = [m.group("name").strip(), m.group("street").strip()]
                if city_at is not None and city_at >= i:
                    city_at += 1
                street_at = i + 1
                break
    if street_at is not None:
        out["street"] = parts[street_at]
        if city_at is not None and city_at == street_at:
            # "123 Main St Springfield" before the state: the city is after the street-type word.
            out["street"], out["city"] = _cut_street_and_city(parts[street_at])
        elif city_at is not None and city_at > street_at:
            out["city"] = parts[city_at]
        elif city_at is None and street_at + 1 < len(parts):
            out["city"] = parts[street_at + 1]
        out["name"] = ", ".join(parts[:street_at])
    elif city_at is not None:
        out["city"] = parts[city_at]
        out["name"] = ", ".join(parts[:city_at])
    else:
        out["name"] = ", ".join(parts)
    if out["city"] and _UNIT.match(out["city"]):
        out["city"] = ""
    return out


def street_key(street):
    """A street written the same way whatever the source: "123 North Main Street, Suite 4" -> ("123", "n main st");
    returns (house number, street words)."""
    s = str(street or "").lower().replace(".", " ").replace(",", " ").replace("#", " # ")
    s = re.split(r"\b(?:suite|ste|unit|apt|apartment|room|rm|floor|fl|bldg)\b| # ", s)[0]
    words = s.split()
    number = ""
    if words and re.match(r"^\d", words[0]):
        number = words.pop(0)
        if words and re.fullmatch(r"[a-dfg-mo-rt-vx-z]|\d/\d", words[0]) and len(words) > 1:  # "123 B Main St"
            words.pop(0)
    out = []
    for w in words:
        w = ORDINALS.get(w, w)
        out.append(STREET_TYPES.get(w) or DIRECTIONS.get(w) or OTHER_WORDS.get(w) or w)
    return number, " ".join(out)


def street_core(words):
    """The street's own name without its type and directions: "n main st" -> "main"."""
    parts = [w for w in words.split() if w not in DIRECTIONS.values()]
    while len(parts) > 1 and parts[-1] in STREET_TYPES.values():
        parts.pop()
    return " ".join(parts)


def house_number(text):
    """123 for "123", "123A", "123-125"; None if there is no number."""
    m = re.match(r"^(\d+)", str(text or "").strip())
    return int(m.group(1)) if m else None


def name_key(name):
    """A name as it is compared for duplicates: letters and digits only, lower case."""
    return re.sub(r"[^0-9a-z]+", "", str(name or "").lower())


_TOWN_KEYS = {}


def town_key(name):
    """A town's name as compared: "St. Louis" -> "st louis", "Saint Louis" -> "st louis"."""
    key = _TOWN_KEYS.get(name)
    if key is None:
        words = header_key(name).replace("#", "").split()
        key = " ".join(OTHER_WORDS.get(w, w) if w in ("saint", "mount", "fort") else w for w in words)
        if len(_TOWN_KEYS) < 200_000:
            _TOWN_KEYS[name] = key
    return key


# ------------------------------------------------------------------------------------------- pasted text

_BULLET = re.compile(r"^(?P<indent>\s*)(?:[-*+•●▪◦‣]|\d{1,4}[.)]|[a-zA-Z][.)](?=\s))\s+(?P<text>.*)$")
_TABLE_RULE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
_LABEL = re.compile(r"^\s*(?:[-*+•]\s*)?(?P<label>[A-Za-z][A-Za-z /]{1,30}?)\s*:\s*(?P<value>.*)$")
_COORDS = re.compile(r"(?<![\d.])(-?\d{1,2}\.\d{2,})\s*[,;/ ]\s*(-?\d{1,3}\.\d{2,})(?![\d.])")
FIELD_LABELS = {"address": "street", "street": "street", "street address": "street", "location": "street",
                "addr": "street", "where": "street", "city": "city", "town": "city", "state": "state",
                "zip": "zip", "zip code": "zip", "postal code": "zip", "country": "country",
                "coordinates": "coords", "coords": "coords", "gps": "coords", "lat/long": "coords",
                "lat/lon": "coords", "latitude": "lat", "longitude": "lon", "name": "name"}
SKIP_LABELS = {"phone", "tel", "telephone", "fax", "email", "e-mail", "website", "web", "url", "hours", "contact",
               "principal", "director", "manager", "owner", "notes", "note", "description", "grades", "type",
               "category", "rating", "price", "services", "programs", "enrollment", "founded", "why", "about",
               "specialty", "contact person", "head", "superintendent"}


def parse_pasted(text):
    """The Rows of text pasted from a chat answer, a web page or a spreadsheet (see the module docstring). Each Row's
    where is "line N" of the pasted text."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows, i, loose = [], 0, []
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and line.count("|") >= 2:
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            rows += _parse_table(lines[i:j], i + 1)
            i = j
            continue
        loose.append((i + 1, line))
        i += 1
    rows += _parse_loose(loose)
    rows.sort(key=lambda r: int(r.where.split()[-1]) if r.where.split()[-1].isdigit() else 0)
    return rows


def _cells(line, delimiter="|"):
    """The cells of a Markdown table row."""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split(delimiter)]


def _parse_table(lines, first_line):
    """Rows of a Markdown table (lines starting with "|"); first_line: the number of its first line."""
    body = [(first_line + k, line) for k, line in enumerate(lines) if not _TABLE_RULE.match(line.strip())]
    if not body:
        return []
    header = [strip_markdown(c) for c in _cells(body[0][1])]
    mapping = map_headers(header)
    if mapping:
        body = body[1:]
    else:
        # No header we know: the first column is the name and the rest is the address.
        mapping = {}
    rows = []
    for number, line in body:
        cells = _cells(line)
        if not any(c.strip() for c in cells):
            continue
        if mapping:
            row = _row_from_cells(cells, mapping, f"line {number}")
            if "name" not in mapping and cells:
                first = next((k for k in range(len(cells)) if k not in mapping.values() and cells[k].strip()
                              and not re.fullmatch(r"\d+\.?", cells[k].strip())), None)
                if first is not None:
                    row.name = tidy(cells[first])
        else:
            cells = [c for c in cells if c.strip() and not re.fullmatch(r"\d+\.?", c.strip())]
            row = _row_from_text(", ".join(cells), f"line {number}")
        if row is not None and (row.name or row.street or row.located):
            rows.append(row)
    return rows


def _row_from_cells(cells, mapping, where):
    """A Row from the cells of a table or CSV row and its {field: index}."""
    def get(field):
        i = mapping.get(field)
        return cells[i] if i is not None and i < len(cells) and cells[i] is not None else ""
    row = Row(name=get("name"), street=get("street"), city=get("city"), state=get("state"), zip=get("zip"),
              country=get("country"), lat=get("lat"), lon=get("lon"), metres=get("metres"), list=get("list"),
              where=where)
    _complete_address(row)
    return row


def _complete_address(row):
    """A whole address in one column ("123 Main St, Springfield, IL 62701") is split into its parts; a state
    written out ("Illinois") becomes its code."""
    if row.street and ("," in row.street or not row.city) and not row.located:
        parts = split_address(row.street)
        if parts["street"] or parts["city"]:
            row.street = parts["street"] or ("" if parts["city"] else row.street)
            row.city = row.city or parts["city"]
            row.state = row.state or parts["state"]
            row.zip = row.zip or parts["zip"]
            row.country = row.country or parts["country"]
    if row.state and len(row.state) > 2:
        row.state = state_code(row.state) or row.state
    if row.zip and re.fullmatch(r"\d{3,4}", row.zip):              # a spreadsheet dropped the leading zeros
        row.zip = row.zip.zfill(5)


def _row_from_text(text, where):
    """A Row from one entry written as text ("**Name** - 123 Main St, Springfield, IL"), or None if it has no
    name, address or position."""
    raw = _LINK.sub(r"\1", text.strip())
    coords = _COORDS.search(raw)
    lat = lon = None
    if coords:
        lat, lon = coords.group(1), coords.group(2)
        raw = (raw[:coords.start()] + raw[coords.end():]).strip()
    name, rest = "", raw
    m = re.match(r"^\s*(\*\*|__)(?P<name>.+?)\1\s*(?P<rest>.*)$", raw)
    if m:
        name, rest = m.group("name"), m.group("rest")
    else:
        for sep in (" — ", " – ", " -- ", " - ", " | ", "\t"):
            if sep in raw:
                left, right = raw.split(sep, 1)
                if left.strip() and not _HOUSE.match(left.strip()):
                    name, rest = left, right
                    break
        else:
            label = re.match(r"^(?P<name>[^:]{2,80}):\s+(?P<rest>.+)$", raw)
            if label and not re.search(r"\d", label.group("name")) and \
                    header_key(label.group("name")) not in FIELD_LABELS:
                name, rest = label.group("name"), label.group("rest")
    rest = tidy(strip_contacts(strip_markdown(rest)))
    rest = re.sub(r"\(\s*\)", "", rest).strip(" ,;:-–—")
    if name:
        parts = split_address(rest)
        if not (parts["street"] or parts["city"]) and rest:
            parts = split_address(f"{name}, {rest}")
            name = parts["name"] or name
        else:
            name = f"{name}, {parts['name']}" if parts["name"] and not parts["street"] and not parts["city"] else name
    else:
        parts = split_address(rest)
        name = parts["name"]
    row = Row(name=name, street=parts["street"], city=parts["city"], state=parts["state"], zip=parts["zip"],
              country=parts["country"], lat=lat, lon=lon, where=where)
    if row.state and len(row.state) > 2:
        row.state = state_code(row.state) or row.state
    if not (row.name or row.street or row.located):
        return None
    return row


def _looks_like_address(text):
    """True if a line is an address on its own: "123 Main St, Springfield, IL 62701" or "Springfield, IL 62701"."""
    t = tidy(text)
    if not t:
        return False
    parts = split_address(t)
    return bool((parts["street"] and not parts["name"]) or (parts["city"] and parts["state"] and not parts["name"]))


def _parse_loose(numbered):
    """Rows of the lines outside tables: CSV or tab-separated text with a header, else list items and lines."""
    text_lines = [(n, text_line) for n, text_line in numbered if text_line.strip()]
    if not text_lines:
        return []
    # Tab-separated (from a spreadsheet) or CSV with a header row we know.
    for delimiter in ("\t", ",", ";"):
        if delimiter == "\t" and sum("\t" in t for _, t in text_lines) < max(1, len(text_lines) // 2):
            continue
        for k, (n, line) in enumerate(text_lines[:5]):
            if delimiter not in line:
                continue
            header = next(csv.reader([line], delimiter=delimiter))
            if looks_like_header(header):
                mapping = map_headers(header)
                out = []
                for n2, line2 in text_lines[k + 1:]:
                    if delimiter not in line2:
                        continue
                    cells = next(csv.reader([line2], delimiter=delimiter))
                    row = _row_from_cells(cells, mapping, f"line {n2}")
                    if row.name or row.street or row.located:
                        out.append(row)
                rest = [(n3, l3) for n3, l3 in numbered if n3 < n]
                return _parse_items(rest) + out
        if delimiter == "\t":
            # Tabs without a header we know: each line is "name<TAB>address...".
            return _parse_items([(n, t.replace("\t", " - ", 1).replace("\t", ", ")) for n, t in numbered])
    return _parse_items(numbered)


def _parse_items(numbered):
    """Rows of list items (bulleted, numbered) and plain lines, with the details written under an item ("Address:
    ...", an address on the next line) added to it."""
    has_bullets = any(_BULLET.match(t) for _, t in numbered)
    rows, current, current_indent = [], None, 0

    def finish():
        nonlocal current
        if current is not None:
            _complete_address(current)
            if current.name or current.street or current.located:
                rows.append(current)
        current = None

    for number, line in numbered:
        if not line.strip():
            if current is not None and not current.street and not current.city and not current.located:
                continue                 # a blank line between a name and its address
            finish()
            continue
        stripped = line.strip()
        if re.match(r"^#{1,6}\s", stripped) or re.fullmatch(r"[-*_=]{3,}", stripped):
            finish()
            continue
        bullet = _BULLET.match(line)
        content = bullet.group("text") if bullet else stripped
        indent = len(bullet.group("indent").expandtabs(4)) if bullet else len(line) - len(line.lstrip())
        label = _LABEL.match(strip_markdown(content))
        if label and current is not None:
            key = header_key(label.group("label")).replace("#", "").strip()
            key = {"lat long": "lat/long", "lat lon": "lat/lon", "e mail": "email"}.get(key, key)
            if key in SKIP_LABELS or key in ("email", "e mail"):
                continue
            if key in FIELD_LABELS:
                _add_field(current, FIELD_LABELS[key], label.group("value"))
                continue
        if current is not None and (not bullet or indent > current_indent) and not current.located and \
                not (current.street and current.city) and (_looks_like_address(content) or _COORDS.search(content)):
            _add_field(current, "street", content)
            continue
        if current is not None and bullet and indent > current_indent:
            continue                    # another detail under the item (a description): not a place
        if has_bullets and not bullet and not _looks_like_address(content) and not re.match(r"^\s*(\*\*|__)", content):
            finish()
            continue                    # a sentence before or after the list ("Here are five schools in ...")
        if stripped.endswith(":") and not re.match(r"^\s*(?:[-*+•]|\d+[.)])?\s*(\*\*|__).+(\*\*|__):$", stripped):
            finish()
            continue                    # an introduction or a group heading
        finish()
        row = _row_from_text(content, f"line {number}")
        if row is None:
            continue
        current, current_indent = row, indent
        if not has_bullets and (row.street or row.located or row.city):
            finish()
    finish()
    return [r for r in rows if not _is_sentence(r)]


def _is_sentence(row):
    """True for a Row that is only a sentence of the chat ("Let me know if you want more!"), not a place."""
    if row.street or row.city or row.located:
        return False
    words = row.name.split()
    return len(words) > 8 or row.name.endswith(("?", "!")) or (row.name.endswith(".") and len(words) > 4)


def _add_field(row, field, value):
    """Add a detail written under an item to its Row."""
    value = tidy(value)
    if not value:
        return
    if field == "coords" or (field == "street" and _COORDS.search(value) and not _HOUSE.match(value)):
        m = _COORDS.search(value)
        if m:
            row.lat, row.lon = _position(m.group(1), m.group(2))
        return
    if field in ("lat", "lon"):
        setattr(row, field, _number(value))
        row.lat, row.lon = _position(row.lat, row.lon)
        return
    if field == "street":
        parts = split_address(value)
        if parts["street"] or parts["city"]:
            row.street = row.street or parts["street"]
            row.city = row.city or parts["city"]
            row.state = row.state or parts["state"]
            row.zip = row.zip or parts["zip"]
        return
    if field == "name":
        row.name = row.name or value
        return
    if not getattr(row, field):
        setattr(row, field, value)


# ------------------------------------------------------------------------------------------- files

def read_file(path, table=None, progress=None):
    """The Rows of a file, one at a time (a list of 150,000 places is never all in memory as text): .csv, .tsv and
    .txt (any column layout with a header row we know; otherwise read like pasted text), .xlsx (the first sheet with
    a header row we know), a SQLite database or a .sql file (table: the table to read; None: the best one).
    progress(done, total) is called now and then (total may be 0 when it is not known)."""
    low = path.lower()
    if low.endswith(".xlsx") or low.endswith(".xlsm"):
        yield from _read_xlsx(path, progress)
    elif low.endswith(".sql"):
        con, _stats = load_sql(path)
        try:
            yield from _read_sqlite_con(con, table, progress)
        finally:
            con.close()
    elif low.endswith(SQLITE_ENDINGS) or is_sqlite_file(path):
        con = open_database(path)
        try:
            yield from _read_sqlite_con(con, table, progress)
        finally:
            con.close()
    else:
        yield from _read_text(path, progress)


def is_sqlite_file(path):
    """True if a file starts like a SQLite database."""
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _read_text(path, progress=None):
    """Rows of a CSV, tab-separated or plain text file."""
    size = os.path.getsize(path) or 1
    with open(path, "rb") as fb:
        head = fb.read(65536)
    encoding = "utf-8-sig"
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start < len(head) - 4:
            encoding = "cp1252"
    sample = head.decode(encoding, "replace")
    first = next((t for t in sample.splitlines() if t.strip()), "")
    delimiter = max(("\t", ",", ";", "|"), key=first.count) if first else ","
    with open(path, newline="", encoding=encoding, errors="replace") as f:
        raw = f.buffer                  # its position (bytes read so far) is the progress
        reader = csv.reader(f, delimiter=delimiter)
        header = None
        for header in reader:
            if any(c.strip() for c in header):
                break
        if header is None or not looks_like_header(header):
            f.seek(0)
            yield from parse_pasted(f.read())
            return
        mapping = map_headers(header)
        for n, cells in enumerate(reader, start=2):
            if not any(c.strip() for c in cells):
                continue
            row = _row_from_cells(cells, mapping, f"line {n}")
            if row.name or row.street or row.located:
                yield row
            if progress and n % 2000 == 0:
                progress(min(raw.tell(), size), size)
        if progress:
            progress(size, size)


def _read_xlsx(path, progress=None):
    """Rows of the first sheet of an Excel workbook with a header row we know (in its first 10 rows)."""
    try:
        import openpyxl
    except ImportError:
        raise ValueError("Excel files cannot be read: the openpyxl part of the program is missing. Save the sheet "
                         "as a CSV file (File, Save As, CSV) and open that instead.") from None
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book.worksheets:
            rows = sheet.iter_rows(values_only=True)
            mapping, at = None, 0
            for at, cells in enumerate(rows, start=1):
                cells = ["" if c is None else str(c) for c in cells]
                if looks_like_header(cells):
                    mapping = map_headers(cells)
                    break
                if at >= 10:
                    break
            if not mapping:
                continue
            total = sheet.max_row or 0
            for n, cells in enumerate(rows, start=at + 1):
                cells = ["" if c is None else str(c) for c in cells]
                if not any(c.strip() for c in cells):
                    continue
                row = _row_from_cells(cells, mapping, f"{sheet.title} row {n}")
                if row.name or row.street or row.located:
                    yield row
                if progress and n % 2000 == 0:
                    progress(n, total)
            return
        raise ValueError("No sheet of this workbook has a header row with a name or an address column (such as "
                         "Name, Address, City, State, ZIP, Latitude, Longitude).")
    finally:
        book.close()


def open_database(path):
    """A SQLite database opened read-only (it is never changed)."""
    uri = "file:" + urllib.parse.quote(os.path.abspath(path).replace("\\", "/")) + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
        con.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error as e:
        raise ValueError(f"{os.path.basename(path)} could not be opened as a SQLite database ({e}).") from None
    return con


class TableInfo:
    """A table of a database that holds places: name, columns ([column names]), mapping ({field: index}) and rows
    (how many)."""

    def __init__(self, name, columns, mapping, rows):
        """Store the fields."""
        self.name, self.columns, self.mapping, self.rows = name, columns, mapping, rows

    def label(self):
        """"business (12,345 rows: name, street, city, state, zip, latitude, longitude)"."""
        used = ", ".join(self.columns[i] for _f, i in sorted(self.mapping.items(), key=lambda kv: kv[1]))
        return f"{self.name} ({self.rows:,} rows: {used})"

    def score(self):
        """Better tables first: with positions, with streets, with more rows."""
        m = self.mapping
        return ("lat" in m, "street" in m, "city" in m, self.rows)


def _quote(name):
    """A table or column name quoted for SQL."""
    return '"' + str(name).replace('"', '""') + '"'


def tables_of(con):
    """[TableInfo] of the tables (and views) of a connection that hold places (a name column and a position, street
    or city column), best first."""
    found = []
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE "
                               "'sqlite_%' ORDER BY name").fetchall():
        try:
            columns = [r[0] for r in con.execute(f"SELECT * FROM {_quote(name)} LIMIT 0").description]
        except sqlite3.Error:
            continue
        mapping = map_headers(columns)
        if "name" not in mapping or not ({"lat", "street", "city"} & set(mapping)):
            continue
        try:
            rows = con.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]
        except sqlite3.Error:
            rows = 0
        found.append(TableInfo(name, columns, mapping, rows))
    return sorted(found, key=lambda t: t.score(), reverse=True)


def sqlite_tables(path):
    """[TableInfo] of a SQLite database or .sql file that hold places, best first ([] if none)."""
    con = load_sql(path)[0] if path.lower().endswith(".sql") else open_database(path)
    try:
        return tables_of(con)
    finally:
        con.close()


def _read_sqlite_con(con, table=None, progress=None):
    """Rows of a table of a connection (table None: the best one)."""
    tables = tables_of(con)
    if not tables:
        raise ValueError("No table of this database has a name column and an address or position column (such as "
                         "name, street, city, state, zip, latitude, longitude).")
    info = next((t for t in tables if t.name == table), None) if table else tables[0]
    if info is None:
        raise ValueError(f"The table {table} has no name and address or position columns.")
    used = sorted(set(info.mapping.values()))
    cols = ", ".join(_quote(info.columns[i]) for i in used)
    where = {i: k for k, i in enumerate(used)}
    mapping = {f: where[i] for f, i in info.mapping.items()}
    cur = con.execute(f"SELECT {cols} FROM {_quote(info.name)}")
    for n, values in enumerate(cur, start=1):
        cells = ["" if v is None else str(v) for v in values]
        row = _row_from_cells(cells, mapping, f"{info.name} row {n}")
        if row.name or row.street or row.located:
            yield row
        if progress and n % 2000 == 0:
            progress(n, info.rows)


# ------------------------------------------------------------------------------------------- .sql files, safely

ALLOWED_FUNCTIONS = {"replace", "char", "lower", "upper", "trim", "ltrim", "rtrim", "abs", "round", "coalesce",
                     "ifnull", "unistr", "cast", "printf", "format"}


def _authorizer(action, arg1, arg2, _db, _trigger):
    """What a statement of a .sql file may do: make tables and add rows, nothing else (no ATTACH, PRAGMA, triggers,
    views, DROP, DELETE or UPDATE of anything but the database's own table list)."""
    allowed = {sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT,
               sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_TRANSACTION}    # (the module's own BEGIN and COMMIT)
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_UPDATE and arg1 in ("sqlite_master", "sqlite_schema"):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and str(arg2 or "").lower() in ALLOWED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _statements(f):
    """The statements of a SQL file, one at a time (each complete, ending with ";")."""
    buf = []
    for line in f:
        if not buf and (not line.strip() or line.lstrip().startswith("--")):
            continue
        buf.append(line)
        text = "".join(buf)
        if ";" in line and sqlite3.complete_statement(text):
            yield text.strip()
            buf = []
    tail = "".join(buf).strip()
    if tail:
        yield tail


def _first_words(statement):
    """The first words of a statement in capitals, comments skipped: "INSERT INTO"."""
    s = re.sub(r"^(\s*(--[^\n]*\n|/\*.*?\*/))*", "", statement, flags=re.S).strip()
    return " ".join(s.split()[:4]).upper()


def load_sql(path):
    """A .sql file loaded into an in-memory SQLite database, safely: only CREATE TABLE (and its indexes) and INSERT
    statements run, and even those can only make tables and add rows (an authorizer denies everything else).
    BEGIN, COMMIT and END are passed over. Returns (connection, {"run": n, "skipped": n, "failed": n})."""
    con = sqlite3.connect(":memory:")
    con.set_authorizer(_authorizer)
    stats = {"run": 0, "skipped": 0, "failed": 0}
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for statement in _statements(f):
            head = _first_words(statement)
            if re.match(r"^(BEGIN|COMMIT|END|ROLLBACK)\b", head):
                continue
            if not (re.match(r"^CREATE (TEMP |TEMPORARY )?TABLE\b", head) or re.match(r"^INSERT\b", head) or
                    re.match(r"^CREATE (UNIQUE )?INDEX\b", head)):
                stats["skipped"] += 1
                continue
            try:
                con.execute(statement)
                stats["run"] += 1
            except (sqlite3.Error, sqlite3.Warning, ValueError):
                stats["failed"] += 1
    con.commit()
    con.set_authorizer(None)
    return con, stats


# ------------------------------------------------------------------------------------------- the grid index

class PlaceGrid:
    """Positions in cells of CELL degrees, so the places near a point are found by looking in a few cells instead
    of every place: add(lat, lon, item), nearest(lat, lon, within_m) -> (metres, item) or None."""

    CELL = 0.002                # about 220 metres north to south

    def __init__(self):
        """An empty grid."""
        self.cells = {}
        self.count = 0

    def _cell(self, lat, lon):
        """The cell of a position."""
        return int(math.floor(lat / self.CELL)), int(math.floor(lon / self.CELL))

    def add(self, lat, lon, item):
        """Add an item at a position."""
        self.cells.setdefault(self._cell(lat, lon), []).append((lat, lon, item))
        self.count += 1

    def near(self, lat, lon, within_m):
        """[(metres, item)] of the items within within_m metres, nearest first."""
        rows = int(math.ceil(within_m / (111320.0 * self.CELL)))
        cos = max(0.01, math.cos(math.radians(lat)))
        cols = int(math.ceil(within_m / (111320.0 * cos * self.CELL)))
        r0, c0 = self._cell(lat, lon)
        out = []
        for r in range(r0 - rows, r0 + rows + 1):
            for c in range(c0 - cols, c0 + cols + 1):
                for plat, plon, item in self.cells.get((r, c), ()):
                    d = metres(lat, lon, plat, plon)
                    if d <= within_m:
                        out.append((d, item))
        out.sort(key=lambda t: t[0])
        return out

    def nearest(self, lat, lon, within_m):
        """(metres, item) of the nearest item within within_m metres, or None."""
        found = self.near(lat, lon, within_m)
        return found[0] if found else None


def metres(lat1, lon1, lat2, lon2):
    """The distance between two positions in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


def find_duplicates(rows, existing=()):
    """Mark as "duplicate" each located Row whose name is already in My places within DUPLICATE_M metres (existing:
    [(name, lat, lon)]), or earlier in the same list. Returns how many were marked."""
    grid = PlaceGrid()
    for name, lat, lon in existing:
        grid.add(lat, lon, ("in My places", name_key(name)))
    count = 0
    for row in rows:
        if not row.located or row.status == "not located":
            continue
        key = name_key(row.name)
        hit = next((what for _d, (what, k) in grid.near(row.lat, row.lon, DUPLICATE_M) if k == key), None)
        if hit:
            row.status, row.why = "duplicate", ("already in My places" if hit == "in My places" else
                                                "twice in this list")
            count += 1
            continue
        grid.add(row.lat, row.lon, ("in the list", key))
    return count


# ------------------------------------------------------------------------------------------- finding addresses

TOWN_AREA_CLASSES = ("town", "admin", "settlement", "city", "village", "census_place")
TOWN_POINT_CLASSES = ("settlement", "town", "city", "village", "hamlet")


def region_of_state(code, country=""):
    """The place-pack region id of a US state or Canadian province code ("IL" -> "us-illinois"), or ""."""
    try:
        from placepacks.regions import REGIONS
    except ImportError:
        return ""
    code = (code or "").upper()
    for rid, r in REGIONS.items():
        if r.get("parent"):
            continue                        # a sub-region (Texas: Gulf Coast) is found through its state
        if r.get("code", "").upper() == code and r.get("cc") in ("US", "CA") and \
                (not country or r.get("cc") == country.upper()[:2] or country.upper() in ("USA",)):
            return rid
    return ""


def packs_by_region(folder):
    """{region id: [pack paths, the core part first]} of the place packs in a folder. The packs of a sub-region
    (Texas: Gulf Coast) count as their state's (us-texas), whose addresses the list names."""
    out = {}
    if not folder or not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".osmpack"):
            continue
        path = os.path.join(folder, name)
        try:
            con = open_database(path)
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            con.close()
        except (ValueError, sqlite3.Error):
            continue
        rid = meta.get("parent") or meta.get("region_id") or name.split(".")[0]
        paths = out.setdefault(rid, [])
        if meta.get("part", "core") == "core":
            paths.insert(0, path)
        else:
            paths.append(path)
    return out


class Locator:
    """Finds the positions of Rows that have only an address, in the place packs of folder (read-only, offline):

      1. the address points (NAD and other address sources) of the state's pack: the same house number on the same
         street, in the same town or ZIP code when the street is in several towns;
      2. the address ranges along the streets (TIGER/Line): the house number placed along the block;
      3. a row with a name and a town but no street: the packs' names in that town (PackReader.search, the search
         behind placepacks.search_names).

    One pass through a state's address points finds every row of that state at once, so a list of 150,000 places
    takes about as long as reading the packs of its states once. Rows already located (the list had positions) are
    kept as they are."""

    def __init__(self, folder):
        """folder: where the place packs are."""
        self.folder = folder
        self.packs = packs_by_region(folder)
        self._towns = {}

    def regions_needed(self, rows):
        """{region id: rows} of the rows without a position (their state's pack is needed)."""
        out = {}
        for row in rows:
            if row.located or row.status:
                continue
            rid = region_of_state(row.state, row.country)
            if rid:
                out[rid] = out.get(rid, 0) + 1
        return out

    def locate(self, rows, progress=None, stop=None):
        """Find positions for the rows that have none; mark every row "located" or "not located" (with why).
        progress(text, done, total); stop() -> True to stop early (the rest stay as they are)."""
        stop = stop or (lambda: False)
        by_region = {}
        for row in rows:
            if row.status == "duplicate":
                continue
            if row.located:
                row.status, row.found_by = "located", row.found_by or "position in the list"
                continue
            if not (row.street or row.city):
                row.status, row.why = "not located", "no address or position"
                continue
            rid = region_of_state(row.state, row.country)
            if not rid:
                row.status, row.why = "not located", ("no state in the address" if not row.state else
                                                      f"no place pack for {row.state}")
                continue
            if rid not in self.packs:
                row.status, row.why = "not located", f"the place pack for {row.state} is not on this computer"
                continue
            by_region.setdefault(rid, []).append(row)
        regions = sorted(by_region)
        for k, rid in enumerate(regions):
            if stop():
                break
            label = rid.split("-", 1)[-1].replace("-", " ").title()
            if progress:
                progress(f"Finding addresses in {label}", k, len(regions))
            self._locate_region(rid, by_region[rid], stop)
        for row in rows:
            if not row.status:
                row.status, row.why = "not located", row.why or "not found"
        return rows

    # -- one region

    def _locate_region(self, rid, rows, stop):
        """Steps 1 to 3 for the rows of one region, in every part of its pack (core and extra)."""
        cons = []
        for path in self.packs[rid]:
            try:
                cons.append(open_database(path))
            except ValueError:
                continue
        streets = [r for r in rows if r.street and house_number(street_key(r.street)[0]) is not None]
        try:
            for con in cons:
                left = [r for r in streets if not r.located]
                if left and not stop():
                    self._address_points(rid, cons, con, left, stop)
            for con in cons:
                left = [r for r in streets if not r.located]
                if left and not stop():
                    self._address_ranges(rid, cons, con, left, stop)
            for r in rows:
                if not r.located and r.street and house_number(street_key(r.street)[0]) is None and not r.why:
                    r.why = "the address has no house number"
            named = [r for r in rows if not r.located and r.name and r.city]
            if named and not stop():
                self._names_in_town(rid, self.packs[rid], cons, named)
        finally:
            for con in cons:
                con.close()
        for r in rows:
            if r.located:
                r.status = "located"
            elif not r.why:
                r.why = "the address was not found in the place pack"

    def towns(self, cons, rid):
        """{town key: [(south, west, north, east)]} of the towns and ZIP codes of a region's pack parts (read once
        per region)."""
        if rid in self._towns:
            return self._towns[rid]
        out = {}
        for con in cons:
            self._read_towns(con, out)
        self._towns[rid] = out
        return out

    @staticmethod
    def _read_towns(con, out):
        """Add the towns and ZIP codes of one pack file to out."""
        scale = 1_000_000
        try:
            marks = ",".join("?" * len(TOWN_AREA_CLASSES))
            for name, cls, s, w, n, e in con.execute(
                    f"SELECT name, cls, minlat, minlon, maxlat, maxlon FROM areas WHERE cls IN ({marks}) OR "
                    f"cls = 'zip'", TOWN_AREA_CLASSES):
                out.setdefault(town_key(name) if cls != "zip" else str(name).strip()[:5], []).append(
                    (s / scale, w / scale, n / scale, e / scale))
            marks = ",".join("?" * len(TOWN_POINT_CLASSES))
            for name, lat, lon in con.execute(f"SELECT name, lat, lon FROM points WHERE cls IN ({marks})",
                                              TOWN_POINT_CLASSES):
                lat, lon = lat / scale, lon / scale
                out.setdefault(town_key(name), []).append((lat - 0.05, lon - 0.06, lat + 0.05, lon + 0.06))
        except sqlite3.Error:
            pass

    @staticmethod
    def _inside(boxes, lat, lon, margin=0.01):
        """True if the position is in one of the boxes (with a margin of about a kilometre)."""
        return any(s - margin <= lat <= n + margin and w - margin <= lon <= e + margin for s, w, n, e in boxes)

    def _choose(self, row, candidates, towns):
        """The best candidate [(lat, lon, town of the address, zip)] for a row: the one in the row's town or ZIP
        code; with no town or ZIP given, the only one (or several within 300 m of each other). None if unsure."""
        if not candidates:
            return None
        city = town_key(row.city)
        if city:
            same = [c for c in candidates if c[2] and town_key(c[2]) == city]
            if same:
                return same[0]
            boxes = towns.get(city, [])
            if boxes:
                inside = [c for c in candidates if self._inside(boxes, c[0], c[1])]
                if inside:
                    return inside[0]
        if row.zip:
            same = [c for c in candidates if c[3] and c[3][:5] == row.zip[:5]]
            if same:
                return same[0]
            boxes = towns.get(row.zip[:5], [])
            inside = [c for c in candidates if boxes and self._inside(boxes, c[0], c[1], 0.002)]
            if inside:
                return inside[0]
        first = candidates[0]
        if all(metres(first[0], first[1], c[0], c[1]) <= 300 for c in candidates):
            # One place (a town or ZIP code that could not be checked does not matter: one street of that name
            # with that number in the whole state is the place).
            return first
        row.why = f"{len(candidates)} streets of that name in {row.state}; the town did not match"
        return None

    def _address_points(self, rid, cons, con, rows, stop):
        """Step 1: the address points."""
        from placepacks import fmt
        want, want_core = {}, {}            # {(street words, house number): [rows]}
        streets, cores = set(), set()
        for r in rows:
            number, words = street_key(r.street)
            n = house_number(number)
            want.setdefault((words, n), []).append(r)
            want_core.setdefault((street_core(words), n), []).append(r)
            streets.add(words)
            cores.add(street_core(words))
        found = {id(r): [] for r in rows}
        loose = {id(r): [] for r in rows}
        keys = {}
        try:
            cur = con.execute("SELECT cell, streets, data FROM address_cells")
        except sqlite3.Error:
            return                      # a part without address points
        for k, (cell, streets_json, data) in enumerate(cur):
            if k % 5000 == 0 and stop():
                return
            labels = json.loads(streets_json)
            hits = {}
            for idx, label in enumerate(labels):
                parsed = keys.get(label)
                if parsed is None:
                    street, town, _src = (label.split("|") + ["", ""])[:3]
                    words = street_key("1 " + street)[1]
                    parsed = keys[label] = (words, street_core(words), town)
                if parsed[0] in streets or parsed[1] in cores:
                    hits[idx] = parsed
            if not hits:
                continue
            corner = fmt.cell_corner(cell)
            for dlat, dlon, s, number, _first, _last in fmt.decode_addresses(data):
                parsed = hits.get(s)
                if parsed is None:
                    continue
                n = house_number(number)
                if n is None:
                    continue
                exact, near = want.get((parsed[0], n)), want_core.get((parsed[1], n))
                if not exact and not near:
                    continue
                lat, lon = (corner[0] + dlat) / fmt.SCALE, (corner[1] + dlon) / fmt.SCALE
                for r in exact or ():
                    found[id(r)].append((lat, lon, parsed[2], ""))
                for r in near or ():
                    loose[id(r)].append((lat, lon, parsed[2], ""))
        towns = self.towns(cons, rid)
        for r in rows:
            for candidates, how in ((found[id(r)], "address point"), (loose[id(r)], "address point")):
                if not candidates:
                    continue
                best = self._choose(r, candidates, towns)
                if best is not None:
                    r.lat, r.lon, r.found_by, r.why = best[0], best[1], how, ""
                    break

    def _address_ranges(self, rid, cons, con, rows, stop):
        """Step 2: the address ranges (the house number placed along its block)."""
        import bisect
        from placepacks import fmt
        want, want_core = {}, {}            # {street words: [(house number, k)] sorted}
        for k, r in enumerate(rows):
            number, words = street_key(r.street)
            n = house_number(number)
            want.setdefault(words, []).append((n, k))
            want_core.setdefault(street_core(words), []).append((n, k))
        for table in (want, want_core):
            for items in table.values():
                items.sort()
        hits = {id(r): [] for r in rows}
        keys = {}
        try:
            cur = con.execute("SELECT id, name, lfrom, lto, rfrom, rto, zip FROM ranges")
        except sqlite3.Error:
            return
        for k, (rid, name, lfrom, lto, rfrom, rto, zip_code) in enumerate(cur):
            if k % 20000 == 0 and stop():
                return
            parsed = keys.get(name)
            if parsed is None:
                words = street_key("1 " + (name or ""))[1]
                parsed = keys[name] = (words, street_core(words))
            tables = [want.get(parsed[0])]
            if parsed[1] != parsed[0]:
                tables.append(want_core.get(parsed[1]))
            for items in tables:
                if not items:
                    continue
                for a, b in ((lfrom, lto), (rfrom, rto)):
                    if a is None or b is None:
                        continue
                    lo, hi = min(a, b), max(a, b)
                    for n, k2 in items[bisect.bisect_left(items, (lo, -1)):bisect.bisect_right(items, (hi, 1 << 62))]:
                        if (n - a) % 2 == 0:
                            hits[id(rows[k2])].append((rid, a, b, n, zip_code or ""))
        towns = self.towns(cons, rid)
        for r in rows:
            if not hits[id(r)]:
                continue
            candidates = []
            for rid_, a, b, n, zip_code in hits[id(r)][:50]:
                row = con.execute("SELECT pts FROM ranges WHERE id = ?", (rid_,)).fetchone()
                if not row:
                    continue
                pts = [(y / fmt.SCALE, x / fmt.SCALE) for y, x in fmt.unpack_points(row[0])]
                t = 0.5 if a == b else (n - a) / (b - a)
                lat, lon = _along(pts, t)
                candidates.append((lat, lon, "", zip_code))
            best = self._choose(r, candidates, towns)
            if best is not None:
                r.lat, r.lon, r.found_by, r.why = best[0], best[1], "address range", ""

    def _names_in_town(self, rid, paths, cons, rows):
        """Step 3: a name in the row's town (the packs' name search)."""
        try:
            from placepacks.lookup import PackReader
        except ImportError:
            return
        towns = self.towns(cons, rid)
        readers = []
        for path in paths:
            try:
                readers.append(PackReader(path))
            except Exception:  # noqa: BLE001 - a damaged or old pack: left out
                continue
        try:
            for r in rows:
                boxes = towns.get(town_key(r.city), [])
                if not boxes:
                    r.why = r.why or f"the town {r.city} is not in the place pack"
                    continue
                key = name_key(r.name)
                best = None
                for reader in readers:
                    for hit in reader.search(r.name, limit=40):
                        if not self._inside(boxes, hit["lat"], hit["lon"]):
                            continue
                        exact = name_key(hit["name"]) == key
                        rank = (not exact, len(hit["name"]))
                        if best is None or rank < best[0]:
                            best = (rank, hit)
                if best is not None:
                    r.lat, r.lon, r.found_by, r.why = best[1]["lat"], best[1]["lon"], "name in the town", ""
                elif r.street:
                    r.why = r.why or "the address was not found in the place pack"
                else:
                    r.why = f"no place of that name found in {r.city}"
        finally:
            for reader in readers:
                try:
                    reader.close()
                except Exception:  # noqa: BLE001
                    pass


def _along(pts, t):
    """The position a fraction t of the way along a line [(lat, lon)]."""
    if len(pts) == 1:
        return pts[0]
    lengths = [metres(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]
    total = sum(lengths) or 1.0
    goal, run = max(0.0, min(1.0, t)) * total, 0.0
    for (a, b), d in zip(zip(pts, pts[1:]), lengths):
        if run + d >= goal and d > 0:
            f = (goal - run) / d
            return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
        run += d
    return pts[-1]


# ------------------------------------------------------------------------------------------- summaries

def summary(rows):
    """{"found", "located", "not located", "duplicates"} counts of a list after locate and find_duplicates."""
    out = {"found": len(rows), "located": 0, "not located": 0, "duplicates": 0}
    for r in rows:
        if r.status == "duplicate":
            out["duplicates"] += 1
        elif r.located:
            out["located"] += 1
        else:
            out["not located"] += 1
    return out


def summary_text(rows):
    """"1,234 places found; 1,100 located; 134 could not be located; 20 duplicates of My places"."""
    s = summary(rows)
    repeated = any(r.status == "duplicate" and r.why == "twice in this list" for r in rows)
    return (f"{s['found']:,} place{'s' if s['found'] != 1 else ''} found; {s['located']:,} located; "
            f"{s['not located']:,} could not be located; {s['duplicates']:,} duplicate"
            f"{'s' if s['duplicates'] != 1 else ''} of My places"
            + (" (or repeated in the list)" if repeated else ""))


def report_lines(rows, limit=200):
    """The lines of the short report of the places that could not be located: "line 3: Name — address — why"."""
    out = [f"{r.where}: {r.line()}" for r in rows if r.status == "not located"]
    if len(out) > limit:
        out = out[:limit] + [f"... and {len(out) - limit:,} more"]
    return out


def default_list_name(today=None):
    """"Pasted list 2026-11-09"."""
    import datetime
    return f"Pasted list {(today or datetime.date.today()).isoformat()}"


# ------------------------------------------------------------------------------------------- export

def export_places(path, places):
    """Write places [{"name", "latitude", "longitude", "metres", "list"}] to path, by its ending: a SQLite database
    (.db, .sqlite, .sqlite3), a .sql file of CREATE TABLE and INSERT statements, or a .csv file. The table (and the
    CSV's columns) are EXPORT_TABLE with EXPORT_COLUMNS. Returns how many were written."""
    low = path.lower()
    places = list(places)
    rows = [(str(p.get("name", "")), float(p["latitude"]), float(p["longitude"]),
             float(p.get("metres") or LIST_RADIUS_M), str(p.get("list") or "")) for p in places]
    tmp = path + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    if low.endswith(SQLITE_ENDINGS):
        con = sqlite3.connect(tmp)
        try:
            con.execute(f"CREATE TABLE {EXPORT_TABLE} (name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL "
                        f"NOT NULL, metres REAL NOT NULL, list TEXT NOT NULL DEFAULT '')")
            con.executemany(f"INSERT INTO {EXPORT_TABLE} VALUES (?, ?, ?, ?, ?)", rows)
            con.commit()
        finally:
            con.close()
    elif low.endswith(".sql"):
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(sql_text(rows))
    else:
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            out = csv.writer(f)
            out.writerow(EXPORT_COLUMNS)
            for r in rows:
                out.writerow([r[0], repr(r[1]), repr(r[2]), f"{r[3]:g}", r[4]])
    os.replace(tmp, path)
    return len(rows)


def sql_literal(value):
    """A value written for SQL: numbers as they are, text in single quotes with quotes doubled, NULL for None."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return "NULL"
        return repr(value)
    text = str(value).replace("\x00", "")
    return "'" + text.replace("'", "''") + "'"


def sql_text(rows):
    """The .sql text of exported places [(name, lat, lon, metres, list)]: plain, portable SQL that SQLite, MySQL and
    PostgreSQL can read."""
    buf = io.StringIO()
    buf.write("-- My places, exported. Plain SQL: one CREATE TABLE and one INSERT per place.\n")
    buf.write(f"CREATE TABLE {EXPORT_TABLE} (name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL, "
              f"metres REAL NOT NULL, list TEXT NOT NULL DEFAULT '');\n")
    for r in rows:
        buf.write(f"INSERT INTO {EXPORT_TABLE} (name, latitude, longitude, metres, list) VALUES ("
                  + ", ".join(sql_literal(v) for v in r) + ");\n")
    return buf.getvalue()
