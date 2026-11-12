"""The parts (core, extra, names, businesses, addresses) and the sub-regions (England's regions, Texas's groups of
counties, ...): which parts a lookup downloads, a parent id mapped to its children, lookups at a sub-region border,
old manifests and old programs, the parent's combined pack, the history a sub-region takes from its parent's packs,
the TIGER counties of a sub-region, and the cells of tools/make_subregions.py. Made-up data only; offline."""

import datetime
import io
import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from placepacks import build, catalogue, download, fmt, manifest, regions  # noqa: E402
from placepacks.lookup import Finder, PackReader, close_readers  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

FL = "us-florida"
SOUTH, CENTRAL, NORTH = "us-florida-south", "us-florida-central", "us-florida-north"


def border(lon=-81.5):
    """(latitude just north, latitude just south) of the border between Central and South Florida on a meridian."""
    lat = 26.0
    while regions.in_region(regions.REGIONS[SOUTH], lat, lon):
        lat += 0.001
    assert regions.in_region(regions.REGIONS[CENTRAL], lat, lon)
    return lat + 0.002, lat - 0.002


def pack(path, region_id, part, month=202611, points=(), lines=(), clip=None):
    """A small pack: points [(key, source, name, cls, lat, lon, type)], lines [(key, name, [(lat, lon)])]."""
    w = PackWriter(str(path), month, clip=clip)
    for key, source, name, cls, lat, lon, kind in points:
        w.add_point(key, source, name, cls, "t", lat, lon, type=kind)
    for key, name, pts in lines:
        w.add_line(key, "osm", name, "street", "residential", pts)
    w.add_source(id="osm", name="OpenStreetMap", short="OpenStreetMap", part=part, licence="ODbL-1.0")
    r = regions.REGIONS[region_id]
    w.finish({"region_id": region_id, "region_name": r["name"], "country": r["country"], "part": part,
              "parent": r.get("parent", "")})
    return str(path)


# ------------------------------------------------------------------------------------------- the parts

def test_parts_and_the_catalogue():
    """Five parts; the catalogue puts Overture and the business lists in businesses, the address points and ranges
    in addresses; core keeps OpenStreetMap and the Census areas, no address points."""
    assert fmt.PARTS[:3] == ("core", "extra", "names") and set(fmt.DETAIL_PARTS) == {"businesses", "addresses"}
    part = catalogue.part_of()
    assert part["overture-places"] == part["alltheplaces"] == part["irs-exempt-organizations"] == "businesses"
    assert part["fsa-hygiene"] == part["nyc-restaurant-inspections"] == "businesses"
    assert part["nad"] == part["oda"] == part["tiger-addrfeat"] == part["nrn-address-ranges"] == "addresses"
    assert part["osm"] == part["census-places"] == "core" and part["wikidata"] == part["gnis"] == "extra"
    assert catalogue.check() == []


def test_which_parts_a_lookup_downloads():
    """Core and extra by default; the businesses and the addresses for the detail "address", the exact place (a
    picture's name, Describe this picture), or full detail."""
    assert download.parts_for() == ("core", "extra") == download.parts_for("street")
    for detail in ("address", "exact"):
        assert download.parts_for(detail) == ("core", "extra", "businesses", "addresses")
    assert download.parts_for("area", full=True) == ("core", "extra", "businesses", "addresses")


# ------------------------------------------------------------------------------------------- the sub-regions

def test_every_position_of_a_parent_is_in_at_most_one_child():
    """A position is in at most one child, and a position inside the parent (its towns) in exactly one; positions in
    a neighbour inside the parent's box (Vermont in New York's, Newark beside New York City, Wales beside England,
    Detroit beside Ontario) are in none; regions_for gives the child, never the parent; a parent is expanded to its
    children; the children carry the parent's state fields."""
    rng = random.Random(7)
    for parent in ("gb-england", "us-texas", "au-australia", "ca-ontario", FL, "us-new-york", "us-california",
                   "ca-quebec", "nl-netherlands", "no-norway", "se-sweden"):
        p = regions.REGIONS[parent]
        kids = [regions.REGIONS[c] for c in p["children"]]
        w, s, e, n = p["bbox"]
        for _ in range(300):
            lat, lon = rng.uniform(s, n), rng.uniform(w, e)
            assert sum(regions.in_region(k, lat, lon) for k in kids) <= 1, (parent, lat, lon)
        assert regions.expand(parent) == p["children"] and regions.parent_of(p["children"][0]) == parent
        assert all(k.get("code") == p.get("code") and k["geofabrik"] == p["geofabrik"] for k in kids)
    for lat, lon, parent in ((44.26, -72.58, "us-new-york"), (40.735, -74.17, "us-new-york"),
                             (51.48, -3.18, "gb-england"), (42.33, -83.05, "ca-ontario")):
        assert not any(regions.in_region(regions.REGIONS[c], lat, lon) for c in regions.expand(parent))
    assert regions.regions_near(44.26, -72.58) == ["us-vermont"]                    # not New York's
    assert regions.regions_near(40.735, -74.17) == ["us-new-jersey"]                # Newark
    assert regions.regions_near(51.5, -0.12) == ["gb-england-london"]              # not Scotland's or Wales's box
    for lat, lon, child in ((53.48, -2.24, "gb-england-north-west"), (52.48, -1.9, "gb-england-west-midlands"),
                            (32.78, -96.8, "us-texas-north"), (34.05, -118.24, "us-california-los-angeles"),
                            (37.77, -122.42, "us-california-bay-area"), (25.76, -80.19, "us-florida-south"),
                            (45.5, -73.57, "ca-quebec-montreal"), (59.91, 10.75, "no-norway-east-and-south"),
                            (52.37, 4.9, "nl-netherlands-west"), (59.33, 18.07, "se-sweden-stockholm-and-north")):
        assert regions.regions_for(lat, lon)[0] == child, (lat, lon)
    assert regions.regions_for(51.507, -0.128)[0] == "gb-england-london"
    assert regions.regions_for(29.76, -95.37)[0] == "us-texas-gulf-coast"          # Houston
    assert regions.regions_for(-33.87, 151.21)[0] == "au-new-south-wales"           # Sydney
    assert regions.regions_for(-35.28, 149.13)[0] == "au-australian-capital-territory"
    assert regions.regions_for(43.65, -79.38)[0] == "ca-ontario-toronto"
    assert regions.regions_for(40.71, -74.0)[0] == "us-new-york-city"
    assert "gb-england" not in regions.regions_for(51.507, -0.128)
    # A resolver that names the parent gets the child holding the position.
    assert regions.regions_for(51.507, -0.128, resolver=lambda la, lo: "gb-england")[0] == "gb-england-london"
    assert "gb-england" not in [r for c in regions.tree().values() for ids in c.values() for r in ids]
    assert regions.REGIONS["us-texas-gulf-coast"]["counties"] and "201" in regions.REGIONS["us-texas-gulf-coast"][
        "counties"]                                                                   # Harris County
    assert regions.query_boxes(regions.REGIONS[SOUTH]) == [tuple(regions.REGIONS[SOUTH]["bbox"])]
    assert regions.region_label("gb-england-south-east") == "England: South East, United Kingdom"


def test_a_lookup_at_a_sub_region_border_finds_both_packs(tmp_path):
    """A street across the border is in both children's packs; a café just across the border is in its own child's
    pack only (and in the other's within the overlap); regions_near gives both children near the border, and a
    lookup with both packs finds the café and the street from either side."""
    north, south = border()
    lon = -81.5
    folder = tmp_path / "packs"
    folder.mkdir()
    street = ("w1", "Made-up Border Road", [(south - 0.01, lon), (north + 0.01, lon)])
    cafe = ("n1", "osm", "Made-up Border Cafe", "business", north, lon + 0.0002, "cafe")
    far = ("n2", "osm", "Made-up Far Shop", "business", north + 0.5, lon, "shop")
    for child in (SOUTH, CENTRAL):
        pack(folder / f"{child}.osmpack", child, "core", points=[cafe, far], lines=[street],
             clip=regions.REGIONS[child])
    south_pack, central_pack = PackReader(str(folder / f"{SOUTH}.osmpack")), PackReader(str(folder / f"{CENTRAL}.osmpack"))
    assert [r["name"] for r in central_pack._rows("SELECT name FROM lines")] == ["Made-up Border Road"]
    assert [r["name"] for r in south_pack._rows("SELECT name FROM lines")] == ["Made-up Border Road"]
    assert {r["name"] for r in central_pack._rows("SELECT name FROM points")} == {"Made-up Border Cafe",
                                                                                 "Made-up Far Shop"}
    assert {r["name"] for r in south_pack._rows("SELECT name FROM points")} == {"Made-up Border Cafe"}  # overlap
    near = regions.regions_near(south, lon, km=1.0)
    assert near[0] == SOUTH and CENTRAL in near
    assert regions.regions_near(south - 0.5, lon, km=1.0) == [SOUTH]
    f = Finder(folder=str(folder), water=False)
    assert f.lookup(south, lon, detail="street").street == "Made-up Border Road"
    assert f.lookup(north, lon + 0.0002, detail="address").name == "Made-up Border Cafe"
    close_readers()


# ------------------------------------------------------------------------------------------- downloads

def publish(tmp_path, packs, today=datetime.date(2026, 11, 2)):
    """(manifest bytes, {asset name: bytes}) of a release holding the given packs [(region, part)]."""
    built = tmp_path / f"built{len(os.listdir(tmp_path))}"
    built.mkdir()
    for region_id, part in packs:
        r = regions.REGIONS[region_id]
        lat, lon = (r["bbox"][1] + r["bbox"][3]) / 2, (r["bbox"][0] + r["bbox"][2]) / 2
        pack(built / (manifest.key_of(region_id, part) + fmt.PACK_SUFFIX), region_id, part,
             points=[(f"{region_id}:{part}", "osm", f"Made-up {part} place", "landmark", lat, lon, None)])
    m, uploads = manifest.publish("", str(built), str(tmp_path), today=today)
    files = {release_url(release) + asset: open(path, "rb").read() for path, asset, release in uploads}
    files[download.PUBLIC_RELEASE + "packs.json"] = json.dumps(m).encode()
    return m, files


def release_url(release):
    """The download folder of a release (the detail releases are beside "packs")."""
    root = download.PUBLIC_RELEASE.rstrip("/").rsplit("/", 1)[0]
    return f"{root}/{release}/"


def catalogue_of(folder, files):
    return download.Catalogue(cache_path=str(folder / "packs.json"), opener=lambda url: io.BytesIO(files[url]))


def test_a_parent_id_downloads_its_children_and_detail_parts_only_when_asked(tmp_path):
    """ensure_pack("us-florida") gets each child's core after one question; ensure_packs gets core and extra by
    default and the businesses and addresses for the exact place; a part not published is left out quietly."""
    kids = regions.expand(FL)
    m, files = publish(tmp_path, [(c, p) for c in kids for p in ("core", "extra", "businesses")] +
                       [(SOUTH, "addresses")])
    folder = tmp_path / "packs"
    cat = catalogue_of(folder, files)
    asked = []
    first = download.ensure_pack(FL, "core", folder=str(folder), catalogue=cat, ask=lambda q: asked.append(q) or True)
    assert len(asked) == 1 and "3 areas" in asked[0] and first.endswith(f"{SOUTH}.osmpack")
    assert sorted(os.listdir(folder)) == sorted([f"{c}.osmpack" for c in kids] + ["installed.json", "packs.json"])
    paths = download.ensure_packs(FL, folder=str(folder), catalogue=cat)
    assert sorted(os.path.basename(p) for p in paths) == sorted(f"{manifest.key_of(c, p)}.osmpack" for c in kids
                                                                for p in ("core", "extra"))
    assert not any("businesses" in n for n in os.listdir(folder))
    paths = download.ensure_packs(SOUTH, detail="exact", folder=str(folder), catalogue=cat)
    assert sorted(os.path.basename(p) for p in paths) == sorted(f"{SOUTH}{s}.osmpack" for s in ("", "-extra",
                                                                                             "-businesses",
                                                                                             "-addresses"))
    # Central has no addresses part published: the lookup goes on without it.
    paths = download.ensure_packs(CENTRAL, detail="address", folder=str(folder), catalogue=cat)
    assert len(paths) == 3 and not os.path.exists(folder / f"{CENTRAL}-addresses.osmpack")
    f = Finder(folder=str(folder), water=False)
    assert f.lookup(*border()) is not None                  # never fails, whatever parts are here
    close_readers()


def test_old_manifests_and_old_programs_keep_working(tmp_path, monkeypatch):
    """1. A program newer than the packs (packs.json lists only the parent): the parent's own pack is used for the
    parent and for its children. 2. An installed parent pack is updated as its children, then removed. 3. A program
    made before the parts and the sub-regions reads the new packs.json: it sees the parent's combined packs and its
    known parts, and leaves the rest out."""
    old, old_files = publish(tmp_path, [(FL, "core"), (FL, "extra"), ("us-vermont", "core")])
    folder = tmp_path / "packs"
    cat = catalogue_of(folder, old_files)
    path = download.ensure_pack(SOUTH, "core", folder=str(folder), catalogue=cat)
    assert os.path.basename(path) == f"{FL}.osmpack"
    assert download.ensure_packs(FL, detail="exact", folder=str(folder), catalogue=cat) == [
        str(folder / f"{FL}.osmpack"), str(folder / f"{FL}-extra.osmpack")]
    assert download.updates_available(str(folder), cat) == []
    # 2. The packs of the sub-regions are published (and the parent's combined pack).
    kids = regions.expand(FL)
    new, new_files = publish(tmp_path, [(c, p) for c in kids for p in ("core", "extra", "addresses")] +
                             [(FL, "core"), (FL, "extra")], today=datetime.date(2026, 12, 2))
    os.remove(folder / "packs.json")
    cat = catalogue_of(folder, new_files)
    updates = download.updates_available(str(folder), cat)
    assert sorted(i.key for i in updates) == sorted([*kids, *(f"{c}-extra" for c in kids)])
    for info in updates:
        download.ensure_pack(info.region, info.part, str(folder), catalogue=cat, update=True)
    download.ensure_pack(FL, "core", folder=str(folder), catalogue=cat)
    download.ensure_pack(FL, "extra", folder=str(folder), catalogue=cat)
    assert not os.path.exists(folder / f"{FL}.osmpack") and not os.path.exists(folder / f"{FL}-extra.osmpack")
    # 3. An old program: only the regions and parts it knows.
    old_regions = {rid: r for rid, r in regions.REGIONS.items() if not r.get("parent")}
    monkeypatch.setattr(fmt, "PARTS", ("core", "extra", "names"))
    seen = manifest.parse(new_files[download.PUBLIC_RELEASE + "packs.json"], regions=old_regions)
    assert sorted(seen) == [FL, f"{FL}-extra"]
    monkeypatch.undo()
    assert len(manifest.parse(new_files[download.PUBLIC_RELEASE + "packs.json"])) == len(new["packs"])
    assert manifest.split_key("us-florida-south-addresses") == (SOUTH, "addresses")
    assert manifest.split_key(f"{FL}-extra") == (FL, "extra") and manifest.split_key("x-y") is None
    close_readers()


# ------------------------------------------------------------------------------------------- building

def test_the_parent_pack_is_its_children_put_together(tmp_path):
    """combine: every child's rows once (a street in both children is one row), the type phrases kept, the parent's
    id and the children named; a lookup in it finds what each child has."""
    from placepacks import combine
    north, south = border()
    street = ("w1", "Made-up Border Road", [(south - 0.01, -81.5), (north + 0.01, -81.5)])
    a = pack(tmp_path / "s.osmpack", SOUTH, "core", lines=[street],
             points=[("n1", "osm", "Made-up South Cafe", "business", south - 0.1, -81.5, "cafe")])
    b = pack(tmp_path / "c.osmpack", CENTRAL, "core", lines=[street],
             points=[("n2", "osm", "Made-up Central Park", "park", north + 0.1, -81.5, None)])
    out = tmp_path / f"{FL}.osmpack"
    counts = combine.combine(FL, "core", [a, b], str(out))
    assert counts["lines"] == 1 and counts["points"] == 2
    p = PackReader(str(out))
    assert p.region_id == FL and p.part == "core" and p.meta["combined_from"] == f"{SOUTH},{CENTRAL}"
    f = Finder(packs=[p], water=False)
    assert f.lookup(south - 0.1, -81.5, detail="address").type == "cafe"
    assert f.lookup(south, -81.5, detail="street").street == "Made-up Border Road"
    plan = combine.plan(str(tmp_path / "nothing"), "")
    assert plan == []
    close_readers()


def test_a_sub_region_takes_its_history_from_its_parents_packs(tmp_path):
    """A child's first build in the new parts: previous_files picks its parent's older packs; only the rows of its
    own area and of its own part's sources are taken (Overture went to businesses, the NAD to addresses)."""
    north, south = border()
    folder = tmp_path / "previous"
    folder.mkdir()
    pack(folder / f"{FL}-extra.osmpack", FL, "extra", month=202610, points=[
        ("wd:1", "wikidata", "Made-up Old South Fort", "landmark", south - 0.2, -81.5, None),
        ("wd:2", "wikidata", "Made-up Old North Fort", "landmark", north + 0.2, -81.5, None),
        ("ov:1", "overture-places", "Made-up Old Diner", "business", south - 0.2, -81.4, None)])
    pack(folder / f"{FL}.osmpack", FL, "core", month=202610)
    assert build.previous_files(SOUTH, "extra", str(folder)) == [str(folder / f"{FL}.osmpack"),
                                                                 str(folder / f"{FL}-extra.osmpack")]
    assert build.previous_files(SOUTH, "names", str(folder)) == []
    own = pack(folder / f"{SOUTH}-extra.osmpack", SOUTH, "extra", month=202610)
    assert build.previous_files(SOUTH, "extra", str(folder)) == [own]
    os.remove(own)
    region = regions.REGIONS[SOUTH]
    w = PackWriter(str(tmp_path / "n.osmpack"), 202611, clip=region)
    w.finish({"region_id": SOUTH, "part": "extra"}, previous=build.previous_files(SOUTH, "extra", str(folder)),
             keep=build.keep_for(region, "extra", catalogue.load()))
    rows = PackReader(str(tmp_path / "n.osmpack"))._rows("SELECT name, first, last FROM points")
    assert rows == [{"name": "Made-up Old South Fort", "first": 202610, "last": 202610}]
    assert set(build.previous_keys(SOUTH)) >= {SOUTH, f"{SOUTH}-addresses", FL, f"{FL}-extra"}
    close_readers()


def test_a_sub_region_fetches_only_its_counties(monkeypatch, tmp_path):
    """TIGER's county files: a sub-region of a state downloads its own counties (and those next to it); the state's
    single files are kept; the OpenStreetMap extract is read whole when osmium-tool is missing."""
    from placepacks import fetch
    listing = "".join(f'<a href="tl_2025_48{c}_addrfeat.zip">x</a>' for c in ("201", "113", "029", "999"))

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(fetch, "request", lambda *a, **k: Answer(listing.encode()))
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "tiger-addrfeat")
    for rid, want in (("us-texas-gulf-coast", 1), ("us-texas-north", 1), ("us-texas-south-central", 1)):
        region = regions.REGIONS[rid]
        got = fetch.fetch_source(entry, region, catalogue.settings_for(catalogue.load(), region), str(tmp_path),
                                 None, True)
        assert got["version"].endswith(f"({want} files)"), (rid, got["version"])
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert fetch.clip_osm("x.osm.pbf", regions.REGIONS[SOUTH]) == "x.osm.pbf"


def test_seeds_and_the_workflow_know_the_sub_regions():
    """A seed is per region (its fingerprint includes the region); the workflow builds every part, reads a
    sub-region's parent slice, clips OpenStreetMap with osmium-tool and puts the parents together."""
    from placepacks import seed
    assert seed.fingerprint(region_id=SOUTH) != seed.fingerprint(region_id=CENTRAL) != seed.fingerprint()
    wf = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    for text in ("matrix.region.slice", "osmium-tool", "--previous-dir previous", "placepacks.combine plan",
                 "--list-previous", "--part all", "previous/seed.osmpack", "for part in businesses addresses names"):
        assert text in wf, text
    out = io.StringIO()
    sys_stdout, sys.stdout = sys.stdout, out
    try:
        manifest.main(["plan", "--regions", FL])
    finally:
        sys.stdout = sys_stdout
    planned = json.loads(out.getvalue().split("=", 1)[1])
    assert [p["id"] for p in planned] == regions.expand(FL) and {p["slice"] for p in planned} == {FL}
    with pytest.raises(SystemExit):
        build.build(FL, "core", {}, "x.osmpack")


def test_the_cells_of_a_sub_region(tmp_path):
    """tools/make_subregions.py: a shape's cells, the sea given to the nearest child, the cells joined into
    rectangles; regions.json keeps lists of numbers on one line."""
    import make_subregions as ms
    g = ms.Grid((0.0, 0.0, 1.0, 1.0), 0.1)
    left = [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)]
    for cell in g.rasterise([left]):
        g.owner[cell] = "a"
    g.owner[g.cell_of(0.95, 0.95)] = "b"
    g.foreign.add(g.cell_of(0.05, 0.85))            # another country's cell: nobody's
    g.fill(limit=100)
    assert len(g.owner) == g.rows * g.cols - 1 and g.cell_of(0.05, 0.85) not in g.owner
    near = ms.Grid((0.0, 0.0, 1.0, 1.0), 0.1)
    near.owner[near.cell_of(0.05, 0.05)] = "a"
    near.fill(limit=2)                              # only so far out to sea
    assert len(near.owner) < near.rows * near.cols and near.cell_of(0.95, 0.95) not in near.owner
    assert g.owner[g.cell_of(0.25, 0.25)] == "a" and g.owner[g.cell_of(0.95, 0.95)] == "b"
    area = sum((e - w) * (n - s) for child in ("a", "b") for w, s, e, n in g.boxes(child))
    assert area == pytest.approx((g.rows * g.cols - 1) * 0.01)        # every owned cell in exactly one box
    text = ms.dump({"regions": [{"id": "x", "bbox": [1.5, -2, 3, 4], "boxes": [[1, 2, 3, 4]]}]})
    assert '"bbox": [1.5, -2, 3, 4]' in text and "[1, 2, 3, 4]" in text


def test_the_status_lists_each_regions_parts(tmp_path):
    """sources-status.md's table: each region's parts and sizes, a parent's combined pack said so; the manifest keeps
    which sub-regions a combined pack was made from."""
    from placepacks import combine, status
    north, south = border()
    a = pack(tmp_path / "s.osmpack", SOUTH, "core", points=[("n1", "osm", "Made-up Cafe", "business", south - 0.1,
                                                             -81.5, None)])
    built = tmp_path / "built"
    built.mkdir()
    combine.combine(FL, "core", [a], str(built / f"{FL}.osmpack"))
    m, _ = manifest.publish("", str(built), str(tmp_path), today=datetime.date(2026, 12, 2))
    assert m["packs"][FL]["combined_from"] == [SOUTH]
    m["packs"][f"{SOUTH}-addresses"] = {"region": SOUTH, "part": "addresses", "size": 2_000_000}
    m["packs"]["us-texas"] = {"region": "us-texas", "part": "core", "size": 3_000_000}
    text = status.status(m)
    assert "| us-florida (its sub-regions put together) |" in text and "| us-texas (before its sub-regions) |" in text
    assert "| us-florida-south |  |  |  |  | 2.0 | 0.0 |" in text
    close_readers()


def test_a_sub_region_names_its_state_in_filters():
    """A source filtered by the province's or state's name (the Canadian names by "Ontario") or reading a
    hand-supplied folder by region id: a sub-region uses its parent's name and id."""
    from placepacks.readers.tabular import region_values
    north = regions.REGIONS["ca-ontario-north"]
    assert region_values(north)["name"] == "Ontario" and region_values(north)["id"] == "ca-ontario"
    values = catalogue.settings_for(catalogue.load(), north)
    assert values["name"] == "Ontario" and values["code"] == "ON" and values["pruid"] == "35"
    assert catalogue.settings_for(catalogue.load(), regions.REGIONS["us-vermont"])["name"] == "Vermont"


def test_a_sub_regions_pack_says_its_state(tmp_path):
    """A lookup's region is the state ("Texas"), never the sub-region's name ("Texas: Gulf Coast")."""
    meta = build.build("us-texas-gulf-coast", "core", {}, str(tmp_path / "t.osmpack"), month=202611,
                       removal_list=[])
    assert meta["state"] == "Texas" and meta["region_name"] == "Texas: Gulf Coast"
    assert meta["parent"] == "us-texas"


def test_detail_parts_go_in_a_release_of_their_own(tmp_path):
    """GitHub allows 1000 files in a release: core and extra stay in "packs" (where programs made before this find
    them), the names, businesses and addresses of a publish go in "packs-detail-YYYYMMDD", and the programs download
    each pack from its release."""
    m, files = publish(tmp_path, [(SOUTH, "core"), (SOUTH, "extra"), (SOUTH, "businesses"), (SOUTH, "addresses")])
    assert {e["part"]: e["release"] for e in m["packs"].values()} == {
        "core": "packs", "extra": "packs", "businesses": "packs-detail-20261102", "addresses": "packs-detail-20261102"}
    infos = manifest.parse(json.dumps(m).encode())
    assert infos[f"{SOUTH}-addresses"].release == "packs-detail-20261102" and infos[SOUTH].release == "packs"
    cat = catalogue_of(tmp_path / "packs", files)
    assert cat.url_for(infos[f"{SOUTH}-businesses"]).endswith(
        "/releases/download/packs-detail-20261102/" + infos[f"{SOUTH}-businesses"].name)
    paths = download.ensure_packs(SOUTH, detail="exact", folder=str(tmp_path / "packs"), catalogue=cat)
    assert len(paths) == 4
    # A list that names another release than these two kinds is not followed (an entry's release is checked).
    bad = json.loads(json.dumps(m))
    bad["packs"][f"{SOUTH}-addresses"]["release"] = "../evil"
    assert manifest.parse(json.dumps(bad).encode())[f"{SOUTH}-addresses"].release == "packs"
    keep = manifest.referenced_in(m)
    assert f"packs\t{m['packs'][SOUTH]['name']}" in keep
    assert f"packs-detail-20261102\t{m['packs'][SOUTH + '-addresses']['name']}" in keep


def test_a_pack_replaced_since_the_list_was_read_is_downloaded_from_the_new_list(tmp_path):
    """The cached list names a file a newer publish removed (404): the list is read again and the new pack comes."""
    import urllib.error
    m1, files1 = publish(tmp_path, [(SOUTH, "core")], today=datetime.date(2026, 11, 2))
    m2, files2 = publish(tmp_path, [(SOUTH, "core")], today=datetime.date(2026, 12, 2))
    folder = tmp_path / "packs"
    folder.mkdir()
    (folder / "packs.json").write_bytes(json.dumps(m1).encode())        # the old list, fresh in the cache

    def opener(url):
        if url not in files2:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        return io.BytesIO(files2[url])
    cat = download.Catalogue(cache_path=str(folder / "packs.json"), opener=opener)
    path = download.ensure_pack(SOUTH, "core", folder=str(folder), catalogue=cat)
    assert download.installed(str(folder))[SOUTH]["name"] == m2["packs"][SOUTH]["name"] and os.path.exists(path)


def test_the_packs_list_stays_small(tmp_path):
    """Only the core entry lists every source of its region (plan compares them); the other parts list their own,
    and the file is written compact, so a list of every part of every region stays under manifest.LIMIT."""
    fetched = tmp_path / SOUTH
    fetched.mkdir()
    cat = __import__("placepacks.catalogue", fromlist=["x"]).load()
    region = dict(regions.REGIONS[SOUTH])
    ids = {p: {e["id"] for e in __import__("placepacks.catalogue", fromlist=["x"]).sources_for(region, p, cat)}
           for p in ("core", "businesses")}
    every = sorted(ids["core"] | ids["businesses"])
    (fetched / "fetched.json").write_text(json.dumps({s: {"ok": True, "version": "v1", "date": "2026-11-01"}
                                                      for s in every}))
    m, _ = publish(tmp_path, [(SOUTH, "core"), (SOUTH, "businesses")])
    assert set(m["packs"][SOUTH]["sources"]) == set(every)
    assert set(m["packs"][f"{SOUTH}-businesses"]["sources"]) == ids["businesses"] & set(every)
