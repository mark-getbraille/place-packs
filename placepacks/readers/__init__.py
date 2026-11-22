"""The readers of the place pack sources. Each reader takes a local input (a file or a folder that the fetch step
downloaded), the source's catalogue entry (sources.json) and the region, and adds its records to a PackWriter:

  osm.py      OpenStreetMap extracts (.osm.pbf with pyosmium, .osm with the standard library)
  tabular.py  delimited text: address points (NAD, ODA, OpenAddresses) and named points (GNIS, NCES, IMLS, StatCan
              facilities, FAA, NTAD, NRHP, Canadian names), mapped by the entry's "columns"
  shapes.py   shapefiles (pyshp, MIT): TIGER/Line address ranges and Census areas, PAD-US, trails
  parquet.py  GeoParquet (DuckDB, MIT): Overture Maps places, Foursquare Open Source Places
  gtfs.py     public transit stops from GTFS feeds
  wikidata.py Wikidata query results (names, coordinates and start/end dates)
  sqlite_query.py  SQLite and GeoPackage files a source publishes (GNIS variant names and historical features)
  navigation.py  the navigation part: OpenStreetMap's street network and accessibility details, and the GTFS
              timetables (osm_navigation, gtfs_navigation)
  services.py    the services part: OpenStreetMap's offices and services (osm_services), the NWS county and forecast
              zones (nws_zones) and the NOAA Weather Radio county coverage list (nwr)
  ohm.py      OpenHistoricalMap features (CC0) with their own start and end dates, from its Overpass API
"""

READERS = {}


def reader(name):
    """Register a reader function under name (the "reader" of a catalogue entry)."""
    def register(fn):
        """Add fn to READERS and give it back unchanged (the decorator itself)."""
        READERS[name] = fn
        return fn
    return register


def load_all():
    """Import every reader module, so READERS is complete."""
    from placepacks.readers import (gtfs, navigation, ohm, osm, parquet, services, shapes,  # noqa: F401
                                    sqlite_query, tabular, wikidata)
    return READERS
