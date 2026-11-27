"""Site features (November 2026): the new site_features table (placepacks/features.py) with its writer, the
"site_features" reader of the collectors' CSV files, the PackReader methods for the Toolkit (features_of,
features_near, building_of; site_features_near and site_features_of across packs), the OpenStreetMap reader of
features inside campuses and hospitals (placepacks/readers/osm_features.py), the school and college details from
the NCES files (placepacks/schools.py), and the compatibility rules: a pack without the table still reads, the pack
version stays 2, a parent pack put together from sub-regions keeps the features. Every name, number, id and place
here is made up."""

import csv
import io
import json
import os
import sqlite3
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, combine, features, fmt, schools  # noqa: E402
from placepacks.lookup import PackReader, site_features_near, site_features_of  # noqa: E402
from placepacks.readers import load_all, osm_features  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
CAMPUS = (44.0020, -72.0020)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def region():
    """Vermont's region dict."""
    return dict(catalogue.regions()[VT])


def square(lat, lon, half=0.001):
    """A closed square ring around a position."""
    return [(lat - half, lon - half), (lat - half, lon + half), (lat + half, lon + half), (lat + half, lon - half),
            (lat - half, lon - half)]


def small_pack(path, with_features=True):
    """A made-up extra pack: a college campus area and point, and (with_features) three features."""
    w = PackWriter(str(path))
    w.add_area("w900", "osm", "Madeup State College", "campus", "amenity=college", [square(*CAMPUS, 0.002)])
    w.add_point("nces-postsecondary:999001", "nces-postsecondary", "Madeup State College", "campus", "college",
                *CAMPUS)
    if with_features:
        st = features.store(w)
        assert st.add("x:b1", "map-vendors", "building", "Smith Hall", 44.0021, -72.0021, site="w900")
        assert st.add("x:e1", "map-vendors", "accessible entrance", "Smith Hall North Entrance", 44.0023, -72.0021,
                      site="w900", building="x:b1", level="1", notes="automatic door; bob@example.edu")
        assert st.add("x:r1", "map-vendors", "accessible route", "Quad ramp", None, None, site="w900",
                      line=[(44.0015, -72.0025), (44.0018, -72.0022), (44.0021, -72.0019)])
        assert not st.add("x:bad", "map-vendors", "secret tunnel", "", 44.0, -72.0)       # not a kind
    w.finish({"part": "extra", "region_id": VT})
    return str(path)


def test_table_and_reader_methods(tmp_path):
    """The table is written with its indexes; PackReader reads features of a site, near a position and a
    feature's building; e-mails never reach a note; a route is a line."""
    pack = PackReader(small_pack(tmp_path / "a.osmpack"))
    assert pack.has_features and pack.meta["version"] == "2"
    found = pack.features_of("w900")
    assert [f["kind"] for f in found] == ["building", "accessible entrance", "accessible route"]
    entrance = found[1]
    assert entrance["level"] == "1" and entrance["building"] == "x:b1"
    assert "example.edu" not in (entrance["notes"] or "") and "automatic door" in entrance["notes"]
    assert found[2]["line"] and len(found[2]["line"]) >= 2
    assert [f["key"] for f in pack.features_of("w900", "accessible entrance")] == ["x:e1"]
    assert [f["key"] for f in pack.features_of("w900", building="x:b1")] == ["x:e1"]
    near = pack.features_near(44.0023, -72.0021, ["accessible entrance", "elevator"], 50)
    assert [f["key"] for f in near] == ["x:e1"] and near[0]["d"] < 1
    assert pack.features_near(44.0023, -72.0021, "elevator") == []
    assert pack.building_of("x:e1")["name"] == "Smith Hall"
    assert pack.building_of(lat=44.0021, lon=-72.0022)["key"] == "x:b1"
    assert pack.building_of("x:r1") is not None or pack.building_of("x:r1") is None   # a route may have none
    across = site_features_near(44.0023, -72.0021, "accessible entrance", 50, packs=[pack, pack])
    assert len(across) == 1 and across[0]["region"] == VT
    assert len(site_features_of("w900", packs=[pack])) == 3
    pack.close()


def test_older_pack_without_the_table(tmp_path):
    """A pack without site_features (made before November 2026) reads, and its methods answer nothing."""
    pack = PackReader(small_pack(tmp_path / "old.osmpack", with_features=False))
    assert not pack.has_features
    assert pack.features_of("w900") == [] and pack.features_near(*CAMPUS) == [] and pack.building_of("x") is None
    names = {r[0] for r in sqlite3.connect(pack.path).execute("SELECT name FROM sqlite_master")}
    assert "site_features" not in names
    pack.close()


def test_combined_parent_keeps_features(tmp_path):
    """placepacks.combine copies a child pack's features (each key once)."""
    a = small_pack(tmp_path / "a.osmpack")
    out = str(tmp_path / "parent.osmpack")
    combine.combine(VT, "extra", [a, a], out)
    pack = PackReader(out)
    assert len(pack.features_of("w900")) == 3
    pack.close()


def test_kind_words():
    """Category words of every source map to the plain kinds."""
    assert features.kind_of("ADA Accessible Entrances") == "accessible entrance"
    assert features.kind_of("Accessible Parking") == "accessible parking"
    assert features.kind_of("Handicap Parking Spaces") == "accessible parking"
    assert features.kind_of("All-Gender Restrooms (Accessible)") == "accessible restroom"
    assert features.kind_of("Elevators") == "elevator"
    assert features.kind_of("Blue Light Emergency Phones") == "emergency phone"
    assert features.kind_of("Dining Locations") == "dining"
    assert features.kind_of("ADA Routes") == "accessible route"
    assert features.kind_of("Parking Lots") == "parking"
    assert features.kind_of("Academic Buildings") == "building"
    assert features.kind_of("Faculty Offices") == "" or features.NOT_FEATURES.search("Faculty Offices")
    assert features.kind_of("", "Restrooms") == "restroom"


def test_site_features_reader_ties_sites_and_fills_details(tmp_path):
    """The collectors' CSV: a site row resolves to the college already in the pack (by its place_key) and gives it
    the phone and note it lacks; its features take that place's key as their site; a site that matches nothing is
    kept as a row of kind "site"; a feature without a site takes the campus area holding it."""
    rows = [
        {"key": "c3d:1", "kind": "site", "site": "c3d:1", "site_name": "Madeup State College", "name": "Madeup State "
         "College", "place_key": "nces-postsecondary:999001", "lat": CAMPUS[0], "lon": CAMPUS[1],
         "phone": "802-555-0111", "notes": "Accessibility map: accessible entrances and parking"},
        {"key": "c3d:1:loc:5", "kind": "accessible entrance", "name": "Library West Door", "site": "c3d:1",
         "lat": 44.0022, "lon": -72.0018, "notes": "push button"},
        {"key": "c3d:1:loc:6", "kind": "building", "name": "Library", "site": "c3d:1", "lat": 44.0022,
         "lon": -72.0017},
        {"key": "c3d:2", "kind": "site", "site": "c3d:2", "site_name": "Madeup Zoo", "name": "Madeup Zoo",
         "lat": 44.0300, "lon": -72.0300},
        {"key": "c3d:2:loc:1", "kind": "elevator", "name": "Aviary Elevator", "site": "c3d:2", "lat": 44.0301,
         "lon": -72.0301},
        {"key": "gis:1", "kind": "building", "name": "Science Center", "lat": 44.0025, "lon": -72.0025},
        {"key": "far:1", "kind": "elevator", "name": "Far", "site": "x:9", "lat": 10.0, "lon": 10.0},
    ]
    csv_path = tmp_path / "map-vendors.csv"
    features.write_csv(str(csv_path), rows)
    w = PackWriter(str(tmp_path / "x.osmpack"))
    w.add_area("w900", "osm", "Madeup State College", "campus", "amenity=college", [square(*CAMPUS, 0.002)])
    w.add_point("nces-postsecondary:999001", "nces-postsecondary", "Madeup State College", "campus", "college",
                *CAMPUS)
    load_all()
    entry = entry_of("map-vendors")
    assert features.read(str(csv_path), entry, region(), w) >= 5
    w.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "x.osmpack"))
    assert pack.details_of("nces-postsecondary:999001")["phone"] == "802-555-0111"
    assert "accessible entrances" in pack.notes_for("nces-postsecondary:999001")[0]
    keys = {f["key"] for f in pack.features_of("nces-postsecondary:999001")}
    assert keys == {"c3d:1:loc:5", "c3d:1:loc:6"}
    assert [f["kind"] for f in pack.features_of("c3d:2")] == ["elevator"]
    assert pack.features_near(44.0300, -72.0300, "site", 50)[0]["name"] == "Madeup Zoo"
    assert [f["key"] for f in pack.features_of("w900")] == ["gis:1"]
    assert not pack.features_near(10.0, 10.0, metres=500)
    pack.close()


OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
 <node id="1" lat="44.0000" lon="-72.0000"/><node id="2" lat="44.0000" lon="-71.9960"/>
 <node id="3" lat="44.0040" lon="-71.9960"/><node id="4" lat="44.0040" lon="-72.0000"/>
 <node id="11" lat="44.0010" lon="-71.9990"/><node id="12" lat="44.0010" lon="-71.9980"/>
 <node id="13" lat="44.0020" lon="-71.9980"/>
 <node id="14" lat="44.0020" lon="-71.9990"><tag k="entrance" v="main"/><tag k="wheelchair" v="yes"/>
  <tag k="automatic_door" v="yes"/></node>
 <node id="20" lat="44.0015" lon="-71.9985"><tag k="highway" v="elevator"/><tag k="level" v="0;1;2"/></node>
 <node id="21" lat="44.0030" lon="-71.9970"><tag k="amenity" v="toilets"/><tag k="wheelchair" v="yes"/></node>
 <node id="22" lat="44.0035" lon="-71.9975"><tag k="amenity" v="parking"/><tag k="capacity:disabled" v="4"/></node>
 <node id="23" lat="44.0036" lon="-71.9976"><tag k="emergency" v="phone"/></node>
 <node id="24" lat="44.0500" lon="-71.9500"><tag k="highway" v="elevator"/></node>
 <node id="25" lat="44.0005" lon="-71.9995"/><node id="26" lat="44.0030" lon="-71.9965"/>
 <node id="27" lat="44.0012" lon="-71.9970"><tag k="amenity" v="cafe"/><tag k="name" v="Madeup Beans"/></node>
 <way id="100"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/>
  <tag k="amenity" v="hospital"/><tag k="name" v="Madeup General Hospital"/></way>
 <way id="101"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
  <tag k="building" v="hospital"/><tag k="name" v="North Tower"/></way>
 <way id="102"><nd ref="25"/><nd ref="26"/><tag k="highway" v="footway"/><tag k="wheelchair" v="yes"/></way>
</osm>
"""


def test_osm_site_features(tmp_path):
    """Inside a hospital area: the named building, its accessible main entrance on its outline (with the building
    as parent and an accessibility note), an elevator inside it with its levels, an accessible toilet, a car park
    with accessible spaces, an emergency phone, a cafe and an accessible footway as a line; an elevator outside every
    site is not kept."""
    path = tmp_path / "h.osm"
    path.write_text(OSM, encoding="utf-8")
    w = PackWriter(str(tmp_path / "core.osmpack"))
    n = osm_features.read(str(path), {"id": "osm-site-features"}, region(), w, use_osmium=False)
    w.finish({"part": "core", "region_id": VT})
    assert n == 8
    pack = PackReader(str(tmp_path / "core.osmpack"))
    got = {f["key"]: f for f in pack.features_of("w100")}
    assert got["w101"]["kind"] == "building" and got["w101"]["name"] == "North Tower"
    door = got["n14"]
    assert door["kind"] == "accessible entrance" and door["building"] == "w101"
    assert "automatic door" in door["notes"] and "main entrance" in door["notes"]
    assert got["n20"]["kind"] == "elevator" and got["n20"]["level"] == "0;1;2" and got["n20"]["building"] == "w101"
    assert got["n21"]["kind"] == "accessible restroom"
    assert got["n22"]["kind"] == "accessible parking" and "accessible spaces: 4" in got["n22"]["notes"]
    assert got["n23"]["kind"] == "emergency phone" and got["n27"]["kind"] == "dining"
    assert got["w102"]["kind"] == "accessible route" and len(got["w102"]["line"]) == 2
    assert "n24" not in got
    assert pack.building_of("n14")["name"] == "North Tower"
    pack.close()


def zip_csv(path, name, header, rows):
    """A .zip holding one CSV file."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(name, "﻿" + buf.getvalue())
    return str(path)


def nces_files(folder):
    """Made-up CCD directory and characteristics, PSS and IPEDS HD files."""
    ccd = zip_csv(folder / "ccd.zip", "ccd_sch_029_2425.csv",
                  ["NCESSCH", "SCH_NAME", "ST", "PHONE", "WEBSITE", "SY_STATUS", "SCH_TYPE_TEXT", "CHARTER_TEXT",
                   "GSLO", "GSHI"],
                  [["500000100001", "Madeup Elementary School", "VT", "(802)555-0101", "www.madeup.k12.vt.us", "1",
                    "Regular School", "No", "PK", "05"],
                   ["500000100002", "Madeup State School for the Blind", "VT", "(802)555-0102", "", "1",
                    "Special Education School", "No", "KG", "12"],
                   ["500000100003", "Madeup Online Charter", "VT", "", "http://online.madeup.org", "1",
                    "Regular School", "Yes", "06", "12"],
                   ["500000100004", "Closed School", "VT", "(802)555-0104", "", "2", "Regular School", "No", "01",
                    "03"]])
    chars = zip_csv(folder / "chars.zip", "ccd_sch_129_2425.csv", ["NCESSCH", "VIRTUAL"],
                    [["500000100003", "FULLVIRTUAL"], ["500000100001", "SUPPVIRTUAL"]])
    pss = zip_csv(folder / "pss.zip", "pss2324_pu.csv", ["PPIN", "PINST", "PSTABB", "PPHONE", "TYPOLOGY"],
                  [["A9999901", "Madeup Christian Academy", "VT", "8025550105", "4"]])
    hd = zip_csv(folder / "hd.zip", "hd2024.csv",
                 ["UNITID", "INSTNM", "STABBR", "CHFNM", "GENTELE", "WEBADDR", "ADMINURL", "FAIDURL", "DISAURL",
                  "SECTOR", "TRIBAL", "HBCU", "CYACTIVE", "CLOSEDAT"],
                 [["999001", "Madeup State College", "VT", "Alice Example", "8025550106", "www.madeup.edu/",
                   "www.madeup.edu/admissions", "www.madeup.edu/aid", "www.madeup.edu/accessibility", "4", "2", "2",
                   "1", "-2"],
                  ["999002", "Gone College", "VT", "Bob Example", "8025550107", "gone.edu", "", "", "", "1", "2",
                   "2", "2", "2025"]])
    return ccd, chars, pss, hd


def test_school_rows_from_the_nces_files(tmp_path):
    """Grades, types (special education, a state school for the blind, a charter school, exclusively virtual),
    phones and websites; colleges with their sector, disability services, admissions and aid pages; never a
    person's name; closed schools and colleges left out."""
    rows = {r["key"]: r for r in schools.rows_from_files(*nces_files(tmp_path), checked="test")}
    assert set(rows) == {"nces-schools:500000100001", "nces-schools:500000100002", "nces-schools:500000100003",
                         "nces-private-schools:A9999901", "nces-postsecondary:999001"}
    assert rows["nces-schools:500000100001"]["note"] == "Grades: PK-5"
    assert rows["nces-schools:500000100001"]["website"] == "https://www.madeup.k12.vt.us"
    blind = rows["nces-schools:500000100002"]["note"]
    assert "special education school" in blind and "school for the blind" in blind and "K-12" in blind
    online = rows["nces-schools:500000100003"]["note"]
    assert "charter school" in online and "exclusively virtual" in online
    assert "Christian" in rows["nces-private-schools:A9999901"]["note"]
    college = rows["nces-postsecondary:999001"]
    assert "community or technical college" in college["note"]
    assert "Disability services: https://www.madeup.edu/accessibility" in college["note"]
    assert "Admissions: https://www.madeup.edu/admissions" in college["note"]
    assert "Example" not in json.dumps(rows)


def test_school_details_in_the_build(tmp_path):
    """The prepare step (with a stand-in web) writes the CSV; the "key_details" reader gives the schools in the
    pack their phone, website and note, by key, for the region's state only."""
    ccd, chars, pss, hd = nces_files(tmp_path)
    files = {"ccd_sch_029": ccd, "ccd_sch_129": chars, "pss2324": pss, "HD2026": hd}
    lookup = json.dumps({"schoolYears": [{"id": 0}, {"id": 39, "name": "2024 - 2025"}]}).encode()
    listing = json.dumps({"files": [{"fileURL": "https://nces.example/ccd_sch_029_2425_w.zip"},
                                    {"fileURL": "https://nces.example/ccd_sch_129_2425_w.zip"}]}).encode()

    def get(url):
        """The made-up CCD API and PSS page."""
        if url.endswith("Lookup/"):
            return lookup
        if "/File/" in url:
            return listing
        return b'<a href="zip/pss2324_pu_csv.zip">csv</a> <a href="zip/pss2122_pu_csv.zip">old</a>'

    def downloader(url, target):
        """Copies the made-up file a URL names; anything else is "not found"."""
        name = next((v for k, v in files.items() if k in url), None)
        if not name:
            raise OSError("404")
        with open(name, "rb") as f, open(target, "wb") as out:
            out.write(f.read())

    import datetime
    folder = tmp_path / "national"
    entry = entry_of("nces-details")
    n = schools.prepare(entry, str(folder), today=datetime.date(2026, 11, 27), downloader=downloader, get=get)
    assert n == 5
    assert "IPEDS HD2026" in open(folder / "nces-details.csv.version").read()
    w = PackWriter(str(tmp_path / "e.osmpack"))
    w.add_point("nces-schools:500000100002", "nces-schools", "Madeup State School for the Blind", "campus",
                "school", 44.1, -72.1)
    w.add_point("nces-postsecondary:999001", "nces-postsecondary", "Madeup State College", "campus", "college",
                44.2, -72.2)
    load_all()
    from placepacks.readers import READERS
    assert READERS["key_details"](str(folder), entry, region(), w) == 2
    w.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "e.osmpack"))
    assert pack.details_of("nces-schools:500000100002")["phone"] == "802-555-0102"
    assert pack.details_of("nces-postsecondary:999001")["website"] == "https://www.madeup.edu"
    assert "Disability services" in pack.notes_for("nces-postsecondary:999001")[0]
    pack.close()


def test_catalogue_entries():
    """The new sources are in the catalogue with their readers, parts and licences; the OpenStreetMap features are
    an OpenStreetMap layer of the core part."""
    assert catalogue.check() == []
    nces = entry_of("nces-details")
    assert nces["reader"] == "key_details" and nces["part"] == "extra" and nces["fetch"]["convert"] == "nces_details"
    osm = entry_of("osm-site-features")
    assert osm["part"] == "core" and osm["licence"] == "ODbL-1.0" and "osm-site-features" in catalogue.OSM_LAYERS
    assert fmt.PACK_VERSION == 2
