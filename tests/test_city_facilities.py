"""Cities' and counties' public places (placepacks/directories/city_facilities.py): the monthly discovery through
the Socrata catalogue and ArcGIS Hub's search, the automatic field mapping, the override list, the collection of a
state's layers, and the pack build's reading. Offline: every portal, layer, place and number here is made up; a
stand-in web answers.

Covered: titles that name public places kept and inspections, permits, staff lists and the like left out; state,
federal, university and foreign portals and private ArcGIS accounts left out; a layer with people fields (a staff
directory) never read; fields mapped (NAME/FACILITY, ADDRESS, PHONE, HOURS or a field per weekday, TYPE, WEBSITE)
and never an e-mail or a manager; one record read to find the state; the override list's skip and field fixes;
only the mapped fields asked for when a layer is read; hours turned into OpenStreetMap's syntax or kept as a note;
a layer that refuses left while the state goes on; a layer too big to be a list of places left out whole; the
kind of place from the type, the name or the layer's title; the catalogue entry and the build keeping the phone,
website and hours; the workflow's shape."""

import json
import os
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, contact  # noqa: E402
from placepacks.chains import polite  # noqa: E402
from placepacks.directories import city_facilities as cf  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

import test_yp_lookup as ypt  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402

LAYER = "https://services9.arcgis.com/MadeUp/arcgis/rest/services/Community_Centers/FeatureServer"
PEOPLE = "https://services9.arcgis.com/MadeUp/arcgis/rest/services/Staff_Facilities/FeatureServer/0"


def socrata_result(domain, dataset, name, columns):
    """One made-up result of the Socrata catalogue: columns [(field name, datatype)]."""
    return {"resource": {"name": name, "id": dataset, "columns_field_name": [c for c, _ in columns],
                         "columns_datatype": [t for _, t in columns]},
            "metadata": {"domain": domain, "license": "Public Domain"}}


SOCRATA = {"results": [
    socrata_result("data.madeupcity.gov", "abcd-1234", "Senior Centers",
                   [("site_name", "Text"), ("address", "Text"), ("phone", "Text"), ("hours_of_operation", "Text"),
                    ("location", "Point")]),
    socrata_result("data.madeupcity.gov", "insp-0001", "Facility Inspections",
                   [("name", "Text"), ("location", "Point")]),
    socrata_result("data.vt.gov", "stat-0001", "State Facilities", [("name", "Text"), ("location", "Point")]),
    socrata_result("data.madeupcity.gov", "staf-0001", "City Facilities Contacts",
                   [("name", "Text"), ("first_name", "Text"), ("email", "Text"), ("location", "Point")]),
    socrata_result("data.madeup.ca", "cana-0001", "City Facilities", [("name", "Text"), ("location", "Point")]),
    socrata_result("data.madeupcity.gov", "nopo-0001", "City Facilities", [("name", "Text"), ("notes", "Text")]),
]}
HUB = {"features": [
    {"properties": {"type": "Feature Service", "title": "Community Centers", "url": LAYER,
                    "source": "City of Madeup", "access": "public"}},
    {"properties": {"type": "Feature Service", "title": "Community Centers", "url": LAYER + "x",
                    "source": "Madeup State University", "access": "public"}},
    {"properties": {"type": "Feature Service", "title": "Community Centers", "url": LAYER + "y",
                    "source": "student@example.edu", "access": "public"}},
    {"properties": {"type": "Shapefile", "title": "Libraries", "url": "", "source": "Town of Madeup"}},
    {"properties": {"type": "Feature Service", "title": "Facilities", "url": PEOPLE, "source": "Madeup County"}},
]}
FIELDS = [{"name": n} for n in ("OBJECTID", "GlobalID", "NAME", "ADDRESS", "PHONE", "MANAGER", "EMAIL",
                                "HOURS_MONDAY", "HOURS_TUESDAY", "HOURS_WEDNESDAY", "HOURS_THURSDAY",
                                "HOURS_FRIDAY", "HOURS_SATURDAY", "HOURS_SUNDAY", "CCTYPE", "WEBSITE")]


def feature(gid, name, x=-73.2121, y=44.4759, ctype="Community Center", phone="802-555-0150",
            days=("9:00 AM - 5:00 PM",) * 5 + ("Closed", "Closed")):
    """A made-up ArcGIS feature of the community centers layer."""
    attrs = {"GlobalID": gid, "NAME": name, "ADDRESS": "184 Main St", "PHONE": phone, "CCTYPE": ctype,
             "WEBSITE": "https://madeup.example/cc", "MANAGER": "Alice Example", "EMAIL": "alice@madeup.example"}
    attrs.update({f"HOURS_{d}": t for d, t in zip(("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY",
                                                  "SATURDAY", "SUNDAY"), days)})
    return {"attributes": attrs, "geometry": {"x": x, "y": y}}


def arcgis_query(url):
    """The stand-in ArcGIS layer: the one-record check, and pages of records with only the asked fields."""
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    feats = [feature("{G1}", "Made-up Community Center"), feature("{G2}", "Pretend Senior Center", ctype=""),
             feature("{G3}", "Outside Place", x=2.35, y=48.85)]
    if q.get("resultRecordCount") == "1":
        return json.dumps({"geometryType": "esriGeometryPoint", "fields": FIELDS, "features": feats[:1]})
    asked = q["outFields"].split(",")
    assert "EMAIL" not in asked and "MANAGER" not in asked             # never requested
    page = [{"attributes": {k: v for k, v in f["attributes"].items() if k in asked}, "geometry": f["geometry"]}
            for f in feats]
    return json.dumps({"geometryType": "esriGeometryPoint", "features": page})


def routes():
    """The stand-in web: the two catalogues, the ArcGIS layers and the Socrata dataset."""
    return {
        lambda u: u.startswith(cf.SOCRATA_CATALOG): json.dumps(SOCRATA),
        lambda u: u.startswith(cf.HUB_SEARCH): json.dumps(HUB),
        lambda u: u.startswith(LAYER + "/0/query"): arcgis_query,
        lambda u: u.startswith(PEOPLE + "/query"): json.dumps({
            "geometryType": "esriGeometryPoint", "fields": [{"name": n} for n in ("NAME", "FIRST_NAME", "EMAIL")],
            "features": [{"attributes": {}, "geometry": {"x": -73.2, "y": 44.4}}]}),
        lambda u: u.startswith("https://data.madeupcity.gov/resource/abcd-1234.json"): json.dumps([
            {":id": "row-1", "site_name": "Made-up Senior Center", "address": "12 Elm St", "phone": "(802) 555-0160",
             "hours_of_operation": "Monday - Friday, 8:30 a.m. - 4:30 p.m.",
             "location": {"type": "Point", "coordinates": [-73.2130, 44.4770]}},
            {":id": "row-2", "site_name": "Pretend Hall", "address": "14 Elm St", "phone": "",
             "hours_of_operation": "By appointment; call ahead", "location": {"latitude": "44.4771",
                                                                            "longitude": "-73.2131"}}]),
    }


def fake(budget=200):
    """A polite client over the stand-in web."""
    clock = ypt.Clock()
    web = ypt.FakeWeb(routes())
    return polite.Polite(budget, cf.PAUSE, opener=web, sleep=clock.sleep, clock=clock, waits=(5,),
                         agent=cf.USER_AGENT), web


def test_titles_publishers_and_fields():
    assert cf.good_title("City Facilities") and cf.good_title("Community_Centers") and cf.good_title("Libraries")
    assert not cf.good_title("Facility Inspections") and not cf.good_title("City Bldg Energy Use")
    assert not cf.good_title("Staff Directory of City Facilities") and not cf.good_title("311 Service Requests")
    assert cf.government("City of Madeup") and cf.government("Madeup County GIS")
    assert not cf.government("Madeup State University") and not cf.government("student@example.edu")
    got = cf.map_fields(["OBJECTID", "GlobalID", "FAC_NAME", "FULLADDR", "CITY", "ZIPCODE", "PHONE", "FAX",
                         "MANAGER_NAME", "EMAIL", "HOURS", "FACTYPE", "URL"])
    assert got == {"name": "FAC_NAME", "address": "FULLADDR", "city": "CITY", "zip": "ZIPCODE", "phone": "PHONE",
                   "hours": "HOURS", "type": "FACTYPE", "website": "URL", "id": "GlobalID"}
    week = cf.map_fields([f["name"] for f in FIELDS])
    assert "hours" not in week and week["days"]["Mo"] == "HOURS_MONDAY" and len(week["days"]) == 7
    assert cf.people_layer(["NAME", "First_Name"]) and not cf.people_layer(["NAME", "ADDRESS"])
    assert cf.week_hours({d: "9:00 AM - 5:00 PM" for d in ("Mo", "Tu", "We", "Th", "Fr")} | {"Sa": "Closed"}) == \
        "Mo-Fr 09:00-17:00; Sa off"
    assert cf.week_hours({"Mo": "mornings"}) == ""                         # never a guessed time
    assert cf.kind_of("Branch Library", "Main") == {"amenity": "library"}
    assert cf.kind_of("", "Pilsen", "Senior Centers")["amenity"] == "social_centre"


def test_discovery_keeps_city_point_layers_and_applies_the_overrides():
    client, web = fake()
    layers = cf.discover(client, overrides={"add": [], "skip": {}, "fields": {}}, keywords=["facilities"], pages=1,
                         log=lambda *_: None)
    ids = sorted(l["id"] for l in layers)
    assert ids == ["arcgis:services9-arcgis-com-madeup-community-centers-0",
                   "socrata:data-madeupcity-gov-abcd-1234"]
    cc = next(l for l in layers if l["platform"] == "arcgis")
    assert cc["state"] == "VT" and cc["publisher"] == "City of Madeup" and cc["url"] == LAYER + "/0"
    assert "MANAGER" not in cc["fields"].values() and "EMAIL" not in cc["fields"].values()
    sc = next(l for l in layers if l["platform"] == "socrata")
    assert sc["fields"]["point"] == "location" and sc["fields"]["hours"] == "hours_of_operation"
    assert not any(PEOPLE in u and "query" in u and "outFields=%2A" not in u for u, _ in web.requests)
    client, _ = fake()
    layers = cf.discover(client, overrides={"add": [], "skip": {"Community_Centers": "a duplicate"},
                                            "fields": {"socrata:data-madeupcity-gov-abcd-1234": {"phone": ""}}},
                         keywords=["facilities"], pages=1, log=lambda *_: None)
    assert [l["platform"] for l in layers] == ["socrata"] and layers[0]["fields"]["phone"] == ""
    assert cf.load_overrides()["skip"]                                        # the repository's own list reads


def test_a_states_layers_are_read_with_only_the_mapped_fields(tmp_path, monkeypatch):
    client, _ = fake()
    layers = cf.discover(client, overrides={"add": [], "skip": {}, "fields": {}}, keywords=["facilities"], pages=1,
                         log=lambda *_: None)
    blocked = {"id": "arcgis:refusing", "platform": "arcgis", "url": "https://gis.refusing.example/rest/0",
               "title": "Libraries", "publisher": "Town of Refusing", "state": "VT", "fields": {"name": "NAME"}}
    path = tmp_path / "layers.json"
    cf.write_list(layers + [blocked], str(path))
    monkeypatch.setenv("CITY_FACILITIES_LIST", str(path))
    assert cf.states_with_layers(str(path)) == "vt"
    routes_ = routes()
    routes_["https://gis.refusing.example/rest/0/query?" + "x"] = ""
    routes_[lambda u: u.startswith("https://gis.refusing.example")] = (403, "<title>Just a moment...</title>")
    clock = ypt.Clock()
    client = polite.Polite(100, cf.PAUSE, opener=ypt.FakeWeb(routes_), sleep=clock.sleep, clock=clock, waits=(5,),
                           agent=cf.USER_AGENT)
    stats = {}
    rows = {r["name"]: r for r in cf.collect(client, "vt", stats)}
    assert set(rows) == {"Made-up Community Center", "Pretend Senior Center", "Made-up Senior Center",
                         "Pretend Hall"}                                    # the Paris record is not in the US
    cc = rows["Made-up Community Center"]
    assert cc["main_value"] == "community_centre" and cc["opening_hours"] == "Mo-Fr 09:00-17:00; Sa,Su off"
    assert cc["phone"] == "802-555-0150" and cc["website"] == "https://madeup.example/cc"
    assert rows["Pretend Senior Center"]["main_value"] == "social_centre"         # from the name
    assert rows["Made-up Senior Center"]["opening_hours"] == "Mo-Fr 08:30-16:30"
    assert rows["Pretend Hall"]["opening_hours"] == "" and rows["Pretend Hall"]["note"].startswith("Hours: By")
    assert rows["Made-up Senior Center"]["main_value"] == "social_centre"         # from the layer's title
    assert "alice" not in json.dumps(rows).lower()
    assert stats["blocked"] and stats["blocked"][0].startswith("arcgis:refusing")


def test_a_layer_too_big_to_be_a_list_of_places_is_left_out_whole(monkeypatch):
    monkeypatch.setattr(cf, "MAX_RECORDS", 2)
    monkeypatch.setattr(cf, "PAGE", 1)
    layer = {"id": "arcgis:big", "platform": "arcgis", "url": LAYER + "/0", "title": "Facilities",
             "publisher": "City of Madeup", "state": "VT", "fields": cf.map_fields([f["name"] for f in FIELDS])}

    def answer(url):
        feats = json.loads(arcgis_query(url.replace("resultRecordCount=1&", "resultRecordCount=9&")))["features"]
        return json.dumps({"features": feats[:1], "exceededTransferLimit": True})
    clock = ypt.Clock()
    client = polite.Polite(100, cf.PAUSE, opener=ypt.FakeWeb({lambda u: True: answer}), sleep=clock.sleep,
                           clock=clock, waits=(5,), agent=cf.USER_AGENT)
    stats = {"records": 0, "left_out": 0}
    try:
        list(cf.arcgis_rows(client, layer, stats))
        raise AssertionError("a too-big layer must raise")
    except cf.TooBig:
        pass


def test_the_catalogue_entry_and_the_build_keep_phone_website_and_hours(tmp_path):
    e = next(x for x in catalogue.load()["accepted"] if x["id"] == "city-facilities")
    assert e["fetch"] == {"method": "release_csv", "release": "city-facilities", "prefix": "city-facilities"}
    assert e["licence"] == "government-facts" and e["part"] == "extra"
    assert "owner" in e["notes"].lower() and "staff" in e["notes"].lower()
    assert "city-facilities" in contact.GOVERNMENT_SOURCES and "city-facilities" in contact.HOURS_SOURCES
    import csv
    path = tmp_path / "city-facilities.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cf.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerow({"key": "arcgis:x:{G1}", "name": "Made-up Library", "main_key": "amenity",
                    "main_value": "library", "lat": "44.4759", "lon": "-73.2121", "phone": "802-555-0170",
                    "website": "https://madeup.example/library", "opening_hours": "Mo-Fr 09:00-17:00",
                    "note": "", "state": "VT"})
    pack = str(tmp_path / "e.osmpack")
    writer = PackWriter(pack, 202612)
    assert read_tabular(str(path), e, dict(catalogue.regions()["us-vermont"]), writer) == 1
    writer.finish({**ypt.META, "part": "extra"})
    from placepacks.lookup import PackReader
    reader = PackReader(pack)
    key = reader.con.execute("SELECT key FROM points").fetchone()[0]
    details = reader.details_of(key)
    assert details["phone"] == "802-555-0170" and details["opening_hours"] == "Mo-Fr 09:00-17:00"
    assert reader.con.execute("SELECT cls FROM points").fetchone()[0] == "public"


def test_the_workflow_discovers_then_collects_by_state():
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "city-facilities.yml"), day="18")
    assert dirrun.collections()["cityfacilities"]["extra_files"] == {cf.LIST_FILE: cf.RELEASE_LIST}
    assert {j["unit"] for j in dirrun.matrix("cityfacilities", "vt wa")} == {"vt", "wa"}
