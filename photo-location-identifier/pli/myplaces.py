"""My places: the user's own names for places ("Grandma's house" within 200 metres of a position). A photo taken
inside one of them is named by it, before any name from the place packs.

Kept in "my places.json" in the program's settings folder. Import and export read and write that same JSON, or a
CSV file with the columns name, latitude, longitude, metres (a spreadsheet can make one).
"""

import csv
import json
import math
import os

DEFAULT_RADIUS_M = 200
CSV_COLUMNS = ["name", "latitude", "longitude", "metres"]


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


class MyPlaces:
    """The list of My places (places), saved to path (None: not saved)."""

    def __init__(self, places=None, path=None):
        """The places given, or none."""
        self.places = list(places or [])
        self.path = path

    @classmethod
    def load(cls, path):
        """My places from a JSON file (an empty list if the file is missing or damaged)."""
        out = cls(path=path)
        try:
            with open(path, encoding="utf-8") as f:
                out.places = [MyPlace(d["name"], d["latitude"], d["longitude"], d.get("metres", DEFAULT_RADIUS_M))
                              for d in json.load(f).get("places", [])]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        return out

    def save(self, path=None):
        """Write the list (to path, or to the path it was loaded from)."""
        path = path or self.path
        if not path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"places": [p.as_dict() for p in self.places]}, f, indent=1, ensure_ascii=False)
        os.replace(tmp, path)

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

    def export(self, path):
        """Write the list to a .csv or .json file (by its ending)."""
        if path.lower().endswith(".csv"):
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                out = csv.writer(f)
                out.writerow(CSV_COLUMNS)
                for p in self.places:
                    out.writerow([p.name, p.lat, p.lon, p.radius_m])
        else:
            MyPlaces(self.places).save(path)

    def import_file(self, path):
        """Add the places in a .csv or .json file (same names are replaced). Returns (added, problems): problems
        is a list of "line 3: ..." for rows that could not be read."""
        added, problems = 0, []
        if path.lower().endswith(".csv"):
            with open(path, newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            for i, row in enumerate(rows, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                try:
                    self.add(MyPlace(row.get("name"), row.get("latitude") or row.get("lat"),
                                     row.get("longitude") or row.get("lon"),
                                     row.get("metres") or row.get("meters") or DEFAULT_RADIUS_M))
                    added += 1
                except (ValueError, TypeError) as e:
                    problems.append(f"line {i}: {e}")
        else:
            other = MyPlaces.load(path)
            if not other.places:
                problems.append("no places could be read from the file")
            for p in other.places:
                self.add(p)
                added += 1
        return added, problems
