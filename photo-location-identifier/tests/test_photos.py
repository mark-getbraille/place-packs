"""Reading where and when photos were taken: EXIF GPS, height and date from JPEG, PNG, TIFF, WebP, HEIC and RAW
(all made up with Pillow), dates from file names and file dates, companion files, videos."""

import datetime as dt
import os
import struct

import pytest

from conftest import photo
from pli import photos as ph

WHEN = dt.datetime(2005, 7, 4, 10, 15)


@pytest.mark.parametrize("ext", ["jpg", "png", "tif", "webp"])
def test_exif_gps_height_and_date_from_each_format(tmp_path, ext):
    """GPS (south and west too), height and the date taken are read back exactly."""
    path = photo(tmp_path, f"a.{ext}", (-33.8568, -151.2153), WHEN, altitude=12.5)
    p = ph.read_photo(path)
    assert p.error == ""
    assert p.lat == pytest.approx(-33.8568, abs=1e-6) and p.lon == pytest.approx(-151.2153, abs=1e-6)
    assert p.altitude == pytest.approx(12.5)
    assert p.taken == WHEN and p.date_source == "camera" and p.location_source == "gps"


def test_heic_details_are_read_without_decoding_the_picture(tmp_path):
    """A HEIF file's Exif item is found in its boxes (no HEIC decoder is used)."""
    path = tmp_path / "IMG_0001.HEIC"
    path.write_bytes(ph.heif_with_exif(ph.tiff_exif_bytes(35.9, -75.6, WHEN, altitude=4)))
    p = ph.read_photo(str(path))
    assert (round(p.lat, 6), round(p.lon, 6), p.taken) == (35.9, -75.6, WHEN)
    assert p.altitude == pytest.approx(4)


@pytest.mark.parametrize("ext, head", [(".dng", b""), (".rw2", b"IIU\x00"), (".raf", b"FUJIFILMCCD-RAW 0201" +
                                                                                  b"\x00" * 60 + b"Exif\x00\x00")])
def test_raw_files(tmp_path, ext, head):
    """TIFF-based RAW (DNG), Panasonic's header (RW2) and an Exif block further in (RAF) are all read."""
    tiff = ph.tiff_exif_bytes(34.21, -77.8, WHEN)
    if head == b"IIU\x00":                  # Panasonic: a little-endian TIFF (as Pillow saves .tif) with "IIU"
        little = open(photo(tmp_path, "le.tif", (34.21, -77.8), WHEN), "rb").read()
        assert little[:4] == b"II*\x00"
        data = head + little[4:]
    else:
        data = head + tiff
    path = tmp_path / f"a{ext}"
    path.write_bytes(data)
    p = ph.read_photo(str(path))
    assert (round(p.lat, 4), round(p.lon, 4), p.taken) == (34.21, -77.8, WHEN)


def test_cr3_cmt_boxes(tmp_path):
    """Canon CR3: the date from CMT2 (Exif) and the position from CMT4 (GPS) boxes."""
    from PIL import Image
    gps = Image.Exif()
    for k, v in ph.exif_from_bytes(ph.tiff_exif_bytes(36.03, -75.67)).get_ifd(ph.GPS_IFD).items():
        gps[k] = v
    exif = Image.Exif()
    exif[0x9003] = WHEN.strftime("%Y:%m:%d %H:%M:%S")

    def box(name, body):
        return struct.pack(">I", len(body) + 8) + name + body
    data = b"\x00\x00\x00\x18ftypcrx " + b"\x00" * 12 + box(b"CMT2", exif.tobytes()[6:]) + \
        box(b"CMT4", gps.tobytes()[6:])
    path = tmp_path / "a.cr3"
    path.write_bytes(data)
    p = ph.read_photo(str(path))
    assert (round(p.lat, 4), round(p.lon, 4), p.taken) == (36.03, -75.67, WHEN)


def test_no_gps_and_zero_zero_mean_no_location(tmp_path):
    """A photo without GPS, or with 0,0 (no fix), has no location; its date is still read."""
    a = ph.read_photo(photo(tmp_path, "a.jpg", None, WHEN))
    b = ph.read_photo(photo(tmp_path, "b.jpg", (0.0, 0.0), WHEN))
    assert not a.has_location and not b.has_location and a.taken == WHEN


def test_date_from_the_file_name_then_the_file_date(tmp_path):
    """Without a date taken: a date in the file name, else the file's modified date (marked as such)."""
    a = ph.read_photo(photo(tmp_path, "IMG_20050704_101500.jpg", None, None))
    assert (a.taken, a.date_source) == (WHEN, "file name")
    b = photo(tmp_path, "plain.jpg", None, None)
    os.utime(b, (1120471200, 1120471200))
    p = ph.read_photo(b)
    assert p.date_source == "file date" and p.taken.year == 2005


def test_unreadable_file_keeps_its_file_date(tmp_path):
    """A damaged picture gets an error and its file date; it never stops the others."""
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not a picture")
    p = ph.read_photo(str(bad))
    assert p.error and p.taken is not None and not p.has_location


def test_find_photos_with_companions_and_subfolders(tmp_path):
    """Pictures in subfolders are found (hidden folders skipped); sidecars and a Live Photo's video are companions."""
    photo(tmp_path, "IMG_1.jpg", None, WHEN)
    (tmp_path / "IMG_1.AAE").write_text("edit")
    (tmp_path / "IMG_1.jpg.xmp").write_text("xmp")
    (tmp_path / "IMG_1.MOV").write_bytes(b"live")
    (tmp_path / "notes.txt").write_text("not a photo")
    photo(tmp_path / "sub", "IMG_2.png", None, WHEN)
    photo(tmp_path / ".hidden", "IMG_3.jpg", None, WHEN)
    found = ph.find_photos(str(tmp_path))
    names = [os.path.relpath(p.path, tmp_path) for p in found]
    assert names == ["IMG_1.jpg", os.path.join("sub", "IMG_2.png")]
    assert sorted(os.path.basename(c) for c in found[0].companions) == ["IMG_1.AAE", "IMG_1.MOV", "IMG_1.jpg.xmp"]
    assert [os.path.basename(p.path) for p in ph.find_photos(str(tmp_path), subfolders=False)] == ["IMG_1.jpg"]


def test_videos_need_ffprobe(tmp_path, monkeypatch):
    """Without ffprobe a video is left alone (with a reason); with it, its ISO 6709 location and date are read."""
    v = tmp_path / "clip.mp4"
    v.write_bytes(b"\x00")
    monkeypatch.delenv("PLI_FFPROBE", raising=False)
    monkeypatch.setattr(ph.shutil, "which", lambda name: None)
    p = ph.read_photo(str(v))
    assert "ffprobe" in p.error and not p.has_location
    assert ph.parse_iso6709("+35.9582-075.6201+005.000/") == (35.9582, -75.6201, 5.0)

    class Done:
        stdout = (b'{"format": {"tags": {"com.apple.quicktime.location.ISO6709": "+36.0300-075.6700+003.000/",'
                  b' "creation_time": "2005-07-04T10:15:00.000000Z"}}}')
    monkeypatch.setattr(ph.subprocess, "run", lambda *a, **k: Done())
    p = ph.read_photo(ph.Photo(str(v), "video"), probe="ffprobe")
    assert (p.lat, p.lon, p.taken) == (36.03, -75.67, WHEN)
