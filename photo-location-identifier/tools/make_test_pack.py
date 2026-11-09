"""Build a tiny made-up place pack for North Carolina with placepacks' own pack builder, for the tests and the
installer's smoke test (no internet needed).

    python tools/make_test_pack.py OUT_FOLDER

The made-up OpenStreetMap file has, as squares: the Outer Banks (place=islands) over three towns (Kill Devil Hills,
Nags Head, Duck: town boundaries and town points) in Dare County; a park in Nags Head; and Wrightsville Beach in New
Hanover County (another beach, elsewhere). The pack is OUT_FOLDER/us-north-carolina.osmpack. The positions are
public places; every name is attached to a made-up square, not the real outline.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
REGION = "us-north-carolina"

# (name, tags, (south, west, north, east)) for areas; (name, tags, (lat, lon)) for points.
AREAS = [
    ("Outer Banks", {"place": "islands"}, (35.20, -76.00, 36.55, -75.40)),
    ("Dare County", {"boundary": "administrative", "admin_level": "6"}, (35.20, -76.10, 36.30, -75.42)),
    ("Kill Devil Hills", {"boundary": "administrative", "admin_level": "8"}, (35.99, -75.69, 36.06, -75.63)),
    ("Nags Head", {"boundary": "administrative", "admin_level": "8"}, (35.90, -75.65, 35.99, -75.58)),
    ("Duck", {"boundary": "administrative", "admin_level": "8"}, (36.13, -75.78, 36.22, -75.72)),
    ("Jockey's Ridge State Park", {"leisure": "park"}, (35.955, -75.640, 35.970, -75.625)),
    ("New Hanover County", {"boundary": "administrative", "admin_level": "6"}, (34.00, -78.00, 34.40, -77.70)),
    ("Wrightsville Beach", {"boundary": "administrative", "admin_level": "8"}, (34.18, -77.83, 34.24, -77.78)),
]
POINTS = [
    ("Kill Devil Hills", {"place": "town"}, (36.03, -75.67)),
    ("Nags Head", {"place": "town"}, (35.95, -75.62)),
    ("Duck", {"place": "town"}, (36.17, -75.75)),
    ("Wrightsville Beach", {"place": "town"}, (34.21, -77.80)),
]
# Positions of the made-up photos (public places): used by the tests and the smoke test.
PHOTOS = [
    ("obx-2005-1.jpg", 36.030, -75.670, "2005-07-02 10:00"),      # Kill Devil Hills
    ("obx-2005-2.jpg", 35.940, -75.610, "2005-07-04 12:00"),      # Nags Head
    ("obx-2005-3.jpg", 36.020, -75.660, "2005-07-08 09:30"),      # Kill Devil Hills
    ("obx-2006-1.jpg", 36.170, -75.750, "2006-07-01 10:00"),      # Duck
    ("obx-2006-2.jpg", 36.180, -75.752, "2006-07-05 16:00"),      # Duck
    ("wb-2007-1.jpg", 34.210, -77.800, "2007-08-01 10:00"),       # Wrightsville Beach
    ("wb-2007-2.jpg", 34.215, -77.799, "2007-08-02 11:00"),       # Wrightsville Beach
]
EXPECTED_FOLDERS = ["Outer Banks 2005", "Outer Banks 2006", "Wrightsville Beach 2007"]


def osm_xml():
    """The made-up OpenStreetMap file (text)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="photo-location-identifier test">']
    node = 1
    ways = []
    for i, (name, tags, (s, w, n, e)) in enumerate(AREAS):
        ids = []
        for lat, lon in ((s, w), (s, e), (n, e), (n, w)):
            out.append(f' <node id="{node}" lat="{lat}" lon="{lon}" version="1"/>')
            ids.append(node)
            node += 1
        ids.append(ids[0])
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        refs = "".join(f'<nd ref="{r}"/>' for r in ids)
        ways.append(f' <way id="{1000 + i}" version="1">{refs}{tag_xml}<tag k="name" v="{_x(name)}"/></way>')
    for name, tags, (lat, lon) in POINTS:
        tag_xml = "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items())
        out.append(f' <node id="{node}" lat="{lat}" lon="{lon}" version="1" timestamp="2026-10-01T00:00:00Z">'
                   f'{tag_xml}<tag k="name" v="{_x(name)}"/></node>')
        node += 1
    out += ways + ["</osm>", ""]
    return "\n".join(out)


def _x(text):
    """text escaped for XML."""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("'", "&apos;").replace("<", "&lt;")


def build(out_folder, work=None):
    """Build the pack into out_folder (work: a folder for the made-up OSM file). Returns the pack's path."""
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    from placepacks import build as pp_build
    os.makedirs(out_folder, exist_ok=True)
    work = work or out_folder
    osm = os.path.join(work, "made-up-north-carolina.osm")
    with open(osm, "w", encoding="utf-8") as f:
        f.write(osm_xml())
    out = os.path.join(out_folder, pp_build.pack_name(REGION, "core"))
    if os.path.exists(out):
        os.remove(out)
    pp_build.build(REGION, "core", {"osm": {"path": osm, "ok": True, "version": "test"}}, out, only=["osm"],
                   removal_list=[])
    return out


def write_photos(folder):
    """Write the made-up photos (colour blocks with EXIF GPS and dates) into folder. Returns their paths."""
    import datetime as dt
    sys.path.insert(0, os.path.dirname(HERE))
    from pli.photos import write_test_photo
    os.makedirs(folder, exist_ok=True)
    paths = []
    for i, (name, lat, lon, when) in enumerate(PHOTOS):
        colour = (40 + 30 * i % 200, 120, 200 - 20 * i % 150)
        paths.append(write_test_photo(os.path.join(folder, name), lat, lon,
                                      dt.datetime.strptime(when, "%Y-%m-%d %H:%M"), altitude=3, colour=colour))
    return paths


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = build(sys.argv[1])
    print(path)
    if len(sys.argv) > 2:
        write_photos(sys.argv[2])
        print(f"Photos written to {sys.argv[2]}")
