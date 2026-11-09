"""Shared test set-up: the program's folder and the repository (for placepacks) on the import path, the program's
own files in a temporary folder (PLI_HOME), no browser, and the stand-in finder with the Outer Banks."""

import datetime as dt
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.path.dirname(HERE)
REPO = os.path.dirname(PROGRAM)
for path in (PROGRAM, REPO, os.path.join(PROGRAM, "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)
os.environ["PLI_NO_BROWSER"] = "1"


@pytest.fixture(autouse=True)
def pli_home(tmp_path, monkeypatch):
    """The program's settings, undo files and reports in a temporary folder for each test."""
    home = tmp_path / "pli-home"
    monkeypatch.setenv("PLI_HOME", str(home))
    monkeypatch.setenv("PLACEPACKS_DIR", str(tmp_path / "no-packs"))
    return home


OBX_AREAS = [
    ("Outer Banks", "region", (35.20, -76.00, 36.55, -75.40)),
    ("Cape Hatteras National Seashore", "park", (35.20, -75.80, 35.90, -75.45)),
    ("Dare County", "admin", (35.20, -76.10, 36.30, -75.42)),
    ("Kill Devil Hills", "town", (35.99, -75.69, 36.06, -75.63)),
    ("Nags Head", "town", (35.90, -75.65, 35.99, -75.58)),
    ("Duck", "town", (36.13, -75.78, 36.22, -75.72)),
    ("Wrightsville Beach", "town", (34.18, -77.83, 34.24, -77.78)),
    ("New Hanover County", "admin", (34.00, -78.00, 34.40, -77.70)),
    ("North Carolina", "state", (33.80, -84.40, 36.60, -75.30)),
    ("United States", "country", (24.0, -125.0, 49.5, -66.0)),
]
KDH, NAGS, DUCK, WB = (36.03, -75.67), (35.94, -75.61), (36.17, -75.75), (34.21, -77.80)
HATTERAS = (35.30, -75.55)            # in the national seashore, outside the towns
JOCKEYS = (35.96, -75.63)


@pytest.fixture
def finder():
    """The stand-in finder: the Outer Banks over three towns, Wrightsville Beach elsewhere, a park, and Vineyard
    Sound off Martha's Vineyard (water) and the Pacific (air)."""
    from pli.places import StandInFinder
    return StandInFinder(areas=OBX_AREAS, places=[("Jockey's Ridge State Park", (35.955, -75.64, 35.97, -75.625))],
                         water=[("Martha's Vineyard", (41.30, -70.70, 41.35, -70.55), "water"),
                                ("the Pacific Ocean", (20.0, -160.0, 40.0, -125.5), "air")])


def photo(folder, name, pos=None, when=None, altitude=None):
    """Write a made-up photo (a colour block) with EXIF GPS (pos: (lat, lon) or None) and date ("2005-07-02 10:00"
    or a datetime). Returns its path."""
    from pli.photos import write_test_photo
    if isinstance(when, str):
        when = dt.datetime.strptime(when, "%Y-%m-%d %H:%M")
    os.makedirs(folder, exist_ok=True)
    lat, lon = pos if pos else (None, None)
    return write_test_photo(os.path.join(str(folder), name), lat, lon, when, altitude)


@pytest.fixture
def album(tmp_path):
    """A folder of made-up photos: the Outer Banks in July 2005 (two towns) and July 2006 (Duck only), Wrightsville
    Beach in August 2007, one photo without GPS taken an hour after an Outer Banks photo, and one without GPS
    and far in time from any other."""
    folder = tmp_path / "album"
    photo(folder, "IMG_0001.jpg", KDH, "2005-07-02 10:00")
    photo(folder, "IMG_0002.jpg", NAGS, "2005-07-04 12:00")
    photo(folder, "IMG_0003.jpg", (36.02, -75.66), "2005-07-08 09:30")
    photo(folder, "IMG_0004.jpg", None, "2005-07-04 13:00")
    photo(folder, "IMG_0005.jpg", DUCK, "2006-07-01 10:00")
    photo(folder, "IMG_0006.jpg", (36.18, -75.752), "2006-07-05 16:00")
    photo(folder, "IMG_0007.jpg", WB, "2007-08-01 10:00")
    photo(folder, "IMG_0008.jpg", (34.215, -77.799), "2007-08-02 11:00")
    photo(folder, "IMG_0009.jpg", None, "2009-01-01 10:00")
    return str(folder)
