"""My places: the user's own names for places ("Grandma's house" within 200 metres of a position). A photo taken
inside one of them is named by it, before any name from the place packs.

Places from a list (Import places from a list, pli/placelist.py): businesses, schools and other places read from a
pasted list or a file, each list kept under its own name (its "source", such as "Schools list" or the file's name)
so it can be removed in one go. A place from a list names a picture taken within 60 metres of it (the picture's
name, not its folder), before the place packs' names; your own places still come first. They are found through a
grid index (placelist.PlaceGrid), so 150,000 of them stay fast.

Kept in "my places.json" in the program's settings folder, on this computer only. Import and export read and write
that same JSON, a CSV file with the columns name, latitude, longitude, metres and list (a spreadsheet can make
one), a SQLite database or a .sql file (the table my_places with the same columns).
"""

import csv
import json
import math
import os

from pli import placelist

DEFAULT_RADIUS_M = 200
CSV_COLUMNS = ["name", "latitude", "longitude", "metres", "list"]
LIST_RADIUS_M = placelist.LIST_RADIUS_M
DATABASE_ENDINGS = placelist.SQLITE_ENDINGS + (".sql",)


class MyPlace:
    """One of My places: name, lat, lon (degrees) and radius_m (metres around the position it covers)."""

    def __init__(self, name, lat, lon, radius_m=DEFAULT_RADIUS_M):
        """Check and store the fields (ValueError for an empty name or a position outside the earth)."""
        name = " ".join(str(name or "").split())
        if not name:
            raise ValueError("a place needs a name")
        try:
            lat, lon, radius_m = float(lat), float(lon), float(radius_m or DEFAULT_RADIUS_M)
        except (TypeError, ValueError):
            raise ValueError("the latitude, longitude and distance must be numbers") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"{lat}, {lon} is not a position on the earth")
        if radius_m <= 0:
            raise ValueError("the distance must be more than 0 metres")
        self.name, self.lat, self.lon, self.radius_m = name, lat, lon, radius_m

    def as_dict(self):
        """For saving."""
        return {"name": self.name, "latitude": self.lat, "longitude": self.lon, "metres": self.radius_m}

    def describe(self):
        """For the list in the window: "Grandma's house, within 200 metres of 36.01234, -75.67890"."""
        return f"{self.name}, within {self.radius_m:g} metres of {self.lat:.5f}, {self.lon:.5f}"

    def __repr__(self):
        """For test messages."""
        return f"MyPlace({self.name!r}, {self.lat}, {self.lon}, {self.radius_m})"


def distance_m(lat1, lon1, lat2, lon2):
    """The distance between two positions in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(min(1.0, math.sqrt(a)))


class ListedPlace:
    """A place from a list: name, lat, lon, radius_m (LIST_RADIUS_M unless the list said otherwise) and source (the
    list's name)."""

    __slots__ = ("name", "lat", "lon", "radius_m", "source")

    def __init__(self, name, lat, lon, source, radius_m=LIST_RADIUS_M):
        """Store the fields."""
        self.name, self.lat, self.lon, self.source = name, float(lat), float(lon), source
        self.radius_m = float(radius_m or LIST_RADIUS_M)

    def __repr__(self):
        """For test messages."""
        return f"ListedPlace({self.name!r}, {self.lat}, {self.lon}, {self.source!r})"


class MyPlaces:
    """The list of My places (places, your own) and the places from lists (lists: {source: [ListedPlace]}), saved
    to path (None: not saved)."""

    def __init__(self, places=None, path=None):
        """The places given, or none."""
        self.places = list(places or [])
        self.lists = {}
        self.path = path
        self._grid = None

    @classmethod
    def load(cls, path):
        """My places from a JSON file (an empty list if the file is missing or damaged)."""
        out = cls(path=path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            out.places = [MyPlace(d["name"], d["latitude"], d["longitude"], d.get("metres", DEFAULT_RADIUS_M))
                          for d in data.get("places", [])]
            for source, items in (data.get("lists") or {}).items():
                out.lists[source] = [ListedPlace(i[0], i[1], i[2], source, i[3] if len(i) > 3 else LIST_RADIUS_M)
                                     for i in items if len(i) >= 3]
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            pass
        return out

    def save(self, path=None):
        """Write the list (to path, or to the path it was loaded from). Places from lists are written compactly,
        one [name, latitude, longitude] each (and the metres when not the usual 60)."""
        path = path or self.path
        if not path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        data = {"places": [p.as_dict() for p in self.places]}
        if self.lists:
            data["lists"] = {source: [[p.name, round(p.lat, 7), round(p.lon, 7)] +
                                      ([p.radius_m] if p.radius_m != LIST_RADIUS_M else []) for p in items]
                             for source, items in self.lists.items()}
        with open(tmp, "w", encoding="utf-8") as f:
            if self.lists:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)

    # ------------------------------------------------------------ places from lists

    def grid(self):
        """The grid index of the places from lists (made when first needed, again after a change)."""
        if self._grid is None:
            self._grid = placelist.PlaceGrid()
            self._grid.widest = LIST_RADIUS_M
            for items in self.lists.values():
                for p in items:
                    self._grid.add(p.lat, p.lon, p)
                    self._grid.widest = max(self._grid.widest, p.radius_m)
        return self._grid

    def find_listed(self, lat, lon):
        """The place from a list a position is within (the nearest if several), or None."""
        if not self.lists:
            return None
        grid = self.grid()
        for d, p in grid.near(lat, lon, grid.widest):
            if d <= p.radius_m:
                return p
        return None

    def listed_count(self):
        """How many places from lists there are."""
        return sum(len(items) for items in self.lists.values())

    def list_names(self):
        """[(source, number of places)] of the lists, in the order they were imported."""
        return [(source, len(items)) for source, items in self.lists.items()]

    def add_list(self, source, rows):
        """Add the located rows (placelist.Row, not marked "duplicate" or "not located") to the list called source
        (made if new; a list of that name gets the new places too). Returns how many were added."""
        source = " ".join(str(source or "").split()) or placelist.default_list_name()
        items = self.lists.setdefault(source, [])
        added = 0
        for r in rows:
            if r.located and r.status not in ("duplicate", "not located") and r.name:
                items.append(ListedPlace(r.name, r.lat, r.lon, source, r.metres or LIST_RADIUS_M))
                added += 1
        if not items:
            del self.lists[source]
        self._grid = None
        return added

    def remove_list(self, source):
        """Remove every place of the list called source. Returns how many were removed."""
        items = self.lists.pop(source, [])
        self._grid = None
        return len(items)

    def existing(self):
        """[(name, lat, lon)] of every place, yours and from lists (to find duplicates)."""
        out = [(p.name, p.lat, p.lon) for p in self.places]
        out += [(p.name, p.lat, p.lon) for items in self.lists.values() for p in items]
        return out

    def export_rows(self, which=None):
        """The places to export as dicts (name, latitude, longitude, metres, list). which: None for all, "" for
        only your own places, or a list's name for only that list."""
        out = []
        if which in (None, ""):
            out += [{"name": p.name, "latitude": p.lat, "longitude": p.lon, "metres": p.radius_m, "list": ""}
                    for p in self.places]
        for source, items in self.lists.items():
            if which is None or which == source:
                out += [{"name": p.name, "latitude": p.lat, "longitude": p.lon, "metres": p.radius_m,
                         "list": source} for p in items]
        return out

    def find(self, lat, lon):
        """The place a position is inside (the nearest centre if it is inside several), or None."""
        best = None
        for p in self.places:
            d = distance_m(lat, lon, p.lat, p.lon)
            if d <= p.radius_m and (best is None or d < best[0]):
                best = (d, p)
        return best[1] if best else None

    def add(self, place):
        """Add a place, replacing one of the same name (any capitals). Returns the place."""
        self.places = [p for p in self.places if p.name.lower() != place.name.lower()] + [place]
        return place

    def remove(self, index):
        """Remove the place at index."""
        del self.places[index]

    def export(self, path, which=None):
        """Write the places to a .json, .csv, SQLite database (.db, .sqlite, .sqlite3) or .sql file (by its ending).
        which: None for all, "" for only your own places, or a list's name for only that list. Returns how many
        places were written."""
        rows = self.export_rows(which)
        low = path.lower()
        if low.endswith(".csv") or low.endswith(DATABASE_ENDINGS):
            return placelist.export_places(path, rows)
        out = MyPlaces([p for p in self.places] if which in (None, "") else [])
        if which != "":
            out.lists = {s: items for s, items in self.lists.items() if which is None or which == s}
        out.save(path)
        return len(rows)

    def _add_row(self, name, lat, lon, metres, source):
        """Add one imported place: to a list when source is given, else to your own places."""
        if source:
            p = ListedPlace(" ".join(str(name or "").split()), lat, lon, source, metres or LIST_RADIUS_M)
            if not p.name:
                raise ValueError("a place needs a name")
            MyPlace(p.name, p.lat, p.lon, p.radius_m)          # the same checks as your own places
            self.lists.setdefault(source, []).append(p)
            self._grid = None
        else:
            self.add(MyPlace(name, lat, lon, metres or DEFAULT_RADIUS_M))

    def import_file(self, path):
        """Add the places in a .json, .csv, SQLite database or .sql file (your own places of the same name are
        replaced; a place with a list name goes into that list). Returns (added, problems): problems is a list of
        "line 3: ..." for rows that could not be read (and, for a .sql file, how many statements were skipped)."""
        added, problems = 0, []
        low = path.lower()
        if low.endswith(".csv"):
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            for i, row in enumerate(rows, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                try:
                    self._add_row(row.get("name"), row.get("latitude") or row.get("lat"),
                                  row.get("longitude") or row.get("lon"),
                                  row.get("metres") or row.get("meters") or None, row.get("list") or "")
                    added += 1
                except (ValueError, TypeError) as e:
                    problems.append(f"line {i}: {e}")
        elif low.endswith(DATABASE_ENDINGS) or placelist.is_sqlite_file(path):
            if low.endswith(".sql"):
                stats = placelist.load_sql(path)[1]
                if stats["skipped"] or stats["failed"]:
                    problems.append(f"{stats['skipped'] + stats['failed']} statements of the .sql file were skipped "
                                    f"(only CREATE TABLE and INSERT statements are read)")
            try:
                for row in placelist.read_file(path):
                    if not row.located:
                        problems.append(f"{row.where}: {row.name or 'a place'} has no position (Import places from "
                                        f"a list can find it by its address)")
                        continue
                    try:
                        self._add_row(row.name, row.lat, row.lon, row.metres, row.list)
                        added += 1
                    except (ValueError, TypeError) as e:
                        problems.append(f"{row.where}: {e}")
            except (ValueError, OSError) as e:
                problems.append(str(e))
        else:
            other = MyPlaces.load(path)
            if not other.places and not other.lists:
                problems.append("no places could be read from the file")
            for p in other.places:
                self.add(p)
                added += 1
            for source, items in other.lists.items():
                self.lists.setdefault(source, []).extend(items)
                added += len(items)
            self._grid = None
        return added, problems
