"""The services part (placepacks/services.py, readers/services.py, local.py): offices and services from
OpenStreetMap, the NWS county and forecast zones and the NOAA Weather Radio county coverage list, with the lookups
"the nearest Social Security office" and "my NOAA Weather Radio frequency". Offline: made-up samples only."""

import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
import samples  # noqa: E402
from placepacks import build, catalogue, download, fetch, fmt, services  # noqa: E402
from placepacks.local import LocalServices, kind_of  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.readers.services import parse_ccl  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
HERE = (44.0000, -72.0000)


@pytest.fixture()
def pack(tmp_path):
    """The made-up services pack of Vermont."""
    fetched = {"osm-services": {"ok": True, "path": samples.svc_osm_file(str(tmp_path))},
               "nws-counties": {"ok": True, "path": samples.nws_folder(str(tmp_path / "c"), "county")},
               "nws-zones": {"ok": True, "path": samples.nws_folder(str(tmp_path / "z"), "zone")},
               "noaa-weather-radio": {"ok": True, "path": samples.nwr_file(str(tmp_path / "nwr"))}}
    out = str(tmp_path / "us-vermont-services.osmpack")
    build.build(VT, "services", fetched, out, removal_list=[])
    return out


def test_the_services_part_and_its_sources_are_in_the_catalogue():
    cat = catalogue.load()
    assert "services" in fmt.PARTS and catalogue.check(cat) == []
    ids = {e["id"]: e for e in catalogue.sources_for(catalogue.regions()[VT], "services", cat)}
    assert set(ids) == {"osm-services", "nws-counties", "nws-zones", "noaa-weather-radio", "cpi-polling-places"}
    assert ids["osm-services"]["licence"] == "ODbL-1.0" and ids["noaa-weather-radio"]["licence"] == "US-Government-Work"
    assert set(catalogue.sources_for(catalogue.regions()["ca-prince-edward-island"], "services", cat)[i]["id"]
               for i in range(1)) == {"osm-services"}
    rejected = " ".join(r["name"] for r in cat["rejected"])
    for name in ("Social Security", "VA Facilities", "FindTreatment", "211", "FEMA", "Feeding America"):
        assert name in rejected
    assert download.parts_for("services") == ("core", "extra", "services")
    assert build.previous_files(VT, "services", "/nowhere") == []


def test_nws_file_dates_pick_the_newest():
    assert fetch.nws_date("16ap26") == 20260416 and fetch.nws_date("18mr25") == 20250318 and fetch.nws_date("x") == -1
    entry = next(e for e in catalogue.load()["accepted"] if e["id"] == "nws-counties")

    class Page:
        """A fake listing page."""
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return (b'<a href="/source/gis/Shapefiles/County/c_18mr25.zip">old</a>'
                    b'<a href="/source/gis/Shapefiles/County/c_16ap26.zip">new</a>')
    files = fetch.national_files(entry, {}, opener=Page)
    assert files == [("https://www.weather.gov/source/gis/Shapefiles/County/c_16ap26.zip", "c_16ap26.zip", None)]


def test_service_kinds():
    k = services.service_kind
    assert k({"office": "government", "government": "social_security", "name": "SSA Office"}) == \
        "social security office"
    assert k({"office": "government", "name": "Social Security Administration"}) == "social security office"
    assert k({"office": "government", "government": "transportation", "name": "Testville DMV"}) == \
        "motor vehicle office"
    assert k({"office": "government", "name": "ServiceOntario"}) == "motor vehicle office"
    assert k({"amenity": "clinic", "name": "VA Clinic Testville"}) == "veterans office"
    assert k({"amenity": "food_bank", "name": "X"}) == "food bank"
    assert k({"emergency": "defibrillator"}) == "defibrillator"
    assert k({"office": "government"}) is None and k({"shop": "bakery", "name": "Buns"}) is None
    assert kind_of("DMV") == "motor vehicle office" and kind_of("Social Security") == "social security office"


def test_parse_ccl():
    rows = parse_ccl(samples.NWR_JS)
    assert len(rows) == 3 and rows[0]["call_sign"] == "WXX99" and rows[0]["same"] == "050999"
    assert rows[1]["status"] == "OUT OF SERVICE" and rows[2]["state"] == "NH"


def test_the_pack_holds_places_zones_and_radio(pack):
    con = sqlite3.connect(pack)
    assert dict(con.execute("SELECT key, value FROM meta"))["part"] == "services"
    kinds = dict(con.execute("SELECT name, kind FROM svc_places"))
    assert kinds == {"Social Security Administration": "social security office",
                     "Testville DMV": "motor vehicle office",
                     "Testville Food Shelf": "food bank", "Pretend Pharmacy": "pharmacy",
                     "Defibrillator": "defibrillator"}
    assert con.execute("SELECT kind, code, name, state, office FROM svc_zones ORDER BY kind").fetchall() == [
        ("county", "50999", "Made-up", "VT", "BTV"), ("forecast zone", "VTZ099", "Made-up Valley", "VT", "BTV")]
    assert [r[0] for r in con.execute("SELECT call_sign FROM svc_radio ORDER BY call_sign")] == ["WXX98", "WXX99"]
    assert {r[0]: r[1] for r in con.execute("SELECT id, licence FROM sources")}["osm-services"] == "ODbL-1.0"


def test_the_nearest_social_security_office(pack):
    local = LocalServices(packs=[PackReader(pack)])
    r = local.nearest(*HERE, "Social Security")
    p = r["places"][0]
    assert p["name"] == "Social Security Administration" and p["phone"] == "+1 800 555 0100"
    assert p["address"] == "12 Made-up Street, Testville" and p["bearing"] == "northwest"
    assert r["phrase"] == ("The nearest social security office is Social Security Administration, 12 Made-up Street, "
                           "Testville, about 0.9 miles northwest. Phone +1 800 555 0100. Hours: Mo-Fr 09:00-16:00. "
                           "Step-free access.")
    assert local.nearest(*HERE, "DMV")["places"][0]["name"] == "Testville DMV"
    assert local.nearest(*HERE, "food bank")["places"][0]["name"] == "Testville Food Shelf"
    assert local.nearest(*HERE, "veterans office") is None


def test_nearest_also_searches_the_other_parts_and_merges_the_same_place(pack, tmp_path):
    extra = str(tmp_path / "us-vermont-extra.osmpack")
    w = PackWriter(extra)
    w.add_point("imls:1", "imls-libraries", "Testville Free Library", "public", "C_OUT_TY=CE", 44.001, -72.001,
                type="library")
    w.add_point("osm:n9", "osm", "Pretend Pharmacy", "business", "amenity=pharmacy", 44.0002, -72.0001,
                type="pharmacy")
    w.finish({"part": "extra", "region_id": VT})
    local = LocalServices(packs=[PackReader(pack), PackReader(extra)])
    lib = local.nearest(*HERE, "library", units="metres")
    assert lib["places"][0]["name"] == "Testville Free Library" and "metres" in lib["phrase"]
    pharm = local.nearest(*HERE, "pharmacy")["places"]
    assert len(pharm) == 1 and pharm[0]["sources"] == ["osm", "osm-services"]


def test_my_weather_zone_and_weather_radio(pack):
    local = LocalServices(packs=[PackReader(pack)])
    z = local.weather_zone(*HERE)
    assert (z["county"], z["same"], z["zone"], z["office"]) == ("Made-up", "050999", "VTZ099", "BTV")
    assert z["phrase"] == ("You are in Made-up County, VT (SAME code 050999). Forecast zone VTZ099, Made-up Valley. "
                           "Forecast office: BTV.")
    r = local.weather_radio(*HERE)
    assert [s["call_sign"] for s in r["stations"]] == ["WXX99", "WXX98"]
    assert r["phrase"].startswith("Your NOAA Weather Radio station is WXX99 from Pretend Mountain, 162.550 MHz")
    assert "SAME code for Made-up County: 050999." in r["phrase"] and "WXX98 162.475 MHz" in r["phrase"]
    assert local.weather_radio(10.0, 10.0) is None and local.weather_zone(10.0, 10.0) is None
