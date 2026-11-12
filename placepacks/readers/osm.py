"""OpenStreetMap extracts (ODbL): named points, named areas (closed ways and multipolygons, with holes) and named
streets. Keys are OpenStreetMap's own ids ("n123", "w45", "r6"), so a renamed shop keeps its id and gets a new row.
No house numbers and no tags except the main one are kept; the fine type ("pizza restaurant", from amenity, shop,
cuisine, craft, tourism, leisure, healthcare, man_made, historic, religion and denomination) is kept beside the
class (placepacks.types)."""

import xml.etree.ElementTree as ET

from placepacks import fmt, types
from placepacks.readers import reader

ROAD_KINDS = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
              "living_street", "pedestrian", "service", "road", "footway", "path", "cycleway", "track", "steps",
              "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
SETTLEMENTS = {"city", "town", "village", "hamlet"}
MAIN_KEYS = ("leisure", "boundary", "tourism", "historic", "amenity", "shop", "office", "craft", "landuse",
             "natural", "waterway", "man_made", "aeroway", "railway", "public_transport", "highway", "place",
             "building")


REGION_PLACES = {"region", "archipelago", "islands", "island", "islet", "peninsula", "state", "county",
                 "province", "district"}
REGION_NATURE = {"peninsula", "valley", "cape", "isthmus", "plateau", "ridge"}


def main_tag(tags):
    """(key, value, class) of the tag that says what a named object is, or None when a pack does not keep it.
    Regional names (island chains, islands, peninsulas, valleys, tourist regions) get the class "region";
    administrative boundaries (counties, states, towns) "admin", with their admin_level as the tag."""
    if tags.get("boundary") == "administrative" and tags.get("admin_level", "").isdigit() and \
            3 <= int(tags["admin_level"]) <= 10:
        return "admin_level", tags["admin_level"], "admin"
    if tags.get("place") in REGION_PLACES or tags.get("natural") in REGION_NATURE or \
            tags.get("tourism") == "region":
        key = "place" if tags.get("place") in REGION_PLACES else ("natural" if tags.get("natural") in REGION_NATURE
                                                                  else "tourism")
        return key, tags[key], "region"
    for key in MAIN_KEYS:
        value = tags.get(key)
        if not value or value == "no":
            continue
        if key == "place" and value in SETTLEMENTS:
            return key, value, "settlement"
        if key == "building":
            return key, value, "building"
        if key == "landuse" and value not in ("cemetery", "recreation_ground", "village_green", "retail"):
            continue
        if key == "highway" and value != "bus_stop":
            continue
        cls = fmt.classify(key, value)
        if cls:
            return key, value, cls
    return None


def is_area_tags(tags):
    """True when a closed way is an area (not a closed street or a roundabout)."""
    if tags.get("area") == "yes":
        return True
    return "highway" not in tags and tags.get("area") != "no"


def join_rings(ways):
    """Closed rings from the member ways of a multipolygon, joined end to end."""
    open_ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while open_ways:
        ring = open_ways.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, w in enumerate(open_ways):
                if w[0] == ring[-1]:
                    ring += w[1:]
                elif w[-1] == ring[-1]:
                    ring += w[::-1][1:]
                elif w[-1] == ring[0]:
                    ring = w[:-1] + ring
                elif w[0] == ring[0]:
                    ring = w[::-1][:-1] + ring
                else:
                    continue
                open_ways.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _add(writer, source, key, tags, points=None, rings=None, point=None):
    """Add one named object (a point, a street or an area) to writer."""
    name = tags.get("name")
    if not name:
        return
    if points is not None:
        kind = tags.get("highway")
        if kind in ROAD_KINDS and tags.get("area") != "yes":
            writer.add_line(key, source, name, "street", f"highway={kind}", points)
        return
    found = main_tag(tags)
    if not found:
        return
    tag = f"{found[0]}={found[1]}"
    kind = types.osm(tags) or None          # the fine type: "pizza restaurant", "catholic church", "hardware store"
    if rings is not None:
        writer.add_area(key, source, name, found[2], tag, rings, type=kind)
    elif point is not None:
        brand = (tags.get("brand"), tags.get("brand:wikidata")) if tags.get("brand") else None
        writer.add_point(key, source, name, found[2], tag, *point, type=kind, brand=brand)


@reader("osm")
def read(path, entry, region, writer, use_osmium=None, index=None):
    """Read an extract into writer. Returns the extract's date (text, "" if it has none)."""
    if use_osmium is None:
        try:
            import osmium  # noqa: F401
            use_osmium = True
        except ImportError:
            use_osmium = False
    if str(path).lower().endswith(".pbf") and not use_osmium:
        raise SystemExit("A .osm.pbf extract needs pyosmium (BSD-2-Clause): pip install osmium")
    return _read_osmium(path, entry["id"], writer, index) if use_osmium else _read_xml(path, entry["id"], writer)


def _read_xml(path, source, writer):
    """A small .osm XML file with the standard library."""
    nodes, ways, relations, stamp = {}, {}, [], ""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag not in ("node", "way", "relation"):
            continue
        tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
        stamp = max(stamp, el.get("timestamp") or "")
        oid = el.get("id")
        if el.tag == "node":
            nodes[oid] = (float(el.get("lat")), float(el.get("lon")))
            _add(writer, source, "n" + oid, tags, point=nodes[oid])
        elif el.tag == "way":
            refs = [nd.get("ref") for nd in el.findall("nd")]
            ways[oid] = refs
            points = [nodes[r] for r in refs if r in nodes]
            if tags.get("name") and len(points) >= 2:
                if tags.get("highway") in ROAD_KINDS and tags.get("area") != "yes":
                    _add(writer, source, "w" + oid, tags, points=points)
                elif points[0] == points[-1] and len(points) >= 4 and is_area_tags(tags):
                    _add(writer, source, "w" + oid, tags, rings=[points])
        else:
            relations.append((oid, tags, [(m.get("type"), m.get("ref")) for m in el.findall("member")]))
        el.clear()
    for oid, tags, members in relations:
        if tags.get("type") in ("multipolygon", "boundary") and tags.get("name"):
            rings = join_rings([[nodes[r] for r in ways.get(ref, []) if r in nodes] for kind, ref in members
                                if kind == "way"])
            if rings:
                _add(writer, source, "r" + oid, tags, rings=rings)
    return stamp


def _read_osmium(path, source, writer, index=None):
    """An extract with pyosmium (BSD-2-Clause); the node index on disk when index is "sparse_file_array,<file>"."""
    import osmium

    class Handler(osmium.SimpleHandler):
        """pyosmium's callbacks: each named node, named road and named area is added to the writer."""
        def node(self, n):
            """A named node with a valid position: a point."""
            if "name" in n.tags and n.location.valid():
                _add(writer, source, f"n{n.id}", {t.k: t.v for t in n.tags},
                     point=(n.location.lat, n.location.lon))

        def way(self, w):
            """A named road (highway in ROAD_KINDS) with two points or more: a line."""
            if "name" in w.tags and w.tags.get("highway") in ROAD_KINDS:
                points = [(nd.lat, nd.lon) for nd in w.nodes if nd.location.valid()]
                if len(points) >= 2:
                    _add(writer, source, f"w{w.id}", {t.k: t.v for t in w.tags}, points=points)

        def area(self, a):
            """A named area (a closed way with area tags, or a multipolygon relation): its outer and inner rings."""
            if "name" not in a.tags:
                return
            tags = {t.k: t.v for t in a.tags}
            if a.from_way() and not is_area_tags(tags):
                return
            rings = []
            for outer in a.outer_rings():
                rings.append([(nd.lat, nd.lon) for nd in outer])
                for inner in a.inner_rings(outer):
                    rings.append([(nd.lat, nd.lon) for nd in inner])
            if rings:
                _add(writer, source, ("w" if a.from_way() else "r") + str(a.orig_id()), tags, rings=rings)

    reader_ = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
    stamp = reader_.header().get("osmosis_replication_timestamp", "") or ""
    reader_.close()
    Handler().apply_file(str(path), locations=True, idx=index or "flex_mem")
    return stamp
