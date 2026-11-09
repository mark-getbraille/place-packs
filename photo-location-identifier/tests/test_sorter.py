"""Moving and copying, name collisions, companions, the report, Undo the last sort, and My places files."""

import json
import os

import pytest

from conftest import KDH, photo
from pli import grouping, job, myplaces as mp, sorter
from pli.places import Places


def sort(album, finder, dest=None, **opts):
    """Build the plan for album with the stand-in finder and apply it. Returns (plan, outcome)."""
    plan, _ = job.build_plan(album, grouping.options(**opts), Places(finder=finder), "never")
    return plan, sorter.apply(plan, dest)


def tree(folder):
    """{relative path} of every file under folder, without the reports."""
    out = set()
    for here, _, files in os.walk(folder):
        for f in files:
            if "report" not in f:
                out.add(os.path.relpath(os.path.join(here, f), folder).replace(os.sep, "/"))
    return out


def test_move_then_undo_puts_everything_back(album, finder):
    """The Outer Banks album is moved into its folders; Undo puts every file back and removes the folders."""
    before = tree(album)
    plan, out = sort(album, finder, unknown="unknown")
    assert out.moved == 9 and not out.problems
    assert tree(album) == {"Outer Banks 2005/IMG_0001.jpg", "Outer Banks 2005/IMG_0002.jpg",
                           "Outer Banks 2005/IMG_0003.jpg", "Outer Banks 2006/IMG_0005.jpg",
                           "Outer Banks 2006/IMG_0006.jpg", "Wrightsville Beach 2007/IMG_0007.jpg",
                           "Wrightsville Beach 2007/IMG_0008.jpg", "Unknown place/IMG_0004.jpg",
                           "Unknown place/IMG_0009.jpg"}
    report = open(out.report_path, encoding="utf-8-sig").read()
    assert "Outer Banks 2005: 3 photos, 2 to 8 July 2005" in report and "OpenStreetMap" in report
    assert sorter.last_undo() == out.undo_path
    restored, problems = sorter.undo(out.undo_path)
    assert (restored, problems) == (9, [])
    assert tree(album) == before
    assert sorted(d for d in os.listdir(album) if os.path.isdir(os.path.join(album, d))) == []
    assert sorter.last_undo() is None


def test_guess_puts_the_photo_with_its_neighbour(album, finder):
    """With guessing, the photo taken an hour after an Outer Banks photo joins it; the other stays."""
    plan, out = sort(album, finder, unknown="guess")
    assert "Outer Banks 2005/IMG_0004.jpg" in tree(album) and "IMG_0009.jpg" in tree(album)
    assert "probably" in open(out.report_path, encoding="utf-8-sig").read()


def test_copy_and_undo_deletes_only_unchanged_copies(album, finder, tmp_path):
    """Copy leaves the originals; undo deletes the copies, but keeps one that was changed since."""
    dest = str(tmp_path / "sorted")
    plan, out = sort(album, finder, dest=dest, mode="copy")
    assert out.copied == 7 and len(tree(album)) == 9
    changed = os.path.join(dest, "Outer Banks 2006", "IMG_0005.jpg")
    with open(changed, "ab") as f:
        f.write(b"edited")
    restored, problems = sorter.undo(out.undo_path)
    assert restored == 6 and len(problems) == 1 and "changed" in problems[0][1]
    assert tree(dest) == {"Outer Banks 2006/IMG_0005.jpg"}


def test_never_overwrites_and_moves_companions(tmp_path, finder):
    """A name already in the new folder gets " (2)"; the companions get the same new name."""
    album = tmp_path / "a"
    photo(album, "IMG_1.jpg", KDH, "2005-07-02 10:00")
    (album / "IMG_1.AAE").write_text("edit")
    photo(album / "sub", "IMG_1.jpg", KDH, "2005-07-02 11:00")
    photo(album / "Kill Devil Hills 2005", "IMG_1.jpg", None, "2001-01-01 10:00")    # already there, no GPS
    plan, out = sort(str(album), finder, detail="town")
    assert out.moved == 2
    assert tree(str(album)) == {"Kill Devil Hills 2005/IMG_1.jpg", "Kill Devil Hills 2005/IMG_1 (2).jpg",
                                "Kill Devil Hills 2005/IMG_1 (2).AAE", "Kill Devil Hills 2005/IMG_1 (3).jpg"}
    sorter.undo(out.undo_path)
    assert tree(str(album)) == {"IMG_1.jpg", "IMG_1.AAE", "sub/IMG_1.jpg", "Kill Devil Hills 2005/IMG_1.jpg"}


def test_a_second_sort_leaves_sorted_photos_alone(album, finder):
    """Photos already in the folder they belong in are not moved again."""
    sort(album, finder)
    plan, out = sort(album, finder)
    assert out.moved == 0 and out.skipped == 7


def test_stop_part_way_can_be_undone(album, finder):
    """A sort stopped after two photos is undone completely (the undo file was written as it went)."""
    plan, _ = job.build_plan(album, grouping.options(), Places(finder=finder), "never")
    calls = []
    out = sorter.apply(plan, stop=lambda: len(calls) >= 2, progress=lambda d, t, f: calls.append(d))
    assert out.stopped and out.moved == 2 and "stopped" in out.summary()
    header, entries = sorter.read_undo(out.undo_path)
    assert header["mode"] == "move" and sum(e["op"] == "move" for e in entries) == 2
    assert sorter.undo(out.undo_path)[0] == 2


def test_undo_leaves_files_moved_since(album, finder):
    """A file moved again after the sort is reported, not lost; the undo file stays for another try."""
    plan, out = sort(album, finder)
    moved = os.path.join(album, "Outer Banks 2005", "IMG_0001.jpg")
    os.rename(moved, os.path.join(album, "elsewhere.jpg"))
    restored, problems = sorter.undo(out.undo_path)
    assert restored == 6 and problems[0][1] == "it is not there any more"
    assert os.path.exists(out.undo_path)


def test_my_places_files(tmp_path):
    """My places are saved, found within their distance, replaced by name, imported and exported (JSON, CSV)."""
    places = mp.MyPlaces(path=str(tmp_path / "my.json"))
    places.add(mp.MyPlace("Grandma's house", 36.0, -75.7, 200))
    places.add(mp.MyPlace("grandma's HOUSE", 36.0, -75.7, 300))
    places.save()
    again = mp.MyPlaces.load(str(tmp_path / "my.json"))
    assert len(again.places) == 1 and again.places[0].radius_m == 300
    assert again.find(36.0015, -75.7).name == "grandma's HOUSE" and again.find(36.01, -75.7) is None
    again.export(str(tmp_path / "out.csv"))
    other = mp.MyPlaces()
    (tmp_path / "in.csv").write_text("name,latitude,longitude,metres\nCabin,44.1,-72.1,150\nBad,,1,2\n")
    assert other.import_file(str(tmp_path / "in.csv")) == (1, ["line 3: the latitude, longitude and distance must be numbers"])
    assert other.import_file(str(tmp_path / "out.csv"))[0] == 1
    assert [p.name for p in other.places] == ["Cabin", "grandma's HOUSE"]
    with pytest.raises(ValueError):
        mp.MyPlace("", 1, 2)
    with pytest.raises(ValueError):
        mp.MyPlace("x", 100, 2)
    assert json.load(open(tmp_path / "my.json"))["places"][0]["metres"] == 300
