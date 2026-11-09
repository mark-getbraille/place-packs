"""Build placepacks/data/water.json.gz, the small global layer that works without any pack (a developer tool).

    python tools/build_water.py NE_FOLDER airports.csv

NE_FOLDER holds Natural Earth's GeoJSON files (public domain, github.com/nvkelso/natural-earth-vector):
ne_50m_land, ne_10m_geography_marine_polys, ne_50m_lakes and ne_10m_populated_places_simple, and Marine Regions' bays and gulfs as mr_world_bay_gulf.geojson (CC BY 4.0, VLIZ:
the WFS layer MarineRegions:world_bay_gulf as GeoJSON in EPSG:4326; optional). airports.csv is
OurAirports' file (public domain, github.com/davidmegginson/ourairports-data). The output keeps:
  land     the land polygons (simplified to about 1 km)
  marine   named oceans, seas, bays, sounds, straits... (class and English name); Marine Regions adds the bays,
           gulfs, inlets, fjords and lagoons whose names Natural Earth does not have (the smallest area holding a
           position names it, so a bay inside a sea is found first)
  lakes    named large lakes
  places   populated places (name, region, country, position)
  airports large and medium airports with an IATA code (name, code, position, elevation in feet)
Positions are whole 1/10000 degrees; rings are lists of [lon, lat] pairs.
"""

import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from placepacks import fmt  # noqa: E402

S = 10000


def rings_of(geometry, tolerance_m):
    """The rings of a (Multi)Polygon, simplified, as [[lon, lat] * S] lists."""
    polys = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
    out = []
    for poly in polys:
        for ring in poly:
            pts = fmt.simplify([(y, x) for x, y in ring], tolerance_m)
            if len(pts) >= 4:
                out.append([[int(round(x * S)), int(round(y * S))] for y, x in pts])
    return out


def area(name, cls, geometry, tolerance_m):
    """One area: name, class, bounds (west, south, east, north * S) and rings."""
    rings = rings_of(geometry, tolerance_m)
    if not rings:
        return None
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    return {"n": name, "c": cls, "b": [min(xs), min(ys), max(xs), max(ys)], "p": rings}


def main(ne, airports_csv, out):
    """Build the file."""
    load = lambda name: json.load(open(os.path.join(ne, name + ".geojson"), encoding="utf-8"))  # noqa: E731
    land = [a for a in (area("", "land", f["geometry"], 1000) for f in load("ne_50m_land")["features"]) if a]
    # Split the big land polygons into one area per ring, so the bounds narrow the search.
    land = [{"n": "", "c": "land", "b": [min(p[0] for p in r), min(p[1] for p in r), max(p[0] for p in r),
                                         max(p[1] for p in r)], "p": [r]} for a in land for r in a["p"]]
    marine = []
    for f in load("ne_10m_geography_marine_polys")["features"]:
        p = f["properties"]
        name = p.get("name_en") or p.get("name")
        if name:
            a = area(name, p.get("featurecla", "sea").lower(), f["geometry"], 2000)
            if a:
                marine.append(a)
    mr_file = os.path.join(ne, "mr_world_bay_gulf.geojson")
    added = 0
    if os.path.exists(mr_file):
        known = {a["n"].lower() for a in marine}
        for f in json.load(open(mr_file, encoding="utf-8"))["features"]:
            p = f["properties"]
            name = (p.get("geoname") or "").strip()
            if not name or name.lower() in known or not f.get("geometry"):
                continue
            a = area(name, (p.get("placetype") or "bay").lower(), f["geometry"], 500)
            if a:
                marine.append(a)
                known.add(name.lower())
                added += 1
    lakes = []
    for f in load("ne_50m_lakes")["features"]:
        p = f["properties"]
        if p.get("name"):
            a = area(p["name"], "lake", f["geometry"], 300)   # "Lake Champlain" (name_en is "Champlain")
            if a:
                lakes.append(a)
    places = []
    for f in load("ne_10m_populated_places_simple")["features"]:
        p = f["properties"]
        x, y = f["geometry"]["coordinates"][:2]
        places.append([p.get("name"), p.get("adm1name") or "", p.get("adm0name") or "", int(round(y * S)),
                       int(round(x * S))])
    import csv
    airports = []
    with open(airports_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["type"] in ("large_airport", "medium_airport") and r["iata_code"]:
                airports.append([r["name"], r["iata_code"], int(round(float(r["latitude_deg"]) * S)),
                                 int(round(float(r["longitude_deg"]) * S)), int(float(r["elevation_ft"] or 0))])
    doc = {"note": "Natural Earth (public domain) land, marine names, lakes and populated places; Marine Regions "
                   "(VLIZ, CC BY 4.0) bays and gulfs; OurAirports (public domain) airports. Built by "
                   "tools/build_water.py.",
           "scale": S, "land": land, "marine": marine, "lakes": lakes, "places": places, "airports": airports}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"), ensure_ascii=False)
    print(f"{out}: {os.path.getsize(out):,} bytes; land {len(land)}, marine {len(marine)}, lakes {len(lakes)}, "
          f"places {len(places)}, airports {len(airports)}; {added} marine areas from Marine Regions")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else
         os.path.join(os.path.dirname(HERE), "placepacks", "data", "water.json.gz"))
