"""The fixes for the source failures of the first full build: huge polygon fields in CSV, cut-off zips, ArcGIS id
queries that fail on a big state's box, servers that refuse heavy pages or a single record, pages in parallel,
Foursquare reported as skipped, FDIC's Oregon filter, ODA's regions and Wikidata's shared tile plan. Offline."""

import csv
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def test_a_polygon_field_larger_than_ten_megabytes_is_read(tmp_path):
    ring = [[50.0 + i * 1e-6, -97.0 - i * 1e-6] for i in range(450000)] + [[50.0, -97.0]]
    rings = json.dumps([ring])
    assert len(rings) > 10_000_000
    path = tmp_path / "csd.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["CSDUID", "CSDNAME", "CSDTYPE", "_lat", "_lon", "_rings"])
        w.writerow(["4611040", "Made-up Rural Municipality", "RM", "50.1", "-97.1", rings])
    entry = dict(entry_of("statcan-csd"), regions=["ca-manitoba"])
    wr = PackWriter(str(tmp_path / "c.osmpack"), 202611)
    assert read_tabular(str(path), entry, dict(catalogue.regions()["ca-manitoba"]), wr) == 1


class Answer(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status, self.headers = status, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_cut_off_zip_is_downloaded_again(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ROADSEG.dbf", "made-up " * 500)
    whole, calls = buf.getvalue(), []

    def answer(url, *a, headers=None, **k):
        calls.append(headers)
        return Answer(whole[:200] if len(calls) == 1 else whole)
    monkeypatch.setattr(fetch, "request", answer)
    target = str(tmp_path / "nrn.zip")
    fetch.download("https://x/nrn.zip", target, sleep=lambda s: None)
    assert len(calls) == 2 and zipfile.is_zipfile(target)
    html_calls = []

    def html(url, *a, headers=None, **k):
        html_calls.append(1)
        return Answer(b"<html>busy</html>" if len(html_calls) == 1 else whole)
    monkeypatch.setattr(fetch, "request", html)
    fetch.download("https://x/canvec.zip", str(tmp_path / "c.zip"), sleep=lambda s: None)
    assert len(html_calls) == 2


def test_an_id_query_that_fails_on_a_big_box_is_asked_in_quarters():
    asked = []

    def fake(url, params, **kw):
        asked.append(params["geometry"])
        w, s, e, n = (float(v) for v in params["geometry"].split(","))
        if (e - w) > 7:
            raise ValueError("ArcGIS error: ")              # the empty error of a big state's query
        return {"objectIds": [int(w * 10) * 1000 + int(s * 10)]}
    old = fetch.post_json
    fetch.post_json = fake
    try:
        ids = fetch.arcgis_ids("https://x/0", {"geometry": "-106,25,-93,37"}, (-106, 25, -93, 37), lambda s: None,
                               "made-up")
    finally:
        fetch.post_json = old
    assert len(ids) == 4 and len(asked) == 5


def test_busy_pages_are_split_and_a_single_refused_record_is_left_out(monkeypatch, tmp_path):
    calls = []

    def fake(url, params, **kw):
        if not url.endswith("/query"):
            return {"geometryType": "esriGeometryPoint", "fields": []}
        if params.get("returnIdsOnly"):
            return {"objectIds": list(range(1, 9))}
        ids = params["objectIds"].split(",")
        calls.append(ids)
        if "5" in ids:
            raise ValueError("ArcGIS error: Unable to perform query. Too many requests.")
        return {"features": [{"attributes": {"ID": int(i), "NAME": f"Made-up Area {i}"}, "geometry": {"x": -72,
                                                                                                    "y": 44}}
                             for i in ids]}
    monkeypatch.setattr(fetch, "post_json", fake)
    entry = {"id": "made-up", "fetch": {"method": "arcgis", "url": "https://x/0", "fields": "ID,NAME", "page": 4,
                                        "parallel": 2}}
    got = fetch.fetch_arcgis(entry, catalogue.regions()["us-vermont"], str(tmp_path), False, sleep=lambda s: None)
    rows = list(csv.DictReader(open(got["path"], encoding="utf-8")))
    assert [r["ID"] for r in rows] == ["1", "2", "3", "4", "6", "7", "8"]       # in order, record 5 left out
    assert fetch.arcgis_busy(ValueError("ArcGIS error:")) and not fetch.arcgis_busy(ValueError("ArcGIS error: no "
                                                                                                "such field"))


def test_catalogue_fixes():
    assert "%22{code}%22" in entry_of("fdic-branches")["fetch"]["url"]          # STALP:"OR" (OR is a keyword)
    oda = entry_of("oda")
    assert {"ca-newfoundland-and-labrador", "ca-nunavut", "ca-yukon"}.isdisjoint(oda["regions"])
    assert "no longer publishes" in entry_of("fsq-places")["unavailable_reason"]
    for sid, at_least in (("nhd-named-flowlines", 120), ("nhd-named-waterbodies", 60), ("wikidata", 90),
                          ("padus", 60)):
        assert entry_of(sid)["time_limit_min"] >= at_least, sid
    assert entry_of("nhd-named-flowlines")["fetch"]["parallel"] >= 2


def test_foursquare_without_a_release_is_skipped(monkeypatch):
    def none(entry, opener=None):
        raise ValueError("no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com")
    monkeypatch.setattr(fetch, "latest_release", none)
    entry = entry_of("fsq-places")
    region = catalogue.regions()["us-vermont"]
    got = fetch._fetch_one(entry, region, catalogue.load(), "work", None, False)
    assert got["status"] == "skipped" and got["reason"].startswith("Foursquare no longer publishes")


def test_the_wikidata_tile_plan_is_shared_by_the_region_sources():
    src = open(os.path.join(ROOT, "placepacks", "fetch.py"), encoding="utf-8").read()
    assert "_wikidata_tiles.json" in src


def test_a_shape_across_180_degrees_is_kept_only_where_its_parts_are(tmp_path):
    import shapefile
    import sqlite3
    from placepacks.readers.shapes import read as read_shapes
    from placepacks.writer import merge_history

    def box(w, s, e, n):
        return [[w, s], [w, n], [e, n], [e, s], [w, s]]
    base = str(tmp_path / "ne")
    with shapefile.Writer(base, shapeType=shapefile.POLYGON) as w:
        for f in ("NAME_EN", "WIKIDATAID", "FEATURECLA"):
            w.field(f, "C", 40)
        w.poly([box(178.0, -18.0, 179.9, -16.0), box(-172.0, -14.0, -171.0, -13.0)])        # a made-up "Polynesia"
        w.record("Made-up Ocean Islands", "Q1", "Island group")
        w.poly([box(-100.0, 30.0, -99.0, 31.0), box(-99.8, 30.2, -99.6, 30.4), box(-150.0, 60.0, -149.0, 61.0)])
        w.record("Made-up Plain", "Q2", "Plain")                                           # Texas, a hole, Alaska
    entry = entry_of("natural-earth-regions")
    texas = catalogue.regions()["us-texas"]
    path = str(tmp_path / "t.osmpack")
    wr = PackWriter(path, 202611)
    assert read_shapes(base + ".shp", entry, texas, wr) == 1
    wr.finish({"region_id": "us-texas", "state": "Texas", "country": "United States"})
    db = sqlite3.connect(path)
    (name, minlon, maxlon), = db.execute("SELECT name, minlon, maxlon FROM areas").fetchall()
    assert name == "Made-up Plain" and (minlon, maxlon) == (-100_000_000, -99_000_000)
    assert db.execute("SELECT count(*) FROM grid WHERE what = 'a'").fetchone()[0] <= 121     # one degree of fine cells
    db.close()
    # Last month's pack still held the islands across 180°: not carried forward as history.
    prev = str(tmp_path / "prev.osmpack")
    old = PackWriter(prev, 202610)
    old.add_area("Q1", "natural-earth-regions", "Made-up Ocean Islands", "region", "region",
                 [[(-18, 178), (-16, 178), (-16, 179.9), (-18, 179.9), (-18, 178)],
                  [(-14, -172), (-13, -172), (-13, -171), (-14, -171), (-14, -172)]])
    old.finish({"region_id": "us-texas", "state": "Texas", "country": "United States"})
    now = PackWriter(str(tmp_path / "n.osmpack"), 202611)
    now.add_area("Q2", "natural-earth-regions", "Made-up Plain", "region", "region",
                 [[(30, -100), (31, -100), (31, -99), (30, -99), (30, -100)]])
    merge_history(now.db, prev, 202611)
    assert [r[0] for r in now.db.execute("SELECT name FROM areas")] == ["Made-up Plain"]
