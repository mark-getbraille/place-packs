"""The place packs: the format, each reader on its made-up sample, the history merge (renamed, closed, reopened and
moved places, stable ids and the position fallback, no deletion), the lookup by date (before the oldest data, at a
change, without a date, a date range), the layers' order, the areas, the manifest and the download."""

import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import samples  # noqa: E402
from placepacks import build, catalogue, fmt, manifest  # noqa: E402
from placepacks.lookup import Finder, PackReader, search_names  # noqa: E402
from placepacks.when import When  # noqa: E402

VT = "us-vermont"
PARK, CAFE, MAIN = (44.002, -72.002), (44.0006, -71.9981), (44.0007, -71.9990)


def fetched(**paths):
    """A fetched.json-like dict for the given source paths."""
    return {sid: {"path": str(p), "ok": True, "version": "test"} for sid, p in paths.items()}


def core(tmp_path, out, month, previous=None, cafe="Joe's Diner", street="Main Street", nad=None, removals=()):
    """Build a core pack of the made-up region."""
    work = tmp_path / f"w{month}"
    work.mkdir(exist_ok=True)
    inputs = {"osm": samples.osm_file(str(work), cafe, street)}
    if nad is not None:
        inputs["nad"] = samples.nad_file(str(work), nad)
    return build.build(VT, "core", fetched(**inputs), str(out), previous=previous, month=month,
                       removal_list=list(removals))


# ------------------------------------------------------------------------------------------- format and catalogue

def test_format_helpers():
    """Address records survive the round trip; months move and index."""
    rows = [(10, 20, 0, "120A", 202611, 202612), (9999, 1, 1, "7", 201101, 202611)]
    assert fmt.decode_addresses(fmt.encode_addresses(rows)) == rows
    assert fmt.add_months(202612, 1) == 202701 and fmt.month_from_index(fmt.month_index(202611)) == 202611
    assert fmt.parse_month("+1923-05-00T00:00:00Z") == 192305 and fmt.parse_month("x") is None


def test_the_catalogue_is_complete():
    """Every accepted source has an open licence, an attribution and its licence text; every rejection says why;
    every licence of a used source has a LICENSES file or is public domain; SOURCES.md names every source."""
    cat = catalogue.load()
    assert catalogue.check(cat) == []
    text = open(os.path.join(ROOT, "SOURCES.md"), encoding="utf-8").read()
    for e in cat["accepted"]:
        assert e["name"] in text, e["name"]
        assert e["licence"] in catalogue.ALLOWED
    for r in cat["rejected"]:
        assert r["name"] in text and r["reason"]
    assert {"Microsoft Global ML Building Footprints", "Ireland: Eircode"} <= {r["name"] for r in cat["rejected"]}
    bad = dict(cat, accepted=cat["accepted"] + [dict(cat["accepted"][0], id="nc", licence="CC-BY-NC-4.0")])
    assert any("nc" in p for p in catalogue.check(bad))


# ------------------------------------------------------------------------------------------- readers

def test_core_pack_from_osm_and_addresses(tmp_path):
    """OpenStreetMap and NAD address points in one core pack; excluded NAD states and other states are left out;
    capitals are made ordinary."""
    nad = [("120", "MAIN STREET", "TESTVILLE", "VT", 44.0007, -71.9990), ("9", "Elm St", "X", "MI", 44.0, -72.0),
           ("1", "Far Rd", "Y", "NH", 44.0, -72.0)]
    meta = core(tmp_path, tmp_path / "p.osmpack", 202611, nad=nad)
    assert meta["sources_used"].startswith("osm=") and "nad=1" in meta["sources_used"]
    p = PackReader(str(tmp_path / "p.osmpack"))
    a = p.addresses_near(*MAIN, 40)
    assert [(x["number"], x["street"], x["city"], x["source"]) for x in a] == [("120", "Main Street", "Testville",
                                                                               "nad")]
    assert p.sources["osm"]["licence"] == "ODbL-1.0" and "OpenStreetMap" in p.sources["osm"]["attribution"]
    assert "collective database" in p.meta["notice"]


def test_extra_layers(tmp_path):
    """GNIS (pipe text), TIGER address ranges (shapefile), Overture places (Parquet), Wikidata (with dates) and a
    GTFS stop, each with its source."""
    pytest.importorskip("shapefile")
    pytest.importorskip("duckdb")
    inputs = fetched(**{"gnis": samples.gnis_file(str(tmp_path)),
                        "tiger-addrfeat": samples.addrfeat_folder(str(tmp_path / "tiger")),
                        "overture-places": samples.places_parquet(str(tmp_path), [("g1", "Tony''s Pizza", "pizza",
                                                                                       44.0003, -71.9999)]),
                        "wikidata": samples.wikidata_file(str(tmp_path)), "gtfs": samples.gtfs_file(str(tmp_path))})
    meta = build.build(VT, "extra", inputs, str(tmp_path / "x.osmpack"), month=202611, removal_list=[])
    used = dict(u.split("=") for u in meta["sources_used"].split(","))
    assert used == {"tiger-addrfeat": "1", "overture-places": "1", "gnis": "2", "gtfs": "1", "wikidata": "1"}
    p = PackReader(str(tmp_path / "x.osmpack"))
    r = p.ranges_near(*MAIN, 40)[0]
    assert r["name"] == "Main St" and r["number"] == 162 and r["source"] == "tiger-addrfeat"
    mill = [x for x in p.points_near(44.0041, -71.9990, 20) if x["source"] == "wikidata"][0]
    assert (mill["first"], mill["last"]) == (192305, 199801)
    assert p.points_near(44.0004, -71.9995, 5, {"transit"})[0]["name"] == "Main St & 5th Ave"


# ------------------------------------------------------------------------------------------- history

def test_history_renamed_closed_reopened_and_moved(tmp_path):
    """Month 1: Joe's Diner. Month 2: renamed Tony's Pizza (old row closed, new row). Month 3: gone (closed).
    Month 4: Tony's Pizza is back (a new row: the gap is kept). Nothing is ever deleted."""
    p1, p2, p3, p4 = (tmp_path / f"m{i}.osmpack" for i in range(1, 5))
    core(tmp_path, p1, 202601, cafe="Joe's Diner")
    core(tmp_path, p2, 202602, previous=str(p1), cafe="Tony's Pizza")
    work = tmp_path / "w3"
    work.mkdir()
    gone = samples.osm_file(str(work)).replace("tiny", "tiny")
    text = open(gone, encoding="utf-8").read().replace('<tag k="amenity" v="cafe"/><tag k="name" v="Joe\'s Diner"/>',
                                                        "")
    open(gone, "w", encoding="utf-8").write(text)
    build.build(VT, "core", fetched(osm=gone), str(p3), previous=str(p2), month=202603, removal_list=[])
    core(tmp_path, p4, 202604, previous=str(p3), cafe="Tony's Pizza")
    rows = PackReader(str(p4))._rows("SELECT name, first, last FROM points WHERE key = 'n8' ORDER BY first")
    assert [(r["name"], r["first"], r["last"]) for r in rows] == [("Joe's Diner", 202601, 202601),
                                                                  ("Tony's Pizza", 202602, 202602),
                                                                  ("Tony's Pizza", 202604, 202604)]
    park = PackReader(str(p4))._rows("SELECT first, last FROM points WHERE key = 'n1'")
    assert park == [{"first": 202601, "last": 202604}]          # still there: one row, extended
    # No deletion: every row of month 1 is still in month 4.
    old = {(r["key"], r["name"], r["first"]) for r in PackReader(str(p1))._rows("SELECT key, name, first FROM points")}
    new = {(r["key"], r["name"], r["first"]) for r in PackReader(str(p4))._rows("SELECT key, name, first FROM points")}
    assert old <= new


def test_moved_place_and_location_fallback(tmp_path):
    """A record without a stable id is matched by position (5 m) and name; one that moved 100 m starts a new row;
    a removal (takedown) deletes the key's rows and is listed."""
    from placepacks.writer import PackWriter
    w = PackWriter(str(tmp_path / "a.osmpack"), 202601)
    w.add_point("loc:gnis:landmark:44.0000:-72.0000", "gnis", "Old Oak", "landmark", "t", 44.000049, -72.00004)
    w.add_point("k1", "gnis", "Moving Kiosk", "business", "t", 44.0, -72.0)
    w.add_point("k2", "gnis", "Private Home", "building", "t", 44.0, -72.0)
    w.finish({})
    w = PackWriter(str(tmp_path / "b.osmpack"), 202602)
    w.add_point("loc:gnis:landmark:44.0001:-72.0000", "gnis", "Old Oak", "landmark", "t", 44.000051, -72.00004)
    w.add_point("k1", "gnis", "Moving Kiosk", "business", "t", 44.001, -72.0)
    w.add_point("k2", "gnis", "Private Home", "building", "t", 44.0, -72.0)
    w.finish({}, previous=str(tmp_path / "a.osmpack"), removals=[{"key": "k2", "reason": "takedown request"}])
    p = PackReader(str(tmp_path / "b.osmpack"))
    oak = p._rows("SELECT first, last FROM points WHERE name = 'Old Oak'")
    assert oak == [{"first": 202601, "last": 202602}]
    kiosk = p._rows("SELECT first, last FROM points WHERE key = 'k1' ORDER BY first")
    assert kiosk == [{"first": 202601, "last": 202601}, {"first": 202602, "last": 202602}]
    assert p._rows("SELECT * FROM points WHERE key = 'k2'") == []
    assert p._rows("SELECT key, reason FROM removals") == [{"key": "k2", "reason": "takedown request"}]


def test_street_and_address_history(tmp_path):
    """A renamed street keeps both names; an address point on it keeps the old street name for old dates."""
    p1, p2 = tmp_path / "s1.osmpack", tmp_path / "s2.osmpack"
    core(tmp_path, p1, 201501, street="Main St", nad=[("120", "Main St", "Testville", "VT", 44.0007, -71.9990)])
    core(tmp_path, p2, 202611, previous=str(p1), street="Martin Luther King Jr. Blvd",
         nad=[("120", "Martin Luther King Jr. Blvd", "Testville", "VT", 44.0007, -71.9990)])
    f = Finder(packs=[PackReader(str(p2))], water=False)
    old = f.lookup(*MAIN, when=201506, detail="address")
    assert old.house_number == "120" and old.street == "Main St" and old.street_now == "Martin Luther King Jr. Blvd"
    assert old.phrase("address").startswith("near 120 Main St (now Martin Luther King Jr. Blvd)")
    new = f.lookup(*MAIN, when=202611, detail="address")
    assert new.street == "Martin Luther King Jr. Blvd" and not new.street_now


# ------------------------------------------------------------------------------------------- lookup by date

def months(tmp_path):
    """Packs of 2026-01 (Joe's Diner) and 2026-03 (Tony's Pizza): a change between them."""
    p1, p2 = tmp_path / "d1.osmpack", tmp_path / "d2.osmpack"
    core(tmp_path, p1, 202601, cafe="Joe's Diner")
    core(tmp_path, p2, 202603, previous=str(p1), cafe="Tony's Pizza")
    return Finder(packs=[PackReader(str(p2))], water=False)


def test_lookup_by_the_pictures_date(tmp_path):
    """The name valid then; at the change (within a month) both; before the oldest data the oldest, said so; no
    date: the newest, as listed now; a date range: every name valid in it, "probably"."""
    f = months(tmp_path)
    then = f.lookup(*CAFE, when=202601)
    assert then.name == "Joe's Diner" and then.now_name == "Tony's Pizza"
    assert "Joe's Diner (now Tony's Pizza)" in then.phrase()
    assert f.lookup(*CAFE, when=202604).name == "Tony's Pizza"
    before = f.lookup(*CAFE, when=(2005, 2006))
    assert before.name == "Joe's Diner" and before.no_older_record
    now = f.lookup(*CAFE)
    assert now.name == "Tony's Pizza" and now.as_listed_now
    span = f.lookup(*CAFE, when=(202601, 202604))
    assert span.probably and span.name == "Joe's Diner or Tony's Pizza" and span.phrase().startswith("probably")
    assert When.parse((1950, 1960)).text() == "1950 to 1960"
    import datetime
    span = When.parse((datetime.date(1955, 6, 1), datetime.datetime(1957, 2, 3, 10, 0)))
    assert (span.start, span.end, span.is_range) == (195506, 195702, True)


def test_order_of_answers_and_attribution(tmp_path):
    """In the park: the park (OpenStreetMap); by the café: the café; on Main Street off any place: the address
    point (NAD) with "near"; at street detail: the street; the details give the dates and the attributions."""
    p = tmp_path / "o.osmpack"
    core(tmp_path, p, 202611, nad=[("120", "Main Street", "Testville", "VT", 44.0007, -71.9990)])
    f = Finder(packs=[PackReader(str(p))], water=False)
    assert f.lookup(*PARK).phrase() == "at Riverside Park, Testville"
    near = f.lookup(44.00066, -71.99900, detail="address")
    assert near.kind == "address" and near.phrase("address") == "near 120 Main Street, Testville"
    assert near.source_text() == "the National Address Database"
    assert "OpenStreetMap" in f.lookup(*CAFE).details() and "2026" in f.lookup(*CAFE).details()
    cafe = f.lookup(*CAFE, detail="street")
    assert cafe.phrase() == "at Joe's Diner, Main Street, Testville" and cafe.short("street") == "Joe's Diner"


def test_areas_at_lists_every_named_area(tmp_path):
    """areas_at gives the park and the "Outer Banks" (an island chain over two towns), smallest first; a point
    in the other town is in the Outer Banks too."""
    p = tmp_path / "a.osmpack"
    core(tmp_path, p, 202611)
    f = Finder(packs=[PackReader(str(p))], water=False)
    names = [(n, c) for n, c, size, src in f.areas_at(*PARK)]
    assert names == [("Riverside Park", "park"), ("Outer Banks", "region")]
    assert [n for n, *_ in f.areas_at(44.0, -71.95)] == ["Outer Banks"]
    assert f.lookup(44.0, -71.951).town == "Nexttown"
    found = search_names("riverside", folder=str(tmp_path))
    assert found and found[0].name == "Riverside Park" and abs(found[0].latitude - 44.002) < 0.01


# ------------------------------------------------------------------------------------------- manifest and download

def test_manifest_publish_parse_and_download(tmp_path):
    """The manifest lists dated asset names and is parsed as untrusted data; the anonymous download checks size and
    SHA-256, merges with an older copy, and offers updates."""
    from placepacks import download
    built = tmp_path / "built"
    built.mkdir()
    core(tmp_path, built / "us-vermont.osmpack", 202611)
    import datetime
    m, uploads = manifest.publish("", str(built), str(tmp_path), today=datetime.date(2026, 11, 2))
    assert uploads[0][1] == "us-vermont-20261102.osmpack" and m["packs"][VT]["part"] == "core"
    data = json.dumps(m).encode()
    info = manifest.parse(data)[VT]
    for bad in (b"[]", b"x" * (manifest.LIMIT + 1), json.dumps(dict(m, format="other")).encode()):
        with pytest.raises(ValueError):
            manifest.parse(bad)
    evil = json.loads(data)
    evil["packs"][VT]["name"] = "../../x.exe"
    assert manifest.parse(json.dumps(evil).encode()) == {}
    files = {download.PUBLIC_RELEASE + "packs.json": data,
             download.PUBLIC_RELEASE + info.name: open(built / "us-vermont.osmpack", "rb").read()}
    asked = []

    def opener(url):
        return io.BytesIO(files[url])
    folder = tmp_path / "packs"
    cat = download.Catalogue(cache_path=str(folder / "packs.json"), opener=opener)
    path = download.ensure_pack(VT, folder=str(folder), catalogue=cat, ask=lambda q: asked.append(q) or True)
    assert os.path.exists(path) and "us-vermont" in asked[0]
    assert download.updates_available(str(folder), cat) == []
    files[download.PUBLIC_RELEASE + info.name] = b"tampered"
    os.remove(path)
    with pytest.raises(download.PackError):
        download.ensure_pack(VT, folder=str(folder), catalogue=cat)
    assert not os.path.exists(path)


def test_osm_reader_without_pyosmium(tmp_path):
    """A small .osm file is read with the standard library too (keys are OpenStreetMap ids)."""
    from placepacks.readers import osm as osm_reader
    from placepacks.writer import PackWriter
    w = PackWriter(str(tmp_path / "x.osmpack"), 202611)
    osm_reader.read(samples.osm_file(str(tmp_path)), {"id": "osm"}, catalogue.regions()[VT], w, use_osmium=False)
    w.finish({})
    p = PackReader(str(tmp_path / "x.osmpack"))
    assert {r["key"] for r in p._rows("SELECT key FROM points")} >= {"n1", "n8", "n9", "n15"}
    assert [r["name"] for r in p.areas_at(*PARK)] == ["Riverside Park", "Outer Banks"]


# ------------------------------------------------------------------------------------------- build diagnostics

def test_every_source_gets_a_status_line(tmp_path, capsys):
    """A build prints "source: ok (version, rows)", "source: skipped (reason)" or "source: failed (error)" for each
    source, keeps them in the pack, and sources-status.md lists them; a source read with 0 rows is a failure."""
    from placepacks import status as status_mod
    from placepacks.fetch import status_line
    nad = samples.nad_file(str(tmp_path), [("1", "A St", "X", "ME", 44.5, -69.5)])        # Maine only: 0 rows
    inputs = {"osm": {"path": samples.osm_file(str(tmp_path)), "ok": True, "status": "ok", "version": "v1"},
              "nad": {"path": nad, "ok": True, "status": "ok", "version": "r21"},
              "openaddresses": {"ok": False, "status": "skipped",
                                "reason": "needs a hand-supplied file in inputs/openaddresses/us-vermont"}}
    build.build(VT, "core", inputs, str(tmp_path / "p.osmpack"), month=202611, removal_list=[])
    out = capsys.readouterr().out
    assert "osm: ok (v1, " in out and "rows)" in out
    assert "nad: failed (read, but no rows matched" in out
    assert "openaddresses: skipped (needs a hand-supplied file in inputs/openaddresses/us-vermont)" in out
    p = PackReader(str(tmp_path / "p.osmpack"))
    st = json.loads(p.meta["source_status"])
    assert st["osm"]["status"] == "ok" and st["nad"]["status"] == "failed" and st["openaddresses"]["status"] == \
        "skipped"
    text = status_mod.status({"packs": {VT: {"size": 1, "built_month": 202611, "history_start": 202611,
                                             "sources": {}, "status": st}}})
    assert "| us-vermont | openaddresses | skipped | needs a hand-supplied file" in text
    assert status_line("x", {"status": "failed", "reason": "HTTP Error 403"}) == "x: failed (HTTP Error 403)"


def test_release_discovery_and_retries(monkeypatch):
    """The newest Overture and Foursquare releases and NAD file come from the bucket listings; a busy host is tried
    again (429, 5xx, Azure ServerBusy), a missing file (404) is not."""
    import urllib.error
    from placepacks import fetch
    listing = (b'<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
               b'<CommonPrefixes><Prefix>release/2026-09-17.0/</Prefix></CommonPrefixes>'
               b'<CommonPrefixes><Prefix>release/2026-10-22.0/</Prefix></CommonPrefixes></ListBucketResult>')
    opener = lambda url: io.BytesIO(listing)  # noqa: E731
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "overture-places")
    assert fetch.latest_release(entry, opener) == "2026-10-22.0"
    keys = (b'<ListBucketResult><Contents><Key>NAD_r19_TXT.zip</Key></Contents><Contents><Key>NAD_r21_TXT.zip'
            b'</Key></Contents><Contents><Key>NAD_r21_GDB.zip</Key></Contents></ListBucketResult>')
    assert fetch.nad_url({}, lambda url: io.BytesIO(keys)).endswith("/NAD_r21_TXT.zip")

    def refused(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b""))
    assert fetch.nad_url({"nad_release": "20"}, refused).endswith("/NAD_r20_TXT.zip")
    busy = urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(b"<Code>ServerBusy</Code>"))
    assert fetch.retryable(busy) and fetch.retryable(urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"")))
    assert not fetch.retryable(urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO(b"")))
    calls, waits = [], []

    class Answer(io.BytesIO):
        headers = {"ETag": "e1"}

    def flaky(url, *a, **k):
        calls.append(url)
        if len(calls) < 3:
            raise urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b"Egress is over the account limit"))
        return Answer(b"data")
    monkeypatch.setattr(fetch, "request", flaky)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        version, _ = fetch.download("https://x/y.zip", os.path.join(tmp, "y.zip"), sleep=waits.append)
        assert version == "e1" and len(calls) == 3 and waits == [30, 60]


def test_old_wikidata_dates_do_not_change_modern_lookups(tmp_path):
    """A pack with Wikidata rows from 1717 and businesses from 2026: a 2005 photo at the business says "no older
    record" (the business layer starts in 2026), a 2020 photo of the old building gets its name, and a building
    Wikidata says was demolished in 1998 is not named for a 2020 photo."""
    from placepacks.writer import PackWriter
    w = PackWriter(str(tmp_path / "x.osmpack"), 202611)
    w.add_point("wikidata:Q1", "wikidata", "Old Meeting House", "landmark", "t", 44.0, -72.0, 171701, None)
    w.add_point("wikidata:Q2", "wikidata", "Gone Mill", "building", "t", 44.0100, -72.0, 192305, 199801)
    w.add_point("overture-places:g1", "overture-places", "Tony's Pizza", "business", "pizza", 44.0200, -72.0)
    w.finish({"region_id": VT})
    f = Finder(packs=[PackReader(str(tmp_path / "x.osmpack"))], water=False)
    pizza = f.lookup(44.0200, -72.0, when=200506)
    assert pizza.name == "Tony's Pizza" and pizza.no_older_record and "no older record" in pizza.phrase()
    assert f.lookup(44.0, -72.0, when=202006).name == "Old Meeting House"
    assert f.lookup(44.0100, -72.0, when=202006).name == ""
    assert f.lookup(44.0100, -72.0, when=195006).name == "Gone Mill"


def test_address_range_history_is_in_the_extra_pack(tmp_path):
    """Seeded TIGER years live in the extra pack (its builds start in 2011) while the core pack starts now; the
    lookup over both packs uses the range valid in 2015 and today's street name with it."""
    pytest.importorskip("shapefile")
    seed = tmp_path / "seed.osmpack"
    build.build(VT, "extra", fetched(**{"tiger-addrfeat": samples.addrfeat_folder(str(tmp_path / "t1"),
                                                                                  name="Main St")}),
                str(seed), month=201101, only={"tiger-addrfeat"}, removal_list=[])
    extra = tmp_path / "x.osmpack"
    build.build(VT, "extra", fetched(**{"tiger-addrfeat": samples.addrfeat_folder(
        str(tmp_path / "t2"), name="Martin Luther King Jr. Blvd")}), str(extra), previous=str(seed), month=202611,
        only={"tiger-addrfeat"}, removal_list=[])
    corep = tmp_path / "c.osmpack"
    core(tmp_path, corep, 202611, street="Martin Luther King Jr. Blvd")
    packs = [PackReader(str(corep)), PackReader(str(extra))]
    assert packs[1].meta["builds"] == "201101,202611" and packs[0].meta["history_start"] == "202611"
    f = Finder(packs=packs, water=False)
    old = f.lookup(*MAIN, when=201506, detail="address")
    assert old.house_number == "162" and old.street == "Main St"
    assert old.phrase("address") == "at about 162 Main St (now Martin Luther King Jr. Blvd), Testville"
    assert f.lookup(*MAIN, when=202611, detail="address").street == "Martin Luther King Jr. Blvd"


def test_foursquare_is_split_per_region(tmp_path):
    """The prepared Foursquare slice is cut per region by its box."""
    duckdb = pytest.importorskip("duckdb")
    path = tmp_path / "fsq.parquet"
    duckdb.connect().execute(f"COPY (SELECT * FROM (VALUES ('a', 'Cafe', 44.2, -72.5), ('b', 'Bar', 43.66, -70.26)) "
                             f"t(fsq_place_id, name, latitude, longitude)) TO '{path}' (FORMAT PARQUET)")
    from placepacks import split
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "fsq-places")
    counts = split.split_parquet(entry, str(path), str(tmp_path / "out"),
                                 {k: v for k, v in catalogue.regions().items() if k in (VT, "us-maine")})
    assert counts == {VT: 1, "us-maine": 1}
