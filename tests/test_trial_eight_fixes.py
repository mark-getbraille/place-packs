"""The fixes after trial #8: the NAD's Deflate64 zip read through unzip/7z, ArcGIS servers that refuse heavy
geometry, Wikidata tiles that time out, the Newberry's longer retries, a region that simply has none of a source's
rows ("ok (0 in this region)") and four-digit years. Offline: made-up fixtures only."""

import json
import os
import shutil
import sys
import urllib.error

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import build, catalogue, fetch, fmt, split, status  # noqa: E402
from placepacks.readers.tabular import open_texts  # noqa: E402

VT = "us-vermont"
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sample_deflate64.zip")
HAVE_EXTRACTOR = bool(shutil.which("unzip") or shutil.which("7z"))


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


@pytest.mark.skipif(not HAVE_EXTRACTOR, reason="neither unzip nor 7z is installed")
def test_a_deflate64_zip_is_read_and_split_through_an_extractor(tmp_path):
    import zipfile
    with zipfile.ZipFile(FIXTURE) as z:
        assert z.infolist()[0].compress_type == 9                   # Deflate64: zipfile alone cannot read it
    lines = [line for text in open_texts(FIXTURE, "*.txt") for line in text]
    assert len(lines) == 401 and lines[1].startswith("0,,100,Madeup,Street,Testville,VT")
    folder = tmp_path / "nad"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / "NAD_r20_TXT.zip")
    assert fetch.repair_zip(str(folder / "NAD_r20_TXT.zip")) is False     # left as it is, not "repaired"
    entry = dict(entry_of("nad"), member="*.txt")
    counts = split.split_tabular(entry, str(folder), str(tmp_path / "out"), catalogue.regions())
    assert counts == {VT: 400}


def test_a_heavy_geometry_refusal_is_retried_in_halves_with_simpler_shapes(monkeypatch, tmp_path):
    calls = []

    def fake(url, params, **kw):
        if not url.endswith("/query"):
            return {"geometryType": "esriGeometryPolygon", "fields": []}
        if params.get("returnIdsOnly"):
            return {"objectIds": [1, 2, 3, 4]}
        ids = params["objectIds"].split(",")
        calls.append((ids, params.get("maxAllowableOffset"), params.get("geometryPrecision")))
        if len(ids) > 1:
            raise ValueError("ArcGIS error: Unable to perform operation. Too many large geometry non-cacheable "
                             "requests.")
        ring = [[-72.0, 44.0], [-71.99, 44.0], [-71.99, 44.01], [-72.0, 44.0]]
        return {"features": [{"attributes": {"ID": i, "NAME": f"Invented Refuge {i}"}, "geometry": {"rings": [ring]}}
                             for i in ids]}
    monkeypatch.setattr(fetch, "post_json", fake)
    entry = {"id": "made-up-padus", "fetch": {"method": "arcgis", "url": "https://x/FeatureServer/0", "fields": "ID,NAME",
                                              "page": 4, "simplify": 0.0005}}
    got = fetch.fetch_arcgis(entry, catalogue.regions()[VT], str(tmp_path), False, sleep=lambda s: None)
    rows = open(got["path"], encoding="utf-8").read().splitlines()
    assert len(rows) == 5
    assert calls[0][0] == ["1", "2", "3", "4"] and calls[0][1] == 0.0005 and calls[0][2] == 6
    assert all(c[1] > 0.0005 for c in calls[1:])                   # simpler geometry after the refusal
    assert sorted(i for ids, _, _ in calls if len(ids) == 1 for i in ids) == ["1", "2", "3", "4"]


def test_a_wikidata_504_splits_the_tile_and_a_failing_smallest_tile_is_left_out():
    asked = []

    def ask(query):
        asked.append(query)
        if len(asked) == 1:
            raise urllib.error.HTTPError("https://query.wikidata.org/sparql", 504, "Gateway Timeout", {}, None)
        return [{"item": {"value": "Q1"}}]
    rows = fetch.wikidata_tiles(ask, [(-4.0, 51.5, -3.0, 52.5)], limit=10)          # a Welsh tile
    assert len(asked) == 5 and len(rows) == 4

    def always_fails(query):
        raise TimeoutError("504")
    with pytest.raises(ValueError):
        fetch.wikidata_tiles(always_fails, [(-4.0, 51.5, -3.98, 51.52)], limit=10)
    calls = []

    def one_tile_fails(query):
        calls.append(query)
        if len(calls) == 2:
            raise TimeoutError("504")
        return [{"item": {"value": "Q2"}}]
    from placepacks.readers import wikidata
    tiles = [(-4.0, 51.5, -3.99, 51.51), (-3.99, 51.5, -3.98, 51.51)]
    assert len(fetch.wikidata_tiles(one_tile_fails, tiles, limit=10)) == 1           # one left out, one kept
    assert wikidata.MIN_TILE >= 0.01


def test_every_wikidata_source_uses_tiles_in_every_country():
    for e in catalogue.load()["accepted"]:
        if e["fetch"]["method"] == "wikidata":
            assert e["fetch"].get("mode", "all") in ("all", "labels", "filming"), e["id"]
    src = open(os.path.join(ROOT, "placepacks", "fetch.py"), encoding="utf-8").read()
    assert 'f.get("mode", "all") == "all"' in src and "wd.class_query(box, g)" in src


def test_the_newberry_has_longer_retries(monkeypatch, tmp_path):
    seen = {}

    def fake_download(url, target, pause=0, waits=fetch.RETRY_WAITS, sleep=None):
        seen["waits"] = waits
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(b"not a zip")
        return "v1", "2026-11-10"
    monkeypatch.setattr(fetch, "download", fake_download)
    entry = entry_of("newberry-counties")
    fetch.prepare_national(entry, str(tmp_path), {})
    assert seen["waits"] == (60, 180, 600, 1200)
    workflow = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert "national/newberry-counties" in workflow and "command -v unzip" in workflow


def test_a_region_with_none_of_a_national_source_is_ok_and_a_column_mismatch_fails(tmp_path):
    out = tmp_path / "split"
    entry = entry_of("va-national-cemeteries")
    split.mark_empty(dict(entry, countries=["US"], regions=None), str(out), {VT: catalogue.regions()[VT]},
                     {"us-new-york": 3})
    assert open(out / VT / entry["id"] / split.EMPTY).read().strip() == "3"
    assert build.empty_reason(entry, str(out / VT / entry["id"])) == ""
    good = tmp_path / "good.csv"
    cols = sorted(c for c in split.needed_columns(entry) or [] if not c.startswith("_"))
    good.write_text(",".join(cols + ["_lat", "_lon"]) + "\n", encoding="utf-8")
    assert build.empty_reason(entry, str(good)) == ""
    bad = tmp_path / "bad.csv"
    bad.write_text("something,else\n1,2\n", encoding="utf-8")
    assert build.empty_reason(entry, str(bad)).startswith("missing columns:")
    assert fetch.status_line("va-national-cemeteries", {"status": "ok", "rows": 0, "note": "0 in this region",
                                                        "version": "v"}) == \
        "va-national-cemeteries: ok (v, 0 in this region)"


def test_years_before_1000_have_four_digits():
    assert fmt.month_label(5501) == "0055-01" and fmt.month_label(202611) == "2026-11"
    from placepacks.lookup import month_text
    from placepacks.when import When
    assert month_text(5501) == "January 0055"
    assert When.parse((55, 60)).text() == "0055 to 0060"
    text = status.status({"packs": {"gb-wales-extra": {"built_month": 202611, "history_start": 5501, "size": 1}}})
    assert "| 0055-01 |" in text
