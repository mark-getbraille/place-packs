"""The command line, and the real placepacks: a tiny pack built with placepacks' own builder from a made-up
OpenStreetMap file (tools/make_test_pack.py, the same one the installer's smoke test uses), and the pack
download question (ask, automatic, never) with placepacks' download module given a made-up catalogue."""

import os

import pytest

import make_test_pack
from pli import cli, sorter
from pli.places import Places


@pytest.fixture(scope="module")
def real_pack(tmp_path_factory):
    """The made-up North Carolina pack, built with placepacks (skipped if placepacks cannot build here)."""
    pytest.importorskip("placepacks.lookup")
    folder = tmp_path_factory.mktemp("packs")
    make_test_pack.build(str(folder))
    return str(folder)


def test_real_placepacks_outer_banks(real_pack, tmp_path, capsys):
    """The command line with the real placepacks: Outer Banks 2005, Outer Banks 2006, Wrightsville Beach 2007."""
    photos = str(tmp_path / "photos")
    make_test_pack.write_photos(photos)
    code = cli.main(["--folder", photos, "--packs", "never", "--packs-folder", real_pack, "--detail", "trip-area",
                     "--time", "year", "--template", "{place} {year}"])
    assert code == 0
    made = sorted(d for d in os.listdir(photos) if os.path.isdir(os.path.join(photos, d)))
    assert made == make_test_pack.EXPECTED_FOLDERS
    out = capsys.readouterr().out
    assert "Moved 7 photos into 3 new folders." in out
    report = open(next(os.path.join(photos, f) for f in os.listdir(photos) if f.endswith(".txt")),
                  encoding="utf-8-sig").read()
    assert "OpenStreetMap" in report


def test_real_placepacks_place_detail(real_pack):
    """The park comes from the pack at the place detail; the admin areas give the county."""
    places = Places(packs_folder=real_pack)
    park = places.lookup(35.96, -75.63)
    assert park.place == "Jockey's Ridge State Park" and park.town == "Nags Head"
    assert park.county == "Dare County" and park.state == "North Carolina"
    assert [a.name for a in park.areas if not a.level] == ["Jockey's Ridge State Park", "Outer Banks"]


def test_dry_run_moves_nothing(album, finder, monkeypatch, capsys, tmp_path):
    """--dry-run prints the plan (and --report writes it) without moving anything."""
    monkeypatch.setattr(cli, "Places", lambda **k: Places(finder=finder, **{x: y for x, y in k.items()
                                                                             if x == "my_places"}))
    report = str(tmp_path / "plan.txt")
    assert cli.main(["--folder", album, "--dry-run", "--report", report, "--unknown", "unknown"]) == 0
    out = capsys.readouterr().out
    assert "trial run" in out and "Outer Banks 2005: 3 photos" in out and "Unknown place: 2 photos" in out
    assert sorted(os.listdir(album))[0] == "IMG_0001.jpg" and len(os.listdir(album)) == 9
    assert "Outer Banks 2006" in open(report, encoding="utf-8").read()


def test_cli_sort_copy_template_and_undo(album, finder, monkeypatch, capsys, tmp_path):
    """--copy --to with a "{year}\\{place}" template makes nested folders; --undo-last removes the copies."""
    monkeypatch.setattr(cli, "Places", lambda **k: Places(finder=finder))
    dest = str(tmp_path / "sorted")
    assert cli.main(["--folder", album, "--copy", "--to", dest, "--template", "{year}\\{place}"]) == 0
    assert os.path.exists(os.path.join(dest, "2005", "Outer Banks", "IMG_0001.jpg"))
    assert os.path.exists(os.path.join(album, "IMG_0001.jpg"))
    assert cli.main(["--undo-last"]) == 0
    assert not os.path.exists(os.path.join(dest, "2005"))
    assert cli.main(["--undo-last"]) == 1
    assert "There is no sort to undo." in capsys.readouterr().out


def test_cli_my_places_file(album, finder, monkeypatch, tmp_path):
    """--my-places names the photos inside one of them."""
    from pli import myplaces as mp
    f = str(tmp_path / "mine.json")
    mp.MyPlaces([mp.MyPlace("Beach house", 34.21, -77.80, 2000)]).save(f)
    seen = {}

    def make(**k):
        seen.update(k)
        return Places(finder=finder, my_places=k["my_places"])
    monkeypatch.setattr(cli, "Places", make)
    assert cli.main(["--folder", album]) == 0
    assert os.path.isdir(os.path.join(album, "Wrightsville Beach 2007"))
    sorter.undo(sorter.last_undo())
    assert cli.main(["--folder", album, "--my-places", f]) == 0
    assert os.path.isdir(os.path.join(album, "Beach house 2007"))


def test_cli_rejects_a_missing_folder(tmp_path, capsys):
    """A folder that does not exist: exit code 2 and a plain message."""
    assert cli.main(["--folder", str(tmp_path / "nope")]) == 2
    assert "is not a folder that exists" in capsys.readouterr().err


class FakeCatalogue:
    """Stands in for placepacks.download.Catalogue: one pack, North Carolina, 12 MB."""

    class Info:
        size = 12_000_000
        name = "us-north-carolina.osmpack"

    def packs(self):
        return {"us-north-carolina": self.Info()}


def test_pack_downloads_ask_auto_never(monkeypatch, tmp_path):
    """Ask: the question has the region, size and photo count, and No downloads nothing; Automatic downloads
    without asking; Never does not even look. Only the region id goes to the download."""
    pytest.importorskip("placepacks.download")
    from placepacks import download
    got = []
    monkeypatch.setattr(download, "ensure_pack", lambda region, part="core", **k: got.append(region))
    places = Places(packs_folder=str(tmp_path))
    asked = []
    positions = [(36.03, -75.67), (35.94, -75.61)]
    done, problems = places.get_packs(positions, "ask", ask=lambda *a: asked.append(a) or False,
                                      catalogue=FakeCatalogue())
    assert asked == [("North Carolina, United States", 12_000_000, 2)] and got == [] and done == []
    done, _ = places.get_packs(positions, "auto", catalogue=FakeCatalogue())
    assert got == ["us-north-carolina"] and done == ["North Carolina, United States"]
    assert places.get_packs(positions, "never", ask=lambda *a: 1 / 0) == ([], [])
