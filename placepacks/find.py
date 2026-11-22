"""Find the nearest place of a kind, in plain words, with directions: "where's the nearest hardware store?", "the
nearest Catholic church", "a mosque", "the nearest polling place". Only the Python standard library is used.

    from placepacks.find import find_nearest

    r = find_nearest("hardware store", start=(44.4759, -73.2121))           # or start="Main Street and Elm Street",
    r["place"]["name"], r["place"]["phone"], r["place"]["opening_hours"]    # or start="12 Main Street, Burlington"
    r["directions"]["steps"]                                                # walking directions (mode="drive" or
    r["phrase"]                                                             # "transit" for the others)

How a kind is found: the words asked are made plain ("drugstore" -> pharmacy, "grocery" -> supermarket, "DIY" ->
home improvement store, "Catholic church", "mosque"; SYNONYMS), then every place whose fine type (types.json: the
phrases of OpenStreetMap's shop, amenity, craft and healthcare tags, of Overture's and Foursquare's categories, of
NAICS codes and of religions and denominations) is one of those phrases, or holds all the words asked ("bicycle"
finds "bicycle shop"), is a candidate, in every pack of the folder: core, extra, businesses and the services part's
offices. A place listed by several sources is given once; the phone, opening hours, website and wheelchair access
come from the services part (svc_details) where OpenStreetMap gives them. Closed places (not seen at the last build)
are left out. Polling places are only of past elections and are always said with their election date.
"""

import re

from placepacks import fmt
from placepacks.lookup import default_folder, normal_name, open_packs
from placepacks.water import bearing_word

# Plain words -> the type phrases they mean (the first is the one said). Words not listed are matched against every
# type phrase of the packs.
SYNONYMS = {
    "hardware store": ["hardware store", "home improvement store", "building materials store", "diy store",
                       "home improvement", "hardware"],
    "hardware": ["hardware store", "home improvement store"],
    "diy": ["home improvement store", "hardware store"],
    "home improvement": ["home improvement store", "hardware store"],
    "drugstore": ["pharmacy", "drugstore", "chemist"],
    "drug store": ["pharmacy", "drugstore"],
    "chemist": ["pharmacy"],
    "pharmacy": ["pharmacy", "drugstore"],
    "grocery": ["supermarket", "grocery store", "convenience store", "greengrocer"],
    "grocery store": ["supermarket", "grocery store"],
    "groceries": ["supermarket", "grocery store"],
    "food store": ["supermarket", "grocery store"],
    "gas station": ["gas station", "fuel station"],
    "gas": ["gas station"],
    "petrol station": ["gas station"],
    "atm": ["atm", "bank"],
    "cash machine": ["atm"],
    "doctor": ["doctor's office", "clinic", "medical clinic"],
    "dentist": ["dentist", "dental clinic"],
    "vet": ["veterinary clinic", "veterinarian"],
    "hair salon": ["hair salon", "barber shop", "hairdresser"],
    "barber": ["barber shop", "hair salon"],
    "liquor store": ["liquor store", "wine shop", "beverage store"],
    "coffee": ["coffee shop", "cafe"],
    "coffee shop": ["coffee shop", "cafe"],
    "cafe": ["cafe", "coffee shop"],
    "restaurant": ["restaurant", "fast food restaurant", "diner"],
    "laundromat": ["laundromat", "laundry"],
    "thrift store": ["thrift store", "second hand shop", "charity shop"],
    "bookstore": ["bookstore", "book store"],
    "eye doctor": ["optician", "optometrist"],
    "optometrist": ["optometrist", "optician"],
    "auto repair": ["auto repair shop", "car repair"],
    "mechanic": ["auto repair shop"],
    "auto parts": ["auto parts store"],
    "pet store": ["pet store", "pet supply store"],
    "bank": ["bank", "credit union"],
    "post office": ["post office"],
    "library": ["library", "public library"],
    "hospital": ["hospital"],
    "urgent care": ["urgent care", "urgent care center", "walk-in clinic"],
    "police": ["police station", "police"],
    "police station": ["police station", "police"],
    "fire station": ["fire station"],
    "school": ["school", "elementary school", "middle school", "high school"],
    "community center": ["community center", "community centre"],
    "senior center": ["senior center", "senior centre"],
    "food bank": ["food bank", "food pantry"],
    "food pantry": ["food bank", "food pantry"],
    "shelter": ["shelter", "homeless shelter"],
    "town hall": ["town hall", "city hall"],
    "church": ["church", "catholic church", "baptist church", "methodist church", "lutheran church",
               "presbyterian church", "episcopal church", "anglican church", "orthodox church",
               "greek orthodox church", "pentecostal church", "latter-day saints church", "congregational church",
               "unitarian church", "quaker meeting house", "evangelical church", "christian church",
               "christian place of worship"],
    "catholic church": ["catholic church", "roman catholic church"],
    "catholic": ["catholic church"],
    "baptist church": ["baptist church"],
    "methodist church": ["methodist church", "united methodist church"],
    "mosque": ["mosque", "islamic center", "masjid", "muslim place of worship", "islamic place of worship"],
    "masjid": ["mosque"],
    "synagogue": ["synagogue", "temple (jewish)", "jewish place of worship"],
    "temple": ["buddhist temple", "hindu temple", "synagogue"],
    "gurdwara": ["gurdwara"],
    "place of worship": ["place of worship", "church", "mosque", "synagogue", "buddhist temple", "hindu temple",
                         "gurdwara"],
}
# Kinds answered by the services part's offices (services.SERVICE_KINDS) rather than by type phrases.
SERVICE_WORDS = {"social security office": "social security office", "social security": "social security office",
                 "dmv": "motor vehicle office", "motor vehicle office": "motor vehicle office",
                 "veterans office": "veterans office", "va": "veterans office", "courthouse": "courthouse",
                 "defibrillator": "defibrillator", "aed": "defibrillator", "service canada": "service canada centre"}
WORSHIP = {"church", "chapel", "mosque", "synagogue", "temple", "cathedral"}
POLLING = re.compile(r"^(polling place|polling station|where (do|can) i vote|voting place|vote)$", re.I)
WHEELCHAIR = {"yes": "Step-free access.", "limited": "Partly step-free.", "no": "Not step-free.",
              "designated": "Made for wheelchair users."}


def plain(text):
    """Asked words made plain: lower case, single spaces, without "the nearest", "a", "an" and a plural "s"."""
    t = " ".join(re.sub(r"[^\w\s'&-]", " ", (text or "").lower()).split())
    t = re.sub(r"^(where'?s|where is|find|the|a|an|nearest|closest|my|me)\s+", "", t)
    t = re.sub(r"^(the|a|an|nearest|closest)\s+", "", t)
    t = re.sub(r"^(nearest|closest)\s+", "", t)
    if t.endswith("ies") and t[:-3] + "y" in SYNONYMS:
        t = t[:-3] + "y"
    elif t.endswith("s") and not t.endswith("ss") and t[:-1] in SYNONYMS:
        t = t[:-1]
    return t


def phrases_for(text, known=()):
    """The type phrases a request means: its SYNONYMS, else the known phrases (of the packs) that hold every word
    asked ("bicycle" -> "bicycle shop"), else the words themselves."""
    t = plain(text)
    words = t.split()
    found = {p for p in known if all(re.search(rf"\b{re.escape(w)}", p) for w in words)}
    if len(words) >= 2 and words[-1] in WORSHIP:
        # "Catholic church" also finds Overture's "roman catholic place of worship", "Baptist church" its "baptist
        # place of worship".
        found |= {p for p in known if "place of worship" in p and all(re.search(rf"\b{re.escape(w)}", p)
                                                                      for w in words[:-1])}
    if t in SYNONYMS:
        return list(dict.fromkeys(SYNONYMS[t] + [t] + sorted(found - set(SYNONYMS[t]), key=len)))
    return [t] + sorted(found - {t}, key=len)


class Finder:
    """The places of every pack in a folder, searched by kind (see the module docstring)."""

    def __init__(self, folder=None, packs=None):
        """folder: where the packs are; packs: PackReaders (for tests)."""
        self.packs = packs if packs is not None else open_packs(folder or default_folder())

    def known_phrases(self):
        """Every type phrase of the packs."""
        out = set()
        for p in self.packs:
            out.update(p.types.values())
        return out

    def details(self, key):
        """{phone, opening_hours, website, wheelchair} of a place's key from a services part, or {}."""
        for p in self.packs:
            if p.part == "services":
                rows = p._rows("SELECT phone, opening_hours, website, wheelchair FROM svc_details WHERE key = ?",
                               (key,))
                if rows:
                    return {k: v for k, v in rows[0].items() if v}
        return {}

    def candidates(self, lat, lon, phrases, service_kind, rings):
        """Places of the phrases (or of a services-part kind) in the coarse cells around a position."""
        step = 1.0 / fmt.COARSE
        cells = ",".join(str(fmt.coarse_cell(lat + dy * step, lon + dx * step)) for dy in range(-rings, rings + 1)
                         for dx in range(-rings, rings + 1))
        out = []
        for p in self.packs:
            tables = {r["name"] for r in p._rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "svc_places" in tables and service_kind:
                for r in p._rows(f"SELECT key, source, kind AS type, name, lat, lon, details FROM svc_places WHERE "
                                 f"kind = ? AND ccell IN ({cells})", (service_kind,)):
                    out.append(dict(r, pack=p))
            if p.part not in ("core", "extra", "businesses") or not p._typed or not phrases:
                continue
            ids = [i for i, name in p.types.items() if name in phrases]
            if not ids:
                continue
            for r in p._rows(f"SELECT p.key, p.source, p.name, p.lat, p.lon, p.last, t.type FROM points p JOIN "
                             f"point_types t ON t.id = p.id WHERE t.type IN ({','.join(map(str, ids))}) AND p.ccell IN "
                             f"({cells})"):
                if r["last"] and p.latest and r["last"] < p.latest:
                    continue                    # closed, or no longer listed
                out.append({"key": r["key"], "source": r["source"], "name": r["name"], "lat": r["lat"],
                            "lon": r["lon"], "type": p.types.get(r["type"], ""), "pack": p, "details": ""})
        for r in out:
            r["lat"], r["lon"] = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
            r["d"] = fmt.metres(lat, lon, r["lat"], r["lon"])
        return out

    def nearest(self, kind, lat, lon, limit=3, max_km=50):
        """The nearest places of a kind, nearest first, each once: [{"name", "type", "lat", "lon", "distance_m",
        "bearing", "phone", "opening_hours", "website", "wheelchair", "sources"}]."""
        t = plain(kind)
        service_kind = SERVICE_WORDS.get(t)
        phrases = set() if service_kind and t not in SYNONYMS else set(phrases_for(t, self.known_phrases()))
        found, rings = [], 1
        while True:
            found = [r for r in self.candidates(lat, lon, phrases, service_kind, rings) if r["d"] <= max_km * 1000]
            if len(found) >= limit or rings * 11 >= max_km:
                break
            rings = rings * 2 + 1
        found.sort(key=lambda r: r["d"])
        merged = []
        for r in found:
            same = next((m for m in merged if normal_name(m["name"]) == normal_name(r["name"]) and
                         fmt.metres(m["lat"], m["lon"], r["lat"], r["lon"]) < 150), None)
            if same:
                same["sources"].add(r["source"])
                continue
            merged.append(dict(r, sources={r["source"]}))
        out = []
        for r in merged[:limit]:
            info = {}
            if r.get("details"):
                import json
                d = json.loads(r["details"])
                info = {"phone": d.get("phone") or d.get("contact:phone"), "opening_hours": d.get("opening_hours"),
                        "website": d.get("website"), "wheelchair": d.get("wheelchair")}
            for k, v in self.details(r["key"]).items():
                if not info.get(k):
                    info[k] = v
            out.append({"name": r["name"], "type": r["type"], "lat": r["lat"], "lon": r["lon"],
                        "distance_m": round(r["d"]), "bearing": bearing_word(lat, lon, r["lat"], r["lon"]),
                        "phone": info.get("phone") or "", "opening_hours": info.get("opening_hours") or "",
                        "website": info.get("website") or "", "wheelchair": info.get("wheelchair") or "",
                        "sources": sorted(r["sources"]), "key": r["key"]})
        return out

    def polling_places(self, lat, lon, limit=3):
        """The nearest polling places of the newest election listed (services part), each with its election date."""
        out = []
        for p in self.packs:
            if p.part != "services":
                continue
            for r in p._rows("SELECT * FROM svc_polling WHERE lat IS NOT NULL"):
                y, x = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
                out.append({"name": r["name"], "address": r["address"], "election_date": r["election_date"],
                            "election": r["election"], "precinct": r["precinct"], "lat": y, "lon": x,
                            "distance_m": round(fmt.metres(lat, lon, y, x)), "bearing": bearing_word(lat, lon, y, x),
                            "located": r["located"], "type": "polling place", "phone": "", "opening_hours": "",
                            "website": "", "wheelchair": "", "sources": [r["source"]], "key": r["key"]})
        out.sort(key=lambda r: r["distance_m"])
        return out[:limit]


def resolve_start(start, packs):
    """(lat, lon) of a start: a (lat, lon) pair; "Main Street and Elm Street" (an intersection of the navigation
    part); or "12 Main Street[, Town]" (an address point of the addresses part). None when it cannot be found."""
    if isinstance(start, (tuple, list)) and len(start) == 2:
        return float(start[0]), float(start[1])
    text = " ".join(str(start or "").split())
    parts = re.split(r"\s+(?:and|&|at)\s+", text, flags=re.I)
    if len(parts) == 2:
        a, b = (normal_name(x) for x in parts)
        for p in packs:
            if p.part != "navigation":
                continue
            for r in p._rows("SELECT lat, lon, streets FROM nav_intersections WHERE streets LIKE ? AND streets LIKE ?",
                             (f"%{parts[0].split()[0]}%", f"%{parts[1].split()[0]}%")):
                import json
                names = [normal_name(s) for s in json.loads(r["streets"])]
                if any(n.startswith(a) or a.startswith(n) for n in names) and \
                        any(n.startswith(b) or b.startswith(n) for n in names):
                    return r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
    m = re.match(r"^(\d+[A-Za-z]?)\s+([^,]+)(?:,\s*(.+))?$", text)
    if m:
        from placepacks.geocode import norm_street
        number, street, town = m.group(1), norm_street(m.group(2)), (m.group(3) or "").strip().lower()
        for p in packs:
            if p.part != "addresses":
                continue
            import json
            for r in p._rows("SELECT cell, streets, data FROM address_cells WHERE streets LIKE ?",
                             (f"%{m.group(2).split()[0]}%",)):
                names = json.loads(r["streets"])
                corner = fmt.cell_corner(r["cell"])
                for dlat, dlon, si, num, first, last in fmt.decode_addresses(r["data"]):
                    s, city = (names[si].split("|") + [""])[:2]
                    if num == number and norm_street(s) == street and (not town or town in city.lower()):
                        return (corner[0] + dlat) / fmt.SCALE, (corner[1] + dlon) / fmt.SCALE
    return None


def find_nearest(kind, start, folder=None, packs=None, mode="walk", units="miles", when=None, limit=3,
                 avoid_steps=False):
    """The nearest place of a kind from a start (see resolve_start), with directions: {"place", "others",
    "directions", "phrase"}; None when the start or no place is found. mode: "walk", "drive" or "transit"."""
    from placepacks.navigate import Navigator
    from placepacks.route import directions, length_words
    packs = packs if packs is not None else open_packs(folder or default_folder())
    here = resolve_start(start, packs)
    if here is None:
        return {"place": None, "others": [], "directions": None,
                "phrase": "I could not find that starting point in the downloaded packs."}
    finder = Finder(packs=packs)
    if POLLING.match(plain(kind)):
        places = finder.polling_places(*here, limit=limit)
    else:
        places = finder.nearest(kind, *here, limit=limit)
    if not places:
        return {"place": None, "others": [], "directions": None,
                "phrase": f"No {plain(kind)} was found within 50 km in the downloaded packs."}
    place = places[0]
    nav = Navigator(packs=packs)
    route = directions(nav, here, (place["lat"], place["lon"]), mode=mode, to_name=place["name"], units=units,
                       avoid_steps=avoid_steps, when=when)
    what = place["type"] or plain(kind)
    bits = [f"The nearest {plain(kind)} is {place['name']}" + (f" ({what})" if what and what != plain(kind) else "") +
            f", {length_words(place['distance_m'], units)} {place['bearing']} in a straight line."]
    if place.get("election_date"):
        bits = [f"The nearest polling place in the list for the {place['election']} of {place['election_date']} "
                f"was {place['name']}, {place['address']}, {length_words(place['distance_m'], units)} "
                f"{place['bearing']}. This list is from a past election and polling places change: check your "
                f"polling place with your town or county election office before you go."]
    if place["phone"]:
        bits.append(f"Phone {place['phone']}.")
    if place["opening_hours"]:
        bits.append(f"Hours: {place['opening_hours']}.")
    if place["wheelchair"] in WHEELCHAIR:
        bits.append(WHEELCHAIR[place["wheelchair"]])
    if route:
        bits.append(route["phrase"])
    else:
        bits.append("No directions: the navigation part of this region is not downloaded, or no path joins the two.")
    return {"place": place, "others": places[1:], "directions": route, "start": here, "phrase": " ".join(bits)}
