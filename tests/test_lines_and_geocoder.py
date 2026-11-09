"""Named lines (trails, rivers) and the offline address geocoder: a photo near a trail is "on the X Trail" when
nothing nearer names it, streets stay streets; addresses of address-only sources (the IRS's exempt organizations)
are located against the region's NAD points, a home address is put on its street (not at the house), post office
boxes are left out, and the "in care of" names are never read. Every name and place here is made up."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fmt, geocode, types  # noqa: E402
from placepacks.lookup import Finder, PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def test_trails_and_rivers_name_a_place_when_nothing_nearer_does(tmp_path):
    """A trail line read from the arcgis fetch's paths; a photo 20 m from it is "on the ... Trail", one beside a
    river "beside the ..."; a street nearby still wins (it is a street, not a trail)."""
    region = dict(catalogue.regions()[VT])
    (tmp_path / "t.csv").write_text(
        "trail_cn,trail_name,_lat,_lon,_paths\n"
        'T1,MADEUP RIDGE TRAIL,44.0,-72.01,"[[[44.0,-72.01],[44.0,-71.99]]]"\n', encoding="utf-8")
    pack = tmp_path / "x.osmpack"
    w = PackWriter(str(pack), 202611)
    assert read_tabular(str(tmp_path / "t.csv"), entry_of("usfs-trails"), region, w) == 1
    w.add_line("wsr:1:0", "wild-scenic-rivers", "Invented River", "water", "river", [(44.1, -72.01), (44.1, -71.99)])
    w.add_line("osm:w9", "osm", "Pretend Road", "street", "highway=residential", [(44.2, -72.01), (44.2, -71.99)])
    w.add_line("usfs:2:0", "usfs-trails", "Other Trail", "trail", "trail", [(44.2002, -72.01), (44.2002, -71.99)])
    w.finish({"region_id": VT})
    f = Finder(packs=[PackReader(str(pack))], water=False)
    trail = f.lookup(44.0002, -72.0)
    assert (trail.line, trail.line_cls) == ("Madeup Ridge Trail", "trail")
    assert trail.phrase() == "on the Madeup Ridge Trail" and trail.short() == "Madeup Ridge Trail"
    assert f.lookup(44.1002, -72.0).phrase() == "beside the Invented River"
    street = f.lookup(44.2001, -72.0)
    assert street.street == "Pretend Road" and not street.line


def test_addresses_are_split_and_normalised():
    """House number and street; units dropped; post office boxes and rural routes cannot be located."""
    assert geocode.split_address("123 North Main Street, Apt 4") == ("123", "N MAIN ST")
    assert geocode.split_address("12-14 Elm Ave.") == ("12", "ELM AVE")
    assert geocode.split_address("PO BOX 455") is None and geocode.split_address("RR 2 Box 7") is None
    assert geocode.zip5("05089-0455") == "05089"


def nad_slice(folder):
    """A NAD-like slice: two business addresses and one home on Madeup St, in ZIP 05000."""
    path = folder / "nad.txt"
    path.write_text("AddNo_Full,StNam_Full,Post_City,Inc_Muni,State,Zip_Code,Addr_Type,Latitude,Longitude\n"
                    "10,MADEUP ST,Testville,,VT,05000,Commercial,44.0001,-72.0001\n"
                    "12,MADEUP ST,Testville,,VT,05000,Residential,44.0003,-72.0003\n"
                    "14,MADEUP ST,Testville,,VT,05000,Commercial,44.0005,-72.0005\n"
                    "5,INVENTED RD,Testville,,VT,05000,Unknown,44.0100,-72.0100\n", encoding="utf-8")
    return str(path)


def test_the_geocoder_matches_by_zip_or_city_and_puts_homes_on_the_street(tmp_path):
    """Matched with the ZIP, else the city; a home is put at the middle of the street's points; the match line."""
    nad = entry_of("nad")
    found = geocode.locate([("10 Madeup Street", "Testville", "05000-1234"), ("12 Madeup St", "", "05000"),
                            ("5 Invented Road", "Testville", ""), ("PO Box 9", "Testville", "05000"),
                            ("99 Nowhere Ln", "Testville", "05000")], nad_slice(tmp_path), nad)
    assert found[0] == (44.0001, -72.0001, "address") and found[2] == (44.01, -72.01, "address")
    lat, lon, how = found[1]
    assert how == "street" and abs(lat - 44.0003) < 1e-9 and abs(lon + 72.0003) < 1e-9   # the street's middle
    assert set(found) == {0, 1, 2}
    assert geocode.stats(found, 5) == "located 3 of 5 addresses (60%): 2 at the address, 1 on the street (homes)"


def test_exempt_organizations_are_located_typed_and_never_name_people(tmp_path, capsys):
    """The IRS file: located against the NAD slice, typed by NTEE, dated by the ruling month; the "in care of"
    column (a person) is never kept; a post office box is left out; the match rate is printed."""
    region = dict(catalogue.regions()[VT])
    region["_inputs"] = {"nad": nad_slice(tmp_path)}
    (tmp_path / "eo.csv").write_text(
        "EIN,NAME,ICO,STREET,CITY,STATE,ZIP,SUBSECTION,RULING,NTEE_CD\n"
        "1,FIRST MADEUP CHURCH,% JANE DOE,14 MADEUP ST,TESTVILLE,VT,05000-0001,03,195301,X21\n"
        "2,INVENTED HISTORY MUSEUM,% JOHN ROE,5 INVENTED RD,TESTVILLE,VT,05000,03,198807,A54\n"
        "3,PRETEND GARDEN CLUB,% ANN POE,12 MADEUP ST,TESTVILLE,VT,05000,03,200102,C42\n"
        "4,FICTIONAL FUND,% BOB COE,PO BOX 1,TESTVILLE,VT,05000,03,201005,T20\n", encoding="utf-8")
    w = PackWriter(str(tmp_path / "i.osmpack"), 202611)
    assert read_tabular(str(tmp_path / "eo.csv"), entry_of("irs-exempt-organizations"), region, w) == 3
    rows = sorted(w.db.execute("SELECT name, cls, type, first FROM points").fetchall())
    assert rows == [("First Madeup Church", "landmark", "protestant church", 195301),
                    ("Invented History Museum", "landmark", "history museum", 198807),
                    ("Pretend Garden Club", "public", "garden club", 200102)]
    everything = " ".join(str(v) for r in w.db.execute("SELECT * FROM points").fetchall() for v in r)
    assert "DOE" not in everything.upper() and "ROE" not in everything.upper()
    assert "located 3 of 4 addresses (75%): 2 at the address, 1 on the street (homes)" in capsys.readouterr().out
    assert types.ntee("X22") == "catholic church" and fmt.parse_month("195301") == 195301


def test_public_buildings_and_malls_from_osm():
    """Town halls, courthouses, police and fire stations and post offices are public places; a named retail area
    (a mall) is kept."""
    for kind in ("townhall", "courthouse", "police", "fire_station", "post_office"):
        assert fmt.classify("amenity", kind) == "public", kind
    from placepacks.readers.osm import main_tag
    assert main_tag({"landuse": "retail", "name": "Madeup Mall"}) == ("landuse", "retail", "business")
    assert types.osm({"shop": "mall"}) == "shopping mall"


def test_gnis_variant_names_are_searchable_but_never_spoken(tmp_path):
    """A made-up GNIS GeoPackage: a lake's variant name is kept (class variant, searchable) and never said as the
    place's name; a historical feature keeps its "(historical)" name."""
    import sqlite3
    import zipfile
    from placepacks.lookup import search_names
    from placepacks.readers.sqlite_query import read as read_sqlite
    db = tmp_path / "Gazetteer_VT_GPKG.gpkg"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE Gaz_Names (fid INTEGER, feature_id INTEGER, feature_name TEXT, feature_name_official INTEGER);
        CREATE TABLE Gaz_Features (feature_id INTEGER, feature_class TEXT, prim_lat_dec REAL, prim_long_dec REAL);
        CREATE TABLE HistoricalFeatures (feature_id INTEGER, feature_name TEXT, feature_class TEXT,
                                         prim_lat_dec REAL, prim_long_dec REAL);
        INSERT INTO Gaz_Names VALUES (1, 10, 'Madeup Lake', 1), (2, 10, 'Old Pretend Pond', 2);
        INSERT INTO Gaz_Features VALUES (10, 'Lake', 44.0, -72.0);
        INSERT INTO HistoricalFeatures VALUES (20, 'Invented Mill (historical)', 'Locale', 44.01, -72.0);
    """)
    con.commit()
    con.close()
    with zipfile.ZipFile(tmp_path / "g.zip", "w") as z:
        z.write(db, db.name)
    folder = tmp_path / "packs"
    folder.mkdir()
    pack = folder / "us-vermont-extra.osmpack"
    w = PackWriter(str(pack), 202611)
    assert read_sqlite(str(tmp_path / "g.zip"), entry_of("gnis-variant-names"), dict(catalogue.regions()[VT]), w) == 2
    w.add_point("gnis:10", "gnis", "Madeup Lake", "water", "t", 44.0, -72.0)
    w.finish({"region_id": VT})
    reader = PackReader(str(pack))
    assert Finder(packs=[reader], water=False).lookup(44.0, -72.0).name == "Madeup Lake"
    found = search_names("Old Pretend", folder=str(folder))
    assert [(r.name, r.cls, r.type) for r in found] == [("Old Pretend Pond", "variant", "variant name of Madeup Lake")]
    assert [r.name for r in search_names("Invented Mill", folder=str(folder))] == ["Invented Mill (historical)"]


def test_several_arcgis_layers_make_one_source(monkeypatch, tmp_path):
    """The battlefields of three wars come from three layers, fetched into one CSV."""
    from placepacks import fetch
    calls = []

    def answer(url, params, **kw):
        calls.append(url)
        if not url.endswith("/query"):
            return {"geometryType": "esriGeometryPoint", "fields": []}
        if params.get("returnIdsOnly"):
            return {"objectIds": [1]}
        war = url.split("/")[-2]
        return {"features": [{"attributes": {"SITE": f"S{war}", "NAME": f"MADEUP {war}"},
                              "geometry": {"x": -72.0, "y": 44.0}}]}
    monkeypatch.setattr(fetch, "post_json", answer)
    entry = {"id": "made-up", "fetch": {"method": "arcgis", "urls": ["https://x/1", "https://x/6"], "fields": "SITE,NAME"}}
    got = fetch.fetch_arcgis(entry, catalogue.regions()[VT], str(tmp_path), False)
    assert open(got["path"], encoding="utf-8").read().splitlines() == [
        "SITE,NAME,_lat,_lon", "S1,MADEUP 1,44.000000,-72.000000", "S6,MADEUP 6,44.000000,-72.000000"]
