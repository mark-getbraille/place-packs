"""The county a photo is filed under comes from placepacks' Finder.areas_at, which keeps only the county versions
valid on the photo's date: an undated photo gets today's county, never an 1800s one beside it. The pack is made
up (two versions of one county over the same square)."""

import datetime as dt

import pytest

from pli.places import Places


@pytest.fixture
def finder(tmp_path):
    """A placepacks Finder on a made-up pack: Old County 1790-01 to 1850-12, New County from 1851-01 on."""
    from placepacks.lookup import Finder, PackReader
    from placepacks.writer import PackWriter
    square = [(43.9, -72.1), (43.9, -71.9), (44.1, -71.9), (44.1, -72.1), (43.9, -72.1)]
    path = str(tmp_path / "us-vermont-extra.osmpack")
    w = PackWriter(path, 202611)
    w.add_area("newberry-counties:1", "newberry-counties", "Old County", "county", "county", [square], 179001, 185012)
    w.add_area("newberry-counties:2", "newberry-counties", "New County", "county", "county", [square], 185101, None)
    w.finish({"region_id": "us-vermont", "region_name": "Vermont", "state": "Vermont", "country": "United States",
              "part": "extra"})
    return Finder(packs=[PackReader(path)], water=False)


def counties(info):
    """The county-level areas of a PlaceInfo."""
    return [a.name for a in info.areas if a.cls == "county"]


def test_an_undated_photo_gets_only_todays_county(finder):
    info = Places(finder=finder).lookup(44.0, -72.0, when=None)
    assert counties(info) == ["New County"]
    assert info.county == "New County"


def test_a_dated_photo_gets_the_county_of_its_date(finder):
    places = Places(finder=finder)
    old, new = places.lookup(44.0, -72.0, when=dt.datetime(1820, 5, 1)), places.lookup(44.0, -72.0,
                                                                                         when=dt.datetime(2005, 7, 4))
    assert (counties(old), old.county) == (["Old County"], "Old County")
    assert (counties(new), new.county) == (["New County"], "New County")
