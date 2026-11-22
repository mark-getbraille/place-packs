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
