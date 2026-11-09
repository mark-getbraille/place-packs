"""The global water and air layer (no pack needed), and the workflow's structure: the schedule, the inputs, the
token used, the order of the uploads and the keep-alive. Also the national splitter and the status file."""

import json
import os
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import samples  # noqa: E402
from placepacks import split, status  # noqa: E402
from placepacks.water import WaterLayer, distance_text, short  # noqa: E402


@pytest.fixture(scope="module")
def water():
    return WaterLayer()


def test_on_a_lake_offshore_and_the_open_ocean(water):
    """A lake by name; off a coast with the nearest town, distance and direction; the open ocean; land is not
    water."""
    lake = water.describe(44.55, -73.33)
    assert lake.kind == "water" and lake.phrase() == "on Lake Champlain" and short(lake) == "Lake Champlain"
    off = water.describe(41.20, -70.60, nearest=lambda lat, lon: ("Edgartown", 41.389, -70.513))
    assert off.kind == "water" and off.town == "Edgartown" and off.bearing == "south"
    assert off.phrase(units="both").endswith("about 14 miles (20 km) south of Edgartown")
    assert short(off) == "Off Edgartown"
    ocean = water.describe(30.0, -40.0)
    assert "Atlantic Ocean" in ocean.phrase() and short(ocean) == "The Atlantic Ocean"
    assert water.describe(39.74, -104.99) is None                     # Denver: land
    assert water.describe(41.389, -70.513) is None                    # Edgartown itself: on land (the coast margin)


def test_in_the_air(water):
    """High over the ocean; over a city; low near an airport; a mountain without altitude is not "in the air"."""
    high = water.describe(25.0, -150.0, altitude=10700)
    assert high.kind == "air" and high.phrase().startswith("in the air, about 35,000 feet (10,700 m) over the Pacific "
                                                           "Ocean, about")
    assert short(high) == "Over the Pacific Ocean"
    assert high.phrase(units="km").startswith("in the air, about 10,700 m over")
    denver = water.describe(39.74, -104.99, altitude=9000, nearest=lambda la, lo: ("Denver", 39.74, -104.99))
    assert denver.phrase() == "in the air, about 30,000 feet (9,000 m) over Denver" and short(denver) == "Over Denver"
    logan = water.describe(42.40, -71.0, altitude=600)
    assert "near Boston Logan International Airport" in logan.phrase()
    assert water.describe(39.74, -104.99, altitude=1650) is None      # standing in Denver (1,600 m up)


def test_units():
    """Miles, kilometres, both, and nautical miles."""
    assert distance_text(5000) == "about 3 miles" and distance_text(5000, "km") == "about 5 km"
    assert distance_text(5000, "both") == "about 3 miles (5 km)"
    assert distance_text(5556, "nautical") == "about 3 nautical miles"
    assert distance_text(500) == "less than a mile"


def test_the_workflow():
    """Monthly on the 2nd and by hand (regions, force, seed); only GITHUB_TOKEN; packs, then packs-previous.json,
    then packs.json; the keep-alive commit; untrusted inputs only through the environment."""
    text = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    doc = yaml.safe_load(text)
    on = doc.get("on", doc.get(True))
    assert on["schedule"][0]["cron"].split()[2] == "2"
    assert set(on["workflow_dispatch"]["inputs"]) == {"regions", "force", "seed_history"}
    assert doc["permissions"] == {"contents": "write"}
    assert "secrets." not in text and "github.token" in text
    jobs = doc["jobs"]
    assert list(jobs) == ["plan", "prepare", "build", "publish"]
    assert jobs["build"]["strategy"]["max-parallel"] <= 2 and jobs["build"]["timeout-minutes"] <= 360
    publish = "\n".join(s.get("run", "") for s in jobs["publish"]["steps"])
    a, b, c = (publish.index(x) for x in ('dist/$asset" --repo', "packs-previous.json --repo",
                                           'upload "$RELEASE_TAG" packs.json'))
    assert a < b < c and "delete-asset" in publish[c:]
    assert "sources-status.md" in publish and "git push" in publish
    for job in jobs.values():
        for step in job["steps"]:
            assert "${{ inputs" not in step.get("run", "") and "${{ matrix" not in step.get("run", "")
    ci = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8"))
    assert "pull_request" in ci.get("on", ci.get(True))


def test_split_and_status(tmp_path):
    """The NAD is split per state in one pass; the status file lists the packs."""
    from placepacks import catalogue
    nad = samples.nad_file(str(tmp_path), [("1", "A St", "X", "VT", 44.0, -72.0), ("2", "B St", "Y", "ME", 44.5, -69.5),
                                           ("3", "C St", "Z", "VT", 44.1, -72.1)])
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "nad")
    counts = split.split_tabular(entry, nad, str(tmp_path / "split"), catalogue.regions())
    assert counts == {"us-vermont": 2, "us-maine": 1}
    assert os.path.exists(tmp_path / "split" / "us-vermont" / "nad" / "nad.txt")
    text = status.status({"packs": {"us-vermont": {"size": 2_000_000, "built_month": 202611,
                                                   "history_start": 201101, "sources": {"osm": {}}}}})
    assert "| us-vermont | 2026-11 | 2.0 | 2011-01 | osm |" in text


def test_sources_md_is_up_to_date():
    """SOURCES.md is what tools/write_sources_md.py writes from sources.json."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import write_sources_md
    with open(os.path.join(ROOT, "sources.json"), encoding="utf-8") as f:
        expected = write_sources_md.text(json.load(f))
    assert open(os.path.join(ROOT, "SOURCES.md"), encoding="utf-8").read() == expected


def test_fetched_json_with_its_bounding_box_entry():
    """fetched.json carries "_bbox" (a list) beside the sources: the rebuild check and the publish step skip it (the
    first real build stopped on it)."""
    from placepacks import manifest
    fetched = {"osm": {"ok": True, "version": "2026-11-09"}, "nad": {"ok": False}, "_bbox": [-73.4, 42.7, -71.5, 45.0]}
    assert manifest.fingerprint(fetched) == {"osm": "2026-11-09"}


def test_point_shapefile_is_split_per_region(tmp_path):
    """A shapefile of points (the NCES schools) is split per state: pyshp's points have no bbox (the second real
    build stopped on it)."""
    import shapefile
    from placepacks import catalogue
    path = str(tmp_path / "schools")
    with shapefile.Writer(path, shapeType=shapefile.POINT) as w:
        w.field("NAME", "C", 40)
        w.point(-72.0, 44.0)
        w.record("Made-up School")
        w.point(-71.4, 41.8)
        w.record("Invented Academy")
    entry = {"id": "nces-schools", "countries": ["US"]}
    counts = split.split_shapes(entry, path + ".shp", str(tmp_path / "split"), catalogue.regions())
    assert counts.get("us-vermont") == 1 and counts.get("us-rhode-island") == 1
