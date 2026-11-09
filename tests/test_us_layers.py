"""The US layers read from public services without a hand step: the arcgis fetch (ids in the region's box, then
records in chunks; dates, points and polygon rings), the newest yearly file from a listing page (NCES, IMLS), the
repair of a .zip with shifted offsets (the Newberry atlas), names made from several columns (bridges), areas from
rings (PAD-US, military installations), dated county versions and the county on a picture's date. Every name and
place here is made up."""

import io
import json
import os
import struct
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


class FakeArcGIS:
    """Answers post_json like an ArcGIS layer: metadata, ids in the box, then features by ids."""

    def __init__(self, geometry_type, features, fields):
        self.geometry_type, self.features, self.fields, self.calls = geometry_type, features, fields, []

    def __call__(self, url, params, **kw):
        self.calls.append((url, dict(params)))
        if not url.endswith("/query"):
            return {"geometryType": self.geometry_type, "editingInfo": {"lastEditDate": 1700000000000},
                    "fields": self.fields}
        if params.get("returnIdsOnly"):
            return {"objectIds": [3, 1, 2]}
        wanted = {int(x) for x in params["objectIds"].split(",")}
        return {"features": [f for i, f in self.features.items() if i in wanted]}


def test_arcgis_points_in_the_box_with_dates(monkeypatch, tmp_path):
    """The ids are asked inside the region's box with the entry's filter; records come in chunks of ids; dates in
    milliseconds become YYYY-MM-DD; the version is the last edit date and the number of records."""
    feats = {i: {"attributes": {"ID": f"D{i}", "NAME": f"Invented Dam {i}", "BUILT": -1262304000000},
                 "geometry": {"x": -72.0 - i / 100, "y": 44.0}} for i in (1, 2, 3)}
    fake = FakeArcGIS("esriGeometryPoint", feats, [{"name": "BUILT", "type": "esriFieldTypeDate"}])
    monkeypatch.setattr(fetch, "post_json", fake)
    entry = {"id": "made-up-dams", "fetch": {"method": "arcgis", "url": "https://x/FeatureServer/0", "fields":
                                             "ID,NAME,BUILT", "where": "NAME IS NOT NULL", "page": 2}}
    region = catalogue.regions()[VT]
    got = fetch.fetch_arcgis(entry, region, str(tmp_path), False)
    assert got["ok"] and got["version"] == "1700000000000:3 records"
    ids_call = fake.calls[1][1]
    assert ids_call["where"] == "NAME IS NOT NULL" and ids_call["geometryType"] == "esriGeometryEnvelope"
    assert ids_call["geometry"] == ",".join(str(v) for v in region["bbox"])
    assert [c[1]["objectIds"] for c in fake.calls[2:]] == ["1,2", "3"]
    lines = open(got["path"], encoding="utf-8").read().splitlines()
    assert lines[0] == "ID,NAME,BUILT,_lat,_lon" and lines[1] == "D1,Invented Dam 1,1930-01-01,44.000000,-72.010000"
    assert fetch.fetch_arcgis(entry, region, str(tmp_path), True)["version"] == "1700000000000:3 records"


def test_arcgis_polygons_become_areas(monkeypatch, tmp_path):
    """A polygon layer is written with its rings and read as named areas (PAD-US, military installations)."""
    ring = [[-72.01, 44.0], [-72.0, 44.0], [-72.0, 44.01], [-72.01, 44.01], [-72.01, 44.0]]
    feats = {1: {"attributes": {"Source_PAID": "P1", "Unit_Nm": "Madeup State Forest", "Des_Tp": "SF",
                                "Date_Est": "1931"}, "geometry": {"rings": [ring]}}}
    monkeypatch.setattr(fetch, "post_json", FakeArcGIS("esriGeometryPolygon", feats, []))
    entry = entry_of("padus")
    got = fetch.fetch_arcgis(entry, catalogue.regions()[VT], str(tmp_path), False)
    w = PackWriter(str(tmp_path / "a.osmpack"), 202611)
    assert read_tabular(got["path"], entry, dict(catalogue.regions()[VT]), w) == 1
    assert w.db.execute("SELECT name, cls, first, last FROM areas").fetchall() == [
        ("Madeup State Forest", "park", 193101, 202611)]


def test_a_table_without_shapes_is_not_asked_for_a_box(monkeypatch, tmp_path):
    """A layer without geometry (DC's licences) is filtered by "where" only; its own columns give the position."""
    fake = FakeArcGIS(None, {1: {"attributes": {"CUSTOMERNUMBER": "1", "ENTITYTRADENAME": "Invented Deli",
                                                "LATITUDE": 38.9, "LONGITUDE": -77.0}}}, [])
    monkeypatch.setattr(fetch, "post_json", fake)
    entry = entry_of("dc-business-licences")
    fetch.fetch_arcgis(entry, catalogue.regions()["us-district-of-columbia"], str(tmp_path), False)
    assert "geometry" not in fake.calls[1][1] and fake.calls[2][1]["returnGeometry"] == "false"


def test_bridge_names_are_made_from_what_they_carry_and_cross(tmp_path):
    """The bridge inventory has no names: "<carried> bridge over <crossed>", without the HWY and WATER codes; a
    bridge without one of them is left out; the year built is its first month."""
    entry = entry_of("nbi-bridges")
    (tmp_path / "b.csv").write_text(
        "STATE_CODE_001,STRUCTURE_NUMBER_008,FACILITY_CARRIED_007,FEATURES_DESC_006A,YEAR_BUILT_027,_lat,_lon\n"
        "50,B1,HWY   INVENTED RD,WATER MADEUP RIVER,1932,44.0,-72.0\n"
        "50,B2,'PRETEND ST',,1950,44.001,-72.0\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "b.osmpack"), 202611)
    assert read_tabular(str(tmp_path / "b.csv"), entry, dict(catalogue.regions()[VT]), w) == 1
    assert w.db.execute("SELECT key, name, first FROM points").fetchall() == [
        ("nbi-bridges:50 B1", "Invented Rd bridge over Madeup River", 193201)]
    dams = entry_of("nid-dams")
    (tmp_path / "d.csv").write_text("nidId,name,yearCompleted,_lat,_lon\nVT1,MADEUP POND DAM,1925,44.0,-72.0\n"
                                    "VT2,Invented Lake,0,44.1,-72.0\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "d.osmpack"), 202611)
    read_tabular(str(tmp_path / "d.csv"), dams, dict(catalogue.regions()[VT]), w)
    assert sorted(w.db.execute("SELECT name, first FROM points").fetchall()) == [
        ("Invented Lake Dam", 202611), ("Madeup Pond Dam", 192501)]


def test_the_newest_yearly_file_is_taken_from_the_listing():
    """NCES and IMLS rename their files every year: the listing's newest one is downloaded."""
    page = ('<a href="/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_15_16.zip">'
            '<a href="/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2324.zip">'
            '<a href="/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_1920.zip">').encode()
    files = fetch.national_files(entry_of("nces-private-schools"), {}, lambda url: io.BytesIO(page))
    assert files == [("https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PRIVATESCH_2324.zip",
                      "EDGE_GEOCODE_PRIVATESCH_2324.zip", None)]
    page = (b'<a href="/sites/default/files/2025-08/pls_fy2023_csv.zip"><a href="/sites/default/files/2026-06/'
            b'pls_fy2024_csv.zip"><a href="/sites/default/files/2026-06/pls_fy2024_sas.zip">')
    url, name, _ = fetch.national_files(entry_of("imls-libraries"), {}, lambda u: io.BytesIO(page))[0]
    assert url == "https://www.imls.gov/sites/default/files/2026-06/pls_fy2024_csv.zip" and name == "pls_fy2024_csv.zip"


def test_a_zip_with_shifted_offsets_is_repaired(tmp_path):
    """A .zip whose central directory points 100 bytes past each member (as the Newberry atlas's does) is rewritten
    so that Python and pyshp can read it; a good .zip is left alone."""
    path = tmp_path / "shifted.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("folder/a.txt", "made-up county data\n" * 50)
        z.writestr("folder/b.txt", "more\n")
    data = bytearray(path.read_bytes())
    at = data.find(b"PK\x01\x02")
    while at >= 0:
        offset = struct.unpack_from("<I", data, at + 42)[0]
        struct.pack_into("<I", data, at + 42, offset + 100)
        at = data.find(b"PK\x01\x02", at + 4)
    path.write_bytes(bytes(data))
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(path).read("folder/a.txt")
    assert fetch.repair_zip(str(path)) is True
    assert zipfile.ZipFile(path).read("folder/a.txt").startswith(b"made-up county data")
    assert fetch.repair_zip(str(path)) is False


def test_counties_have_their_dates_and_the_lookup_uses_the_pictures_date(tmp_path):
    """Each version of a county is an area with its own dates (the atlas ends in 2000: its last versions are
    current); a lookup gives the county as it was on the picture's date."""
    shapefile = pytest.importorskip("shapefile")
    import datetime
    base = str(tmp_path / "counties")
    with shapefile.Writer(base, shapeType=shapefile.POLYGON) as w:
        for name in ("ID_NUM", "NAME", "CNTY_TYPE"):
            w.field(name, "C", 40)
        w.field("START_DATE", "D")
        w.field("END_DATE", "D")
        square = [[[-72.1, 43.9], [-71.9, 43.9], [-71.9, 44.1], [-72.1, 44.1], [-72.1, 43.9]]]
        w.poly(square)
        w.record("1", "OLD MADEUP", "County", datetime.date(1781, 2, 16), datetime.date(1810, 10, 31))
        w.poly(square)
        w.record("2", "INVENTED", "County", datetime.date(1810, 11, 1), datetime.date(2000, 12, 31))
    from placepacks.readers.shapes import read as read_shapes
    entry = entry_of("newberry-counties")
    pack = tmp_path / "c.osmpack"
    w = PackWriter(str(pack), 202611)
    assert read_shapes(base + ".shp", entry, dict(catalogue.regions()[VT]), w) == 2
    w.finish({"region_id": VT, "state": "Vermont", "country": "United States"})
    rows = sorted(PackReader(str(pack))._rows("SELECT name, first, last FROM areas"), key=lambda r: r["first"])
    assert [(r["name"], r["first"], r["last"]) for r in rows] == [("Old Madeup County", 178102, 181010),
                                                                  ("Invented County", 181011, 202611)]
    f = Finder(packs=[PackReader(str(pack))], water=False)
    assert f.lookup(44.0, -72.0, when=180006).county == "Old Madeup County"
    assert f.lookup(44.0, -72.0, when=199006).county == "Invented County"
    assert f.lookup(44.0, -72.0).county == "Invented County"


def test_the_hand_supplied_us_sources_are_automatic_now():
    """NRHP, PAD-US, FAA airports, Amtrak stations and IMLS libraries no longer need a hand-supplied file."""
    for sid in ("nrhp", "padus", "faa-airports", "ntad-amtrak", "imls-libraries"):
        assert entry_of(sid)["fetch"]["method"] != "manual", sid


# ------------------------------------------------------------------------------------------- dated areas


def county_pack(path):
    """A pack with two versions of a made-up county over one square: Old County 1790-01 to 1850-12, New County
    from 1851-01 on (still current), and a town that kept its name."""
    square = [(43.9, -72.1), (43.9, -71.9), (44.1, -71.9), (44.1, -72.1), (43.9, -72.1)]
    w = PackWriter(str(path), 202611)
    w.add_area("newberry-counties:1", "newberry-counties", "Old County", "county", "county", [square], 179001, 185012)
    w.add_area("newberry-counties:2", "newberry-counties", "New County", "county", "county", [square], 185101, None)
    w.add_area("census-places:1", "census-places", "Madeupton", "town", "census-places",
               [[(43.99, -72.01), (43.99, -71.99), (44.01, -71.99), (44.01, -72.01), (43.99, -72.01)]])
    w.finish({"region_id": VT, "state": "Vermont", "country": "United States"})
    return str(path)


def test_areas_at_and_lookup_keep_only_the_county_of_the_date(tmp_path):
    """An undated picture gets only the current county (as lookup() does for undated pictures); 1820 the old one;
    2005 the new one; the writer never stores an open end as None."""
    pack = county_pack(tmp_path / "c.osmpack")
    reader = PackReader(pack)
    assert all(r["last"] is not None for r in reader._rows("SELECT last FROM areas"))
    f = Finder(packs=[reader], water=False)
    names = lambda when: [a[0] for a in f.areas_at(44.0, -72.0, when=when) if a[1] == "county"]  # noqa: E731
    assert names(None) == ["New County"]
    assert names("1820-05-01") == ["Old County"]
    assert names("2005-07-04") == ["New County"]
    assert f.lookup(44.0, -72.0).county == "New County"
    assert f.lookup(44.0, -72.0, when="1820-05-01").county == "Old County"
    assert f.lookup(44.0, -72.0, when="2005-07-04").county == "New County"
    assert f.lookup(44.0, -72.0, when="1820-05-01").town == "Madeupton"     # no older record: the oldest is kept


def test_choose_is_safe_without_builds_and_with_an_open_end():
    """choose, valid and until accept builds=None, and a row without a last month (None) counts as current."""
    from placepacks.lookup import choose, until, valid
    from placepacks.when import When
    row = {"name": "Old County", "first": 179001, "last": 185012}
    assert choose([row], When.parse("1820-05-01"), 202611, 162901, None)[0] == [row]
    assert choose([row], When.parse("1900-05-01"), 202611, 162901, None)[0] == []
    still = {"name": "New County", "first": 185101, "last": None}
    assert choose([row, still], When.parse(None), 202611, 162901, None)[0] == [still]
    assert valid(185101, None, When.parse("2005-07-04"), 202611, None) and until(None, 202611, None) == 999912
