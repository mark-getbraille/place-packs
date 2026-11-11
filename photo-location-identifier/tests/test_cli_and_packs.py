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


def test_real_placepacks_exact_place_in_names(real_pack, tmp_path):
    """With the real placepacks, --rename looks the photos up at the "address" detail without trouble, the folders
    stay as without it, every photo gets a name that is safe and does not repeat its folder's place, and Undo puts
    back the old names."""
    from pli import naming
    photos = str(tmp_path / "photos")
    make_test_pack.write_photos(photos)
    before = sorted(os.listdir(photos))
    spot = Places(packs_folder=real_pack).exact(35.96, -75.63)
    assert spot.name == "Jockey's Ridge State Park" and spot.town == "Nags Head"
    assert cli.main(["--folder", photos, "--packs", "never", "--packs-folder", real_pack, "--rename"]) == 0
    made = sorted(d for d in os.listdir(photos) if os.path.isdir(os.path.join(photos, d)))
    assert made == make_test_pack.EXPECTED_FOLDERS
    for d in made:
        for f in os.listdir(os.path.join(photos, d)):
            assert not any(c in f for c in '<>:"/\\|?*') and len(f) <= naming.FILE_NAME_LIMIT
            assert d.rsplit(" ", 1)[0] not in f, (d, f)
    assert cli.main(["--undo-last"]) == 0
    assert sorted(f for f in os.listdir(photos) if not f.endswith(".txt")) == before


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
    monkeypatch.setattr(download, "ensure_packs", lambda region, parts=None, **k: got.append(region))
    places = Places(packs_folder=str(tmp_path))
    asked = []
    positions = [(36.03, -75.67), (35.94, -75.61)]
    done, problems = places.get_packs(positions, "ask", ask=lambda *a: asked.append(a) or False,
                                      catalogue=FakeCatalogue())
    assert asked == [("North Carolina, United States", 12_000_000, 2)] and got == [] and done == []
    done, _ = places.get_packs(positions, "auto", catalogue=FakeCatalogue())
    assert got == ["us-north-carolina"] and done == ["North Carolina, United States"]
    assert places.get_packs(positions, "never", ask=lambda *a: 1 / 0) == ([], [])


class FullCatalogue:
    """Stands in for placepacks.download.Catalogue: every part of North Carolina, and the sub-regions of Texas."""

    class Info:
        def __init__(self, size):
            self.size = size

    def packs(self):
        keys = {"us-north-carolina": 12, "us-north-carolina-extra": 30, "us-north-carolina-businesses": 50,
                "us-north-carolina-addresses": 80, "us-texas-gulf-coast": 60, "us-texas-gulf-coast-extra": 20,
                "us-texas-south-central": 50, "us-texas-south-central-extra": 20}
        return {k: self.Info(v * 1_000_000) for k, v in keys.items()}


def test_detail_parts_and_sub_regions(monkeypatch, tmp_path):
    """Core and extra by default; the businesses and address points too for the exact place in the pictures' names
    or with "Download full detail"; a photo near the border of two parts of Texas gets both, with one question
    each naming the part and its size."""
    pytest.importorskip("placepacks.download")
    from placepacks import download
    got = []
    monkeypatch.setattr(download, "ensure_packs", lambda region, parts=None, **k: got.append((region, tuple(parts))))
    nc = [(36.03, -75.67)]
    places = Places(packs_folder=str(tmp_path))
    places.get_packs(nc, "auto", catalogue=FullCatalogue())
    assert got == [("us-north-carolina", ("core", "extra"))]
    got.clear()
    places.get_packs(nc, "auto", catalogue=FullCatalogue(), exact=True)
    assert got == [("us-north-carolina", ("core", "extra", "businesses", "addresses"))]
    got.clear()
    Places(packs_folder=str(tmp_path), full_detail=True).get_packs(nc, "auto", catalogue=FullCatalogue())
    assert got[0][1] == ("core", "extra", "businesses", "addresses")
    # Already here: nothing more is downloaded.
    for part in ("", "-extra"):
        open(tmp_path / f"us-north-carolina{part}.osmpack", "wb").close()
    got.clear()
    assert places.get_packs(nc, "auto", catalogue=FullCatalogue()) == ([], []) and got == []
    # The border of Texas's Gulf Coast and Central and South parts (sub-regions), about 1 km apart.
    from placepacks import regions
    lat, lon = 28.8, -97.3
    while not regions.in_region(regions.REGIONS["us-texas-gulf-coast"], lat, lon):
        lon += 0.001
    asked = []
    places.get_packs([(lat, lon + 0.005)], "ask", ask=lambda *a: asked.append(a) or True,
                     catalogue=FullCatalogue())
    assert [a[0] for a in asked] == ["Texas: Gulf Coast, United States", "Texas: Central and South, United States"]
    assert asked[0][1] == 80_000_000 and {g[0] for g in got} == {"us-texas-gulf-coast", "us-texas-south-central"}
