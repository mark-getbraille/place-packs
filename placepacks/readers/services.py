"""The readers of the services part (placepacks/services.py says what it holds):

  osm_services  the region's OpenStreetMap extract (the same file as the core part's, fetch "same_as": "osm"): the
                offices and services a person goes to (services.service_kind), with phone, hours and wheelchair
                access (ODbL)
  nws_zones     a National Weather Service shapefile (the county areas, c_DDmmYY.zip, or the public forecast zones,
                z_DDmmYY.zip; public domain): the region's state's polygons, each with its code and name
  nwr           the NOAA Weather Radio county coverage list (www.weather.gov/source/nwr/JS/CCL.js, the data of the
                weather.gov/nwr/county_coverage page; public domain): every transmitter covering each county of the
                region's state
"""

import re
import xml.etree.ElementTree as ET

from placepacks import services
from placepacks.readers import reader
from placepacks.regions import touches_region


# ------------------------------------------------------------------------------------------- OpenStreetMap

@reader("osm_services")
def read_osm(path, entry, region, writer, use_osmium=None, index=None):
    """Read an extract's services into writer. Returns the number kept."""
    svc = services.store(writer)
    if use_osmium is None:
        try:
            import osmium  # noqa: F401
            use_osmium = True
        except ImportError:
            use_osmium = False
    if str(path).lower().endswith(".pbf") and not use_osmium:
        raise SystemExit("A .osm.pbf extract needs pyosmium (BSD-2-Clause): pip install osmium")
    before = writer.db.execute("SELECT COUNT(*) FROM svc_places").fetchone()[0]
    if use_osmium:
        _read_osmium(path, entry["id"], svc, index)
    else:
        _read_xml(path, entry["id"], svc)
    return writer.db.execute("SELECT COUNT(*) FROM svc_places").fetchone()[0] - before


def _centre(points):
    """The mean of [(lat, lon)] (a building's or a site's middle, good enough to walk to)."""
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)


def _read_xml(path, source, svc):
    """A small .osm XML file with the standard library."""
    nodes = {}
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag == "node":
            pos = (float(el.get("lat")), float(el.get("lon")))
            nodes[el.get("id")] = pos
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            if tags:
                svc.add_osm(f"n{el.get('id')}", source, tags, *pos)
        elif el.tag == "way":
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            points = [nodes[nd.get("ref")] for nd in el.findall("nd") if nd.get("ref") in nodes]
            if tags and points and "highway" not in tags:
                svc.add_osm(f"w{el.get('id')}", source, tags, *_centre(points))
        if el.tag in ("node", "way", "relation"):
            el.clear()


def _read_osmium(path, source, svc, index=None):
    """An extract with pyosmium (BSD-2-Clause)."""
    import osmium

    class Handler(osmium.SimpleHandler):
        """pyosmium's callbacks: services that are nodes, and those drawn as buildings or sites (their centre)."""
        def node(self, n):
            """A tagged node."""
            if len(n.tags) and n.location.valid() and services.service_kind(n.tags) is not None:
                svc.add_osm(f"n{n.id}", source, {t.k: t.v for t in n.tags}, n.location.lat, n.location.lon)

        def way(self, w):
            """A way that is a service (not a road)."""
            if "highway" in w.tags or services.service_kind(w.tags) is None:
                return
            points = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
            if points:
                svc.add_osm(f"w{w.id}", source, {t.k: t.v for t in w.tags}, *_centre(points))

    Handler().apply_file(str(path), locations=True, idx=index or "flex_mem")


# ------------------------------------------------------------------------------------------- weather zones

@reader("nws_zones")
def read_zones(path, entry, region, writer):
    """The region's polygons of a National Weather Service shapefile. entry["zones"]: {"kind": "county" or
    "forecast zone", "code": a format of the record's fields ("{FIPS}", "{STATE}Z{ZONE}"), "name", "state",
    "office" (field names)}. Returns the number kept."""
    import shapefile
    from placepacks.readers.shapes import files_of
    svc = services.store(writer)
    z = entry["zones"]
    count = 0
    for file in files_of(path, entry.get("shp_member")):
        with shapefile.Reader(file) as shp:
            names = [f[0] for f in shp.fields[1:]]
            for shape_rec in shp.iterShapeRecords():
                rec = dict(zip(names, shape_rec.record))
                if str(rec.get(z["state"], "")).strip() != region.get("code"):
                    continue
                shape = shape_rec.shape
                if not shape.points:
                    continue
                xs, ys = [p[0] for p in shape.points], [p[1] for p in shape.points]
                if not touches_region(region, (min(xs), min(ys), max(xs), max(ys)), 0.05):
                    continue
                parts = list(shape.parts) + [len(shape.points)]
                rings = [[(y, x) for x, y in shape.points[a:b]] for a, b in zip(parts, parts[1:])]
                code = z["code"].format(**{k: str(v).strip() for k, v in rec.items()})
                if svc.add_zone(f"nws:{z['kind']}:{code}", entry["id"], z["kind"], code,
                                str(rec.get(z["name"], "")).strip(), str(rec.get(z["state"], "")).strip(),
                                str(rec.get(z.get("office", ""), "")).strip(), rings):
                    count += 1
    return count


# ------------------------------------------------------------------------------------------- NOAA Weather Radio

CCL_LINE = re.compile(r'^\s*([A-Z]+)\[(\d+)\]\s*=\s*"(.*)";\s*$')
CCL_FIELDS = {"ST": "state", "STATE": "state_name", "COUNTY": "county", "SAME": "same", "SITENAME": "site",
              "SITELOC": "site_location", "SITESTATE": "site_state", "FREQ": "frequency", "CALLSIGN": "call_sign",
              "LAT": "lat", "LON": "lon", "PWR": "power", "STATUS": "status", "WFO": "office", "REMARKS": "remarks"}


def parse_ccl(text):
    """The rows of the county coverage list (CCL.js: parallel JavaScript arrays ST[0] = "AK"; ...), as dicts with
    the CCL_FIELDS names."""
    rows = {}
    for line in text.splitlines():
        m = CCL_LINE.match(line)
        if m and m.group(1) in CCL_FIELDS:
            rows.setdefault(int(m.group(2)), {})[CCL_FIELDS[m.group(1)]] = m.group(3).strip()
    return [rows[i] for i in sorted(rows)]


@reader("nwr")
def read_nwr(path, entry, region, writer):
    """Every transmitter covering a county of the region's state (for a sub-region, its counties and those next to
    it, regions.json "counties"). path: CCL.js, or a folder holding it. Returns the number of rows."""
    import os
    if os.path.isdir(path):
        path = os.path.join(path, next(n for n in sorted(os.listdir(path)) if n.lower().endswith(".js")))
    with open(path, encoding="utf-8", errors="replace") as f:
        rows = parse_ccl(f.read())
    svc = services.store(writer)
    mine = set(region.get("counties") or [])
    count = 0
    for r in rows:
        same = r.get("same", "")
        if r.get("state") != region.get("code") or (mine and same[-3:] not in mine):
            continue
        try:
            lat, lon = float(r.get("lat", "")), float(r.get("lon", ""))
        except ValueError:
            lat = lon = 0.0
        svc.add_radio({"call_sign": r.get("call_sign", ""), "frequency": r.get("frequency", ""),
                       "site": r.get("site", ""), "site_state": r.get("site_state", ""), "lat": lat, "lon": lon,
                       "power": r.get("power", ""), "status": r.get("status", ""),
                       "office": r.get("office", "").replace("|", ", "), "same": same,
                       "county": r.get("county", ""), "state": r.get("state", ""), "remarks": r.get("remarks", "")})
        count += 1
    return count
