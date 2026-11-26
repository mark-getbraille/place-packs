"""Local services and emergency information from the packs: "the nearest Social Security office", "the nearest
library", "my NOAA Weather Radio frequency", "my forecast zone". Only the Python standard library is used.

    from placepacks.download import ensure_pack
    from placepacks.local import LocalServices

    ensure_pack("us-vermont", part="services")
    local = LocalServices()
    local.nearest(44.4759, -73.2121, "social security office")   # {"name", "distance_m", "bearing", "phone", ...,
                                                                   #  "phrase"}
    local.weather_radio(44.4759, -73.2121)    # the transmitters covering the county, nearest first, with frequencies
    local.weather_zone(44.4759, -73.2121)     # the NWS county and forecast zone, and the forecast office

nearest() searches the services part's own places (from OpenStreetMap) and the places of the core and extra parts
whose type or tag says the same (the IMLS libraries, HRSA health centres, USGS post offices and courthouses, the
pharmacies and food banks of OpenStreetMap and Overture), and gives a place listed by several sources once.
Each answer has "phrase", a plain sentence, and "attribution".
"""

import json
import math
import re

from placepacks import fmt
from placepacks.lookup import default_folder, inside_rings, join_details, normal_name, open_packs
from placepacks.water import bearing_word

# For each kind: the type phrases and tags of the other parts' places that are the same kind, and a name pattern.
KINDS = {
    "social security office": {"name": r"\bsocial security\b"},
    "service canada centre": {"name": r"\bservice canada\b"},
    "motor vehicle office": {"types": {"vehicle inspection"}, "name": r"\b(dmv|bmv|mvd|motor vehicles?|driver'?s? "
                                                                      r"licen[cs]e|serviceontario|saaq)\b"},
    "veterans office": {"name": r"\b(veterans? affairs|vet center|va medical|va clinic|vamc)\b"},
    "courthouse": {"types": {"courthouse"}, "tags": {"amenity=courthouse"}},
    "post office": {"types": {"post office"}, "tags": {"amenity=post_office"}},
    "library": {"types": {"library", "public library"}, "tags": {"amenity=library"}},
    "pharmacy": {"types": {"pharmacy", "drugstore"}, "tags": {"amenity=pharmacy"}},
    "food bank": {"types": {"food bank"}},
    "health centre": {"tags": {"health center"}, "services": {"clinic"}},
    "hospital": {"types": {"hospital"}, "tags": {"amenity=hospital"}},
    "police": {"types": {"police station", "police"}, "tags": {"amenity=police"}},
    "fire station": {"types": {"fire station"}, "tags": {"amenity=fire_station"}},
    "town hall": {"types": {"town hall", "city hall"}, "tags": {"amenity=townhall"}},
}
ALIASES = {"dmv": "motor vehicle office", "ssa": "social security office", "social security": "social security office",
           "va": "veterans office", "health center": "health centre", "drugstore": "pharmacy",
           "post office": "post office", "court": "courthouse"}
WHEELCHAIR = {"yes": "Step-free access.", "limited": "Partly step-free.", "no": "Not step-free.",
              "designated": "Made for wheelchair users."}
ATTRIBUTION_NWS = "National Weather Service (NOAA), public domain"


def distance_words(metres, units="miles"):
    """"about 3.2 miles" or "about 5.1 km" ("about 300 feet" or "about 90 metres" when close)."""
    if units == "miles":
        miles = metres / 1609.344
        return f"about {int(round(metres * 3.28084 / 50) * 50)} feet" if miles < 0.2 else f"about {miles:.1f} miles"
    return f"about {int(round(metres / 10) * 10)} metres" if metres < 1000 else f"about {metres / 1000:.1f} km"


def _coarse_cells(lat, lon, rings):
    """The coarse cells (1/10 degree) within rings cells of a position."""
    step = 1.0 / fmt.COARSE
    return sorted({fmt.coarse_cell(lat + dy * step, lon + dx * step) for dy in range(-rings, rings + 1)
                   for dx in range(-rings, rings + 1)})


def kind_of(text):
    """The kind a person asked for ("DMV" -> "motor vehicle office"), or the text itself when it is a kind."""
    t = " ".join((text or "").lower().split())
    return ALIASES.get(t, t)


class LocalServices:
    """The local services and emergency lookups over the packs in a folder (see the module docstring)."""

    def __init__(self, folder=None, packs=None):
        """folder: where the packs are (placepacks.lookup.default_folder()); packs: PackReaders (for tests)."""
        self.packs = packs if packs is not None else open_packs(folder or default_folder())

    def _tables(self, pack):
        """The table names of a pack."""
        return {r["name"] for r in pack._rows("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _candidates(self, lat, lon, kind, rings):
        """Every place of a kind in the coarse cells around a position, from every pack: [{name, lat, lon, source,
        details, d}]."""
        spec = KINDS.get(kind, {})
        pattern = re.compile(spec["name"], re.I) if spec.get("name") else None
        cells = ",".join(map(str, _coarse_cells(lat, lon, rings)))
        out = []
        for pack in self.packs:
            tables = self._tables(pack)
            if "svc_places" in tables:
                wanted = {kind} | set(spec.get("services", ()))
                marks = ",".join("?" * len(wanted))
                for r in pack._rows(f"SELECT key, source, kind, name, lat, lon, details FROM svc_places WHERE kind IN "
                                    f"({marks}) AND ccell IN ({cells})", tuple(wanted)):
                    out.append(dict(r, details=json.loads(r["details"]) if r["details"] else {}))
            if "points" not in tables or pack.part not in ("core", "extra", "businesses"):
                continue
            typed = {"types", "point_types"} <= tables
            # A business's phone, website and hours (the businesses part's biz_details; none in older packs).
            has = "biz_details" in tables
            sql = ("SELECT p.key, p.source, p.name, p.tag, p.lat, p.lon, p.last" +
                   (", d.phone, d.website, d.opening_hours" if has else "") +
                   (", t.name AS type FROM points p LEFT JOIN point_types l ON l.id = p.id LEFT JOIN types t ON "
                    "t.id = l.type" if typed else ", NULL AS type FROM points p") +
                   (" LEFT JOIN biz_details d ON d.id = p.id" if has else "") + f" WHERE p.ccell IN ({cells})")
            for r in pack._rows(sql):
                if r["last"] and pack.latest and r["last"] < pack.latest:
                    continue                    # closed or gone: only places listed at the last build
                hit = (r["type"] in spec.get("types", ())) or (r["tag"] in spec.get("tags", ())) or \
                    (pattern is not None and pattern.search(r["name"] or ""))
                if hit:
                    out.append({"key": r["key"], "source": r["source"], "kind": kind, "name": r["name"],
                                "lat": r["lat"], "lon": r["lon"],
                                "details": {k: r[k] for k in ("phone", "website", "opening_hours") if r.get(k)},
                                "attribution": (pack.sources.get(r["source"]) or {}).get("attribution", "")})
        for r in out:
            r["lat"], r["lon"] = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
            r["d"] = fmt.metres(lat, lon, r["lat"], r["lon"]) if abs(r["lat"] - lat) < 2 else \
                fmt.EARTH_M * math.radians(abs(r["lat"] - lat))
        return out

    def nearest(self, lat, lon, kind, limit=3, max_km=100, units="miles"):
        """The nearest places of a kind (KINDS, or services.SERVICE_KINDS; "DMV" and other ALIASES work), nearest
        first: {"kind", "places": [{"name", "distance_m", "bearing", "phone", "opening_hours", "address",
        "wheelchair", "sources"}], "phrase"}, or None when there is none within max_km."""
        kind = kind_of(kind)
        found, rings = [], 1
        while True:
            found = [r for r in self._candidates(lat, lon, kind, rings) if r["d"] <= max_km * 1000]
            if len(found) >= limit or rings * 11 >= max_km:
                break
            rings = rings * 2 + 1
        if not found:
            return None
        found.sort(key=lambda r: r["d"])
        merged = []
        for r in found:                         # one place listed by several sources: kept once, details joined
            same = next((m for m in merged if normal_name(m["name"]) == normal_name(r["name"]) and
                         fmt.metres(m["lat"], m["lon"], r["lat"], r["lon"]) < 150), None)
            if same:
                same["sources"].add(r["source"])
                same["found"].append((r["source"], r["details"]))
                # each detail from the best source that has it: OpenStreetMap, then All The Places, Overture,
                # Foursquare (lookup.join_details)
                same["details"] = join_details(same["found"])
            else:
                merged.append(dict(r, sources={r["source"]}, details=dict(r["details"]),
                                   found=[(r["source"], r["details"])]))
        places = []
        for r in merged[:limit]:
            d = r["details"]
            address = " ".join(x for x in (d.get("addr:housenumber"), d.get("addr:street")) if x)
            if d.get("addr:city"):
                address = f"{address}, {d['addr:city']}" if address else d["addr:city"]
            places.append({"name": r["name"], "kind": r["kind"], "distance_m": round(r["d"]),
                           "bearing": bearing_word(lat, lon, r["lat"], r["lon"]), "lat": r["lat"], "lon": r["lon"],
                           "phone": d.get("phone") or d.get("contact:phone") or "",
                           "opening_hours": d.get("opening_hours", ""), "address": address,
                           "website": d.get("website") or d.get("contact:website") or "",
                           "wheelchair": d.get("wheelchair", ""), "sources": sorted(r["sources"])})
        p = places[0]
        bits = [f"The nearest {kind} is {p['name']}" + (f", {p['address']}" if p["address"] else "") +
                f", {distance_words(p['distance_m'], units)} {p['bearing']}."]
        if p["phone"]:
            bits.append(f"Phone {p['phone']}.")
        if p["opening_hours"]:
            bits.append(f"Hours: {p['opening_hours']}.")
        if p["wheelchair"] in WHEELCHAIR:
            bits.append(WHEELCHAIR[p["wheelchair"]])
        if len(places) > 1:
            bits.append("Next: " + "; ".join(f"{q['name']}, {distance_words(q['distance_m'], units)} {q['bearing']}"
                                             for q in places[1:]) + ".")
        return {"kind": kind, "places": places, "phrase": " ".join(bits),
                "attribution": "; ".join(sorted({s for q in places for s in q["sources"]}))}

    # -- weather

    def _zone_at(self, lat, lon, kind):
        """The svc_zones row of a kind ("county", "forecast zone") holding a position, or None."""
        y, x = int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE))
        for pack in self.packs:
            if "svc_zones" not in self._tables(pack):
                continue
            for r in pack._rows("SELECT * FROM svc_zones WHERE kind = ? AND minlat <= ? AND maxlat >= ? AND "
                                "minlon <= ? AND maxlon >= ?", (kind, y, y, x, x)):
                if inside_rings(lat, lon, fmt.unpack_rings(r["rings"])):
                    return dict(r, pack=pack)
        return None

    def weather_zone(self, lat, lon):
        """The NWS county and public forecast zone at a position: {"county", "fips", "same", "zone", "zone_name",
        "office", "phrase"}, or None when no services pack covers it."""
        county, zone = self._zone_at(lat, lon, "county"), self._zone_at(lat, lon, "forecast zone")
        if county is None and zone is None:
            return None
        fips = county["code"] if county else ""
        bits = []
        if county:
            bits.append(f"You are in {county['name']} County, {county['state']} (SAME code 0{fips}).")
        if zone:
            bits.append(f"Forecast zone {zone['code']}, {zone['name']}.")
        office = (zone or county)["office"]
        if office:
            bits.append(f"Forecast office: {office}.")
        return {"county": county["name"] if county else "", "fips": fips, "same": f"0{fips}" if fips else "",
                "state": (county or zone)["state"], "zone": zone["code"] if zone else "",
                "zone_name": zone["name"] if zone else "", "office": office, "phrase": " ".join(bits),
                "attribution": ATTRIBUTION_NWS}

    def weather_radio(self, lat, lon, units="miles"):
        """The NOAA Weather Radio transmitters covering the county at a position, nearest first: {"county", "same",
        "stations": [{"call_sign", "frequency", "site", "distance_m", "bearing", "power", "status"}], "phrase"};
        None when the county or its transmitters are not known. A weather radio set to the SAME code warns only for
        that county."""
        zone = self.weather_zone(lat, lon)
        if not zone or not zone["same"]:
            return None
        stations = {}
        for pack in self.packs:
            if "svc_radio" not in self._tables(pack):
                continue
            for r in pack._rows("SELECT * FROM svc_radio WHERE same = ?", (zone["same"],)):
                slat, slon = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
                stations[r["call_sign"]] = {"call_sign": r["call_sign"], "frequency": r["frequency"],
                                            "site": r["site"], "site_state": r["site_state"],
                                            "distance_m": round(fmt.metres(lat, lon, slat, slon)),
                                            "bearing": bearing_word(lat, lon, slat, slon), "power": r["power"],
                                            "status": r["status"], "remarks": r["remarks"]}
        if not stations:
            return None
        ordered = sorted(stations.values(), key=lambda s: s["distance_m"])
        s = ordered[0]
        bits = [f"Your NOAA Weather Radio station is {s['call_sign']} from {s['site']}, {s['frequency']} MHz, "
                f"{distance_words(s['distance_m'], units)} {s['bearing']}."]
        if s["status"] and s["status"].upper() != "NORMAL":
            bits.append(f"Its status: {s['status'].lower()}.")
        bits.append(f"SAME code for {zone['county']} County: {zone['same']}.")
        if len(ordered) > 1:
            bits.append("Also covering this county: " + "; ".join(
                f"{o['call_sign']} {o['frequency']} MHz from {o['site']}" for o in ordered[1:4]) + ".")
        return {"county": zone["county"], "same": zone["same"], "stations": ordered, "phrase": " ".join(bits),
                "attribution": "NOAA Weather Radio county coverage list, " + ATTRIBUTION_NWS}
