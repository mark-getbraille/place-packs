"""The local services and emergency layers, written into the optional "services" part
(us-vermont-services.osmpack). FORMAT.md, "The services part", describes the tables; placepacks/local.py reads them
("the nearest Social Security office", "my NOAA Weather Radio frequency", "my forecast zone").

What is kept:
  - svc_places, from OpenStreetMap (source osm-services, ODbL like every OpenStreetMap layer): the offices and
    services a person goes to, each with its kind (SERVICE_KINDS: Social Security office, Service Canada centre,
    motor vehicle office, veterans office, courthouse, post office, library, pharmacy, food bank, soup kitchen,
    shelter, social services, hospital, clinic, police, fire station, town hall, government office, community
    centre, defibrillator) and its phone, opening hours, address, website and wheelchair access;
  - svc_zones, from the National Weather Service (public domain): the county areas (with their FIPS code, the
    county's SAME code without the leading digit) and the public forecast zones, as polygons;
  - svc_radio, from the NOAA Weather Radio county coverage list (public domain): every transmitter that covers each
    county of the region, with its call sign, frequency, site, power and status.
The libraries (IMLS), health centres (HRSA), post offices and courthouses (USGS structures) and the pharmacies and
food banks of the core and extra parts are not copied here: placepacks/local.py also searches those packs.

A ServiceStore is attached to a PackWriter (store(writer)), like the navigation part's NavStore; PackWriter.finish
calls ServiceStore.finish, which writes the indexes. Only the standard library is used here.
"""

import json
import re

from placepacks import fmt

TABLES = {
    "svc_places": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, kind TEXT, name TEXT, lat INTEGER, lon INTEGER, "
                  "cell INTEGER, ccell INTEGER, details TEXT",
    "svc_zones": "id INTEGER PRIMARY KEY, key TEXT, source TEXT, kind TEXT, code TEXT, name TEXT, state TEXT, "
                 "office TEXT, minlat INTEGER, minlon INTEGER, maxlat INTEGER, maxlon INTEGER, rings BLOB",
    "svc_radio": "id INTEGER PRIMARY KEY, call_sign TEXT, frequency TEXT, site TEXT, site_state TEXT, lat INTEGER, "
                 "lon INTEGER, power TEXT, status TEXT, office TEXT, same TEXT, county TEXT, state TEXT, "
                 "remarks TEXT",
}
DETAIL_TAGS = ("phone", "contact:phone", "opening_hours", "website", "contact:website", "addr:housenumber",
               "addr:street", "addr:unit", "addr:city", "addr:postcode", "wheelchair", "wheelchair:description",
               "toilets:wheelchair", "operator", "description", "social_facility:for", "healthcare:speciality")

# Motor vehicle offices go by many names (and a few have a government tag of their own).
MOTOR_VEHICLE = re.compile(r"\b(dmv|bmv|mvd|rmv|mva|motor vehicles?|driver'?s?'? licen[cs](e|ing)|driver services|"
                           r"drivers? exam|tag (and|&) title|tag office|title office|license office|licence office|"
                           r"serviceontario|service ?bc|saaq|icbc|access nova scotia|service new brunswick|"
                           r"registry agent|sgi )", re.I)
SOCIAL_SECURITY = re.compile(r"\bsocial security\b|\bSSA\b", re.I)
SERVICE_CANADA = re.compile(r"\bservice canada\b", re.I)
VETERANS = re.compile(r"\b(veterans? affairs|vet center|veterans administration|VA (medical|clinic|outpatient|"
                      r"community|health|regional|benefits)|VAMC|CBOC)\b", re.I)

# The kinds, as a person would say them; local.py asks for these words.
SERVICE_KINDS = ("social security office", "service canada centre", "motor vehicle office", "veterans office",
                 "courthouse", "post office", "library", "pharmacy", "food bank", "soup kitchen", "shelter",
                 "social services", "hospital", "clinic", "police", "fire station", "town hall", "government office",
                 "community centre", "defibrillator")


def store(writer):
    """The ServiceStore of a PackWriter (made, with its tables, the first time it is asked for)."""
    if getattr(writer, "_svc", None) is None:
        writer._svc = ServiceStore(writer)
    return writer._svc


def service_kind(tags):
    """The service an OpenStreetMap object is (one of SERVICE_KINDS), or None. Named objects only, except
    defibrillators."""
    name = tags.get("name") or ""
    amenity, office, gov = tags.get("amenity"), tags.get("office"), tags.get("government")
    social = tags.get("social_facility")
    if tags.get("emergency") == "defibrillator":
        return "defibrillator"
    if not name:
        return None
    if gov == "social_security" or (SOCIAL_SECURITY.search(name) and (office or amenity or tags.get("building"))):
        return "social security office"
    if SERVICE_CANADA.search(name) and (office or amenity or tags.get("building") or tags.get("shop")):
        return "service canada centre"
    if gov in ("transportation", "vehicle_registration", "licensing") and MOTOR_VEHICLE.search(name) or \
            (MOTOR_VEHICLE.search(name) and (office or amenity in ("townhall", "public_building") or
                                             tags.get("building") or tags.get("shop") == "licence")):
        return "motor vehicle office"
    if VETERANS.search(name) and (office or amenity or tags.get("healthcare")):
        return "veterans office"
    if amenity == "courthouse":
        return "courthouse"
    if amenity == "post_office":
        return "post office"
    if amenity == "library":
        return "library"
    if amenity == "pharmacy" or tags.get("healthcare") == "pharmacy":
        return "pharmacy"
    if amenity == "food_bank" or social == "food_bank":
        return "food bank"
    if social == "soup_kitchen":
        return "soup kitchen"
    if social in ("shelter", "outreach") or amenity == "shelter" and tags.get("shelter_type") == "emergency":
        return "shelter" if social != "outreach" else "social services"
    if amenity == "social_facility" or gov in ("social_services", "social_welfare"):
        return "social services"
    if amenity == "hospital":
        return "hospital"
    if amenity == "clinic" or tags.get("healthcare") in ("clinic", "centre"):
        return "clinic"
    if amenity == "police":
        return "police"
    if amenity == "fire_station":
        return "fire station"
    if amenity == "townhall":
        return "town hall"
    if office == "government":
        return "government office"
    if amenity == "community_centre":
        return "community centre"
    return None


class ServiceStore:
    """The services tables of one pack being written (see the module docstring)."""

    def __init__(self, writer):
        """Make the tables in the writer's database."""
        self.writer, self.db = writer, writer.db
        for name, columns in TABLES.items():
            self.db.execute(f"CREATE TABLE {name} ({columns})")

    def _inside(self, lat, lon):
        """True when a position is kept (always, except outside a sub-region's area)."""
        w = self.writer
        if w.clip is not None and not w._inside(lat, lon):
            return False
        w._extend(lat, lon)
        return True

    def add_place(self, key, source, kind, name, lat, lon, details=None):
        """A service (its kind one of SERVICE_KINDS) at a position (degrees); details: {tag: value}."""
        if not self._inside(lat, lon):
            return False
        picked = {k: v for k, v in (details or {}).items() if v}
        self.db.execute("INSERT INTO svc_places (key, source, kind, name, lat, lon, cell, ccell, details) VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, kind, name, int(round(lat * fmt.SCALE)), int(round(lon * fmt.SCALE)),
                         fmt.fine_cell(lat, lon), fmt.coarse_cell(lat, lon),
                         json.dumps(picked, ensure_ascii=False, separators=(",", ":")) if picked else ""))
        return True

    def add_osm(self, key, source, tags, lat, lon):
        """An OpenStreetMap node or area centre: kept when service_kind names it."""
        kind = service_kind(tags)
        if kind:
            name = (tags.get("name") or ("Defibrillator" if kind == "defibrillator" else "")).strip()
            self.add_place(key, source, kind, name, lat, lon, {k: tags.get(k) for k in DETAIL_TAGS})

    def add_zone(self, key, source, kind, code, name, state, office, rings):
        """A county or forecast zone: rings of (lat, lon) degrees, simplified at 50 m (holes are rings too)."""
        rings = [r for r in (fmt.simplify(r, 50.0) for r in rings if len(r) >= 4) if len(r) >= 4]
        if not rings:
            return False
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        s, w, n, e = min(lats), min(lons), max(lats), max(lons)
        if self.writer.clip is not None and not self.writer._touches(s, w, n, e):
            return False
        self.writer._extend(s, w, n, e)
        self.db.execute("INSERT INTO svc_zones (key, source, kind, code, name, state, office, minlat, minlon, maxlat, "
                        "maxlon, rings) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, source, kind, code, name, state, office, *fmt.micro([(s, w)])[0],
                         *fmt.micro([(n, e)])[0], fmt.pack_rings([fmt.micro(r) for r in rings])))
        return True

    def add_radio(self, row):
        """One transmitter covering one county: {call_sign, frequency, site, site_state, lat, lon (degrees), power,
        status, office, same, county, state, remarks}."""
        self.db.execute("INSERT INTO svc_radio (call_sign, frequency, site, site_state, lat, lon, power, status, "
                        "office, same, county, state, remarks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["call_sign"], row["frequency"], row["site"], row["site_state"],
                         int(round(row["lat"] * fmt.SCALE)), int(round(row["lon"] * fmt.SCALE)), row["power"],
                         row["status"], row["office"], row["same"], row["county"], row["state"], row["remarks"]))

    def finish(self):
        """Write the indexes. Returns the counts {table: rows}."""
        self.db.executescript("""
            CREATE INDEX svc_places_ccell ON svc_places (kind, ccell);
            CREATE INDEX svc_zones_kind ON svc_zones (kind);
            CREATE INDEX svc_radio_same ON svc_radio (same);
        """)
        return {name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in TABLES}
