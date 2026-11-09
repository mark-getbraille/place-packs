"""Places not on land: on a lake, off a coast, on the open ocean, or in the air. Works without any pack, from the
small global layer data/water.json.gz (Natural Earth land, marine names, lakes and populated places; OurAirports
airports; all public domain; tools/build_water.py).

WaterLayer().describe(lat, lon, altitude=None, nearest=None) -> lookup.Result with kind "water" or "air", or None
when the position is on land (and not in the air):
  - in the air: GPS altitude above the ground. Over water, more than AIR_OVER_WATER_M; within AIRPORT_KM of an
    airport, more than AIR_ABOVE_AIRPORT_M above the airport's elevation ("near Boston Logan International
    Airport"); elsewhere over land, more than AIR_OVER_LAND_M (no terrain model is shipped: high mountains are lower
    than that). "in the air, about 35,000 feet (10,700 m) over the Pacific Ocean, about 400 miles northeast of
    Honolulu";
  - on a lake (Natural Earth's large lakes): "on Lake Champlain";
  - at sea: the position is off the land polygons and more than COAST_M from them (the coastline is simplified to
    about 1 km, so a beach stays on land): the marine area holding it ("Vineyard Sound") or the nearest one, and the
    nearest town with distance and direction: "on Vineyard Sound, about 3 miles south of Edgartown"; farther than
    OPEN_OCEAN_KM from land: "on the Atlantic Ocean, about 400 miles east of Boston".
nearest(lat, lon) -> (name, lat, lon) gives a better nearest town (a pack's or the program's own place names);
otherwise Natural Earth's populated places are used.
phrase(result, units) and short(result) give the words; units: "miles", "km", "both" or "nautical".
"""

import gzip
import json
import math
import os
import threading

from placepacks import fmt

AIR_OVER_WATER_M = 300
AIR_ABOVE_AIRPORT_M = 300
AIR_OVER_LAND_M = 4500
AIRPORT_KM = 15
COAST_M = 1000
OPEN_OCEAN_KM = 50
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "water.json.gz")
COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def bearing_word(lat1, lon1, lat2, lon2):
    """The compass direction from point 1 to point 2: "south", "northeast"."""
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return COMPASS[int((deg + 22.5) // 45) % 8]


def great_circle_m(lat1, lon1, lat2, lon2):
    """Distance in metres along the Earth (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * fmt.EARTH_M * math.asin(math.sqrt(min(1.0, a)))


def distance_text(metres, units="miles"):
    """"about 3 miles", "about 5 km", "about 3 miles (5 km)", "about 3 nautical miles"; "less than a mile"."""
    km, miles, nm = metres / 1000, metres / 1609.344, metres / 1852

    def rounded(v):
        return round(v) if v < 20 else int(round(v / 5) * 5) if v < 200 else int(round(v / 50) * 50)
    if units == "km":
        return "less than 1 km" if km < 0.75 else f"about {rounded(km)} km"
    if units == "nautical":
        return "less than a nautical mile" if nm < 0.75 else \
            f"about {rounded(nm)} nautical mile{'s' if rounded(nm) != 1 else ''}"
    text = "less than a mile" if miles < 0.75 else f"about {rounded(miles)} mile{'s' if rounded(miles) != 1 else ''}"
    if units == "both" and miles >= 0.75:
        text += f" ({rounded(km)} km)"
    return text


def altitude_text(metres, units="miles"):
    """"about 35,000 feet (10,700 m)" (feet first unless units is "km": "about 10,700 m")."""
    feet = metres * 3.28084
    f = int(round(feet / 1000) * 1000) if feet >= 10000 else int(round(feet / 100) * 100)
    m = int(round(metres / 100) * 100)
    return f"about {m:,} m" if units == "km" else f"about {f:,} feet ({m:,} m)"


def _inside(rings, x, y):
    """Even-odd rule on rings of [lon, lat] scaled integers."""
    inside = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


class WaterLayer:
    """The global layer (see the module docstring). path: the data file (default the one shipped)."""

    _cache, _lock = {}, threading.Lock()

    def __init__(self, path=None):
        path = path or DATA
        with self._lock:
            if path not in self._cache:
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    self._cache[path] = json.load(f)
        d = self._cache[path]
        self.s = d["scale"]
        self.land, self.marine, self.lakes = d["land"], d["marine"], d["lakes"]
        self.places, self.airports = d["places"], d["airports"]

    def _containing(self, areas, lat, lon):
        """The areas holding the position."""
        x, y = lon * self.s, lat * self.s
        return [a for a in areas if a["b"][0] <= x <= a["b"][2] and a["b"][1] <= y <= a["b"][3] and
                _inside(a["p"], x, y)]

    def on_land(self, lat, lon):
        """True when the position is on Natural Earth's land (lakes count as water)."""
        return bool(self._containing(self.land, lat, lon)) and not self._containing(self.lakes, lat, lon)

    def coast_m(self, lat, lon, limit_km=OPEN_OCEAN_KM + 10):
        """Metres to the nearest land edge (at most about limit_km; more is said as limit_km * 1000)."""
        pad = limit_km / 111.0 * self.s
        x, y = lon * self.s, lat * self.s
        best = limit_km * 1000.0
        for a in self.land:
            w, s, e, n = a["b"]
            if x < w - pad * 3 or x > e + pad * 3 or y < s - pad or y > n + pad:
                continue
            for ring in a["p"]:
                pts = [(p[1] * 100, p[0] * 100) for p in ring]       # to microdegrees (lat, lon)
                for p1, p2 in zip(pts, pts[1:]):
                    d = fmt.segment_metres(lat, lon, p1, p2)
                    if d < best:
                        best = d
        return best

    def nearest_place(self, lat, lon):
        """(name, lat, lon) of the nearest Natural Earth populated place."""
        best = None
        for name, adm1, adm0, py, px in self.places:
            d = (py / self.s - lat) ** 2 + ((px / self.s - lon) * math.cos(math.radians(lat))) ** 2
            if best is None or d < best[0]:
                best = (d, name, py / self.s, px / self.s)
        return best[1:] if best else None

    def nearest_airport(self, lat, lon):
        """(name, code, lat, lon, elevation m, distance m) of the nearest listed airport."""
        best = None
        for name, code, py, px, elev in self.airports:
            d = great_circle_m(lat, lon, py / self.s, px / self.s)
            if best is None or d < best[5]:
                best = (name, code, py / self.s, px / self.s, elev * 0.3048, d)
        return best

    def marine_at(self, lat, lon):
        """(name, class) of the smallest marine area holding the position, else of the nearest one, or None."""
        found = self._containing(self.marine, lat, lon)
        if found:
            a = min(found, key=lambda a: (a["b"][2] - a["b"][0]) * (a["b"][3] - a["b"][1]))
            return a["n"], a["c"]
        x, y = lon * self.s, lat * self.s
        best = None
        for a in self.marine:
            w, s, e, n = a["b"]
            dx = max(w - x, 0, x - e)
            dy = max(s - y, 0, y - n)
            d = dx * dx + dy * dy
            if best is None or d < best[0]:
                best = (d, a["n"], a["c"])
        return best[1:] if best else None

    def describe(self, lat, lon, altitude=None, nearest=None):
        """The Result for water or the air, or None (see the module docstring)."""
        from placepacks.lookup import Result
        lake = self._containing(self.lakes, lat, lon)
        land = not lake and bool(self._containing(self.land, lat, lon))
        town = None
        if nearest is not None:
            try:
                town = nearest(lat, lon)
            except Exception:  # noqa: BLE001 - the built-in places instead
                town = None
        town = town or self.nearest_place(lat, lon)

        def place_fields():
            """The nearest town with distance and direction."""
            if not town:
                return {}
            return {"town": town[0], "distance_m": great_circle_m(town[1], town[2], lat, lon),
                    "bearing": bearing_word(town[1], town[2], lat, lon)}
        if altitude is not None:
            airport = self.nearest_airport(lat, lon)
            near_airport = airport and airport[5] <= AIRPORT_KM * 1000
            if (not land and altitude > AIR_OVER_WATER_M) or \
                    (near_airport and altitude - airport[4] > AIR_ABOVE_AIRPORT_M and altitude < AIR_OVER_LAND_M) or \
                    (land and altitude > AIR_OVER_LAND_M):
                over = ""
                if not land:
                    m = self.marine_at(lat, lon)
                    over = m[0] if m else ""
                elif lake:
                    over = lake[0]["n"]
                fields = place_fields()
                if land and fields.get("distance_m", 1e9) <= 25000:
                    over = town[0]
                    fields = {"town": town[0]}
                return Result(kind="air", altitude_m=altitude, over=over, latitude=lat, longitude=lon,
                              airport=airport[0] if near_airport and altitude < AIR_OVER_LAND_M else "",
                              sources=["naturalearth"], source_names=["Natural Earth"],
                              attributions=["Coastline, seas and places from Natural Earth (public domain); airports "
                                            "from OurAirports (public domain)."], **fields)
        if lake:
            return Result(kind="water", water_name=lake[0]["n"], water_cls="lake", latitude=lat, longitude=lon,
                          sources=["naturalearth"], source_names=["Natural Earth"],
                          attributions=["Lakes from Natural Earth (public domain)."])
        if land:
            return None
        coast = self.coast_m(lat, lon)
        if coast < COAST_M:
            return None
        m = self.marine_at(lat, lon)
        return Result(kind="water", water_name=m[0] if m else "", water_cls=m[1] if m else "sea",
                      latitude=lat, longitude=lon, sources=["naturalearth"], source_names=["Natural Earth"],
                      attributions=["Coastline, seas and places from Natural Earth (public domain)."],
                      neighbourhood="open" if coast >= OPEN_OCEAN_KM * 1000 else "", **place_fields())


def _the(name):
    """"the Atlantic Ocean", "Vineyard Sound", "Lake Champlain"."""
    if not name:
        return "the water"
    low = name.lower()
    if low.startswith(("lake ", "the ")) or not low.split()[-1] in ("ocean", "sea", "gulf", "bay", "channel",
                                                                     "strait", "sound", "river", "lagoon", "fjord"):
        return name
    return name if low.split()[0] in ("lake",) else "the " + name


def phrase(result, units="miles"):
    """The words for a water or air result (see the module docstring)."""
    where = ""
    if result.town and result.distance_m is not None:
        if result.distance_m < 1500 and result.kind != "water":
            where = f"over {result.town}"
        else:
            where = f"{distance_text(result.distance_m, units)} {result.bearing} of {result.town}"
    if result.kind == "air":
        head = f"in the air, {altitude_text(result.altitude_m, units)}"
        if result.airport:
            return f"{head}, near {result.airport}"
        if result.over and result.over == result.town:
            return f"{head} over {result.over}"
        if result.over:
            head += f" over {_the(result.over)}"
        return f"{head}, {where}" if where else head
    if result.water_cls == "lake":
        return f"on {_the(result.water_name)}"
    text = f"on {_the(result.water_name)}"
    return f"{text}, {where}" if where else text


def short(result):
    """File-name words: "Over the Pacific Ocean", "Over Denver", "Near Boston Logan International Airport",
    "Lake Champlain", "Off Edgartown"."""
    if result.kind == "air":
        if result.airport:
            return f"Near {result.airport}"
        return f"Over {_the(result.over) if result.over != result.town else result.over}" if result.over else \
            "In the air"
    if result.water_cls == "lake":
        return result.water_name
    if result.town and result.neighbourhood != "open":
        return f"Off {result.town}"
    name = _the(result.water_name)
    return name[:1].upper() + name[1:]
