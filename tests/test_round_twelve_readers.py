"""The reader features added for round 12: Statistics Canada's Lambert projection, JSON and zipped XML records,
exclusion by pattern, records open by status, plain and multi-point positions, postal codes kept as written, and a
few of the new catalogue entries read from made-up fixtures. Offline."""

import csv
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, fmt, types  # noqa: E402
from placepacks.readers.tabular import parse_point, read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT, NS = "us-vermont", "ca-nova-scotia"


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def rows_of_pack(writer, table="points"):
    """(name, cls, type, first, last) of a writer's rows."""
    return writer.db.execute(f"SELECT name, cls, type, first, last FROM {table} ORDER BY name").fetchall()


def test_statcan_lambert_round_trip():
    lon, lat = fmt.to_lonlat("statcan_lambert", 4152217.914177167, 3875468.776729179)   # Dawson City hospital
    assert abs(lat - 64.0565) < 0.001 and abs(lon + 139.4337) < 0.001
    for lon, lat in ((-75.6972, 45.4215), (-63.5752, 44.6488), (-123.1207, 49.2827)):
        x, y = fmt.from_lonlat("statcan_lambert", lon, lat)
        back = fmt.to_lonlat("statcan_lambert", x, y)
        assert abs(back[0] - lon) < 1e-7 and abs(back[1] - lat) < 1e-7


def test_points_in_every_written_form():
    assert parse_point("POINT (-72 44)") == (44.0, -72.0)
    assert parse_point("MULTIPOINT ((-71.184715 48.432735))") == (48.432735, -71.184715)
    assert parse_point("(44.1, -72.2)") == (44.1, -72.2)
    assert parse_point("49.2645, -123.1345") == (49.2645, -123.1345)
    assert parse_point("1234, 5678") is None


def test_json_records_with_list_items(tmp_path):
    src = tmp_path / "h.geojson"
    src.write_text(json.dumps({"features": [{"properties": {"id": "a1", "name": "Made-up Clinic", "type": "Clinic"},
                                             "geometry": {"coordinates": [8000000.5, 1500000.25]}}]}), encoding="utf-8")
    out = tmp_path / "h.csv"
    assert fetch.json_to_csv([str(src)], {"records": "features", "fields": ["properties.id", "properties.name",
                                                                          "geometry.coordinates.0",
                                                                          "geometry.coordinates.1"]}, str(out)) == 1
    row = next(csv.DictReader(open(out, encoding="utf-8")))
    assert row == {"properties_id": "a1", "properties_name": "Made-up Clinic", "geometry_coordinates_0": "8000000.5",
                   "geometry_coordinates_1": "1500000.25"}


def test_xml_records_inside_a_zip_with_paths_and_attributes(tmp_path):
    z = tmp_path / "s.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("s.xml", "<Inventory><Sites><Site FederalSiteIdentifier='007'><Name><EN>Invented Radar Site</EN>"
                            "<FR>Site radar inventé</FR></Name><Location><Latitude>63.5</Latitude>"
                            "<Longitude>-68.5</Longitude></Location></Site></Sites></Inventory>")
    out = tmp_path / "s.csv"
    spec = entry_of("canada-contaminated-sites")["fetch"]["xml_records"]
    assert fetch.xml_to_csv([str(z)], spec, str(out)) == 1
    assert next(csv.DictReader(open(out, encoding="utf-8"))) == {
        "FederalSiteIdentifier": "007", "Name_EN": "Invented Radar Site", "Latitude": "63.5", "Longitude": "-68.5"}


def test_odbus_leaves_out_home_trades_and_the_cities_with_their_own_lists(tmp_path):
    entry = dict(entry_of("statcan-odbus"), regions=[NS])
    f = tmp_path / "ODBus_v1.csv"
    rows = [("1", "Made-up Bakery", "Retail Store (Food)", "..", "City of Halifax"),
            ("2", "Pretend Renovations", "Building Renovator", "..", "City of Halifax"),
            ("3", "Invented Suites", "7316 - Short-Term Rental - Principal Residence", "..", "City of Halifax"),
            ("4", "Fictional Cafe", "Eating Establishment", "..", "City of Calgary"),
            ("5", "Smith, John", "Office", "..", "City of Halifax")]
    with open(f, "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["idx", "business_name", "business_sector", "licence_type", "provider", "latitude", "longitude"])
        for i, (k, n, sector, lt, prov) in enumerate(rows):
            w.writerow([k, n, sector, lt, prov, 44.65 + i * 0.001, -63.58])
    wr = PackWriter(str(tmp_path / "o.osmpack"), 202611)
    read_tabular(str(f), entry, dict(catalogue.regions()[NS]), wr)
    assert [r[:3] for r in rows_of_pack(wr)] == [("Made-up Bakery", "business", "retail store (food)")]


def test_mines_open_while_active_and_closed_at_their_status_date(tmp_path):
    entry = dict(entry_of("msha-mines"), regions=[VT])
    f = tmp_path / "Mines.txt"
    f.write_text("MINE_ID|CURRENT_MINE_NAME|CURRENT_MINE_STATUS|CURRENT_STATUS_DT|LONGITUDE|LATITUDE\n"
                 '"1"|"Made-up Quarry"|"Active"|"01/22/1979"|"-72.6"|"44.2"\n'
                 '"2"|"Invented Slate Pit"|"Abandoned"|"06/30/1994"|"-73.2"|"43.5"\n', encoding="latin-1")
    wr = PackWriter(str(tmp_path / "m.osmpack"), 202611)
    read_tabular(str(f), entry, dict(catalogue.regions()[VT]), wr)
    got = {r[0]: r[3:] for r in rows_of_pack(wr)}
    assert got["Invented Slate Pit"][1] == 199406 and got["Made-up Quarry"][1] in (None, 202611)


def test_post_offices_are_dated_settlement_names(tmp_path):
    entry = dict(entry_of("us-post-offices"), regions=[VT])
    f = tmp_path / "us-post-offices.csv"
    f.write_text("Name,ID,Established,Discontinued,Latitude,Longitude\n"
                 "MADEUP CORNERS,1,1873,1896,44.2,-72.6\nINVENTED,2,1880,,44.3,-72.5\nNOWHERE,3,1890,1900,,\n",
                 encoding="utf-8")
    wr = PackWriter(str(tmp_path / "p.osmpack"), 202611)
    read_tabular(str(f), entry, dict(catalogue.regions()[VT]), wr)
    got = {r[0]: r[1:] for r in rows_of_pack(wr)}
    assert got["Madeup Corners"] == ("settlement", "post office", 187301, 189601)
    assert got["Invented"][2] == 188001 and "Nowhere" not in got


def test_postal_codes_keep_their_capitals_and_municipality_types_are_words():
    assert entry_of("statcan-fsa")["keep_case"] is True
    assert types.table("statcan_csd", "RM") == "rural municipality" and types.table("statcan_csd", "T") == "town"


def test_round_twelve_sources_are_open():
    for e in catalogue.load()["accepted"]:
        assert e["licence"] in catalogue.ALLOWED, e["id"]
    ids = {e["id"] for e in catalogue.load()["accepted"]}
    assert {"usgs-structures", "us-post-offices", "statcan-odbus", "cpcad", "ourairports", "statcan-csd"} <= ids
    assert not {"bc-parks", "ontario-parks", "parks-canada-boundaries", "ny-rest-areas"} & ids
    names = " ".join(r["name"] for r in catalogue.load()["rejected"])
    for n in ("Intercity Bus Atlas", "RIDB", "NHGIS", "MINFILE", "Abandoned Mines", "Canadian Register of Historic",
              "OSHA", "Wage and Hour", "County Business Patterns"):
        assert n in names, n
