"""Street and transit accessibility and museum accessibility (queue item Q4): accessible pedestrian signals and curb
ramps found in made-up open-data catalogues (field auto-mapping, government and US checks, people's names taken
out), transit agencies' elevator lists, Amtrak station pages, GTFS pathways into station features, museums' own
accessibility pages, block handling, the packs (extra part's site features, navigation part's crossings) and the
wiring (runner, catalogue, contact lists, workflows). Offline: every city, station, museum, signal and phone number
here is made up."""

import csv
import datetime
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import samples  # noqa: E402
from placepacks import build, catalogue, contact, features, lookup, museum_access, street_access, writer  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.navigate import Navigator  # noqa: E402
from placepacks.readers import gtfs_stations  # noqa: E402
from placepacks.readers import street_access as nav_street  # noqa: E402
from placepacks.street_access import amtrak, open_data as od, transit_lists  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

from test_map_vendors import Web, client  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402

TODAY = datetime.date(2026, 12, 12)
VT = "us-vermont"
ROBOTS_OK = (200, "User-agent: *\nAllow: /\n")
CORNER = (44.0005, -72.0000)


# ------------------------------------------------------------------------------------------------ field mapping

def test_new_kinds():
    """The kinds added for street and transit accessibility exist."""
    for kind in ("accessible pedestrian signal", "curb ramp", "stairs"):
        assert kind in features.KINDS


def test_aps_fields_are_mapped_automatically():
    """Field names in the shapes cities use become the right facts; people and comment fields are never mapped."""
    got = od.map_fields(["OBJECTID", "Location", "Status", "Date_Installed", "Locator_Tone", "Vibrotactile_Arrow",
                         "Push_Button", "Inspector_Name", "Comments", "GlobalID"])
    assert got == {"name": "Location", "installed": "Date_Installed", "status": "Status", "locator": "Locator_Tone",
                   "vibration": "Vibrotactile_Arrow", "button": "Push_Button", "id": "GlobalID"}
    got = od.map_fields(["First_Intersect", "Second_Intersect", "APS", "APS_TYPE", "Voice_Message_Requested"])
    assert got["street1"] == "First_Intersect" and got["street2"] == "Second_Intersect" and got["aps"] == "APS"
    assert got["aps_type"] == "APS_TYPE" and "speech" not in got          # a request is not a feature
    ramp = od.map_fields(["RAMP_ID", "ADA_COMPLIANT", "DETECTABLE_WARNING", "CONDITION", "YEAR_BUILT", "RAMP_TYPE"])
    assert ramp == {"installed": "YEAR_BUILT", "condition": "CONDITION", "compliant": "ADA_COMPLIANT",
                    "warning": "DETECTABLE_WARNING", "ramp_type": "RAMP_TYPE", "id": "RAMP_ID"}


def test_titles_publishers_and_values():
    """Which layers count (signals, curb ramps, a signal layer with an APS column; never plans, requests or
    statistics), which publishers are governments, and how values, dates and names are made plain."""
    assert od.kind_of_title("Accessible Pedestrian Signals (Active)") == od.APS
    assert od.kind_of_title("Curb Ramp Inventory") == od.RAMP
    assert od.kind_of_title("Traffic Signals", {"aps": "APS"}) == od.APS
    assert od.kind_of_title("Traffic Signals") == ""
    for title in ("Planned APS Locations", "Missing Curb Ramps", "Curb Ramps Built Or Improved", "APS Requests"):
        assert od.kind_of_title(title) == "", title
    assert od.government("City of Testville") and od.government("Madeup Department of Transportation")
    assert od.government("Testville Dept. of Transportation")
    for who in ("Madeup Engineering LLC", "someone@example.org", "madeupuser123", "Madeup University", ""):
        assert not od.government(who), who
    assert od.yes_no("Y") == "yes" and od.yes_no("absent") == "no" and od.yes_no(" Good ") == "good"
    assert od.date_text(1702684800000, "esriFieldTypeDate") == "2023-12-16"
    assert od.date_text("2023-12-16T00:00:00.000") == "2023-12-16" and od.date_text("12/16/2023") == "2023-12-16"
    assert od.date_text("2014") == "2014" and od.date_text("1/1/1900") == "" and od.date_text("soon") == ""
    assert od.clean_name("N MAIN ST_ELM ST- Alice Example") == "N Main St and Elm St"
    assert od.clean_name("Grant Street") == "Grant Street"
    assert od.clean_name("Park Avenue East S/R and East 179 Street") == "Park Avenue East S/R and East 179 Street"
    assert od.street_name({"street1": "MAIN ST", "street2": "ELM ST"}) == "Main St and Elm St"
    assert od.present({"status": "Installed"}, od.APS) and not od.present({"status": "Planned 2027"}, od.APS)
    assert not od.present({"aps": "No"}, od.APS) and od.present({"aps": "Yes"}, od.APS)
    assert not od.present({"aps": "Pending"}, od.APS)


def test_a_row_of_each_kind():
    """A signal's and a curb ramp's rows: the name, the note and the JSON tags; a position outside the US gives
    nothing."""
    layer = {"id": "arcgis:madeup-aps", "publisher": "City of Testville"}
    row = od.make_row(layer, od.APS, "7", {"name": "MAIN ST AND ELM ST", "installed": "2023-12-16",
                                          "locator": "Y", "vibration": "yes", "aps_type": "RRFB"}, 44.0, -72.0)
    assert row["kind"] == od.APS and row["name"] == "Main St and Elm St" and row["key"] == "arcgis:madeup-aps:7"
    assert json.loads(row["tags"]) == {"installed": "2023-12-16", "locator_tone": "yes", "vibration": "yes",
                                       "type": "rrfb", "source": "City of Testville"}
    assert "locator tone" in row["notes"] and "flashing beacons" in row["notes"]
    ramp = od.make_row(layer, od.RAMP, "9", {"compliant": "N", "warning": "Y", "condition": "Fair"}, 44.0, -72.0)
    assert json.loads(ramp["tags"])["detectable_warning"] == "yes" and "condition: fair" in ramp["notes"]
    assert od.make_row(layer, od.APS, "8", {"name": "Somewhere"}, 43.65, -79.38) is None       # Toronto


# ------------------------------------------------------------------------------------------------ discovery

def catalogue_web():
    """A made-up Socrata catalogue and Hub search with: a city's APS dataset (kept), a federal research dataset
    (left out), a city's ArcGIS signal layer (kept), a consultant's own layer (left out), a layer whose records lie
    outside the US (left out) and a curb ramp layer (kept)."""
    socrata = {"resultSetSize": 2, "results": [
        {"resource": {"id": "abcd-1234", "name": "Accessible Pedestrian Signal Locations",
                      "columns_field_name": ["location", "date_insta", "the_geom"],
                      "columns_datatype": ["text", "calendar_date", "point"]},
         "metadata": {"domain": "data.testville.example", "license": "Public Domain"}},
        {"resource": {"id": "zzzz-0000", "name": "Accessible Pedestrian Signal research",
                      "columns_field_name": ["location", "the_geom"], "columns_datatype": ["text", "point"]},
         "metadata": {"domain": "datahub.transportation.gov"}}]}
    hub = {"features": [
        {"properties": {"type": "Feature Service", "title": "Accessible Pedestrian Signals",
                        "source": "City of Testville",
                        "url": "https://gis.testville.example/arcgis/rest/services/APS/FeatureServer"}},
        {"properties": {"type": "Feature Service", "title": "Accessible Pedestrian Signals", "source": "madeupuser123",
                        "url": "https://gis.madeup.example/rest/services/APS/FeatureServer"}},
        {"properties": {"type": "Feature Service", "title": "Accessible Pedestrian Signal",
                        "source": "City of Elsewhere",
                        "url": "https://gis.elsewhere.example/rest/services/APS/FeatureServer"}},
        {"properties": {"type": "Feature Service", "title": "Curb Ramps", "source": "Testville Public Works",
                        "url": "https://gis.testville.example/arcgis/rest/services/Ramps/MapServer/3"}}]}
    aps_first = {"geometryType": "esriGeometryPoint",
                 "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}, {"name": "Location", "type": "x"},
                            {"name": "INSTALL_DATE", "type": "esriFieldTypeDate"},
                            {"name": "Status", "type": "esriFieldTypeString"}],
                 "features": [{"attributes": {}, "geometry": {"x": -72.0, "y": 44.0005}}]}
    abroad = dict(aps_first, features=[{"attributes": {}, "geometry": {"x": -79.38, "y": 43.65}}])
    ramps_first = {"geometryType": "esriGeometryPoint",
                   "fields": [{"name": "RAMP_ID"}, {"name": "CONDITION"}, {"name": "DETECTABLE_WARNING"}],
                   "features": [{"attributes": {}, "geometry": {"x": -72.0001, "y": 44.0004}}]}
    return Web({
        od.cf.SOCRATA_CATALOG: (200, socrata), od.cf.HUB_SEARCH: (200, hub),
        "https://data.testville.example/resource/abcd-1234.json?%24select=the_geom&%24limit=1":
            (200, [{"the_geom": {"type": "Point", "coordinates": [-72.0, 44.0005]}}]),
        "https://gis.testville.example/arcgis/rest/services/APS/FeatureServer/0/query?where=1%3D1&outFields=%2A&"
        "resultRecordCount=1": (200, aps_first),
        "https://gis.elsewhere.example/rest/services/APS/FeatureServer/0/query": (200, abroad),
        "https://gis.testville.example/arcgis/rest/services/Ramps/MapServer/3/query?where=1%3D1&outFields=%2A&"
        "resultRecordCount=1": (200, ramps_first),
    })


def test_discovery_keeps_governments_layers_in_the_us():
    """The sweep keeps the city's two signal layers and its curb ramp layer (with their fields mapped and the date
    field's type), and leaves out the federal research portal, the personal account and the layer abroad."""
    web = catalogue_web()
    layers = od.discover(client(web), keywords=["accessible pedestrian signal"], pages=1, log=lambda *a: None)
    got = {(l["platform"], l["kind"], l["state"]) for l in layers}
    assert got == {("socrata", od.APS, "VT"), ("arcgis", od.APS, "VT"), ("arcgis", od.RAMP, "VT")}
    aps = next(l for l in layers if l["platform"] == "arcgis" and l["kind"] == od.APS)
    assert aps["fields"]["name"] == "Location" and aps["dates"] == {"installed": "esriFieldTypeDate"}
    assert not any("gis.madeup.example" in u for u in web.asked)                 # a personal account: never asked
    assert sum("elsewhere" in u for u in web.asked) == 1                         # one record read: abroad


def test_signals_unit_reads_layers_and_records_a_block(tmp_path):
    """The signals unit reads each signal layer of the month's list, asking only for the mapped fields; a planned
    signal is left out; a layer that refuses is recorded as blocked and the others still count."""
    layers = [{"id": "arcgis:testville-aps", "platform": "arcgis", "kind": od.APS, "state": "VT",
               "url": "https://gis.testville.example/arcgis/rest/services/APS/FeatureServer/0",
               "publisher": "City of Testville", "dates": {"installed": "esriFieldTypeDate"},
               "fields": {"name": "Location", "installed": "INSTALL_DATE", "status": "Status", "id": "OBJECTID"}},
              {"id": "socrata:data-testville-example-abcd-1234", "platform": "socrata", "kind": od.APS, "state": "VT",
               "domain": "data.testville.example", "dataset": "abcd-1234", "publisher": "data.testville.example",
               "fields": {"name": "location", "installed": "date_insta", "point": "the_geom"}},
              {"id": "arcgis:refusing-aps", "platform": "arcgis", "kind": od.APS, "state": "VT",
               "url": "https://gis.refusing.example/rest/services/APS/FeatureServer/0", "publisher": "Town of X",
               "fields": {"name": "Location"}}]
    path = tmp_path / "layers.json"
    od.write_list(layers, str(path))
    page = {"features": [
        {"attributes": {"OBJECTID": 1, "Location": "MAIN ST AND ELM ST", "INSTALL_DATE": 1702684800000,
                        "Status": "Installed"}, "geometry": {"x": -72.0002, "y": 44.0005}},
        {"attributes": {"OBJECTID": 2, "Location": "OAK ST AND ELM ST", "INSTALL_DATE": None, "Status": "Planned"},
         "geometry": {"x": -72.0, "y": 44.001}}]}
    web = Web({"https://gis.testville.example/arcgis/rest/services/APS/FeatureServer/0/query": (200, page),
               "https://data.testville.example/resource/abcd-1234.json": (200, [
                   {":id": "row-1", "location": "Pine Street and Elm Street", "date_insta": "2022-10-28T00:00:00.000",
                    "the_geom": {"type": "Point", "coordinates": [-72.0, 44.002]}}]),
               "https://gis.refusing.example/": (403, "<title>Access Denied</title>")})
    os.environ["STREET_ACCESS_LIST"] = str(path)
    try:
        stats = {}
        rows = list(od.collect(client(web), "signals", stats))
    finally:
        del os.environ["STREET_ACCESS_LIST"]
    assert [r["name"] for r in rows] == ["Main St and Elm St", "Pine Street and Elm Street"]
    assert rows[0]["installed"] == "2023-12-16" and stats["left_out"] == 1
    assert stats["blocked"] and stats["blocked"][0].startswith("arcgis:refusing-aps")
    asked = next(u for u in web.asked if "testville.example/arcgis" in u)
    import urllib.parse
    fields = urllib.parse.parse_qs(urllib.parse.urlsplit(asked).query)["outFields"][0].split(",")
    assert sorted(fields) == ["INSTALL_DATE", "Location", "OBJECTID", "Status"]          # only the mapped fields
    assert od.units_for("curb-ramps-1", layers + [dict(layers[0], kind=od.RAMP)]) and \
        od.units_for("curb-ramps-2", [dict(layers[0], kind=od.RAMP)]) == []


# ------------------------------------------------------------------------------------------------ transit lists

def test_mta_and_mbta_elevator_lists():
    """New York City Transit's list (placed by the station list; inactive equipment and other operators' left out)
    and the MBTA's facilities (a facility without its own position takes its station's) become stations and their
    elevators and escalators."""
    equipment = [{"station": "Madeup Av", "equipmentno": "EL001", "equipmenttype": "EL", "isactive": "Y",
                  "nonNYCT": "N", "ADA": "Y", "serving": "Street to uptown platform", "elevatorsgtfsstopid": "Z01",
                  "shortdescription": "Street to uptown platform", "linesservedbyelevator": "Z"},
                 {"station": "Madeup Av", "equipmentno": "ES002", "equipmenttype": "ES", "isactive": "Y",
                  "nonNYCT": "N", "ADA": "N", "elevatorsgtfsstopid": "Z01"},
                 {"station": "Madeup Av", "equipmentno": "EL003", "equipmenttype": "EL", "isactive": "N",
                  "nonNYCT": "N", "elevatorsgtfsstopid": "Z01"},
                 {"station": "Other Line", "equipmentno": "EL004", "equipmenttype": "EL", "isactive": "Y",
                  "nonNYCT": "Y", "elevatorsgtfsstopid": "Z01"}]
    stations = [{"gtfs_stop_id": "Z01", "complex_id": "900", "stop_name": "Madeup Av", "gtfs_latitude": "44.001",
                 "gtfs_longitude": "-72.001"}]
    rows = transit_lists.mta_rows(equipment, stations)
    assert [(r["kind"], r["key"]) for r in rows] == [("site", "mta-nyct:station:900"), ("elevator", "mta-nyct:EL001"),
                                                     ("escalator", "mta-nyct:ES002")]
    assert rows[0]["site_name"] == "Madeup Av" and rows[0]["name"] == "Madeup Av station"
    assert "ADA accessible" in rows[1]["notes"] and "not an ADA route" in rows[2]["notes"]
    attributes = {"type": "ELEVATOR", "latitude": None, "longitude": None, "short_name": "Lobby to platform",
                  "long_name": "Madeup Elevator 50"}
    page = {"data": [{"id": "50", "type": "facility", "attributes": attributes,
                      "relationships": {"stop": {"data": {"id": "place-mdp", "type": "stop"}}}}],
            "included": [{"id": "place-mdp", "type": "stop", "attributes": {"name": "Madeup Square", "latitude": 44.003,
                                                                            "longitude": -72.003,
                                                                            "wheelchair_boarding": 1}}]}
    web = Web({transit_lists.MBTA_FACILITIES: (200, page)})
    stats = {}
    rows = list(transit_lists.collect(client(web), "mbta-elevators", stats))
    assert [r["kind"] for r in rows] == ["site", "elevator"] and stats["elevators"] == 1
    assert rows[1]["lat"] == "44.003000" and rows[0]["notes"] == "wheelchair boarding: yes"


# ------------------------------------------------------------------------------------------------ Amtrak

STATION_PAGE = """<html><title>Testville, VT &#8211; Amtrak Station (TVL)</title>
<h3><a href="#"><i class="icon-minus-sign"></i>Features</a></h3><div style="display: block;"><ul class="">
<li>ATM available</li><li>Elevator <i class="fa fa-wheelchair-alt"></i></li><li>Restrooms</li></ul></div>
<h3><a href="#"><i class="icon-plus-sign"></i>Accessibility</a></h3><div><ul>
<li>Payphones</li><li>Accessible platform</li><li>Accessible restrooms</li><li>Wheelchair available</li>
<li>No wheelchair lift</li></ul></div>
<div class="hours" id="stationHours"><table><tr><td>Mon</td><td>05:00 am - 11:30 pm<br/></td></tr>
<tr><td>Tue</td><td>05:00 am - 11:30 pm<br/></td></tr><tr><td>Wed</td><td>05:00 am - 11:30 pm<br/></td></tr>
<tr><td>Thu</td><td>05:00 am - 11:30 pm<br/></td></tr><tr><td>Fri</td><td>05:00 am - 11:30 pm<br/></td></tr>
<tr><td>Sat</td><td>CLOSED</td></tr><tr><td>Sun</td><td>CLOSED</td></tr></table></div>
<div class="hours" id="ticketHours"><table><tr><td>Mon</td><td>CLOSED</td></tr><tr><td>Tue</td><td>CLOSED</td></tr>
<tr><td>Wed</td><td>CLOSED</td></tr><tr><td>Thu</td><td>CLOSED</td></tr><tr><td>Fri</td><td>CLOSED</td></tr>
<tr><td>Sat</td><td>CLOSED</td></tr><tr><td>Sun</td><td>CLOSED</td></tr></table></div>
<div class="hours" id="meetAndAssistHours"><table><tr><td>Mon</td><td>12:00 am - 01:00 am 04:00 am - 11:59 pm</td></tr>
</table></div><p>Regional Contact Alice Example alice@example.org</p></html>"""


def test_amtrak_station_page():
    """A station page's accessibility list, elevator and hours become the station's note, hours and features; the
    regional contact's name and e-mail are never kept."""
    rows = amtrak.parse_station(STATION_PAGE, "TVL", {"TVL": (44.01, -72.01, "Testville")}, "https://gas/tvl/")
    site = rows[0]
    assert site["place_key"] == "ntad-amtrak:TVL" and site["opening_hours"] == "Mo-Fr 05:00-23:30; Sa,Su off"
    assert site["notes"] == ("Accessibility (Amtrak station information): accessible platform; accessible restrooms; "
                             "wheelchair available; no wheelchair lift; elevator; ticket office closed; passenger "
                             "assistance Mo 00:00-01:00,04:00-24:00")
    assert {r["kind"] for r in rows[1:]} == {"elevator", "accessible restroom", "accessibility service"}
    assert "Alice" not in json.dumps(rows) and "@" not in json.dumps(rows)
    assert amtrak.station_code("https://www.greatamericanstations.com/stations/testville-vt-tvl/") == "TVL"
    assert amtrak.parse_station(STATION_PAGE, "XXX", {}) == []


def test_amtrak_obeys_the_crawl_delay_and_stops_on_a_block(tmp_path):
    """robots.txt's Crawl-delay becomes the client's pause; a disallowed page is not read; a refusal of the site
    stops the unit as blocked."""
    robots = "User-agent: *\nCrawl-delay: 12\nDisallow: /stations/hidden-vt-hdn/\n"
    web = Web({amtrak.SITE + "/robots.txt": (200, robots),
               amtrak.NTAD: (200, {"features": [{"attributes": {"Code": "TVL", "City": "Testville"},
                                                 "geometry": {"x": -72.01, "y": 44.01}},
                                                {"attributes": {"Code": "HDN", "City": "Hidden"},
                                                 "geometry": {"x": -72.02, "y": 44.02}}]}),
               amtrak.SITEMAP: (200, f"<loc>{amtrak.SITE}/stations/testville-vt-tvl/</loc>"
                                     f"<loc>{amtrak.SITE}/stations/hidden-vt-hdn/</loc>"),
               amtrak.SITE + "/stations/testville-vt-tvl/": (200, STATION_PAGE)})
    c = client(web)
    stats = {}
    rows = list(amtrak.collect(c, "amtrak-stations", stats))
    assert c.pause == 12 and stats["stations"] == 1 and rows[0]["key"] == "amtrak-station:TVL"
    assert not any("hidden" in u for u in web.asked)
    web = Web({amtrak.SITE + "/robots.txt": (403, "<title>Access Denied</title>")})
    summary = dirrun.run("streetaccess", "amtrak-stations", str(tmp_path), opener=web, sleep=lambda s: None,
                         today=TODAY)
    assert summary["status"] == "blocked" and not (tmp_path / "amtrak-stations.csv.gz").exists()
    assert len(web.asked) == 1


# ------------------------------------------------------------------------------------------------ GTFS pathways

def station_feed(folder):
    """A made-up feed with a station, two entrances (one step-free), a platform, levels and pathways: an elevator
    listed in both directions, stairs and a walkway (left out)."""
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,Made-up Transit,https://example.org,"
                      "America/New_York\n",
        "levels.txt": "level_id,level_index,level_name\nL0,0,Street\nL1,-1,Platform\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type,parent_station,wheelchair_boarding,level_id\n"
                     "ST,Madeup Station,44.0010,-71.9995,1,,1,\n"
                     "E1,Main Street entrance,44.0011,-71.9994,2,ST,0,L0\n"
                     "E2,Elm Street stairs entrance,44.0009,-71.9996,2,ST,2,L0\n"
                     "P1,Madeup Station platform,44.0010,-71.9995,0,ST,0,L1\n"
                     "N1,,,,3,ST,,L0\nN2,,,,3,ST,,L1\n"
                     "S9,Lonely Stop,44.0030,-71.9990,0,,2,\n",
        "pathways.txt": "pathway_id,from_stop_id,to_stop_id,pathway_mode,is_bidirectional,stair_count,signposted_as\n"
                        "PW1,E1,N2,5,1,,Elevator to platform\nPW2,N2,E1,5,1,,Elevator to platform\n"
                        "PW3,E2,P1,2,1,24,\nPW4,E1,E2,1,1,,\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\nR1,A,1,Line 1,1\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "WK,1,1,1,1,1,0,0,20261101,20270131\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,wheelchair_accessible\nR1,WK,T1,Out,0,1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,08:00:00,08:00:00,P1,1\n",
    }
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "mdb-mdb-8888.zip")
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return path


def test_gtfs_pathways_become_station_features(tmp_path):
    """Entrances (step-free one by its parent station's wheelchair boarding), the elevator once, the stairs with
    their step count and levels; the walkway left out."""
    with zipfile.ZipFile(station_feed(str(tmp_path))) as z:
        found, stops = gtfs_stations.station_features(z)
    got = {(f["key"], f["kind"]) for f in found}
    assert got == {("E1", "accessible entrance"), ("E2", "entrance"), ("pathway:PW1", "elevator"),
                   ("pathway:PW3", "stairs")}
    stairs = next(f for f in found if f["kind"] == "stairs")
    assert stairs["notes"] == "Stairs from Street to Platform; 24 steps" and stairs["station"] == "ST"
    elevator = next(f for f in found if f["kind"] == "elevator")
    assert (elevator["lat"], elevator["lon"]) == (44.0011, -71.9994) and elevator["name"] == "Elevator to platform"
    assert gtfs_stations.wheelchair_of(stops, "P1") == 1 and gtfs_stations.wheelchair_of(stops, "S9") == 2


def test_station_features_and_wheelchair_notes_in_the_packs(tmp_path):
    """In the extra part: the station's features tied to the station's transit point and the stops' wheelchair
    boarding notes; in the navigation part: the entrances (wheelchair yes or no) and the elevator."""
    feed = station_feed(str(tmp_path / "gtfs"))
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    region = dict(catalogue.regions()[VT])
    pw = PackWriter(str(tmp_path / "extra.osmpack"))
    from placepacks.readers.gtfs import read as read_gtfs
    read_gtfs(feed, cat["gtfs"], region, pw)
    assert gtfs_stations.read(feed, cat["gtfs-station-features"], region, pw) >= 5
    pw.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "extra.osmpack"))
    station = "gtfs:mdb-mdb-8888:ST"
    kinds = sorted(r["kind"] for r in pack.features_of(station))
    assert kinds == ["accessible entrance", "elevator", "entrance", "stairs"]
    assert pack.notes_for("gtfs:mdb-mdb-8888:S9") == ["Wheelchair boarding: no (the agency's timetable data)"]
    assert pack.notes_for("gtfs:mdb-mdb-8888:P1") == ["Wheelchair boarding: yes (the agency's timetable data)"]
    near = pack.features_near(44.0011, -71.9994, kinds="accessible entrance", metres=30)
    assert near and near[0]["name"] == "Main Street entrance"
    pack.close()
    fetched = {"osm-navigation": {"ok": True, "path": samples.nav_osm_file(str(tmp_path)), "version": "test"},
               "gtfs-navigation": {"ok": True, "path": str(tmp_path / "gtfs"), "version": "mdb-8888"}}
    out = str(tmp_path / "us-vermont-navigation.osmpack")
    build.build(VT, "navigation", fetched, out, removal_list=[])
    nav = Navigator(packs=[PackReader(out)])
    entrances = nav.features_near(44.0010, -71.9995, 40, {"entrance"})
    by_name = {f["name"]: f["tags"].get("wheelchair") for f in entrances}
    assert by_name["Main Street entrance"] == "yes" and by_name["Elm Street stairs entrance"] == "no"
    assert [f["tags"]["station"] for f in nav.features_near(44.0011, -71.9994, 5, {"elevator"})] == ["Madeup Station"]


# ------------------------------------------------------------------------------------------------ signals in packs

def street_csv(path, rows):
    """Write street-access rows as the collectors' CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=street_access.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return str(path)


def street_rows():
    """A city's signal at the made-up corner's crossing, one far from any crossing, a curb ramp by the crossing and
    a station elevator."""
    layer = {"id": "arcgis:testville-aps", "publisher": "City of Testville"}
    aps = od.make_row(layer, od.APS, "1", {"name": "MAIN ST AND ELM ST", "installed": "2023-12-16", "locator": "Y"},
                      44.0005, -72.0003)
    lone = od.make_row(layer, od.APS, "2", {"name": "OAK ST AND PINE ST"}, 44.0100, -72.0100)
    ramp = od.make_row({"id": "arcgis:testville-ramps", "publisher": "City of Testville"}, od.RAMP, "5",
                       {"compliant": "Y", "warning": "Y", "condition": "Good"}, 44.00048, -72.00021)
    station = transit_lists.station_row("mbta:station:place-x", "Madeup Square", 44.003, -72.003, "MBTA")
    elevator = {"key": "mbta:facility:1", "kind": "elevator", "name": "Lobby to platform",
                "site": "mbta:station:place-x",
                "site_name": "Madeup Square", "lat": "44.003", "lon": "-72.003", "notes": "Madeup Elevator 1"}
    return [aps, lone, ramp, station, elevator]


def test_signals_in_the_extra_part_and_the_crossings(tmp_path):
    """The extra part gets the signals (without a site) and the station's elevator, never the curb ramp; the
    navigation part gets the signals and the curb ramp, and crossing_here says the city's listed signal and ramp
    after the map's facts; where no crossing is mapped, the listed signal alone is said."""
    path = street_csv(tmp_path / "street.csv", street_rows())
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    region = dict(catalogue.regions()[VT])
    pw = PackWriter(str(tmp_path / "extra.osmpack"))
    pw.add_point("gtfs:mdb-1:place-x", "gtfs", "Madeup Square", "transit", "transit=station", 44.003, -72.003)
    features.read(path, cat["street-access"], region, pw)
    pw.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "extra.osmpack"))
    signals = pack.features_near(44.0005, -72.0003, kinds="accessible pedestrian signal", metres=50)
    assert [s["name"] for s in signals] == ["Main St and Elm St"] and signals[0]["site"] is None
    assert "installed 2023-12-16" in signals[0]["notes"]
    assert pack.features_near(44.0005, -72.0002, kinds="curb ramp", metres=50) == []
    assert [r["kind"] for r in pack.features_of("gtfs:mdb-1:place-x")] == ["elevator"]
    pack.close()
    fetched = {"osm-navigation": {"ok": True, "path": samples.nav_osm_file(str(tmp_path)), "version": "test"},
               "street-access-navigation": {"ok": True, "path": path, "version": "2026-12-12"}}
    out = str(tmp_path / "us-vermont-navigation.osmpack")
    build.build(VT, "navigation", fetched, out, removal_list=[])
    nav = Navigator(packs=[PackReader(out)])
    r = nav.crossing_here(44.00045, -72.00025)
    assert r["listed_signal"]["tags"]["installed"] == "2023-12-16"
    assert "The city lists an accessible pedestrian signal here (installed 2023-12-16; locator tone)." in r["phrase"]
    assert "A curb ramp in the city's list (the nearest: ADA compliant: yes; detectable warning surface: yes; " \
           "condition: good)." in r["phrase"]
    assert "City of Testville" in r["attribution"]
    alone = nav.crossing_here(44.0100, -72.0101)
    assert alone["listed_signal"] and alone["phrase"].startswith(
        "No crossing is mapped here, but the city lists an accessible pedestrian signal at Oak St and Pine St")
    assert nav_street.KINDS == ("accessible pedestrian signal", "curb ramp")


# ------------------------------------------------------------------------------------------------ museums

MUSEUM_HOME = ('<html><a href="/visit/accessibility">Accessibility</a><a href="/visit">Plan your visit</a>'
               '<a href="https://www.facebook.com/madeup">Facebook</a><p>Open daily. Contact Alice Example.</p></html>')
MUSEUM_ACCESS = ("<html><h1>Accessibility</h1><p>Audio description tours are offered monthly. Touch tours of the "
                 "sculpture hall can be booked. Large-print and braille gallery guides are at the front desk. "
                 "Wheelchairs are available free of charge at the coat check. The accessible entrance is on Elm "
                 "Street, with a ramp; call 802-555-0100 to arrange a drop-off. Service animals are welcome. "
                 "Sensory-friendly mornings are held on the first Saturday. Questions: access@madeup-museum.example."
                 "</p></html>")


def museum_web(home_status=200):
    """A made-up museum site: robots.txt, the homepage and its accessibility page."""
    base = "https://www.madeup-museum.example"
    return Web({base + "/robots.txt": ROBOTS_OK, base + "/": (home_status, MUSEUM_HOME),
                base + "/visit/accessibility": (200, MUSEUM_ACCESS), base + "/visit": (200, "<p>Tickets.</p>")})


MUSEUM = {"org": "Madeup Museum of Art", "homepage": "https://www.madeup-museum.example",
          "place_key": "imls-museums:8400199999", "lat": "44.004", "lon": "-72.004"}


def test_museum_page_extraction():
    """The accessibility page's facts become the site's note and its features; the entrance keeps its sentence
    without the phone number; no person's name or e-mail address is kept; a social network link is not
    followed."""
    web = museum_web()
    rows, status = museum_access.scan_museum(client(web), MUSEUM)
    assert status == "ok"
    site = rows[0]
    assert site["kind"] == "site" and site["place_key"] == "imls-museums:8400199999"
    assert site["notes"] == ("Accessibility (museum's website): audio description; touch tours; braille; large print; "
                             "wheelchairs available; accessible entrance; service animals welcome; sensory-friendly "
                             "programs; page https://www.madeup-museum.example/visit/accessibility")
    by_name = {r["name"]: r for r in rows[1:]}
    assert set(by_name) == {"Audio description", "Touch tours", "Braille materials", "Large print materials",
                            "Wheelchairs available", "Accessible entrance", "Sensory-friendly programs"}
    entrance = by_name["Accessible entrance"]
    assert entrance["kind"] == "accessible entrance" and "Elm Street, with a ramp" in entrance["notes"]
    text = json.dumps(rows)
    assert "555-0100" not in text and "@" not in text and "Alice" not in text
    assert not any("facebook" in u for u in web.asked)


def test_museum_blocks_robots_and_nothing():
    """A museum whose site refuses is counted as blocked after one request; robots.txt that disallows us stops
    before the homepage; a homepage saying one fact in passing is "nothing"."""
    base = "https://www.madeup-museum.example"
    web = Web({base + "/robots.txt": (403, "<title>Access Denied</title>")})
    assert museum_access.scan_museum(client(web), MUSEUM) == ([], "blocked") and len(web.asked) == 1
    web = Web({base + "/robots.txt": (200, "User-agent: *\nDisallow: /\n")})
    assert museum_access.scan_museum(client(web), MUSEUM) == ([], "robots") and len(web.asked) == 1
    web = Web({base + "/robots.txt": ROBOTS_OK, base + "/": (200, "<p>We have an elevator.</p>")})
    assert museum_access.scan_museum(client(web), MUSEUM) == ([], "nothing")

def test_a_share_goes_on_past_a_blocked_museum(tmp_path):
    """In a share, a museum that refuses is counted and the next one is still read."""
    seeds = [dict(MUSEUM, place_key="imls-museums:1", homepage="https://www.refusing-museum.example"), MUSEUM]
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps(seeds))
    web = museum_web()
    web.pages["https://www.refusing-museum.example/"] = (403, "<title>Just a moment...</title>")
    web.pages["https://www.refusing-museum.example/robots.txt"] = ROBOTS_OK
    os.environ["MUSEUM_SEEDS"] = str(path)
    try:
        totals, rows = {"blocked": 0, "ok": 0}, []
        for i in range(1, museum_access.SHARDS + 1):
            stats = {}
            rows += list(museum_access.collect(client(web), f"museums-{i}", stats))
            totals = {k: totals[k] + stats[k] for k in totals}
    finally:
        del os.environ["MUSEUM_SEEDS"]
    assert totals == {"blocked": 1, "ok": 1} and rows[0]["place_key"] == "imls-museums:8400199999"


def imls_zip():
    """A made-up Museum Universe Data File: an art museum with a website, a historical society (left out), one
    whose website is a social network page (left out) and one without a website."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["MID", "DISCIPL", "COMMONNAME", "LEGALNAME", "WEBURL", "LATITUDE", "LONGITUDE"])
    w.writerow(["8400199999", "ART", "MADEUP MUSEUM OF ART", "X", "HTTP://WWW.MADEUP-MUSEUM.EXAMPLE/", "44.004",
                "-72.004"])
    w.writerow(["8400199998", "HSC", "MADEUP HISTORICAL SOCIETY", "X", "www.madeup-history.example", "44.0", "-72.0"])
    w.writerow(["8400199997", "GMU", "SAMPLE MUSEUM", "X", "https://www.facebook.com/samplemuseum", "44.0", "-72.0"])
    w.writerow(["8400199996", "GMU", "QUIET MUSEUM", "X", "", "44.0", "-72.0"])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("MuseumFile2018_File1_Nulls.csv", buf.getvalue().encode("latin-1"))
    return out.getvalue()


def test_museum_seeds():
    """IMLS's museums with their own website, merged with Wikidata's (each website once)."""
    imls = museum_access.imls_museums(imls_zip())
    assert [(m["org"], m["place_key"]) for m in imls] == [("Madeup Museum Of Art", "imls-museums:8400199999")]
    wikidata = [{"org": "Madeup Museum of Art", "homepage": "https://madeup-museum.example",
                 "place_key": "wikidata:Q9990010", "lat": "44.004", "lon": "-72.004"},
                {"org": "Sample Science Center", "homepage": "https://www.sample-science.example",
                 "place_key": "wikidata:Q9990011", "lat": "44.01", "lon": "-72.01"}]
    merged = museum_access.merge_seeds(imls, wikidata)
    assert [m["place_key"] for m in merged] == ["imls-museums:8400199999", "wikidata:Q9990011"]


def test_museum_rows_in_the_pack(tmp_path):
    """A museum's rows give its IMLS place the note and the features; a museum matching no place adds nothing."""
    rows, _ = museum_access.scan_museum(client(museum_web()), MUSEUM)
    stray = museum_access.museum_rows({**MUSEUM, "org": "Nowhere Museum", "place_key": "wikidata:Q9990099",
                                       "lat": "44.03", "lon": "-72.03"}, ["braille"], "", "")
    path = tmp_path / "museums.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=museum_access.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows + stray)
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    region = dict(catalogue.regions()[VT])
    pw = PackWriter(str(tmp_path / "extra.osmpack"))
    pw.add_point("imls-museums:8400199999", "imls-museums", "MADEUP MUSEUM OF ART", "landmark", "museum", 44.004,
                 -72.004)
    features.read(str(path), cat["museum-access"], region, pw)
    pw.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "extra.osmpack"))
    assert "touch tours" in pack.notes_for("imls-museums:8400199999")[0]
    names = {r["name"] for r in pack.features_of("imls-museums:8400199999", kinds="accessibility service")}
    assert {"Audio description", "Touch tours", "Braille materials"} <= names
    assert pack.features_near(44.03, -72.03, metres=100) == []
    pack.close()


# ------------------------------------------------------------------------------------------------ wiring

def test_runner_catalogue_contact_and_workflows():
    """The collections "streetaccess" and "museumaccess" in the runner, the four catalogue entries, the contact
    lists (one order everywhere) and the two monthly workflows."""
    specs = dirrun.collections()
    assert set(specs["streetaccess"]["units"]) == {"signals", "curb-ramps-1", "curb-ramps-2", "curb-ramps-3",
                                                   "curb-ramps-4", "mta-elevators", "mbta-elevators",
                                                   "amtrak-stations"}
    assert set(specs["museumaccess"]["units"]) == {f"museums-{i}" for i in range(1, museum_access.SHARDS + 1)}
    assert specs["streetaccess"]["tag"] == "street-access" and specs["museumaccess"]["tag"] == "museum-access"
    assert specs["streetaccess"]["extra_files"] == {od.LIST_FILE: od.RELEASE_LIST}
    assert specs["streetaccess"]["fields"][:len(features.FEATURE_FIELDS)] == features.FEATURE_FIELDS
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    assert cat["street-access"]["reader"] == "site_features" and cat["street-access"]["part"] == "extra"
    assert "curb ramp" not in cat["street-access"]["kinds"] and cat["street-access"]["sites"] is False
    assert cat["street-access-navigation"]["part"] == "navigation"
    assert cat["street-access-navigation"]["reader"] == "nav_street_access"
    assert cat["street-access"]["fetch"] == cat["street-access-navigation"]["fetch"] == {
        "method": "release_csv", "release": "street-access", "prefix": "street-access"}
    assert cat["gtfs-station-features"]["fetch"] == {"method": "same_as", "same_as": "gtfs"}
    assert cat["museum-access"]["keep_unmatched_sites"] is False
    assert cat["museum-access"]["fetch"]["release"] == "museum-access"
    for sid in ("street-access", "gtfs-station-features", "museum-access"):
        assert sid in contact.INSTITUTION_SOURCES and sid in contact.HOURS_SOURCES
    assert lookup.DETAIL_ORDER == writer.CONTACT_ORDER == contact.CONTACT_SOURCES
    assert contact.CONTACT_SOURCES[-1] == "yp-lookups"
    from placepacks.readers import load_all
    readers = load_all()
    assert {"gtfs_station_features", "nav_street_access"} <= set(readers)
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "street-access.yml"), "12")
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "museum-access.yml"), "20")
