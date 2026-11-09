"""The adapter between this program and the placepacks package (the free offline place packs of this repository).

Everything the program needs from placepacks goes through here, so the rest of the program does not depend on its
details, and the tests can use a stand-in finder (StandInFinder) without any pack.

  PlaceInfo            where one photo was taken, at every level: place, the named areas around it (smallest
                       first, such as "Nags Head" then "Outer Banks" then "Dare County"), town, county, state,
                       country, or the water/air description ("Off Martha's Vineyard", "Over the Pacific Ocean")
  Places               looks up positions (with a cache: photos taken close together are looked up once), using the
                       photo's date for the names of that time (placepacks keeps history), and gets the packs a
                       folder needs: ask first with the size, download automatically, or never (the setting)
  Spot                 the most specific place known for one photo, for its file name ("Put the exact place in each
                       picture's name"): a named place at the point as named on the photo's date, the street
                       address, the neighbourhood, the town, the water; Places.exact looks it up
  StandInFinder        a finder made of rectangles, for the tests and for trying the program without packs

placepacks calls used (all on this computer, except ensure_pack, which downloads a pack from the public releases):
  placepacks.lookup.Finder(folder=...).lookup(lat, lon, when=..., detail="area", altitude=...) -> Result
      (detail "area" names the folders; detail "address" gives the exact place for the file names: a business,
      building, school or landmark at the point, else the address point or street, with the neighbourhood and town)
  Finder.areas_at(lat, lon, when=None) -> [(name, cls, size_m2, source)], smallest first (when it exists)
  placepacks.regions.regions_for(lat, lon) -> [region id, best first]; region_label(id)
  placepacks.download.Catalogue().packs() -> {key: PackInfo}; ensure_pack(region, ...); default_folder()
  placepacks.when.When.parse(datetime)
No photo data is ever sent anywhere: a pack download asks only for the pack's file.
"""

import math
import os
import re
import sys

from pli import myplaces as mp

# Kinds of area (the cls of placepacks.lookup.Finder.areas_at) and what each is to this program:
#   "town" (Census places, county subdivisions)                         the town level
#   "admin" (government divisions, admin levels 3 to 10)                town, county or state: see resolve_admin
#   "region" (islands, island chains, peninsulas, capes, valleys, tourist regions), "park" (parks, protected
#   areas, national parks and seashores), "nature"                       named areas that can name a trip
#   "zip", "neighbourhood", "campus", "landmark", "water"                 not used to name folders
TOWN_CLASSES = ("town", "city", "village", "hamlet", "municipality", "census_place")
COUNTY_CLASSES = ("county", "parish", "district", "census_division")
STATE_CLASSES = ("state", "province", "territory")
COUNTRY_CLASSES = ("country", "nation")
SKIP_CLASSES = ("zip", "neighbourhood", "campus", "landmark", "water", "building", "business", "street", "public",
                "transit", "address", "range", "settlement")
# Words in a government division's name that say it is a county (or its equal elsewhere).
COUNTY_WORDS = re.compile(r"\b(county|parish|borough|census area|regional municipality|regional district|"
                          r"district|municipality of|county of|united counties|shire)\b", re.IGNORECASE)
COUNTY_MIN_M2 = 2e8           # an "admin" area of 200 km2 or more that is not the town or state counts as a county
LEVELS = ("place", "town", "county", "state", "country")
OSM_ATTRIBUTION = "© OpenStreetMap contributors, Open Database License (ODbL)"


def _ensure_import_path():
    """Make placepacks importable when the program runs from this repository's source (it lives one folder up)."""
    try:
        import placepacks  # noqa: F401
    except ImportError:
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isdir(os.path.join(here, "placepacks")) and here not in sys.path:
            sys.path.insert(0, here)


def admin_level(cls):
    """What an area's cls is to this program: "town", "county", "state", "country", "admin" (a government division
    whose level is worked out by resolve_admin), "skip" (not used for folder names), or "" for a named area that can
    name a trip (an island chain such as the Outer Banks, a region, a park, a national seashore)."""
    c = (cls or "").lower().replace("-", "_").replace(" ", "_")
    if c == "admin" or c.startswith("admin"):
        return "admin"
    for level, names in (("town", TOWN_CLASSES), ("county", COUNTY_CLASSES), ("state", STATE_CLASSES),
                         ("country", COUNTRY_CLASSES), ("skip", SKIP_CLASSES)):
        if c in names:
            return level
    return ""


class Area:
    """A named area a photo is in: name, cls (its kind, from placepacks), size_m2 (None if not known), source,
    level ("town", "county", "state", "country", "skip", or "" for a named area that can name a trip)."""

    def __init__(self, name, cls="", size_m2=None, source="", level=None):
        """Store the fields; level from the cls when not given."""
        self.name, self.cls, self.size_m2, self.source = name, cls or "", size_m2, source or ""
        self.level = admin_level(cls) if level is None else level

    def __repr__(self):
        """For test messages."""
        return f"Area({self.name!r}, {self.cls!r}, {self.size_m2})"


class PlaceInfo:
    """Where one photo was taken, at every level (any of them "" when not known).

    place: the place itself (a park, attraction, building); town, county, state, country; areas: [Area], smallest
    first (every named area around it, government divisions included); water: the water or air description
    ("Off Martha's Vineyard", "Over the Pacific Ocean"; "" on land); my_place: the user's own name ("Grandma's
    house") when the photo is inside one of My places; probably: placepacks is not sure of the name; source: where
    the names came from, in words; attributions: the sources' attributions (shown in the report and About)."""

    def __init__(self, place="", town="", county="", state="", country="", areas=None, water="", my_place="",
                 probably=False, source="", attributions=None):
        """Store the fields (see the class docstring)."""
        self.place, self.town, self.county, self.state, self.country = place, town, county, state, country
        self.areas = list(areas or [])
        self.water, self.my_place, self.probably = water, my_place, probably
        self.source = source
        self.attributions = list(attributions or [])

    @property
    def known(self):
        """True if anything at all is known about where it is."""
        return bool(self.my_place or self.water or self.place or self.town or self.county or self.state or
                    self.country or self.areas)

    def name_at(self, level):
        """The name at a level ("place", "town", "county", "state", "country"), falling back to the next wider level
        when that one is not known (a photo outside any town is named by its county). My places come first at the
        place and town levels; on water or in the air the water description is used at every level."""
        if self.water and not (self.my_place and level in ("place", "town")):
            return self.water
        if self.my_place and level in ("place", "town"):
            return self.my_place
        order = LEVELS[LEVELS.index(level):] if level in LEVELS else LEVELS
        for lv in order:
            value = getattr(self, lv)
            if value:
                return value
        return ""

    def level_found(self, level):
        """The level name_at(level) actually used ("water", "my place", "town", ...; "" if none)."""
        if self.water and not (self.my_place and level in ("place", "town")):
            return "water"
        if self.my_place and level in ("place", "town"):
            return "my place"
        order = LEVELS[LEVELS.index(level):] if level in LEVELS else LEVELS
        return next((lv for lv in order if getattr(self, lv)), "")

    def __repr__(self):
        """For test messages."""
        return (f"PlaceInfo(place={self.place!r}, town={self.town!r}, state={self.state!r}, "
                f"areas={[a.name for a in self.areas]}, water={self.water!r}, my_place={self.my_place!r})")


class Spot:
    """The most specific place known for one photo, for its file name (any field "" when not known).

    my_place: the user's own name for the place; name: a named business, landmark, park, school or building at the
    point, as it was named on the photo's date (the packs keep the history of names); house_number and street: the
    address point (house_number only for a real address point, never an estimated one) or the street;
    neighbourhood; town (or village); water: the water or air description ("Off Martha's Vineyard")."""

    FIELDS = ("my_place", "name", "house_number", "street", "neighbourhood", "town", "water")

    def __init__(self, **fields):
        """Store the fields (see the class docstring)."""
        for k in self.FIELDS:
            setattr(self, k, fields.get(k) or "")

    @property
    def known(self):
        """True if anything is known."""
        return any(getattr(self, k) for k in self.FIELDS)

    def __repr__(self):
        """For test messages."""
        return "Spot(" + ", ".join(f"{k}={getattr(self, k)!r}" for k in self.FIELDS if getattr(self, k)) + ")"


def spot_from_result(result, info=None):
    """A Spot from a placepacks Result looked up at the "address" detail, with the PlaceInfo of the same position
    (info) filling the town, the neighbourhood (an area of kind "neighbourhood") and the water when the Result has
    none. A place found only near the point ("next to Riverside Library", kind "nearby") is not used: the file name
    should say where the photo was taken, not what was close by."""
    spot = Spot()
    if result is not None:
        kind, cls = _get(result, "kind"), _get(result, "cls")
        spot.water = water_phrase(result)
        if kind in ("place", "area") and _get(result, "name"):
            if cls == "neighbourhood":
                spot.neighbourhood = _get(result, "name")
            elif cls not in ("water", "zip"):
                spot.name = _get(result, "name")
        spot.street = _get(result, "street")
        if kind == "address" and spot.street:
            spot.house_number = str(_get(result, "house_number") or "")
        spot.neighbourhood = spot.neighbourhood or _get(result, "neighbourhood")
        spot.town = _get(result, "town")
    if info is not None:
        spot.town = spot.town or info.town
        spot.water = spot.water or info.water
        spot.my_place = info.my_place
        if not spot.neighbourhood:
            spot.neighbourhood = next((a.name for a in info.areas if a.cls == "neighbourhood"), "")
    return spot


def _get(obj, name, default=""):
    """obj.name, or default when it is missing or empty."""
    value = getattr(obj, name, default)
    return default if value is None else value


def water_phrase(result):
    """The water or air description of a placepacks Result ("Off Martha's Vineyard", "Over the Pacific Ocean"),
    made safe for a folder name; "" if it is on land."""
    kind = _get(result, "kind")
    if kind not in ("water", "air"):
        return ""
    text = ""
    short = getattr(result, "short", None)
    if callable(short):
        try:
            text = short("area") or ""
        except Exception:  # noqa: BLE001 - an older or newer placepacks: build it below
            text = ""
    if not text:
        name = _get(result, "water_name") or _get(result, "name")
        if not name:
            return ""
        text = f"Over {name}" if kind == "air" else (f"Off {name}" if _get(result, "over") in ("", None, False)
                                                   and _get(result, "distance_m", 0) else name)
    return text


def info_from_result(result, areas=()):
    """A PlaceInfo from a placepacks Result and the areas around the position ([(name, cls, size_m2[, source])]).
    Without areas, the Result's own area (kind "area") is used, with its town, region and country."""
    info = PlaceInfo()
    if result is not None:
        kind = _get(result, "kind")
        info.water = water_phrase(result)
        if kind in ("place", "nearby", "area"):
            info.place = _get(result, "name")
        info.town = _get(result, "town")
        info.state = _get(result, "region")
        info.country = _get(result, "country")
        info.probably = bool(_get(result, "probably", False))
        names = _get(result, "source_names", None) or _get(result, "sources", None) or []
        info.source = ", ".join(str(n) for n in names) if isinstance(names, (list, tuple)) else str(names)
        attrs = _get(result, "attributions", None) or []
        info.attributions = [str(a) for a in attrs] if isinstance(attrs, (list, tuple, set)) else [str(attrs)]
        if kind in ("place", "area") and _get(result, "name") and not areas:
            # An older placepacks without areas_at: the Result's own named area is all there is.
            info.areas.append(Area(_get(result, "name"), _get(result, "cls"), None, info.source))
    for item in areas or ():
        name, cls = item[0], item[1]
        size = item[2] if len(item) > 2 else None
        source = item[3] if len(item) > 3 else ""
        if name:
            info.areas.append(Area(name, cls, size, source))
    resolve_admin(info)
    # The government divisions found among the areas fill the levels the Result did not give.
    for a in info.areas:
        lv = a.level
        if lv in ("town", "county", "state", "country") and not getattr(info, lv):
            setattr(info, lv, a.name)
    if info.town and not any(a.name == info.town for a in info.areas):
        info.areas.append(Area(info.town, "town", None, info.source))
    info.areas.sort(key=lambda a: (a.size_m2 is None, a.size_m2 or 0))
    return info


def resolve_admin(info):
    """Give each "admin" area (placepacks lists government divisions of levels 3 to 10 with one cls) its level: the
    state when it has the state's name, the town when it has the town's name, a county when its name says so
    ("Dare County", "Parish", "Regional Municipality") or, failing that, the largest one of at least COUNTY_MIN_M2;
    any other is left out of the names ("skip": a township inside the county, for instance)."""
    admins = [a for a in info.areas if a.level == "admin"]
    if not admins:
        return info
    for a in admins:
        if info.state and a.name.lower() == info.state.lower():
            a.level = "state"
        elif info.country and a.name.lower() == info.country.lower():
            a.level = "country"
        elif info.town and a.name.lower() == info.town.lower():
            a.level = "town"
        elif COUNTY_WORDS.search(a.name):
            a.level = "county"
    rest = [a for a in admins if a.level == "admin"]
    if not any(a.level == "county" for a in admins):
        big = [a for a in rest if a.size_m2 is not None and a.size_m2 >= COUNTY_MIN_M2]
        if big:
            max(big, key=lambda a: a.size_m2).level = "county"
    for a in admins:
        if a.level == "admin":
            a.level = "skip"
    return info


def metres(lat1, lon1, lat2, lon2):
    """The distance between two positions in metres (haversine)."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class Places:
    """Looks up where photos were taken: My places first, then the finder (placepacks, or a stand-in).

    finder: an object with lookup(lat, lon, when=None, detail=..., altitude=None) and, ideally, areas_at(lat, lon,
    when=None); None: placepacks' Finder on the packs folder (made when first needed, after any downloads).
    my_places: a myplaces.MyPlaces (None: none). packs_folder: where the packs are (None: placepacks' own folder)."""

    CACHE_DIGITS = 3            # positions within about 100 metres share one lookup

    def __init__(self, finder=None, my_places=None, packs_folder=None):
        """Store the parts; nothing is opened yet."""
        self._finder = finder
        self.my_places = my_places or mp.MyPlaces()
        self.packs_folder = packs_folder
        self.cache = {}
        self.exact_cache = {}
        self.attributions = set()
        self.problem = ""                  # why no finder could be made ("" when there is one)
        self._sources = None               # the packs' source names and attributions (_source_table)

    @property
    def finder(self):
        """The finder (placepacks' Finder on the packs folder, made on first use); None if placepacks is missing."""
        if self._finder is None and not self.problem:
            try:
                _ensure_import_path()
                from placepacks.lookup import Finder
                self._finder = Finder(folder=self.packs_folder or self.default_packs_folder())
            except Exception as e:  # noqa: BLE001 - no packs reader: only My places work
                self.problem = f"The place packs could not be opened ({e})."
        return self._finder

    @staticmethod
    def default_packs_folder():
        """placepacks' own packs folder (PLACEPACKS_DIR when set); None if placepacks is missing."""
        if os.environ.get("PLACEPACKS_DIR"):
            return os.environ["PLACEPACKS_DIR"]
        try:
            _ensure_import_path()
            from placepacks.download import default_folder
            return default_folder()
        except Exception:  # noqa: BLE001
            return None

    def lookup(self, lat, lon, when=None, altitude=None):
        """The PlaceInfo for a position (on the date when, a datetime or None). Never raises: a failed lookup is an
        unknown place."""
        key = (round(lat, self.CACHE_DIGITS), round(lon, self.CACHE_DIGITS),
               (when.year, when.month) if when is not None else None,
               None if altitude is None else int(altitude // 300))
        if key in self.cache:
            info = self.cache[key]
        else:
            info = self._lookup(lat, lon, when, altitude)
            self.cache[key] = info
        mine = self.my_places.find(lat, lon)
        if mine is not None:
            copy = PlaceInfo(**{k: getattr(info, k) for k in ("place", "town", "county", "state", "country", "areas",
                                                                "water", "probably", "source", "attributions")})
            copy.my_place = mine.name
            copy.source = "My places"
            return copy
        return info

    EXACT_DIGITS = 4            # the exact place: positions within about 10 metres share one lookup

    def exact(self, lat, lon, when=None, altitude=None):
        """The Spot for a position on the date when: the most specific place known, for the photo's file name
        (see Spot). Never raises: a failed lookup gives what the area lookup knows (the town, the water)."""
        info = self.lookup(lat, lon, when, altitude)
        key = (round(lat, self.EXACT_DIGITS), round(lon, self.EXACT_DIGITS),
               (when.year, when.month) if when is not None else None,
               None if altitude is None else int(altitude // 300))
        if key not in self.exact_cache:
            result = None
            finder = self.finder
            if finder is not None:
                stamp = self._stamp(when)
                try:
                    result = finder.lookup(lat, lon, when=stamp, detail="address", altitude=altitude)
                except TypeError:
                    result = finder.lookup(lat, lon, when=stamp, detail="address")
                except Exception:  # noqa: BLE001 - a broken pack: only what the area lookup knows
                    result = None
            self.exact_cache[key] = result
        return spot_from_result(self.exact_cache[key], info)

    @staticmethod
    def _stamp(when):
        """The date as placepacks wants it (a When); the datetime itself for a stand-in finder."""
        try:
            _ensure_import_path()
            from placepacks.when import When
            return When.parse(when) if when is not None else None
        except Exception:  # noqa: BLE001 - a stand-in finder takes the datetime itself
            return when

    def _lookup(self, lat, lon, when, altitude):
        """Ask the finder (see lookup)."""
        finder = self.finder
        if finder is None:
            return PlaceInfo()
        stamp = self._stamp(when)
        try:
            result = finder.lookup(lat, lon, when=stamp, detail="area", altitude=altitude)
        except TypeError:
            result = finder.lookup(lat, lon, when=stamp, detail="area")
        except Exception:  # noqa: BLE001 - a broken pack: unknown
            result = None
        areas = []
        areas_at = getattr(finder, "areas_at", None)
        if callable(areas_at):
            try:
                areas = list(areas_at(lat, lon, when=stamp) or [])
            except TypeError:
                areas = list(areas_at(lat, lon) or [])
            except Exception:  # noqa: BLE001
                areas = []
        info = info_from_result(result, areas)
        self._credit(info, areas)
        self.attributions.update(info.attributions)
        return info

    def _source_table(self):
        """{source id: (short name, attribution)} from the packs' own source tables (placepacks' PackReader
        .sources); {} for a stand-in finder."""
        if getattr(self, "_sources", None) is None:
            self._sources = {}
            try:
                for pack in getattr(self._finder, "packs", None) or []:
                    for sid, row in (getattr(pack, "sources", None) or {}).items():
                        self._sources.setdefault(sid, (row.get("short") or row.get("name") or sid,
                                                       row.get("attribution") or ""))
            except Exception:  # noqa: BLE001 - names only
                pass
        return self._sources

    def _credit(self, info, areas):
        """Add the sources and attributions of the areas used (the Result alone does not list them when only areas
        matched)."""
        table = self._source_table()
        names = [n for n in (info.source.split(", ") if info.source else []) if n]
        for item in areas:
            sid = item[3] if len(item) > 3 else ""
            if not sid:
                continue
            short, attribution = table.get(sid, ("OpenStreetMap" if sid == "osm" else sid,
                                                 OSM_ATTRIBUTION if sid == "osm" else ""))
            if short not in names:
                names.append(short)
            if attribution and attribution not in info.attributions:
                info.attributions.append(attribution)
        info.source = ", ".join(names)

    # ------------------------------------------------------------ packs

    def regions_needed(self, positions):
        """{region id: number of photos} for the positions [(lat, lon)], from placepacks' regions_for (the best
        region of each). {} without placepacks."""
        try:
            _ensure_import_path()
            from placepacks.regions import regions_for
        except Exception:  # noqa: BLE001
            return {}
        seen, out = {}, {}
        for lat, lon in positions:
            key = (round(lat, 1), round(lon, 1))
            if key not in seen:
                try:
                    found = regions_for(lat, lon)
                except Exception:  # noqa: BLE001
                    found = []
                seen[key] = found[0] if found else None
            if seen[key]:
                out[seen[key]] = out.get(seen[key], 0) + 1
        return out

    def get_packs(self, positions, mode="ask", ask=None, progress=None, catalogue=None):
        """Make sure the packs for the positions are on this computer. mode: "ask" (ask(label, size_bytes, count)
        -> True to download), "auto" (download without asking) or "never" (use only packs already here).
        progress(text, done_bytes, total_bytes) is passed to the download. Returns (downloaded labels, problems).
        Already downloaded packs are used offline; nothing is sent but the request for the pack's file."""
        if mode == "never":
            return [], []
        needed = self.regions_needed(positions)
        if not needed:
            return [], []
        try:
            _ensure_import_path()
            from placepacks import download
            from placepacks.regions import region_label
        except Exception as e:  # noqa: BLE001
            return [], [f"The place packs cannot be downloaded ({e})."]
        folder = self.packs_folder or self.default_packs_folder()
        done, problems = [], []
        infos = {}
        try:
            cat = catalogue or download.Catalogue(cache_path=os.path.join(folder, download.MANIFEST))
            infos = cat.packs()
        except Exception as e:  # noqa: BLE001 - offline: use what is here
            cat = catalogue
            problems.append(f"The list of place packs could not be fetched, so only packs already on this computer "
                            f"are used ({e}).")
        for region, count in sorted(needed.items(), key=lambda kv: -kv[1]):
            if self._have_pack(folder, region):
                continue
            info = infos.get(region)
            if infos and info is None:
                continue                        # no pack is published for that region
            label = region_label(region)
            size = int(getattr(info, "size", 0) or 0)
            if mode == "ask" and (ask is None or not ask(label, size, count)):
                continue
            try:
                download.ensure_pack(region, "core", folder=folder, ask=lambda *a, **k: True,
                                     progress=(lambda *a, **k: progress(label, *a)) if progress else None,
                                     catalogue=cat)
                done.append(label)
            except Exception as e:  # noqa: BLE001
                problems.append(f"The place pack for {label} could not be downloaded ({e}).")
        if done:
            reload = getattr(self._finder, "reload", None)
            if callable(reload):
                reload()                        # placepacks' Finder reads the pack folder again
            self._sources = None
            self.problem = ""
            self.cache.clear()
            self.exact_cache.clear()
        return done, problems

    @staticmethod
    def _have_pack(folder, region):
        """True if region's core pack is already in folder."""
        if not folder:
            return False
        try:
            from placepacks import download, manifest
            name = download.local_name(manifest.key_of(region, "core"))
        except Exception:  # noqa: BLE001
            name = region + ".osmpack"
        return os.path.exists(os.path.join(folder, name))


# ---------------------------------------------------------------- the stand-in finder

class FakeResult:
    """What StandInFinder.lookup returns: the fields of a placepacks Result that this program reads."""

    def __init__(self, **fields):
        """Any Result fields (kind, name, town, region, country, water_name, attributions ...)."""
        self.kind, self.name, self.cls = "none", "", ""
        self.town = self.region = self.country = self.water_name = ""
        self.street = self.house_number = self.neighbourhood = ""
        self.probably = False
        self.over = False
        self.distance_m = 0
        self.source_names = ["test places"]
        self.attributions = ["test data"]
        self.__dict__.update(fields)

    def short(self, detail="area"):
        """The file-name-safe short text (only for water and air here)."""
        if self.kind == "air":
            return f"Over {self.water_name or self.name}"
        if self.kind == "water":
            return f"Off {self.name}" if self.name else self.water_name
        return self.name


def _year_of(when):
    """The year of a date given to a finder (a placepacks When, a datetime, or None)."""
    if when is None:
        return None
    start = getattr(when, "start", None)
    if isinstance(start, int):
        return start // 100
    return getattr(when, "year", None)


class StandInFinder:
    """A finder made of rectangles, for the tests (and for trying the program without packs).

    areas: [(name, cls, (south, west, north, east))]; a position inside several gets them all, smallest first.
    places: [(name, (south, west, north, east))] or [(name, box, {"cls": ..., "years": (first, last)})]: points of
    interest (the "place" level). A business or building (cls "business", "building", "public", "school") is only
    found at the "address" detail, as placepacks does; "years" makes the name valid only in those years, so a place
    can have a history (a shop that changed its name). water: [(name, box, "water" or "air")]: water and air
    descriptions ("Martha's Vineyard" -> "Off Martha's Vineyard"). streets: [(street, box, house number or "")]:
    given at the "street" and "address" details, with the neighbourhood (an area of cls "neighbourhood") and the
    town. Any other position is "none"."""

    POINT_ONLY = ("business", "building", "public", "school", "transit")

    def __init__(self, areas=(), places=(), water=(), streets=()):
        """Store the rectangles."""
        self.areas, self.places, self.water = list(areas), list(places), list(water)
        self.streets = list(streets)
        self.calls = 0

    @staticmethod
    def _inside(box, lat, lon):
        """True if (lat, lon) is inside box (south, west, north, east)."""
        s, w, n, e = box
        return s <= lat <= n and w <= lon <= e

    @staticmethod
    def _size(box):
        """A rough size in square metres of box."""
        s, w, n, e = box
        return abs(n - s) * 111000 * abs(e - w) * 111000 * max(0.1, math.cos(math.radians((n + s) / 2)))

    def areas_at(self, lat, lon, when=None):
        """[(name, cls, size_m2, source)] of the areas around the position, smallest first."""
        found = [(n, c, self._size(b), "test places") for n, c, b in self.areas if self._inside(b, lat, lon)]
        return sorted(found, key=lambda a: a[2])

    def _place_at(self, lat, lon, when, detail):
        """(name, cls) of the place at the position valid on the date, or None."""
        year = _year_of(when)
        for item in self.places:
            name, box = item[0], item[1]
            extra = item[2] if len(item) > 2 else {}
            cls = extra.get("cls", "")
            if not self._inside(box, lat, lon) or (detail == "area" and cls in self.POINT_ONLY):
                continue
            years = extra.get("years")
            if years and year is not None and not years[0] <= year <= years[1]:
                continue
            return name, cls
        return None

    def lookup(self, lat, lon, when=None, detail="area", altitude=None):
        """A FakeResult for the position (see the class docstring)."""
        self.calls += 1
        for name, box, kind in self.water:
            if self._inside(box, lat, lon):
                if kind == "air" or (altitude is not None and altitude > 2000):
                    return FakeResult(kind="air", water_name=name)
                return FakeResult(kind="water", name=name)
        around = self.areas_at(lat, lon)
        fields = {}
        for name, cls, _size, _src in around:
            lv = admin_level(cls)
            key = {"town": "town", "state": "region", "country": "country"}.get(lv)
            if key and key not in fields:
                fields[key] = name
        if detail != "area":
            fields["neighbourhood"] = next((n for n, c, _s, _src in around if c == "neighbourhood"), "")
            street = next((s for s in self.streets if self._inside(s[1], lat, lon)), None)
            if street is not None:
                fields["street"], fields["house_number"] = street[0], street[2] if len(street) > 2 else ""
        place = self._place_at(lat, lon, when, detail)
        if place is not None:
            return FakeResult(kind="place", name=place[0], cls=place[1], **fields)
        if fields.get("house_number"):
            return FakeResult(kind="address", **fields)
        around = [a for a in around if a[1] != "neighbourhood"] if detail == "area" else around
        if around and detail == "area":
            return FakeResult(kind="area", name=around[0][0], cls=around[0][1], **fields)
        if fields.get("street") or fields.get("neighbourhood") or around:
            return FakeResult(kind="area", **fields)
        return FakeResult(kind="none")
