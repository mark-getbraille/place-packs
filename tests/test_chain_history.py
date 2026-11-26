"""The All The Places history seed (placepacks.atp_history): first and last months from archived runs, one a quarter,
and the monthly build merging the seed. Offline: made-up runs in the real archives' formats (a .tar.gz of
output/<spider>.geojson before November 2022, a .zip since), "downloaded" by copying local files."""

import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from placepacks import atp_history, catalogue, fetch  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
BOX = [(-73.5, 42.7, -71.4, 45.1)]
LAT, LON = 44.0006, -71.9981


def feature(spider, ref, dlat, **tags):
    """A made-up All The Places feature, dlat degrees north of the test spot."""
    return {"type": "Feature", "id": f"{spider}-{ref}", "geometry": {"type": "Point",
                                                                    "coordinates": [LON, round(LAT + dlat, 6)]},
            "properties": dict({"@spider": spider, "ref": ref}, **tags)}


def write_run(path, spiders):
    """A run archive at path: .tar.gz (the old runs) or .zip (the new ones), one GeoJSON file per spider."""
    files = {f"output/{s}.geojson": json.dumps({"type": "FeatureCollection", "features": feats}).encode()
             for s, feats in spiders.items()}
    if str(path).endswith(".zip"):
        with zipfile.ZipFile(path, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
    else:
        with tarfile.open(path, "w:gz") as t:
            for name, data in files.items():
                info = tarfile.TarInfo("./" + name)
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return str(path)


# Four made-up quarters. Stores (spider "made_up_mart" unless said):
#   1 "Made-up Mart" in every quarter (still open);
#   2 in 2018 and 2019 only (closed at 201901);
#   3 "Old-Time Diner" in 2018, renamed "New-Time Diner" from 2019;
#   4 missing in 2019 (a failed spider), back in 2020: one record, not closed;
#   5 listed without a name in 2018, named from 2019;
#   the spider "fake_grocer" renamed "pretend_grocer" in 2020 with new references: the same store found by its
#   brand at the same position (the fallback);
#   "pretend_agents" lists an individual's office in 2020 (tagged office=insurance), untagged in 2018: left out.
def runs(tmp_path):
    """{run id: archive path} of the made-up quarters, and the archive's list of runs (history.json)."""
    mart = dict(brand="Made-up Mart", shop="convenience")
    q = {
        "2018-04-25-00-20-03": {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart"),
                                                 feature("made_up_mart", "2", 0.001, name="Made-up Mart"),
                                                 feature("made_up_mart", "3", 0.002, name="Old-Time Diner"),
                                                 feature("made_up_mart", "4", 0.003, name="Made-up Mart"),
                                                 feature("made_up_mart", "5", 0.004)],
                                "fake_grocer": [feature("fake_grocer", "77", 0.005, name="Fake-Mart Grocer")],
                                "pretend_agents": [feature("pretend_agents", "9", 0.006, name="Pretend-Co Agency")]},
        "2019-01-09-03-36-01": {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart"),
                                                 feature("made_up_mart", "2", 0.001, name="Made-up Mart"),
                                                 feature("made_up_mart", "3", 0.002, name="New-Time Diner"),
                                                 feature("made_up_mart", "5", 0.004, name="Made-up Mart")],
                                "fake_grocer": [feature("fake_grocer", "77", 0.005, name="Fake-Mart Grocer")]},
        "2020-01-29-14-39-55": {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart", **mart),
                                                 feature("made_up_mart", "3", 0.002, name="New-Time Diner"),
                                                 feature("made_up_mart", "4", 0.003, name="Made-up Mart", **mart),
                                                 feature("made_up_mart", "5", 0.004, name="Made-up Mart", **mart)],
                                "pretend_grocer": [feature("pretend_grocer", "store-77", 0.00502, name="Fake-Mart Grocer",
                                                           brand="Fake-Mart Grocer", shop="supermarket")],
                                "pretend_agents": [feature("pretend_agents", "9", 0.006, name="Pretend-Co Agency",
                                                           office="insurance")]},
        "2022-11-26-13-31-55": {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart", **mart),
                                                 feature("made_up_mart", "3", 0.002, name="New-Time Diner"),
                                                 feature("made_up_mart", "4", 0.003, name="Made-up Mart", **mart),
                                                 feature("made_up_mart", "5", 0.004, name="Made-up Mart", **mart)],
                                "pretend_grocer": [feature("pretend_grocer", "store-77", 0.00502, name="Fake-Mart Grocer",
                                                           brand="Fake-Mart Grocer", shop="supermarket")]},
    }
    paths, history = {}, []
    for rid, spiders in q.items():
        ext = ".zip" if rid >= "2022-11" else ".tar.gz"
        paths[rid] = write_run(tmp_path / f"{rid}{ext}", spiders)
        url = f"https://alltheplaces-data.openaddresses.io/runs/{rid}/output{ext}"
        history.append({"run_id": rid, "output_url": url, "size_bytes": os.path.getsize(paths[rid])})
    return paths, history


def copier(paths):
    """A stand-in for fetch.download that copies the made-up archive of the run named in the address."""
    def download(url, target):
        shutil.copy(paths[url.split("/runs/")[1].split("/")[0]], target)
    return download


def records(seed_dir):
    """The seed's rows as {(key, name): (first, last)}."""
    manifest = json.load(open(os.path.join(seed_dir, atp_history.MANIFEST)))
    out = {}
    import gzip
    for name in manifest["files"]:
        with gzip.open(os.path.join(seed_dir, name), "rt", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[(r["key"], r["name"])] = (int(r["first"]), int(r["last"]))
    return out


def make_seed(tmp_path, split=False):
    """The seed of the made-up quarters, read as one group (or two, then combined)."""
    tmp_path = tmp_path / ("two-jobs" if split else "one-job")
    tmp_path.mkdir()
    paths, history = runs(tmp_path)
    ids = sorted(paths)
    groups = [ids[:2], ids[2:]] if split else [ids]
    states = []
    for i, group in enumerate(groups):
        state = str(tmp_path / f"state-{i + 1}.sqlite")
        atp_history.read_runs(group, state, scratch=str(tmp_path), history=history, boxes=BOX,
                              download=copier(paths))
        states.append(state)
    out = tmp_path / ("seed-split" if split else "seed")
    atp_history.combine(states, str(out), scratch=str(tmp_path))
    return str(out)


def test_quarterly_runs_are_picked_and_grouped():
    """One run a quarter (the largest, from the archive's hosts only, none without a file), cut into groups of at
    most the byte limit, oldest first."""
    history = [{"run_id": "2017-12-14-02-01-04"},                                    # listed, no file
               {"run_id": "2018-04-25-00-20-03", "output_url": "https://alltheplaces-data.openaddresses.io/runs/"
                "2018-04-25-00-20-03/output.tar.gz", "size_bytes": 30},
               {"run_id": "2018-05-02-00-20-03", "output_url": "https://alltheplaces-data.openaddresses.io/runs/"
                "2018-05-02-00-20-03/output.tar.gz", "size_bytes": 40},
               {"run_id": "2018-07-26-14-05-48", "output_url": "https://example.com/elsewhere.zip", "size_bytes": 99},
               {"run_id": "2026-10-03-13-32-35", "output_url": "https://alltheplaces-data.openaddresses.io/runs/"
                "2026-10-03-13-32-35/output.zip", "size_bytes": 2700}]
    import datetime
    picked = atp_history.pick_quarterly(history, 2017, today=datetime.date(2026, 11, 26))
    assert [r["run_id"] for r in picked] == ["2018-05-02-00-20-03", "2026-10-03-13-32-35"]
    assert atp_history.groups(picked, 1000) == [{"group": 1, "runs": "2018-05-02-00-20-03", "bytes": 40},
                                                {"group": 2, "runs": "2026-10-03-13-32-35", "bytes": 2700}]
    assert len(atp_history.groups(picked, 10_000)) == 1


def test_old_and_new_archives_read_alike(tmp_path):
    """A .tar.gz of 2018 and a .zip of 2022 give the same rows (fetch.iter_atp), and a cut-off spider file is read
    line by line instead of stopping the run."""
    spiders = {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart")]}
    a = list(fetch.iter_atp(write_run(tmp_path / "a.tar.gz", spiders), BOX))
    b = list(fetch.iter_atp(write_run(tmp_path / "b.zip", spiders), BOX))
    assert a == b and a[0]["key"] == "made_up_mart:1" and a[0]["skip"] == ""
    broken = tmp_path / "c.zip"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("output/x.geojson", '{"type":"FeatureCollection","features":[\n'
                   + json.dumps(feature("x", "1", 0, name="Made-up Mart")) + ",\n{\"type\": \"Feat")
        z.writestr("output/empty.geojson", "")
    assert [r["key"] for r in fetch.iter_atp(str(broken), BOX)] == ["x:1"]
    # A damaged feature (a 2025 run had a geometry written as text) is skipped, the rest is read.
    damaged = tmp_path / "d.zip"
    with zipfile.ZipFile(damaged, "w") as z:
        z.writestr("output/y.geojson", json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": "POINT (0 0)", "properties": {"@spider": "y", "ref": "9"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": "broken"},
            feature("y", "2", 0, name="Made-up Mart")]}))
    assert [r["key"] for r in fetch.iter_atp(str(damaged), BOX)] == ["y:2"]


def test_first_and_last_months_across_quarters(tmp_path):
    """Every rule of the module docstring on the made-up quarters."""
    got = records(make_seed(tmp_path))
    assert got[("made_up_mart:1", "Made-up Mart")] == (201804, 202211)            # open all along
    assert got[("made_up_mart:2", "Made-up Mart")] == (201804, 201901)            # closed at its last quarter
    assert got[("made_up_mart:3", "Old-Time Diner")] == (201804, 201804)               # renamed: the old name closes
    assert got[("made_up_mart:3", "New-Time Diner")] == (201901, 202211)
    assert got[("made_up_mart:4", "Made-up Mart")] == (201804, 202211)            # a missing quarter: continues
    assert got[("made_up_mart:5", "Made-up Mart")] == (201804, 202211)            # nameless in 2018 still counts
    # The fallback: the new spider's new reference carries on the old store (same name, same rounded position).
    assert got[("pretend_grocer:store-77", "Fake-Mart Grocer")] == (201804, 202211)
    assert not any(k.startswith("fake_grocer:") for k, _ in got)
    # An individual's office: the whole spider is left out, even its untagged 2018 rows.
    assert not any(k.startswith("pretend_agents:") for k, _ in got)


def test_groups_combined_give_the_same_seed(tmp_path):
    """Reading the quarters in two jobs and combining them gives the same seed as one job (the fallback and the
    closings work across the groups)."""
    assert records(make_seed(tmp_path)) == records(make_seed(tmp_path, split=True))


def test_the_monthly_build_merges_the_seed(tmp_path):
    """The latest run's CSV with the seed applied: listed stores get the seed's first month, closed stores come
    back closed; the packs built from it month after month keep those months and add no duplicate rows."""
    seed = make_seed(tmp_path)
    entry = json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == "alltheplaces")))
    entry["regions"] = [VT]
    region = dict(catalogue.regions()[VT])

    def month_pack(month, spiders, previous=None):
        """A businesses pack of month from a made-up latest run with the seed applied (prepare, then build)."""
        target = tmp_path / f"atp-{month}.csv"
        fetch.atp_to_csv(write_run(tmp_path / f"latest-{month}.zip", spiders), str(target), BOX)
        assert atp_history.apply(str(target), seed) is not None
        w = PackWriter(str(tmp_path / f"b-{month}.osmpack"), month)
        read_tabular(str(target), entry, region, w)
        w.finish({"region_id": VT, "state": "Vermont", "country": "United States"}, previous=previous)
        con = sqlite3.connect(str(tmp_path / f"b-{month}.osmpack"))
        rows = sorted(con.execute("SELECT key, name, first, last FROM points"))
        con.close()
        return str(tmp_path / f"b-{month}.osmpack"), rows

    mart = dict(brand="Made-up Mart", shop="convenience")
    latest = {"made_up_mart": [feature("made_up_mart", "1", 0, name="Made-up Mart", **mart),
                               feature("made_up_mart", "3", 0.002, name="New-Time Diner"),
                               feature("made_up_mart", "9", 0.007, name="Made-up Mart", **mart)]}
    first_pack, rows = month_pack(202612, latest)
    k = "alltheplaces:"
    assert rows == [
        (k + "made_up_mart:1", "Made-up Mart", 201804, 202612),          # still listed: its first month from 2018
        (k + "made_up_mart:2", "Made-up Mart", 201804, 201901),          # closed in 2019
        (k + "made_up_mart:3", "New-Time Diner", 201901, 202612),
        (k + "made_up_mart:3", "Old-Time Diner", 201804, 201804),
        (k + "made_up_mart:4", "Made-up Mart", 201804, 202211),          # no longer listed: closed at its last quarter
        (k + "made_up_mart:5", "Made-up Mart", 201804, 202211),
        (k + "made_up_mart:9", "Made-up Mart", 202612, 202612),          # new this month
        (k + "pretend_grocer:store-77", "Fake-Mart Grocer", 201804, 202211)]
    # The next month, with the same seed applied again: nothing doubles, the open stores move on.
    _, again = month_pack(202701, latest, previous=first_pack)
    assert again == [(key, name, first, 202701 if last == 202612 else last) for key, name, first, last in rows]


def test_no_seed_leaves_the_csv_as_it_was(tmp_path):
    """Without a seed (none made yet, or PLACEPACKS_ATP_HISTORY unset) the latest run is used as before."""
    target = tmp_path / "atp.csv"
    fetch.atp_to_csv(write_run(tmp_path / "r.zip", {"m": [feature("m", "1", 0, name="Made-up Mart")]}),
                     str(target), BOX)
    before = target.read_text()
    assert atp_history.apply(str(target), str(tmp_path / "nothing")) is None
    assert atp_history.apply(str(target), "") is None
    assert target.read_text() == before


def test_the_workflow_seeds_once_and_the_monthly_prepare_reads_the_seed():
    """seed_chain_history: plan, one read job per group (read-only, one archive at a time on /mnt), one store job
    (the only one that writes, uploading the list last); every prepare job downloads the stored seed and points the
    All The Places conversion at it; inputs and matrix values only through the environment."""
    import yaml
    root = os.path.join(os.path.dirname(__file__), "..")
    text = open(os.path.join(root, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    jobs = yaml.safe_load(text)["jobs"]
    assert jobs["chain-plan"]["if"] == "${{ inputs.seed_chain_history }}"
    assert jobs["chain-read"]["strategy"]["matrix"]["group"] == "${{ fromJSON(needs.chain-plan.outputs.groups) }}"
    assert jobs["chain-read"]["timeout-minutes"] <= 360 and jobs["chain-store"]["timeout-minutes"] <= 360
    read = "\n".join(s.get("run", "") for s in jobs["chain-read"]["steps"])
    assert "atp_history read" in read and "/mnt/scratch" in read and '"$RUNS"' in read
    store = "\n".join(s.get("run", "") for s in jobs["chain-store"]["steps"])
    assert "atp_history combine" in store and "gh release upload seeds" in store
    assert store.index("chain-history.json; do") < store.index("delete-asset")    # the list last, old files after
    assert "chain-store" in jobs["prepare"]["needs"] and "always()" in jobs["prepare"]["if"]
    prepare = "\n".join(s.get("run", "") for s in jobs["prepare"]["steps"])
    assert "PLACEPACKS_ATP_HISTORY" in prepare and "--pattern chain-history.json" in prepare
    assert prepare.index("PLACEPACKS_ATP_HISTORY") < prepare.index("fetch --prepare")
    for job in ("chain-plan", "chain-read", "chain-store"):
        for step in jobs[job]["steps"]:
            assert "${{ inputs" not in step.get("run", "") and "${{ matrix" not in step.get("run", "")
