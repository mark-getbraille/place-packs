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
