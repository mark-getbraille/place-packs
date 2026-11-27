"""The "osm_site_features" reader: OpenStreetMap's features INSIDE sites, for the core part's site_features table
(placepacks/features.py; source "osm-site-features", the same extract as the core part's, fetch "same_as": "osm";
ODbL 1.0 like the rest of the core part).

A site is a named area of OpenStreetMap that people visit as one place with several buildings or parts (SITE_TAGS):
a university, college or school campus, a hospital, a zoo, aquarium or theme park, a shopping mall, an airport, a
stadium, a convention or exhibition centre, a museum's grounds. Inside each site this reader keeps:

  building             a named building (building=*), at its outline's middle
  accessible entrance  entrance=* with wheelchair=yes (or limited, said in the note); entrance  any other entrance
  elevator             highway=elevator (a node) or an elevator way
  escalator            a moving staircase (highway=steps with conveying=*)
  accessible restroom  amenity=toilets with wheelchair=yes or toilets:wheelchair=yes; restroom  other toilets
  accessible parking   amenity=parking with capacity:disabled above 0 (or "yes"), or a disabled parking space
                       (amenity=parking_space with parking_space=disabled); parking  a named car park
  accessible route     a footway, path, ramp or corridor with wheelchair=yes (a line)
  service desk         amenity=reception_desk; information desk  tourism=information with information=office
  emergency phone      emergency=phone or amenity=emergency_phone
  dining               a named restaurant, cafe, fast food place or food court; store  a named shop
  gate, terminal       aeroway=gate (its ref or name) and aeroway=terminal

Each feature's site is the smallest site area holding it (its key is the core part's key of that area, "w123" or
"r456", so features_of(site) works with the place a lookup names); its building is the named building holding it
(an entrance on a building's outline counts, within EDGE_M). A feature outside every site is not kept: the
navigation part already has the street-side entrances and elevators. The level comes from level, level:ref or
addr:floor. The note keeps only accessibility facts from the tags (wheelchair, automatic door, door type, width,
ramp, handrail, the number of accessible spaces, toilets:wheelchair, changing table), never a description.
"""

import xml.etree.ElementTree as ET

from placepacks import features, fmt
from placepacks.readers import reader

# The tags that make a named area a site (key: values, or None for any value).
SITE_TAGS = {
    "amenity": {"university", "college", "school", "hospital", "conference_centre", "exhibition_centre",
                "kindergarten"},
    "healthcare": {"hospital"},
    "tourism": {"zoo", "aquarium", "theme_park", "museum"},
    "shop": {"mall", "department_store"},
    "leisure": {"stadium", "water_park"},
    "aeroway": {"aerodrome"},
    "landuse": {"education"},
}
EDGE_M = 3.0                    # an entrance this near a building's outline is on that building
LEVEL_KEYS = ("level:ref", "level", "addr:floor")
DINING = {"restaurant", "cafe", "fast_food", "food_court", "ice_cream", "bar", "pub"}


def site_tags(tags):
    """True when a named area's tags make it a site (SITE_TAGS)."""
    if not tags.get("name"):
        return False
    return any(tags.get(k) in values for k, values in SITE_TAGS.items())


def _yes(value):
    """True for an OpenStreetMap yes."""
    return str(value or "").strip().lower() in ("yes", "designated", "true", "1")


def _count(value):
    """A capacity tag as a number (a "yes" counts as 1), or 0."""
    v = str(value or "").strip().lower()
    if v in ("yes", "true"):
        return 1
    try:
        return int(float(v))
    except ValueError:
        return 0


def note_of(tags):
    """The accessibility facts of a feature's tags as a short note ("wheelchair: yes; automatic door; ...")."""
    parts = []
    w = tags.get("wheelchair")
    if w:
        parts.append(f"wheelchair: {w}")
    if tags.get("automatic_door") and tags["automatic_door"] != "no":
        parts.append("automatic door" + ("" if tags["automatic_door"] == "yes" else f" ({tags['automatic_door']})"))
    if tags.get("door") and tags["door"] not in ("yes", "no"):
        parts.append(f"door: {tags['door']}")
    if tags.get("entrance") in ("main", "service", "emergency", "exit"):
        parts.append(f"{tags['entrance']} entrance" if tags["entrance"] != "exit" else "exit only")
    for key, label in (("width", "width"), ("ramp", "ramp"), ("handrail", "handrail"),
                       ("toilets:wheelchair", "accessible toilet"), ("changing_table", "changing table"),
                       ("capacity:disabled", "accessible spaces"), ("tactile_paving", "tactile paving"),
                       ("ramp:wheelchair", "wheelchair ramp"), ("surface", "surface"),
                       ("opening_hours", "hours")):
        if tags.get(key) and tags[key] != "no" or (key in ("ramp", "handrail") and tags.get(key) == "no"):
            parts.append(f"{label}: {tags[key]}")
    return features.clean_note("; ".join(parts))


def level_of(tags):
    """The level label of a feature's tags, or ""."""
    return next((tags[k] for k in LEVEL_KEYS if tags.get(k)), "")


def point_kind(tags):
    """The kind of a node (or of an area's middle) from its tags, or ""."""
    amenity = tags.get("amenity")
    if "entrance" in tags or tags.get("door") in ("main",):
        return "accessible entrance" if _yes(tags.get("wheelchair")) else "entrance"
    if tags.get("highway") == "elevator" or amenity == "elevator":
        return "elevator"
    if amenity == "toilets":
        return "accessible restroom" if (_yes(tags.get("wheelchair")) or _yes(tags.get("toilets:wheelchair"))) \
            else "restroom"
    if amenity == "parking":
        if _count(tags.get("capacity:disabled")) > 0:
            return "accessible parking"
        return "parking" if tags.get("name") else ""
    if amenity == "parking_space" and tags.get("parking_space") == "disabled":
        return "accessible parking"
    if tags.get("emergency") == "phone" or amenity == "emergency_phone":
        return "emergency phone"
    if amenity == "reception_desk":
        return "service desk"
    if tags.get("tourism") == "information" and tags.get("information") in ("office", "visitor_centre"):
        return "information desk"
    if amenity in DINING and tags.get("name"):
        return "dining"
    if tags.get("shop") and tags.get("shop") not in ("mall", "vacant") and tags.get("name"):
        return "store"
    if tags.get("aeroway") == "gate" and (tags.get("ref") or tags.get("name")):
        return "gate"
    if tags.get("aeroway") == "terminal":
        return "terminal"
    return ""


def way_kind(tags):
    """The kind of an open way (a line) from its tags, or ""."""
    if tags.get("highway") == "steps" and tags.get("conveying"):
        return "escalator"
    if tags.get("highway") == "elevator":
        return "elevator"
    if tags.get("highway") in ("footway", "path", "pedestrian", "corridor", "steps") or tags.get("ramp") == "yes":
        if _yes(tags.get("wheelchair")) and tags.get("highway") != "steps":
            return "accessible route"
    return ""


class Collector:
    """What one pass over an extract finds: sites, named buildings and candidate features. finish() ties each
    feature to its site and building and writes them (see the module docstring)."""

    def __init__(self):
        """Empty lists."""
        self.sites = []          # (key, rings, (s, w, n, e), area m2)
        self.buildings = []      # (key, name, rings, box, level)
        self.items = []          # (key, kind, name, lat, lon, line, level, note)

    def node(self, oid, tags, lat, lon):
        """A tagged node."""
        kind = point_kind(tags)
        if kind:
            self.items.append((f"n{oid}", kind, tags.get("name") or tags.get("ref") or "", lat, lon, None,
                               level_of(tags), note_of(tags)))

    def way(self, oid, tags, points):
        """An open (or any) way with its points: routes, escalators and elevator ways."""
        kind = way_kind(tags)
        pts = [p for p in points if p]
        if kind and len(pts) >= 2:
            self.items.append((f"w{oid}", kind, tags.get("name") or "", None, None, pts, level_of(tags),
                               note_of(tags)))

    def area(self, key, tags, rings):
        """A closed area: a site, a named building, or a feature drawn as an area (toilets, a car park)."""
        rings = [r for r in rings if len(r) >= 4]
        if not rings:
            return
        lats = [p[0] for r in rings for p in r]
        lons = [p[1] for r in rings for p in r]
        box = (min(lats), min(lons), max(lats), max(lons))
        if site_tags(tags):
            self.sites.append((key, rings, box, max(fmt.ring_area_m2(fmt.micro(r)) for r in rings)))
        if tags.get("building") and tags.get("name"):
            self.buildings.append((key, tags["name"], rings, box, level_of(tags)))
            middle = features.centroid(rings)
            self.items.append((key, "building", tags["name"], middle[0], middle[1], None, "", note_of(tags)))
        kind = point_kind(tags)
        if kind and not (kind == "building" or site_tags(tags)):
            middle = features.centroid(rings)
            self.items.append((key, kind, tags.get("name") or tags.get("ref") or "", middle[0], middle[1], None,
                               level_of(tags), note_of(tags)))

    @staticmethod
    def _holds(rings, box, lat, lon, edge=0.0):
        """True when a position is inside the rings (or within edge metres of their outline)."""
        from placepacks.lookup import inside_rings
        pad = edge / 111000.0
        if not (box[0] - pad <= lat <= box[2] + pad and box[1] - pad <= lon <= box[3] + pad):
            return False
        micro = [fmt.micro(r) for r in rings]
        if inside_rings(lat, lon, micro):
            return True
        return bool(edge) and any(fmt.segment_metres(lat, lon, r[i], r[i + 1]) <= edge
                                  for r in micro for i in range(len(r) - 1))

    def _index(self, shapes, box_at):
        """A coarse grid index {cell: [shape]} of shapes by their boxes (0.01 degree cells)."""
        grid = {}
        for shape in shapes:
            s, w, n, e = box_at(shape)
            for y in range(int((s + 90) * 100), int((n + 90) * 100) + 1):
                for x in range(int((w + 180) * 100), int((e + 180) * 100) + 1):
                    grid.setdefault((y, x), []).append(shape)
        return grid

    def finish(self, writer, source):
        """Write each feature inside a site to the writer's site_features. Returns the number written."""
        if not self.sites:
            return 0
        store = features.store(writer)
        sites = self._index(sorted(self.sites, key=lambda s: s[3]), lambda s: s[2])
        buildings = self._index(self.buildings, lambda b: b[3])
        count = 0
        for key, kind, name, lat, lon, line, level, note in self.items:
            if line:
                lat, lon = line[len(line) // 2]
            cell = (int((lat + 90) * 100), int((lon + 180) * 100))
            site = next((s[0] for s in sites.get(cell, ()) if s[0] != key and self._holds(s[1], s[2], lat, lon)), "")
            if not site:
                continue
            building = ""
            if kind != "building":
                edge = EDGE_M if kind in ("entrance", "accessible entrance") else 0.0
                building = next((b[0] for b in buildings.get(cell, ()) if self._holds(b[2], b[3], lat, lon, edge)),
                                "")
                level = level or ""
            if store.add(key, source, kind, name, lat, lon, site=site, building=building, level=level,
                         line=line, notes=note):
                count += 1
        return count


@reader("osm_site_features")
def read(path, entry, region, writer, use_osmium=None, index=None):
    """Read an extract's site features into writer (see the module docstring). Returns the number written."""
    if use_osmium is None:
        try:
            import osmium  # noqa: F401
            use_osmium = True
        except ImportError:
            use_osmium = False
    if str(path).lower().endswith(".pbf") and not use_osmium:
        raise SystemExit("A .osm.pbf extract needs pyosmium (BSD-2-Clause): pip install osmium")
    found = Collector()
    if use_osmium:
        _read_osmium(path, found, index)
    else:
        _read_xml(path, found)
    return found.finish(writer, entry["id"])


def _read_xml(path, found):
    """A small .osm XML file with the standard library (nodes before ways, ways before relations)."""
    from placepacks.readers.osm import join_rings
    nodes, ways, relations = {}, {}, []
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag not in ("node", "way", "relation"):
            continue
        tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
        oid = el.get("id")
        if el.tag == "node":
            nodes[oid] = (float(el.get("lat")), float(el.get("lon")))
            if tags:
                found.node(oid, tags, *nodes[oid])
        elif el.tag == "way":
            refs = [nd.get("ref") for nd in el.findall("nd")]
            ways[oid] = refs
            points = [nodes[r] for r in refs if r in nodes]
            if tags and len(points) >= 2:
                if points[0] == points[-1] and len(points) >= 4 and not way_kind(tags):
                    found.area("w" + oid, tags, [points])
                else:
                    found.way(oid, tags, points)
        else:
            relations.append((oid, tags, [(m.get("type"), m.get("ref")) for m in el.findall("member")]))
        el.clear()
    for oid, tags, members in relations:
        if tags.get("type") == "multipolygon":
            rings = join_rings([[nodes[r] for r in ways.get(ref, []) if r in nodes] for kind, ref in members
                                if kind == "way"])
            if rings:
                found.area("r" + oid, tags, rings)


def _read_osmium(path, found, index=None):
    """An extract with pyosmium (BSD-2-Clause): tagged nodes, open ways and areas (closed ways with area tags and
    multipolygon relations, assembled by pyosmium)."""
    import osmium

    class Handler(osmium.SimpleHandler):
        """pyosmium's callbacks, each handing what it reads to the Collector."""
        def node(self, n):
            """A tagged node with a valid position."""
            if len(n.tags) and n.location.valid():
                found.node(n.id, {t.k: t.v for t in n.tags}, n.location.lat, n.location.lon)

        def way(self, w):
            """A way that may be a route, an escalator or an elevator."""
            tags = {t.k: t.v for t in w.tags}
            if way_kind(tags):
                found.way(w.id, tags, [(nd.lat, nd.lon) if nd.location.valid() else None for nd in w.nodes])

        def area(self, a):
            """An area that may be a site, a named building or a feature drawn as an area."""
            tags = {t.k: t.v for t in a.tags}
            if not (site_tags(tags) or (tags.get("building") and tags.get("name")) or point_kind(tags)):
                return
            rings = []
            for outer in a.outer_rings():
                rings.append([(nd.lat, nd.lon) for nd in outer])
                for inner in a.inner_rings(outer):
                    rings.append([(nd.lat, nd.lon) for nd in inner])
            found.area(("w" if a.from_way() else "r") + str(a.orig_id()), tags, rings)

    Handler().apply_file(str(path), locations=True, idx=index or "flex_mem")
