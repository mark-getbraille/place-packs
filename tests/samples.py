"""Tiny made-up samples of every source format, for the tests (and tools/make_sample_pack.py). All the places,
addresses and names are invented ("Testville", in Vermont's box so the region filters keep them)."""

import csv
import json
import os
import zipfile

TINY_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="made up for tests">
 <node id="1" lat="44.0000" lon="-72.0000" version="1" timestamp="2026-10-01T00:00:00Z"><tag k="place" v="town"/>
  <tag k="name" v="Testville"/></node>
 <node id="2" lat="44.0010" lon="-72.0030" version="1"/>
 <node id="3" lat="44.0010" lon="-72.0010" version="1"/>
 <node id="4" lat="44.0030" lon="-72.0010" version="1"/>
 <node id="5" lat="44.0030" lon="-72.0030" version="1"/>
 <node id="6" lat="44.0005" lon="-72.0040" version="1"/>
 <node id="7" lat="44.0005" lon="-71.9960" version="1"/>
 <node id="8" lat="44.0006" lon="-71.9980" version="1"><tag k="amenity" v="cafe"/><tag k="name" v="{cafe}"/></node>
 <node id="9" lat="44.0040" lon="-71.9990" version="1"><tag k="place" v="neighbourhood"/>
  <tag k="name" v="Old Mill District"/></node>
 <node id="11" lat="43.9500" lon="-72.0500" version="1"/>
 <node id="12" lat="43.9500" lon="-71.9000" version="1"/>
 <node id="13" lat="44.0500" lon="-71.9000" version="1"/>
 <node id="14" lat="44.0500" lon="-72.0500" version="1"/>
 <node id="15" lat="44.0000" lon="-71.9500" version="1"><tag k="place" v="town"/><tag k="name" v="Nexttown"/></node>
 <way id="100" version="1"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="2"/>
  <tag k="leisure" v="park"/><tag k="name" v="Riverside Park"/></way>
 <way id="101" version="1"><nd ref="6"/><nd ref="7"/><tag k="highway" v="residential"/><tag k="name" v="{street}"/></way>
 <way id="105" version="1"><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="14"/><nd ref="11"/>
  <tag k="place" v="islands"/><tag k="name" v="Outer Banks"/></way>
</osm>
"""

NAD_HEADER = ["AddNo_Full", "StNam_Full", "Post_City", "Inc_Muni", "State", "Latitude", "Longitude", "UUID"]


def osm_file(folder, cafe="Joe's Diner", street="Main Street"):
    """The made-up extract (its café and street names can be changed, for history tests)."""
    path = os.path.join(folder, "tiny.osm")
    with open(path, "w", encoding="utf-8") as f:
        f.write(TINY_OSM.replace("{cafe}", cafe).replace("{street}", street))
    return path


def nad_file(folder, rows):
    """A NAD-like text file in a .zip: rows [(number, street, city, state, lat, lon)]."""
    txt = os.path.join(folder, "NAD_sample.txt")
    with open(txt, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(NAD_HEADER)
        for i, (number, street, city, state, lat, lon) in enumerate(rows):
            w.writerow([number, street, city, "", state, lat, lon, f"uuid-{i}"])
    path = os.path.join(folder, "NAD_sample.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.write(txt, "NAD_sample.txt")
    return path


def gnis_file(folder):
    """A pipe-separated GNIS-like file."""
    path = os.path.join(folder, "DomesticNames_VT.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("feature_id|feature_name|feature_class|state_name|prim_lat_dec|prim_long_dec\n")
        f.write("1001|Riverside Library|Building|Vermont|44.00080|-71.99850\n")
        f.write("1002|Testville Falls|Falls|Vermont|44.0100|-72.0100\n")
        f.write("1003|Somewhere Else|Building|Vermont|0|0\n")
    return path


def addrfeat_folder(folder, name="Main St", lfrom="100", lto="198", rfrom="101", rto="199", tlid=555):
    """A folder with one zipped TIGER ADDRFEAT-like shapefile: one street segment along latitude 44.0005."""
    import shapefile
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, "tl_2025_50001_addrfeat")
    with shapefile.Writer(base, shapeType=shapefile.POLYLINE) as w:
        for field in ("TLID", "FULLNAME", "LFROMHN", "LTOHN", "RFROMHN", "RTOHN", "ZIPL", "ZIPR"):
            w.field(field, "C", size=40)
        w.line([[[-72.0040, 44.0005], [-71.9960, 44.0005]]])
        w.record(str(tlid), name, lfrom, lto, rfrom, rto, "05401", "05401")
    with zipfile.ZipFile(base + ".zip", "w") as z:
        for ext in (".shp", ".shx", ".dbf"):
            z.write(base + ext, os.path.basename(base) + ext)
            os.remove(base + ext)
    return folder


def places_parquet(folder, rows):
    """An Overture-like Parquet file: rows [(id, name, category, lat, lon)]."""
    import duckdb
    path = os.path.join(folder, "places.parquet")
    con = duckdb.connect()
    values = ", ".join(f"('{i}', {{'primary': '{n}'}}, {{'primary': '{c}'}}, {{'xmin': {lon}, 'ymin': {lat}, "
                       f"'xmax': {lon}, 'ymax': {lat}}}, 0.9)" for i, n, c, lat, lon in rows)
    con.execute(f"COPY (SELECT * FROM (VALUES {values}) t(id, names, categories, bbox, confidence)) TO '{path}' "
                "(FORMAT PARQUET)")
    con.close()
    return path


def wikidata_file(folder):
    """A saved SPARQL answer: a building with inception and demolition dates."""
    path = os.path.join(folder, "wikidata.json")
    b = [{"item": {"value": "http://www.wikidata.org/entity/Q999"}, "itemLabel": {"value": "Old Testville Mill"},
          "coord": {"value": "Point(-71.9990 44.0041)"}, "class": {"value": "http://www.wikidata.org/entity/Q41176"},
          "start": {"value": "1923-05-01T00:00:00Z"}, "end": {"value": "1998-01-01T00:00:00Z"}}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"results": {"bindings": b}}, f)
    return path


def gtfs_file(folder):
    """A GTFS feed with one stop."""
    path = os.path.join(folder, "mdb-1.zip")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("stops.txt", "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
                                "S1,Main St & 5th Ave,44.0004,-71.9995,0\n")
    return path


# The navigation part's made-up street corner in Testville: Main Street (east-west, latitude 44.0005) meets Elm Street
# (north-south, longitude -72.0000) at node 20, with traffic signals and a signalled crossing with an accessible
# pedestrian signal on Main Street just west of the corner; a footway crossing Elm Street; a bus stop with a
# shelter and a bench; steps; an entrance; a café that says it is step-free; and a private driveway (left out).
NAV_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="made up for tests">
 <node id="20" lat="44.0005" lon="-72.0000"><tag k="highway" v="traffic_signals"/>
  <tag k="traffic_signals:sound" v="yes"/><tag k="button_operated" v="yes"/></node>
 <node id="21" lat="44.0005" lon="-72.0020"/>
 <node id="22" lat="44.0005" lon="-71.9980"/>
 <node id="23" lat="43.9990" lon="-72.0000"/>
 <node id="24" lat="44.0020" lon="-72.0000"/>
 <node id="25" lat="44.0005" lon="-72.0002"><tag k="highway" v="crossing"/><tag k="crossing" v="traffic_signals"/>
  <tag k="crossing:markings" v="zebra"/><tag k="tactile_paving" v="yes"/><tag k="kerb" v="lowered"/>
  <tag k="traffic_signals:sound" v="yes"/><tag k="traffic_signals:vibration" v="yes"/>
  <tag k="button_operated" v="yes"/></node>
 <node id="26" lat="44.0004" lon="-72.0002"/>
 <node id="27" lat="44.0006" lon="-72.0002"/>
 <node id="28" lat="44.0008" lon="-71.9997"><tag k="highway" v="bus_stop"/><tag k="name" v="Main St &amp; Elm St"/>
  <tag k="shelter" v="yes"/><tag k="bench" v="yes"/><tag k="tactile_paving" v="no"/></node>
 <node id="29" lat="44.0012" lon="-71.9990"/>
 <node id="30" lat="44.0012" lon="-71.9988"/>
 <node id="31" lat="44.0009" lon="-71.9985"><tag k="entrance" v="main"/><tag k="wheelchair" v="yes"/>
  <tag k="automatic_door" v="button"/></node>
 <node id="32" lat="44.0003" lon="-71.9990"><tag k="amenity" v="cafe"/><tag k="name" v="Made-up Café"/>
  <tag k="wheelchair" v="yes"/></node>
 <node id="33" lat="44.0000" lon="-71.9990"/>
 <node id="34" lat="43.9995" lon="-71.9990"/>
 <node id="35" lat="44.0004" lon="-72.0001"><tag k="barrier" v="kerb"/><tag k="kerb" v="flush"/></node>
 <way id="200"><nd ref="21"/><nd ref="25"/><nd ref="20"/><nd ref="22"/><tag k="highway" v="residential"/>
  <tag k="name" v="Main Street"/><tag k="sidewalk" v="both"/><tag k="surface" v="asphalt"/><tag k="lit" v="yes"/></way>
 <way id="201"><nd ref="23"/><nd ref="20"/><nd ref="24"/><tag k="highway" v="tertiary"/><tag k="name" v="Elm Street"/>
  <tag k="sidewalk" v="left"/></way>
 <way id="202"><nd ref="26"/><nd ref="25"/><nd ref="27"/><tag k="highway" v="footway"/><tag k="footway" v="crossing"/>
  <tag k="crossing" v="traffic_signals"/></way>
 <way id="203"><nd ref="29"/><nd ref="30"/><tag k="highway" v="steps"/><tag k="step_count" v="12"/>
  <tag k="handrail" v="yes"/></way>
 <way id="204"><nd ref="33"/><nd ref="34"/><tag k="highway" v="service"/><tag k="service" v="driveway"/></way>
</osm>
"""


def nav_osm_file(folder):
    """The made-up street corner (NAV_OSM)."""
    path = os.path.join(folder, "corner.osm")
    with open(path, "w", encoding="utf-8") as f:
        f.write(NAV_OSM)
    return path


def nav_gtfs_folder(folder):
    """A folder like fetch_gtfs's: one made-up feed (mdb-mdb-9999.zip, route 7 from the Main St & Elm St stop,
    weekdays at 08:05, 08:35 and 25:10 (after midnight), plus a Saturday-only trip; an extra run on Saturday
    2026-11-28 and none on Thursday 2026-11-26) and licences.json."""
    os.makedirs(folder, exist_ok=True)
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,Made-up Transit,https://example.org,"
                      "America/New_York\n",
        "stops.txt": "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,wheelchair_boarding\n"
                     "S1,101,Main St & Elm St,44.0008,-71.9998,0,1\nS2,102,Far Away,44.0300,-72.0300,0,2\n"
                     "ST,,Made-up Station,44.0010,-71.9995,1,1\nX,,Somewhere else,10.0,10.0,0,0\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\nR7,A,7,Elm Street Line,3\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "WK,1,1,1,1,1,0,0,20261101,20270131\nSA,0,0,0,0,0,1,0,20261101,20270131\n",
        "calendar_dates.txt": "service_id,date,exception_type\nWK,20261126,2\nWK,20261128,1\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id,wheelchair_accessible\n"
                     "R7,WK,T1,Downtown,0,1\nR7,WK,T2,Downtown,0,2\nR7,WK,T3,Night Loop,0,1\nR7,SA,T4,Weekend,0,1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "T1,08:05:00,08:05:00,S1,1\nT1,08:20:00,08:20:00,S2,2\nT2,08:35:00,08:35:00,S1,1\n"
                          "T3,25:10:00,25:10:00,S1,1\nT4,09:00:00,09:00:00,S1,1\n",
    }
    path = os.path.join(folder, "mdb-mdb-9999.zip")
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    with open(os.path.join(folder, "licences.json"), "w", encoding="utf-8") as f:
        json.dump({"mdb-9999": "https://creativecommons.org/licenses/by/4.0/"}, f)
    return folder


# The services part's made-up Testville: a Social Security office with its phone, hours and step-free access, a
# motor vehicle office, a food bank drawn as a building, a pharmacy, a defibrillator and an unnamed office (left out).
SVC_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="made up for tests">
 <node id="40" lat="44.0100" lon="-72.0100"><tag k="office" v="government"/><tag k="government" v="social_security"/>
  <tag k="name" v="Social Security Administration"/><tag k="phone" v="+1 800 555 0100"/>
  <tag k="opening_hours" v="Mo-Fr 09:00-16:00"/><tag k="wheelchair" v="yes"/><tag k="addr:housenumber" v="12"/>
  <tag k="addr:street" v="Made-up Street"/><tag k="addr:city" v="Testville"/></node>
 <node id="41" lat="44.0300" lon="-72.0300"><tag k="office" v="government"/><tag k="government" v="transportation"/>
  <tag k="name" v="Testville DMV"/></node>
 <node id="42" lat="44.0020" lon="-72.0020"/>
 <node id="43" lat="44.0020" lon="-72.0010"/>
 <node id="44" lat="44.0030" lon="-72.0010"/>
 <node id="45" lat="44.0002" lon="-72.0001"><tag k="amenity" v="pharmacy"/><tag k="name" v="Pretend Pharmacy"/></node>
 <node id="46" lat="44.0004" lon="-72.0004"><tag k="emergency" v="defibrillator"/></node>
 <node id="47" lat="44.0005" lon="-72.0005"><tag k="office" v="government"/></node>
 <way id="300"><nd ref="42"/><nd ref="43"/><nd ref="44"/><nd ref="42"/><tag k="building" v="yes"/>
  <tag k="amenity" v="social_facility"/><tag k="social_facility" v="food_bank"/>
  <tag k="name" v="Testville Food Shelf"/></way>
</osm>
"""


def svc_osm_file(folder):
    """The made-up offices and services (SVC_OSM)."""
    path = os.path.join(folder, "services.osm")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SVC_OSM)
    return path


def nws_folder(folder, kind):
    """A folder with one zipped NWS-like shapefile: kind "county" (c_16ap26.zip: Made-up County, FIPS 50999, around
    Testville, and a county of another state) or "zone" (z_16ap26.zip: zone VTZ099)."""
    import shapefile
    os.makedirs(folder, exist_ok=True)
    base = os.path.join(folder, "c_16ap26" if kind == "county" else "z_16ap26")
    with shapefile.Writer(base, shapeType=shapefile.POLYGON) as w:
        if kind == "county":
            for field in ("STATE", "CWA", "COUNTYNAME", "FIPS"):
                w.field(field, "C", size=40)
            w.poly([[[-72.1, 43.9], [-72.1, 44.1], [-71.9, 44.1], [-71.9, 43.9], [-72.1, 43.9]]])
            w.record("VT", "BTV", "Made-up", "50999")
            w.poly([[[-72.1, 43.9], [-72.1, 44.1], [-71.9, 44.1], [-71.9, 43.9], [-72.1, 43.9]]])
            w.record("NH", "GYX", "Other State", "33999")
        else:
            for field in ("STATE", "CWA", "NAME", "ZONE"):
                w.field(field, "C", size=40)
            w.poly([[[-72.1, 43.9], [-72.1, 44.1], [-71.9, 44.1], [-71.9, 43.9], [-72.1, 43.9]]])
            w.record("VT", "BTV", "Made-up Valley", "099")
    path = base + ".zip"
    with zipfile.ZipFile(path, "w") as z:
        for ext in (".shp", ".shx", ".dbf"):
            z.write(base + ext, os.path.basename(base) + ext)
            os.remove(base + ext)
    return folder


NWR_JS = """var ST = [];
ST[0] = "VT";
STATE[0] = "Vermont";
COUNTY[0] = "Made-up";
SAME[0] = "050999";
SITENAME[0] = "Pretend Mountain";
SITESTATE[0] = "VT";
FREQ[0] = "162.550";
CALLSIGN[0] = "WXX99";
LAT[0] = "44.05";
LON[0] = "-72.05";
PWR[0] = "1000";
STATUS[0] = "NORMAL";
WFO[0] = "Burlington|VT";
REMARKS[0] = "";

ST[1] = "VT";
COUNTY[1] = "Made-up";
SAME[1] = "050999";
SITENAME[1] = "Faraway Hill";
SITESTATE[1] = "NH";
FREQ[1] = "162.475";
CALLSIGN[1] = "WXX98";
LAT[1] = "44.50";
LON[1] = "-72.50";
PWR[1] = "300";
STATUS[1] = "OUT OF SERVICE";
WFO[1] = "Gray|ME";

ST[2] = "NH";
COUNTY[2] = "Other State";
SAME[2] = "033999";
SITENAME[2] = "Elsewhere";
FREQ[2] = "162.400";
CALLSIGN[2] = "WXX97";
LAT[2] = "43.0";
LON[2] = "-71.0";
"""


def nwr_file(folder):
    """A made-up county coverage list (CCL.js)."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "CCL.js")
    with open(path, "w", encoding="utf-8") as f:
        f.write(NWR_JS)
    return path


# The routing test town: Main Street runs east from node 1 through Oak Street (node 2, with a signalled crossing of
# Oak Street just south of the corner) and Elm Street (node 3) to node 4; Oak and Elm run north to Pine Street, a
# one-way street eastbound; Elm goes on north to node 12, beside Made-up Hardware (phone and hours).
ROUTE_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="made up for tests">
 <node id="1" lat="44.0000" lon="-72.0030"/>
 <node id="2" lat="44.0000" lon="-72.0020"/>
 <node id="3" lat="44.0000" lon="-72.0010"/>
 <node id="4" lat="44.0000" lon="-72.0000"/>
 <node id="6" lat="43.99995" lon="-72.0020"><tag k="highway" v="crossing"/><tag k="crossing" v="traffic_signals"/>
  <tag k="tactile_paving" v="yes"/><tag k="button_operated" v="yes"/><tag k="traffic_signals:sound" v="yes"/>
  <tag k="kerb" v="lowered"/></node>
 <node id="8" lat="43.9990" lon="-72.0020"/>
 <node id="9" lat="44.0010" lon="-72.0020"/>
 <node id="10" lat="43.9990" lon="-72.0010"/>
 <node id="11" lat="44.0010" lon="-72.0010"/>
 <node id="12" lat="44.0020" lon="-72.0010"/>
 <node id="60" lat="44.0019" lon="-72.0008"><tag k="shop" v="hardware"/><tag k="name" v="Made-up Hardware"/>
  <tag k="phone" v="+1 802 555 0199"/><tag k="opening_hours" v="Mo-Sa 08:00-18:00"/><tag k="wheelchair" v="yes"/></node>
 <node id="61" lat="44.0011" lon="-72.0025"><tag k="amenity" v="place_of_worship"/><tag k="religion" v="christian"/>
  <tag k="denomination" v="catholic"/><tag k="name" v="Saint Pretend Church"/></node>
 <node id="62" lat="43.9992" lon="-72.0005"><tag k="amenity" v="place_of_worship"/><tag k="religion" v="muslim"/>
  <tag k="name" v="Made-up Masjid"/></node>
 <node id="63" lat="43.9993" lon="-72.0028"><tag k="amenity" v="place_of_worship"/><tag k="religion" v="jewish"/>
  <tag k="denomination" v="orthodox"/><tag k="name" v="Beth Pretend"/></node>
 <way id="400"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><tag k="highway" v="residential"/>
  <tag k="name" v="Main Street"/></way>
 <way id="401"><nd ref="8"/><nd ref="6"/><nd ref="2"/><nd ref="9"/><tag k="highway" v="residential"/>
  <tag k="name" v="Oak Street"/></way>
 <way id="402"><nd ref="10"/><nd ref="3"/><nd ref="11"/><nd ref="12"/><tag k="highway" v="residential"/>
  <tag k="name" v="Elm Street"/></way>
 <way id="403"><nd ref="9"/><nd ref="11"/><tag k="highway" v="residential"/><tag k="name" v="Pine Street"/>
  <tag k="oneway" v="yes"/></way>
</osm>
"""


def route_osm_file(folder):
    """The routing test town (ROUTE_OSM)."""
    path = os.path.join(folder, "town.osm")
    with open(path, "w", encoding="utf-8") as f:
        f.write(ROUTE_OSM)
    return path


def polling_folder(folder):
    """A folder like fetch_polling's: the made-up 2020 general election list of Testville (one address the made-up
    address points know, one they do not)."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "polling_2020-11-03.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("election_date,state,county_name,jurisdiction,jurisdiction_type,precinct_id,precinct_name,"
                "polling_place_id,location_type,name,address,notes,source,source_date,source_notes\n"
                "2020-11-03,VT,,Testville,municipality,,,,,TESTVILLE TOWN HALL,\"12 MAIN ST, TESTVILLE, VT 05401\","
                ",ORR,2020-10-01,\n"
                "2020-11-03,VT,,Nexttown,municipality,,,,,NEXTTOWN SCHOOL,\"99 NOWHERE RD, NEXTTOWN, VT 05402\","
                ",ORR,2020-10-01,\n")
    return folder
