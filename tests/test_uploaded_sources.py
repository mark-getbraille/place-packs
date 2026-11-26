"""The fetch method "uploaded_national" (placepacks/uploaded.py): Foursquare's places read from the owner's upload
in the release "uploaded-sources" (made by Program Downloader from the Hugging Face dataset). A stand-in gh serves a
made-up release from a folder; every file and place here is made up. Covered: the newest complete date is used (a
date without its manifest is not), no release or no manifest skips the source with the owner's reason (never a
failure), the files are checked by their SHA-256 and read one at a time into the national slice with only the
covered countries (Puerto Rico's PR too) and the build's columns, a damaged file is never read, the regions read
their slice, the NOTICE check, and the workflow step's read-only token."""

import hashlib
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, split, uploaded  # noqa: E402

duckdb = pytest.importorskip("duckdb")
DT = "2026-11-17"
NOTICE = "Foursquare Open Source Places\nCopyright 2024 Foursquare Labs, Inc.\n"
ROWS = [  # fsq_place_id, name, category labels, lat, lon, country, created, closed
    ("a1", "Made-up Cafe", "['Dining and Drinking > Cafe']", 44.26, -72.58, "US", "2015-03-01", None),
    ("a2", "Made-up Closed Diner", "['Dining and Drinking > Diner']", 44.27, -72.57, "US", "2010-01-01", "2020-06-01"),
    ("b1", "Made-up San Juan Shop", "['Retail > Shop']", 18.45, -66.07, "PR", "2018-05-05", None),
    ("c1", "Made-up Paris Bakery", "['Dining and Drinking > Bakery']", 48.85, 2.35, "FR", "2019-01-01", None),
    ("d1", "Made-up Brazil Bar", "['Dining and Drinking > Bar']", -23.5, -46.6, "BR", "2019-01-01", None),
]


def entry():
    """The Foursquare entry of the catalogue (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == "fsq-places")))


def write_places(path, rows):
    """A made-up Foursquare Parquet file with the columns of the real one the build uses (and a few more: the
    address, and the e-mail and social accounts that are never read)."""
    con = duckdb.connect()
    values = ", ".join(
        f"('{i}', '{n}', {c}::VARCHAR[], {la}, {lo}, '{cc}', DATE '{cr}', "
        f"{'DATE ' + repr(cl) if cl else 'NULL'}::DATE, 'Somewhere St', '05602', '(802) 555-01{k:02d}', "
        f"'https://shop{k}.example/', 'owner{k}@example.com', 'madeup{k}')"
        for k, (i, n, c, la, lo, cc, cr, cl) in enumerate(rows))
    con.execute(f"COPY (SELECT * FROM (VALUES {values}) t(fsq_place_id, name, fsq_category_labels, latitude, "
                f"longitude, country, date_created, date_closed, address, postcode, tel, website, email, "
                f"instagram)) TO '{path}' (FORMAT PARQUET)")


class FakeRelease:
    """A stand-in for gh: the release "uploaded-sources" is a folder of files; api calls list them (id, then pages
    of assets), release download copies one out. Every call is kept in .calls."""

    def __init__(self, folder, exists=True):
        """folder: the release's files; exists: False for no release at all."""
        self.folder, self.exists, self.calls, self.broken = folder, exists, [], set()

    def __call__(self, args, timeout=1800):
        """Answer like gh."""
        self.calls.append(args)
        if args[0] == "api":
            if not self.exists:
                return 1, "", "gh: Not Found (HTTP 404)"
            if args[1].endswith("/releases/tags/uploaded-sources"):
                return 0, "77\n", ""
            assert args[1].startswith("repos/") and "/releases/77/assets" in args[1] and "--paginate" in args
            return 0, "".join(f"{n}\t{os.path.getsize(os.path.join(self.folder, n))}\n"
                              for n in sorted(os.listdir(self.folder))), ""
        if args[:2] == ["release", "download"]:
            name, target = args[args.index("--pattern") + 1], args[args.index("--dir") + 1]
            source = os.path.join(self.folder, name)
            if not os.path.exists(source):
                return 1, "", f"no assets match the file pattern {name}"
            shutil.copy(source, os.path.join(target, name))
            if name in self.broken:
                with open(os.path.join(target, name), "ab") as f:
                    f.write(b"damaged")
            return 0, "", ""
        return 1, "", f"unknown {args}"


def upload(folder, dt=DT, rows=ROWS, manifest=True):
    """What Program Downloader uploads for one date: two files, the NOTICE and (unless not) the manifest."""
    os.makedirs(folder, exist_ok=True)
    files = []
    for i, part in enumerate((rows[:3], rows[3:])):
        name = f"fsq-{dt}-places_00000{i}.parquet"
        write_places(os.path.join(folder, name), part)
        data = open(os.path.join(folder, name), "rb").read()
        files.append({"name": name, "source_path": f"release/dt={dt}/places/parquet/places_00000{i}.parquet",
                      "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    with open(os.path.join(folder, f"fsq-{dt}-NOTICE.txt"), "w") as f:
        f.write(NOTICE)
    if manifest:
        with open(os.path.join(folder, f"fsq-{dt}.json"), "w") as f:
            json.dump({"dt": dt, "files": files, "licence": "Apache-2.0", "notice": NOTICE}, f)


@pytest.fixture
def release(tmp_path, monkeypatch):
    """The stand-in release (empty), in place of gh, and a fresh file-list cache."""
    folder = tmp_path / "release"
    folder.mkdir()
    fake = FakeRelease(str(folder))
    monkeypatch.setattr(uploaded, "run_gh", fake)
    monkeypatch.setattr(uploaded.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/place-packs")
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(tmp_path))
    return fake


def test_no_release_or_no_manifest_waits_for_the_owner(release, tmp_path):
    release.exists = False
    with pytest.raises(uploaded.Waiting, match="waiting for the owner's upload from Program Downloader"):
        uploaded.version(entry())
    region = catalogue.regions()["us-vermont"]
    got = fetch._fetch_one(entry(), region, catalogue.load(), str(tmp_path / "w"), None, True)
    assert got["status"] == "skipped" and got["reason"].startswith("waiting for the owner's upload")
    # a date whose manifest is not there yet (an upload still running) is not used either
    release.exists = True
    assert not os.path.exists(uploaded._cache_path("uploaded-sources"))   # "no release" is never kept
    upload(release.folder, manifest=False)
    got = fetch._fetch_one(entry(), region, catalogue.load(), str(tmp_path / "w"), None, True)
    assert got["status"] == "skipped" and got["reason"] == uploaded.WAITING
    # and the prepare job leaves the layer out, saying why, without failing
    fetch.prepare_uploaded(entry(), str(tmp_path / "national"))
    note = tmp_path / "national" / "fsq-places" / fetch.FAILED
    assert note.read_text().startswith("waiting for the owner's upload")


def test_the_newest_complete_date_is_the_version(release):
    upload(release.folder, "2026-10-15")
    upload(release.folder, DT)
    upload(release.folder, "2026-12-15", manifest=False)       # still uploading
    assert uploaded.newest(entry()) == (DT, f"fsq-{DT}.json")
    assert uploaded.version(entry()) == f"uploaded-sources/fsq-{DT}"
    # the file list is asked once and reused by the next regions
    asked = len(release.calls)
    uploaded.version(entry())
    assert len(release.calls) == asked


def test_the_upload_is_read_once_into_the_national_slice_and_split(release, tmp_path, capsys):
    upload(release.folder)
    national = tmp_path / "national"
    fetch.prepare(str(national), cat={"accepted": [entry()]})
    target = national / "fsq-places" / "fsq-places.parquet"
    con = duckdb.connect()
    rows = con.execute(f"SELECT * FROM read_parquet('{target}') ORDER BY fsq_place_id").fetchall()
    columns = [d[0] for d in con.description]
    assert columns == ["fsq_place_id", "name", "fsq_category_labels", "latitude", "longitude", "date_created",
                       "date_closed", "tel", "website"]      # only what the build uses: never email or socials
    assert [r[0] for r in rows] == ["a1", "a2", "b1", "c1"]    # US, Puerto Rico (PR) and France; not Brazil
    assert (national / "fsq-places" / "fsq-places.parquet.version").read_text() == f"uploaded-sources/fsq-{DT}"
    downloads = [c for c in release.calls if c[:2] == ["release", "download"]]
    assert [c[c.index("--pattern") + 1] for c in downloads] == [f"fsq-{DT}.json", f"fsq-{DT}-places_000000.parquet",
                                                                f"fsq-{DT}-places_000001.parquet"]
    assert all("owner/place-packs" in c for c in downloads)
    leftovers = [n for n in os.listdir(tmp_path) if n.startswith("fsq-places-")]
    assert leftovers == []                                    # the raw files and pieces are gone
    assert "::warning::" not in capsys.readouterr().out       # the repository's NOTICE has Foursquare's notice
    # split per region, then a region reads its slice with the history dates
    regions = {k: v for k, v in catalogue.regions().items() if k in ("us-vermont", "us-puerto-rico")}
    counts = split.split_parquet(entry(), str(target), str(tmp_path / "split"), regions)
    assert counts == {"us-vermont": 2, "us-puerto-rico": 1}
    region_national = tmp_path / "split" / "us-vermont"
    got = fetch.fetch_source(entry(), catalogue.regions()["us-vermont"], {}, str(tmp_path / "work"),
                             str(region_national))
    assert got["ok"] and got["version"] == f"uploaded-sources/fsq-{DT}"
    sliced = con.execute(f"SELECT key, name, first, last, phone, website FROM read_parquet('{got['path']}') ORDER BY "
                         "key").fetchall()
    assert sliced == [("a1", "Made-up Cafe", "2015-03-01", None, "(802) 555-0100", "https://shop0.example/"),
                      ("a2", "Made-up Closed Diner", "2010-01-01", "2020-06-01", "(802) 555-0101",
                       "https://shop1.example/")]


def test_a_damaged_file_is_never_read(release, tmp_path):
    upload(release.folder)
    release.broken = {f"fsq-{DT}-places_000001.parquet"}
    national = tmp_path / "national"
    fetch.prepare_uploaded(entry(), str(national))
    assert not (national / "fsq-places" / "fsq-places.parquet").exists()
    assert "SHA-256" in (national / "fsq-places" / fetch.FAILED).read_text()
    # the region says why, and is skipped (not failed)
    got = fetch.fetch_source(entry(), catalogue.regions()["us-vermont"], {}, str(tmp_path / "work"), str(national))
    assert got["status"] == "skipped" and "SHA-256" in got["reason"]


def test_every_covered_country_and_puerto_rico_are_kept():
    e = entry()
    assert len(e["countries"]) == 22 and e["fetch"]["also_countries"] == ["PR"]
    assert catalogue.check() == []


def test_the_notice_check(tmp_path):
    ours = tmp_path / "NOTICE"
    ours.write_text("Foursquare  Open Source Places\nCopyright 2024 Foursquare Labs, Inc.\nmore")
    assert uploaded.notice_ok(NOTICE, str(ours))
    assert not uploaded.notice_ok(NOTICE + "A new line Foursquare added\n", str(ours))
    assert uploaded.notice_ok(NOTICE, os.path.join(ROOT, "NOTICE"))


def test_the_prepare_step_reads_the_release_with_a_read_only_token():
    import yaml
    flow = yaml.safe_load(open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8"))
    assert flow["permissions"] == {"contents": "read"}
    prepare = flow["jobs"]["prepare"]
    assert "permissions" not in prepare                       # read-only, as the whole workflow by default
    step = next(s for s in prepare["steps"] if s.get("name") == "Download and split the national files")
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}" and "PLACEPACKS_SCRATCH" in step["run"]
