"""Putting the exact place in each picture's name: the folder keeps the broad place ("Gullwing Coast 2005") and
the name gets the most specific one, in the order of naming.py; the name patterns; not repeating the folder's
place; Windows-safe names and lengths; duplicates; companions; the review preview, the report, the command line,
and Undo putting back the old names. Every place and name here is made up."""

import datetime as dt
import json
import os
import shutil

import pytest

from conftest import photo
from pli import cli, grouping, job, naming, settings, sorter
from pli.photos import Photo
from pli.places import PlaceInfo, Places, Spot, StandInFinder

# A made-up coast: the Gullwing Coast region with two towns, a neighbourhood, a park, a shop that changed its name
# in 2007, two streets (one with a house number), and the water off Tern Island.
AREAS = [
    ("Gullwing Coast", "region", (9.80, 19.80, 10.60, 20.60)),
    ("Pelican Point", "town", (9.90, 19.90, 10.10, 20.10)),
    ("Sandpiper Bay", "town", (10.30, 20.30, 10.50, 20.50)),
    ("Driftwood Heights", "neighbourhood", (10.35, 20.35, 10.37, 20.37)),
    ("Westmarch", "state", (8.0, 18.0, 12.0, 23.0)),
    ("Madeupland", "country", (5.0, 15.0, 15.0, 25.0)),
]
PLACES = [
    ("Heron Dunes State Park", (9.950, 19.950, 9.960, 19.960), {"cls": "park"}),
    ("Captain Ollie's Fish Shack", (10.000, 20.000, 10.001, 20.001), {"cls": "business", "years": (2000, 2006)}),
    ("Sunny Scoops Ice Cream", (10.000, 20.000, 10.001, 20.001), {"cls": "business", "years": (2007, 2030)}),
]
STREETS = [("Seagrass Lane", (10.020, 20.020, 10.030, 20.030), "120"),
           ("Marsh Road", (10.420, 20.420, 10.430, 20.430), "")]
WATER = [("Tern Island", (10.52, 20.52, 10.56, 20.56), "water")]
PARK, SHOP, SEAGRASS = (9.955, 19.955), (10.0005, 20.0005), (10.025, 20.025)
MARSH, DRIFTWOOD, SANDPIPER, PELICAN = (10.425, 20.425), (10.36, 20.36), (10.32, 20.48), (9.92, 19.92)
OFFSHORE = (10.54, 20.54)


@pytest.fixture
def coast():
    """The stand-in finder for the made-up coast."""
    return StandInFinder(areas=AREAS, places=PLACES, water=WATER, streets=STREETS)


def week(folder):
    """A week on the Gullwing Coast in July 2005 (both towns, so the trip is named by the region), and the shop
    again in 2008 under its new name. Returns the folder."""
    photo(folder, "IMG_0001.jpg", PARK, "2005-07-14 10:00")
    photo(folder, "IMG_0002.jpg", SHOP, "2005-07-14 12:00")
    photo(folder, "IMG_0003.jpg", SEAGRASS, "2005-07-14 15:00")
    photo(folder, "IMG_0004.jpg", MARSH, "2005-07-15 10:00")
    photo(folder, "IMG_0005.jpg", DRIFTWOOD, "2005-07-15 11:00")
    photo(folder, "IMG_0006.jpg", SANDPIPER, "2005-07-15 12:00")
    photo(folder, "IMG_0007.jpg", OFFSHORE, "2005-07-15 16:00")
    photo(folder, "IMG_0008.jpg", None, "2005-07-15 17:00")
    photo(folder, "IMG_0009.jpg", SHOP, "2008-08-01 10:00")
    return str(folder)


def plan_of(folder, finder, **opts):
    """The plan with renaming on (and opts)."""
    return job.build_plan(folder, grouping.options(rename=True, **opts), Places(finder=finder), "never")[0]


def names(plan, dest=None):
    """{old file name: new file name} of the pictures that get a new name."""
    return {os.path.basename(p.path): new for _g, p, new in sorter.renamed_names(plan, sorter.preview(plan, dest))}


def tree(folder):
    """{relative path} of every file under folder, without the reports."""
    out = set()
    for here, _, files in os.walk(folder):
        for f in files:
            if "report" not in f:
                out.add(os.path.relpath(os.path.join(here, f), folder).replace(os.sep, "/"))
    return out


# ------------------------------------------------------------ which place goes in the name

def test_exact_place_order():
    """My place, then the named place, then the street address (with the town when the folder does not say it),
    then the neighbourhood, the town, the water; whatever the folder already says is skipped."""
    full = dict(my_place="Aunt Mo's cabin", name="Sunny Scoops Ice Cream", house_number="120",
                street="Seagrass Lane", neighbourhood="Driftwood Heights", town="Pelican Point", water="")
    folder = "Gullwing Coast 2005"
    assert naming.exact_place(Spot(**full), folder) == "Aunt Mo's cabin"
    assert naming.exact_place(Spot(**{**full, "my_place": ""}), folder) == "Sunny Scoops Ice Cream"
    assert naming.exact_place(Spot(**{**full, "my_place": "", "name": ""}), folder) == \
        "120 Seagrass Lane, Pelican Point"
    assert naming.exact_place(Spot(**{**full, "my_place": "", "name": ""}), "Pelican Point 2005") == \
        "120 Seagrass Lane"
    assert naming.exact_place(Spot(street="Marsh Road", town="Sandpiper Bay"), folder) == "Marsh Road, Sandpiper Bay"
    assert naming.exact_place(Spot(neighbourhood="Driftwood Heights", town="Sandpiper Bay"), folder) == \
        "Driftwood Heights"
    assert naming.exact_place(Spot(town="Sandpiper Bay"), folder) == "Sandpiper Bay"
    assert naming.exact_place(Spot(town="Sandpiper Bay"), "Sandpiper Bay 2005") == ""
    assert naming.exact_place(Spot(water="Off Tern Island"), folder) == "Off Tern Island"
    assert naming.exact_place(Spot(water="Off Tern Island"), "Off Tern Island 2005") == ""
    # The folder's own place is never repeated, but a more exact one still comes: My place is the folder here.
    assert naming.exact_place(Spot(my_place="Aunt Mo's cabin", street="Marsh Road", town="Sandpiper Bay"),
                              "Aunt Mo's cabin 2005") == "Marsh Road, Sandpiper Bay"
    # Whole words only: "Bay" alone in a folder does not hide "Sandpiper Bay".
    assert naming.exact_place(Spot(town="Sandpiper Bay"), "Bay trips") == "Sandpiper Bay"
    # A folder named by a park: the town would be wider than the folder, so only the street is added.
    assert naming.exact_place(Spot(street="Marsh Road", town="Sandpiper Bay"), "Heron Dunes 2005", narrow=True) == \
        "Marsh Road"
    assert naming.exact_place(Spot(town="Sandpiper Bay"), "Heron Dunes 2005", narrow=True) == ""
    assert naming.exact_place(None, folder) == "" and naming.exact_place(Spot(), folder) == ""


def test_names_at_the_trip_area_level(tmp_path, coast):
    """In "Gullwing Coast 2005" each picture gets its own exact place; the shop has its 2005 name, and its 2008
    picture its newer name; the photo without a location keeps its name."""
    plan = plan_of(week(tmp_path / "a"), coast, unknown="unknown")
    assert [g.folder for g in plan.groups] == ["Gullwing Coast 2005", "Gullwing Coast 2008", "Unknown place"]
    assert names(plan) == {
        "IMG_0001.jpg": "2005-07-14 Heron Dunes State Park (IMG_0001).jpg",
        "IMG_0002.jpg": "2005-07-14 Captain Ollie's Fish Shack (IMG_0002).jpg",
        "IMG_0003.jpg": "2005-07-14 120 Seagrass Lane, Pelican Point (IMG_0003).jpg",
        "IMG_0004.jpg": "2005-07-15 Marsh Road, Sandpiper Bay (IMG_0004).jpg",
        "IMG_0005.jpg": "2005-07-15 Driftwood Heights (IMG_0005).jpg",
        "IMG_0006.jpg": "2005-07-15 Sandpiper Bay (IMG_0006).jpg",
        "IMG_0007.jpg": "2005-07-15 Off Tern Island (IMG_0007).jpg",
        "IMG_0009.jpg": "2008-08-01 Sunny Scoops Ice Cream (IMG_0009).jpg"}


@pytest.mark.parametrize("detail, expected", [
    ("town", {"IMG_0001.jpg": "2005-07-14 Heron Dunes State Park (IMG_0001).jpg",
              "IMG_0003.jpg": "2005-07-14 120 Seagrass Lane (IMG_0003).jpg",
              "IMG_0004.jpg": "2005-07-15 Marsh Road (IMG_0004).jpg",
              "IMG_0005.jpg": "2005-07-15 Driftwood Heights (IMG_0005).jpg"}),
    ("place", {"IMG_0003.jpg": "2005-07-14 120 Seagrass Lane (IMG_0003).jpg",
               "IMG_0005.jpg": "2005-07-15 Driftwood Heights (IMG_0005).jpg"}),
    ("state", {"IMG_0001.jpg": "2005-07-14 Heron Dunes State Park (IMG_0001).jpg",
               "IMG_0003.jpg": "2005-07-14 120 Seagrass Lane, Pelican Point (IMG_0003).jpg",
               "IMG_0006.jpg": "2005-07-15 Sandpiper Bay (IMG_0006).jpg"}),
])
def test_names_per_place_detail(tmp_path, coast, detail, expected):
    """The folder's level decides what is left to say: under a town folder the town is not repeated, and a photo
    with nothing more exact than its town keeps its name."""
    plan = plan_of(week(tmp_path / "a"), coast, detail=detail)
    got = names(plan)
    for old, new in expected.items():
        assert got.get(old) == new, (old, got)
    if detail == "town":
        assert "IMG_0006.jpg" not in got            # only "Sandpiper Bay" is known: the folder says it already
        assert {g.folder for g in plan.groups} >= {"Pelican Point 2005", "Sandpiper Bay 2005"}
    if detail == "place":
        # The park's own folder ("Heron Dunes State Park 2005") is narrower than a town: nothing wider is added.
        assert "IMG_0001.jpg" not in got and "Heron Dunes State Park 2005" in {g.folder for g in plan.groups}


@pytest.mark.parametrize("pattern, expected", [
    ("date-place-name", "2005-07-14 Heron Dunes State Park (IMG_0001).jpg"),
    ("place-date-name", "Heron Dunes State Park 2005-07-14 (IMG_0001).jpg"),
    ("place-name", "Heron Dunes State Park (IMG_0001).jpg"),
])
def test_name_patterns(tmp_path, coast, pattern, expected):
    """The three patterns of the new names."""
    plan = plan_of(week(tmp_path / "a"), coast, name_pattern=pattern)
    assert names(plan)["IMG_0001.jpg"] == expected


def test_renaming_is_off_by_default(tmp_path, coast):
    """Without the choice nothing is renamed, and the saved setting starts off."""
    assert grouping.DEFAULT_OPTIONS["rename"] is False and settings.load()["rename"] is False
    plan, _ = job.build_plan(week(tmp_path / "a"), grouping.options(), Places(finder=coast), "never")
    assert names(plan) == {}
    with pytest.raises(ValueError):
        grouping.options(name_pattern="nonsense")


def test_guessed_photos_keep_their_names(tmp_path, coast):
    """A photo whose place was guessed from a neighbour in time is moved with it but keeps its name."""
    plan = plan_of(week(tmp_path / "a"), coast, unknown="guess")
    guessed = [p for g in plan.groups for p in g.photos if p.probably]
    assert [os.path.basename(p.path) for p in guessed] == ["IMG_0008.jpg"]
    assert "IMG_0008.jpg" not in names(plan)


# ------------------------------------------------------------ safe names

def _photo(name, spot, when=dt.datetime(2005, 7, 14, 10, 0)):
    """A Photo with a known place and a spot, not read from a file."""
    p = Photo(os.path.join("C:\\", name))
    p.taken, p.info, p.spot = when, PlaceInfo(town="Pelican Point"), spot
    return p


def test_windows_unsafe_characters_and_reserved_names():
    """No < > : " / \\ | ? *, no dot or space at the end, and a reserved name gets "_"."""
    p = _photo("IMG_1.jpg", Spot(name='Bob\'s "Best" Bait: Tackle/Shop? <Pier> | No*1.  '))
    stem = naming.wanted_stem(p, "Gullwing Coast 2005", "date-place-name")
    assert stem == "2005-07-14 Bob's Best Bait Tackle Shop Pier No 1 (IMG_1)"
    assert not any(c in stem for c in '<>:"/\\|?*') and not stem.endswith((".", " "))
    p = _photo("IMG_2.jpg", Spot(name="Con"))
    assert naming.wanted_stem(p, "Gullwing Coast 2005", "place-name") == "_Con (IMG_2)"
    p = _photo("IMG_3.jpg", Spot(name="Nul.   "))
    assert naming.wanted_stem(p, "Gullwing Coast 2005", "place-name").startswith("_Nul")


def test_long_places_are_shortened_and_paths_stay_short(tmp_path):
    """The place is shortened at a word so the name stays within FILE_NAME_LIMIT and the whole path under
    PATH_LIMIT; when even a short place does not fit, the picture keeps its old name."""
    long_name = " ".join(["Grand Old Pelican Point Memorial Boardwalk"] * 6)
    p = _photo("IMG_1234.jpg", Spot(name=long_name))
    stem = naming.wanted_stem(p, "Gullwing Coast 2005", "date-place-name", str(tmp_path), [".JPG.xmp"])
    assert len(stem) + len(".JPG.xmp") <= naming.FILE_NAME_LIMIT
    assert stem.startswith("2005-07-14 Grand Old Pelican") and stem.endswith(" (IMG_1234)")
    assert not stem.endswith(" ") and "  " not in stem
    # A folder deep enough that the long place must be shortened, measured from the temporary folder (whose own
    # length differs: Windows' is much longer).
    room = naming.PATH_LIMIT - 80 - len(os.path.abspath(str(tmp_path))) - 1
    deep = os.path.join(str(tmp_path), "y" * max(room, 1))
    stem = naming.wanted_stem(p, "Gullwing Coast 2005", "date-place-name", deep)
    assert stem is not None and stem.endswith(" (IMG_1234)")
    assert len(os.path.join(os.path.abspath(deep), stem + ".jpg")) + naming.NUMBER_ROOM <= naming.PATH_LIMIT
    deeper = os.path.join(str(tmp_path), "x" * (naming.PATH_LIMIT - 30))
    assert naming.wanted_stem(p, "Gullwing Coast 2005", "date-place-name", deeper) is None


def test_a_second_sort_does_not_wrap_names_twice():
    """A name this program made is recognised, so the old name inside it is used again."""
    p = _photo("2005-07-14 Heron Dunes State Park (IMG_0001).jpg", Spot(name="Heron Dunes State Park"))
    assert naming.wanted_stem(p, "Gullwing Coast 2005", "date-place-name") is None
    assert naming.wanted_stem(p, "Gullwing Coast 2005", "place-name") == \
        "Heron Dunes State Park (2005-07-14 Heron Dunes State Park (IMG_0001))"
    assert naming.original_of("2005-07-14 X (IMG_1) (2)", "2005-07-14 X") == "IMG_1"
    assert naming.is_named("2005-07-14 X (IMG_1) (3)", "2005-07-14 X (IMG_1)")


# ------------------------------------------------------------ sorting, companions, duplicates, undo

def test_sort_rename_companions_duplicates_and_undo(tmp_path, coast):
    """Two IMG_1.jpg at the park (in different folders) get " (2)"; the .AAE and .JPG.xmp sidecars and a RAW+JPG
    pair keep the photo's new base name; Undo puts back both the folder and the old names."""
    album = tmp_path / "a"
    photo(album, "IMG_1.jpg", PARK, "2005-07-14 10:00")
    (album / "IMG_1.AAE").write_text("edit")
    (album / "IMG_1.JPG.xmp").write_text("<xmp/>")
    photo(album / "sub", "IMG_1.jpg", PARK, "2005-07-14 10:05")
    photo(album, "DSC_7.jpg", SHOP, "2005-07-14 12:00")
    shutil.copy(photo(album / "raw", "DSC_7.tif", SHOP, "2005-07-14 12:00"), album / "DSC_7.tif")
    shutil.rmtree(album / "raw")
    before = tree(str(album))
    plan = plan_of(str(album), coast, detail="town")
    out = sorter.apply(plan)
    assert out.moved == 4 and out.renamed == 4 and not out.problems
    assert "4 of them with a new name" in out.summary()
    folder = "Pelican Point 2005/"
    assert tree(str(album)) == {
        folder + "2005-07-14 Heron Dunes State Park (IMG_1).jpg",
        folder + "2005-07-14 Heron Dunes State Park (IMG_1).AAE",
        folder + "2005-07-14 Heron Dunes State Park (IMG_1).JPG.xmp",
        folder + "2005-07-14 Heron Dunes State Park (IMG_1) (2).jpg",
        folder + "2005-07-14 Captain Ollie's Fish Shack (DSC_7).jpg",
        folder + "2005-07-14 Captain Ollie's Fish Shack (DSC_7).tif"}
    header, entries = sorter.read_undo(out.undo_path)
    assert header["rename"] is True and header["name_pattern"] == "date-place-name"
    assert "6 files moved, 6 of them renamed" in sorter.describe_undo(out.undo_path)
    restored, problems = sorter.undo(out.undo_path)
    assert (restored, problems) == (6, [])
    assert tree(str(album)) == before


def test_second_sort_leaves_names_and_renames_in_place(tmp_path, coast):
    """A sort with renaming after a sort without it renames the pictures where they are; a third sort changes
    nothing."""
    album = week(tmp_path / "a")
    job_plan = job.build_plan(album, grouping.options(), Places(finder=coast), "never")[0]
    sorter.apply(job_plan)
    out = sorter.apply(plan_of(album, coast))
    assert out.moved == 8 and out.renamed == 8 and out.folders == []
    assert "Gullwing Coast 2005/2005-07-14 Heron Dunes State Park (IMG_0001).jpg" in tree(album)
    again = sorter.apply(plan_of(album, coast))
    assert again.moved == 0 and again.skipped == 8
    sorter.undo(again.undo_path)
    sorter.undo(out.undo_path)
    assert "Gullwing Coast 2005/IMG_0001.jpg" in tree(album)


def test_copy_with_new_names_and_undo(tmp_path, coast):
    """Copy makes renamed copies elsewhere; the originals keep their names; Undo deletes the copies."""
    album = week(tmp_path / "a")
    dest = str(tmp_path / "sorted")
    out = sorter.apply(plan_of(album, coast, mode="copy"), dest)
    assert out.copied == 8 and "Gullwing Coast 2005/2005-07-15 Off Tern Island (IMG_0007).jpg" in tree(dest)
    assert "IMG_0007.jpg" in tree(album)
    assert sorter.undo(out.undo_path) == (8, [])
    assert tree(dest) == set()


def test_old_undo_files_still_work(tmp_path):
    """An undo file written before renaming existed (no "rename" in its header) is read and undone."""
    folder = tmp_path / "a"
    (folder / "Pelican Point 2005").mkdir(parents=True)
    (folder / "Pelican Point 2005" / "IMG_1.jpg").write_text("x")
    undo_path = tmp_path / "old.jsonl"
    lines = [{"program": "Photo Location Identifier", "version": "1.0.0", "root": str(folder), "dest": str(folder),
              "mode": "move", "time": "2026-01-02T10:00:00"},
             {"op": "mkdir", "path": str(folder / "Pelican Point 2005")},
             {"op": "move", "from": str(folder / "IMG_1.jpg"), "to": str(folder / "Pelican Point 2005" / "IMG_1.jpg")}]
    undo_path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    assert "(1 files moved)" in sorter.describe_undo(str(undo_path))
    assert sorter.undo(str(undo_path)) == (1, [])
    assert tree(str(folder)) == {"IMG_1.jpg"}


# ------------------------------------------------------------ the report and the command line

def test_report_lists_old_and_new_names(tmp_path, coast):
    """The trial-run report and the report after the sort show "old name \u2192 new name" and a count."""
    album = week(tmp_path / "a")
    plan = plan_of(album, coast)
    text = sorter.report_text(plan, dry_run=True)
    assert "Picture names: the exact place put in each name (date-place-name)" in text
    assert "8 pictures would get a new name with the exact place" in text
    assert "IMG_0001.jpg \u2192 2005-07-14 Heron Dunes State Park (IMG_0001).jpg, 2005-07-14 10:00" in text
    out = sorter.apply(plan)
    report = open(out.report_path, encoding="utf-8-sig").read()
    assert "8 pictures got a new name" in report
    assert "IMG_0002.jpg \u2192 2005-07-14 Captain Ollie's Fish Shack (IMG_0002).jpg" in report


def test_command_line_name_pattern(tmp_path, coast, monkeypatch, capsys):
    """--name-pattern turns renaming on with that pattern; --keep-names turns it off; --dry-run moves nothing."""
    album = week(tmp_path / "a")
    monkeypatch.setattr(cli, "Places", lambda **k: Places(finder=coast, **k))
    args = cli.parser().parse_args(["--folder", album, "--name-pattern", "place-date-name"])
    opts = cli.options_from(args, settings.load())
    assert opts["rename"] is True and opts["name_pattern"] == "place-date-name"
    args = cli.parser().parse_args(["--folder", album, "--keep-names", "--name-pattern", "place-name"])
    assert cli.options_from(args, {"rename": True})["rename"] is False
    assert cli.main(["--folder", album, "--name-pattern", "place-name", "--packs", "never", "--dry-run"]) == 0
    assert "IMG_0001.jpg \u2192 Heron Dunes State Park (IMG_0001).jpg" in capsys.readouterr().out
    assert "IMG_0001.jpg" in tree(album)
    assert cli.main(["--folder", album, "--rename", "--packs", "never"]) == 0
    assert "Gullwing Coast 2005/2005-07-14 Heron Dunes State Park (IMG_0001).jpg" in tree(album)
    assert "with a new name" in capsys.readouterr().out
    assert cli.main(["--undo-last"]) == 0
    assert "IMG_0001.jpg" in tree(album)
