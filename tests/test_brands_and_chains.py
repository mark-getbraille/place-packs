"""Brands (a chain's name and its Wikidata id, kept beside each point as data only) and All The Places (chain store
locations). Offline: made-up fixtures only."""

import json
import os
import sqlite3
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from placepacks import catalogue, fetch  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
SPOT = (44.0006, -71.9981)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def pack(path, month, rows, previous=None):
    """A pack of business points [(key, name, brand)] from SPOT northwards, about 22 m apart (the first is clearly
    the nearest; see the several-tenants rule), built at month on previous."""
    w = PackWriter(str(path), month)
    for i, (key, name, brand) in enumerate(rows):
        w.add_point(key, "osm", name, "business", "t", SPOT[0] + i * 2e-4, SPOT[1], brand=brand)
    w.finish({"region_id": VT, "state": "Vermont", "country": "United States"}, previous=previous)
    return str(path)


def test_brands_are_stored_once_and_read_back(tmp_path):
    """A brand is stored once (brands); points link to it; the points table keeps its version 2 columns."""
    p = pack(tmp_path / "a.osmpack", 202611, [("n1", "Made-up Burgers Main Street", ("Made-up Burgers", "Q9999901")),
                                               ("n2", "Made-up Burgers", ("Made-up Burgers", "Q9999901")),
                                               ("n3", "Pretend Park", None)])
    con = sqlite3.connect(p)
    assert con.execute("SELECT name, wikidata FROM brands").fetchall() == [("Made-up Burgers", "Q9999901")]
    assert con.execute("SELECT COUNT(*) FROM point_brands").fetchone()[0] == 2
    assert "brand" not in [r[1] for r in con.execute("PRAGMA table_info(points)")]
    con.close()
    r = Finder(packs=[PackReader(p)], water=False).lookup(*SPOT)
    assert (r.brand, r.brand_wikidata) == ("Made-up Burgers", "Q9999901")


def test_history_and_local_merge_keep_brands(tmp_path):
    """A store kept from last month keeps its brand; the downloader's local merge copies old brands across."""
    from placepacks.download import merge_local
    old = pack(tmp_path / "m1.osmpack", 202601, [("n1", "Invented Coffee", ("Invented Coffee", "Q9999902"))])
    new = pack(tmp_path / "m2.osmpack", 202611, [("n2", "Pretend Pizza", ("Pretend Pizza", ""))], previous=old)
    brands = {r["name"]: r.get("brand") for r in PackReader(new).points_near(*SPOT, 30)}
    assert brands == {"Invented Coffee": ("Invented Coffee", "Q9999902"), "Pretend Pizza": ("Pretend Pizza", "")}
    fresh = pack(tmp_path / "f.osmpack", 202611, [("n2", "Pretend Pizza", None)])
    merge_local(fresh, old)
    assert {r["name"]: r.get("brand") for r in PackReader(fresh).points_near(*SPOT, 30)}["Invented Coffee"] == (
        "Invented Coffee", "Q9999902")


def test_packs_made_before_brands_still_work(tmp_path):
    """An older pack without the brands tables reads with no brand and can be built on."""
    old = pack(tmp_path / "old.osmpack", 202601, [("n1", "Made-up Diner", ("Made-up Diner", "Q9999903"))])
    con = sqlite3.connect(old)
    con.execute("DROP TABLE brands")
    con.execute("DROP TABLE point_brands")
    con.commit()
    con.close()
    assert Finder(packs=[PackReader(old)], water=False).lookup(*SPOT).brand == ""
    new = pack(tmp_path / "new.osmpack", 202611, [("n2", "Invented Bakery", None)], previous=old)
    assert {r["name"] for r in PackReader(new).points_near(*SPOT, 30)} == {"Made-up Diner", "Invented Bakery"}


def test_brands_are_never_spoken(tmp_path):
    """The brand is data for future programs: no phrase or description uses it."""
    p = pack(tmp_path / "s.osmpack", 202611, [("n1", "Corner Store", ("Made-up Mart", "Q9999904"))])
    r = Finder(packs=[PackReader(p)], water=False).lookup(*SPOT)
    assert r.brand == "Made-up Mart"
    for detail in ("area", "street", "address"):
        assert "Made-up Mart" not in r.phrase(detail)
    import inspect
    from placepacks.lookup import Result
    for name, fn in inspect.getmembers(Result, inspect.isfunction):
        assert "self.brand" not in inspect.getsource(fn), name


def feature(spider, ref, lon, lat, **tags):
    """A made-up All The Places GeoJSON feature."""
    return {"type": "Feature", "id": f"{spider}-{ref}", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": dict({"@spider": spider, "ref": ref}, **tags)}


def test_all_the_places_run_becomes_chain_points(tmp_path):
    """A run's zip becomes one CSV of the locations in the covered boxes; individuals' offices and person names
    are left out; the tabular reader keeps each store's brand and type."""
    run = tmp_path / "run.zip"
    with zipfile.ZipFile(run, "w") as z:
        z.writestr("output/made_up_burgers.geojson", json.dumps({"type": "FeatureCollection", "features": [
            feature("made_up_burgers", "1", -71.9981, 44.0006, name="Made-up Burgers", branch="Main Street",
                    brand="Made-up Burgers", **{"brand:wikidata": "Q9999901", "amenity": "fast_food",
                                                "cuisine": "burger"}),
            feature("made_up_burgers", "2", 2.35, 48.85, name="Made-up Burgers", brand="Made-up Burgers",
                    amenity="fast_food")]}))
        z.writestr("output/pretend_insurance.geojson", json.dumps({"type": "FeatureCollection", "features": [
            feature("pretend_insurance", "7", -72.0, 44.1, name="Pretend Insurance - Alice Example",
                    office="insurance"),
            feature("pretend_insurance", "8", -72.0, 44.2, name="Alice Example", shop="gift")]}))
    out = tmp_path / "atp.csv"
    assert fetch.atp_to_csv(str(run), str(out), [(-73.5, 42.7, -71.4, 45.1)]) == 1
    entry = dict(entry_of("alltheplaces"), regions=[VT])
    w = PackWriter(str(tmp_path / "c.osmpack"), 202611)
    read_tabular(str(out), entry, dict(catalogue.regions()[VT]), w)
    w.finish({"region_id": VT, "state": "Vermont", "country": "United States"})
    rows = PackReader(str(tmp_path / "c.osmpack")).points_near(*SPOT, 30)
    assert [(r["name"], r["cls"], r["brand"]) for r in rows] == [
        ("Made-up Burgers", "business", ("Made-up Burgers", "Q9999901"))]
    assert rows[0]["type"]


def test_all_the_places_is_open_and_skips_individuals():
    """CC0, kept by region boxes, and the individuals' offices list is in place."""
    e = entry_of("alltheplaces")
    assert e["licence"] in catalogue.ALLOWED and e["licence"] == "CC0-1.0"
    assert {"insurance", "estate_agent"} <= fetch.ATP_PERSONAL["office"]
