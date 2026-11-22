"""Geofabrik moved each extract into a folder of its own name (November 2026); fetch tries that address first."""

from placepacks import fetch


def test_folder_address():
    flat = "https://download.geofabrik.de/north-america/us/vermont-latest.osm.pbf"
    assert fetch.geofabrik_folder_url(flat) == \
        "https://download.geofabrik.de/north-america/us/vermont/vermont-latest.osm.pbf"
    deep = "https://download.geofabrik.de/europe/france/ile-de-france-latest.osm.pbf"
    assert fetch.geofabrik_folder_url(deep) == \
        "https://download.geofabrik.de/europe/france/ile-de-france/ile-de-france-latest.osm.pbf"


def test_unchanged_addresses():
    already = "https://download.geofabrik.de/north-america/us/vermont/vermont-latest.osm.pbf"
    assert fetch.geofabrik_folder_url(already) == already
    other = "https://www2.census.gov/geo/tiger/x-latest.osm.pbf"
    assert fetch.geofabrik_folder_url(other) == other
    assert fetch.geofabrik_url(other) == other


def test_falls_back_to_flat(monkeypatch):
    def refuse(url, method="GET"):
        raise OSError("HTTP Error 404: Not Found")
    monkeypatch.setattr(fetch, "request", refuse)
    flat = "https://download.geofabrik.de/north-america/us/vermont-latest.osm.pbf"
    assert fetch.geofabrik_url(flat) == flat
