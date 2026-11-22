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
    assert fetch.geofabrik_candidates(other) == [other]


def test_download_tries_folder_then_flat(monkeypatch, tmp_path):
    """A 404 at the folder address moves on to the flat one; the .md5 check uses the address that worked."""
    import urllib.error
    flat = "https://download.geofabrik.de/north-america/us/vermont-latest.osm.pbf"
    tried, checked = [], []

    def fake_download(url, target, pause=0):
        tried.append(url)
        if "/vermont/" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        import os
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "wb").close()
        return "v1", "2026-11-22"
    monkeypatch.setattr(fetch, "download", fake_download)
    monkeypatch.setattr(fetch, "md5_ok", lambda path, url: checked.append(url) or True)
    entry = {"id": "osm", "fetch": {"method": "http", "url": "https://download.geofabrik.de/{geofabrik}-latest.osm.pbf",
                                    "md5": True, "file": "extract.osm.pbf"}}
    out = fetch.fetch_source(entry, {}, {"geofabrik": "north-america/us/vermont"}, str(tmp_path), None)
    assert tried == [fetch.geofabrik_folder_url(flat), flat] and checked == [flat] and out["ok"]
