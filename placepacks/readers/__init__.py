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
  placepacks/details.py  the "details" reader: phone, website and hours for places other sources list (Yellow Pages
              lookups, the businesses' own homepages)
  placepacks/features.py  the "site_features" reader: features inside or around a site (accessible entrances,
              elevators, buildings ...) from the collectors' CSV files (placepacks/mapvendors, placepacks/health_access)
  osm_features.py  the "osm_site_features" reader: OpenStreetMap's buildings, entrances, elevators, accessible
              toilets and parking inside campus, hospital, zoo, mall and other site areas
  placepacks/schools.py  the "key_details" reader: phone, website and a note for schools and colleges by their NCES id
  gtfs_stations.py  the "gtfs_station_features" reader: GTFS stations' entrances, elevators, escalators and stairs
              (pathways.txt) as site features, and the stops' wheelchair boarding as notes
  street_access.py  the "nav_street_access" reader: cities' accessible pedestrian signals and curb ramps
              (placepacks/street_access) into the navigation part
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
    from placepacks import details  # noqa: F401 - the "details" reader (details-only sources)
    from placepacks import features, schools  # noqa: F401 - the "site_features" and "key_details" readers
    from placepacks.readers import osm_features  # noqa: F401 - the "osm_site_features" reader
    # The GTFS stations' entrances, elevators and stairs ("gtfs_station_features") and the open-data signals and
    # curb ramps of the navigation part ("nav_street_access"), queue item Q4.
    from placepacks.readers import gtfs_stations, street_access  # noqa: F401
    return READERS
