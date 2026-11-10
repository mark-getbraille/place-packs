"""The full-build speed fixes: regions whose box crosses 180° (Alaska) as two boxes everywhere, Wikidata tiles planned
from counts, sources fetched in parallel with a time limit and per-host limits, the history merge with indexes,
county files several at a time, and the seed fingerprint. Offline: made-up fixtures only."""

import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, regions, seed, split  # noqa: E402
from placepacks.readers import parquet, wikidata  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

AK = catalogue.regions()["us-alaska"]


def test_alaska_is_two_boxes_and_never_a_band_round_the_globe():
    boxes = regions.boxes_of(AK)
    assert len(boxes) == 2 and all(w < e for w, s, e, n in boxes)
    assert sum((e - w) for w, s, e, n in boxes) < 60                     # not 359 degrees wide
    assert regions.in_region(AK, 52.93, 173.2) and regions.in_region(AK, 61.22, -149.9)   # Attu and Anchorage
    assert not regions.in_region(AK, 55.75, 37.62) and not regions.in_region(AK, 60.0, 100.0)  # Moscow, Siberia
    assert regions.regions_for(55.75, 37.62) == [] or "us-alaska" not in regions.regions_for(55.75, 37.62)
    assert regions.split_box((170.0, 50.0, -170.0, 55.0)) == [(170.0, 50.0, 180.0, 55.0), (-180.0, 50.0, -170.0, 55.0)]
    for rid, r in catalogue.regions().items():
        w, s, e, n = r["bbox"]
        assert r.get("boxes") or (e - w) < 120, rid              # any other region this wide needs its own boxes


def test_every_box_consumer_uses_the_boxes(tmp_path, monkeypatch):
    # Wikidata's tiles stay inside the boxes.
    assert all(regions.touches_region(AK, t) for t in wikidata.first_tiles(AK))
    # ArcGIS: one envelope per box.
    envelopes = []

    def fake(url, params, **kw):
        if not url.endswith("/query"):
            return {"geometryType": "esriGeometryPoint", "fields": []}
        if params.get("returnIdsOnly"):
            envelopes.append(params["geometry"])
            return {"objectIds": [len(envelopes)]}
        return {"features": []}
    monkeypatch.setattr(fetch, "post_json", fake)
    fetch.fetch_arcgis({"id": "x", "fetch": {"method": "arcgis", "url": "https://x/0", "fields": "ID"}}, AK,
                       str(tmp_path), False)
    assert len(envelopes) == 2
    # Overture's slice: one query per box.
    q = parquet.sql({"query": "SELECT * FROM '{src}' WHERE x BETWEEN {west} AND {east}"}, "a.parquet", AK)
    assert q.count("UNION ALL") == 1
    # The splitter sends an Aleutian row to Alaska and a Siberian one nowhere.
    boxes = {"us-alaska": ("US", regions.boxes_of(AK))}
    entry = {"split_box": {"lat": "lat", "lon": "lon"}}
    assert split._targets(entry, {"lat": "52.93", "lon": "173.2"}, None, boxes) == ["us-alaska"]
    assert split._targets(entry, {"lat": "60.0", "lon": "100.0"}, None, boxes) == []


def test_wikidata_tiles_are_planned_from_counts():
    asked = []

    def count(box):
        asked.append(box)
        w, s, e, n = box
        if w <= -149.9 <= e and s <= 61.2 <= n:             # the tile holding Anchorage is dense
            return 20000 if (e - w) * (n - s) > 2 else 3000
        return 0 if s > 66 else 50                          # the far north is empty, a few items elsewhere
    tiles = wikidata.plan_tiles(AK, count)
    assert tiles and len(tiles) < len(wikidata.first_tiles(AK))          # far fewer than fixed-size tiles
    assert all(count(t) != 0 for t in tiles)                             # empty tiles are left out
    assert all(count(t) <= wikidata.TILE_ITEMS for t in tiles)           # dense tiles were split
    assert "COUNT(?item)" in wikidata.count_query((-150, 61, -149, 62))


def slow_or_quick(entry, region, values, work, national, fingerprint=False):
    """A made-up fetch_source: writes when it starts and ends; the entry's "sleep" says how long it takes."""
    log = os.path.join(work, "log.txt")
    with open(log, "a") as f:
        f.write(f"{entry['id']} start {time.time()} {entry['fetch']['url']}\n")
    time.sleep(entry["sleep"])
    with open(log, "a") as f:
        f.write(f"{entry['id']} end {time.time()} {entry['fetch']['url']}\n")
    return {"ok": True, "version": "v", "path": ""}


def test_sources_run_in_parallel_with_a_time_limit_and_per_host_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_source", slow_or_quick)
    entries = [{"id": f"s{i}", "sleep": 0.6, "fetch": {"method": "http", "url": f"https://host{i % 2}.example/f"}}
               for i in range(6)]
    entries.append({"id": "hangs", "sleep": 30, "time_limit_min": 0.02,
                    "fetch": {"method": "http", "url": "https://slow.example/f"}})
    t = time.time()
    got = dict((e["id"], r) for e, r in fetch.run_parallel(entries, AK, catalogue.load(), str(tmp_path), None,
                                                           False, workers=4))
    took = time.time() - t
    assert got["hangs"]["status"] == "failed" and got["hangs"]["reason"].startswith("took longer than")
    assert all(got[f"s{i}"]["ok"] for i in range(6))
    assert took < 6                                         # not 6 x 0.6 s + 30 s one after the other
    events = []
    for line in open(tmp_path / "log.txt"):
        sid, what, when, url = line.split()
        events.append((float(when), what, url))
    running, most = {}, {}
    for when, what, url in sorted(events):
        running[url] = running.get(url, 0) + (1 if what == "start" else -1)
        most[url] = max(most.get(url, 0), running[url])
    assert max(most.values()) <= fetch.HOST_LIMIT
    assert fetch.host_of({"fetch": {"url": "https://query.wikidata.org/sparql"}}) == "query.wikidata.org"
    assert fetch.HOST_LIMITS["query.wikidata.org"] == 1


def ranges(path, month, n, previous=None):
    """A pack of n address ranges (the same keys every month)."""
    w = PackWriter(str(path), month)
    for i in range(n):
        lat = 44 + i * 1e-4
        w.add_range(f"r{i}", "tiger", f"Made-up Street {i % 50}", 1, 99, 2, 100, "05401",
                    [(lat, -72.0), (lat + 1e-4, -72.0)])
    w.finish({"region_id": "us-vermont", "state": "Vermont", "country": "United States"}, previous=previous)
    return str(path)


def test_the_history_merge_is_fast_and_leaves_no_build_index(tmp_path):
    old = ranges(tmp_path / "a.osmpack", 201101, 20000)
    t = time.time()
    new = ranges(tmp_path / "b.osmpack", 201601, 20000, previous=old)
    assert time.time() - t < 30                             # it was quadratic: minutes for this many
    con = sqlite3.connect(new)
    assert con.execute("SELECT COUNT(*), MIN(first) FROM ranges").fetchone() == (20000, 201101)
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")]
    assert not [n for n in names if n.endswith("_merge_key")]


def test_the_seed_fingerprint_follows_years_and_sources():
    cat = catalogue.load()
    a = seed.fingerprint(cat)
    other = json.loads(json.dumps(cat))
    other["settings"]["tiger_seed_years"] = ["2011"]
    assert seed.fingerprint(other) != a and len(a) == 12 and a == seed.fingerprint(cat)
    assert cat["settings"]["tiger_seed_years"] == ["2011", "2016", "2021"]
    workflow = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert "placepacks.seed fingerprint" in workflow and "gh release download seeds" in workflow


def test_county_files_are_downloaded_several_at_a_time(tmp_path, monkeypatch):
    import threading
    active, most, lock = [0], [0], threading.Lock()

    class Listing:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return "".join(f'<a href="tl_2016_50{i:03d}_addrfeat.zip">' for i in range(1, 25)).encode()

    def fake_download(url, target, pause=0, **kw):
        with lock:
            active[0] += 1
            most[0] = max(most[0], active[0])
        time.sleep(0.05)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "wb").close()
        with lock:
            active[0] -= 1
        return "v", ""
    monkeypatch.setattr(fetch, "request", lambda *a, **k: Listing())
    monkeypatch.setattr(fetch, "download", fake_download)
    entry = json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == "tiger-addrfeat")))
    values = dict(catalogue.settings_for(catalogue.load(), catalogue.regions()["us-vermont"]), tiger_year="2016")
    got = fetch.fetch_source(entry, catalogue.regions()["us-vermont"], values, str(tmp_path), None)
    assert got["ok"] and len(os.listdir(tmp_path / "tiger-addrfeat")) == 24 and 1 < most[0] <= 8
