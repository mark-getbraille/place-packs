"""Reading where and when each picture was taken: the GPS position, height and date the camera or phone wrote.

Nothing here changes a file: pictures are only opened for reading, and only their details (EXIF) are read, never
the picture itself.

  find_photos(folder, subfolders)  the pictures (and videos) in a folder, with their companion files
  read_photo(path)                 a Photo: position, height, date, and where each came from

How each kind of file is read:
  JPEG, PNG, TIFF, WebP   Pillow's EXIF reader (getexif)
  HEIC, HEIF, AVIF        the EXIF block is found in the file's boxes by this module (read_heif_exif) and read by
                          Pillow, so no HEIC decoder (and no HEVC patent licence) is needed: only details are read
  RAW (DNG, CR2, NEF,     most are TIFF files inside, so the start of the file is read as TIFF; others (RAF) carry an
  ARW, ORF, RW2, PEF...)  "Exif" block, which is searched for; Canon CR3 keeps its details in CMT boxes
  MP4, MOV, M4V, 3GP      ffprobe's tags (location in ISO 6709, creation_time), only when ffprobe is installed;
                          without it videos are skipped (they stay where they are)

The date, best first: the camera's "date taken" (DateTimeOriginal), the GPS date, a date in the file name
(IMG_20050704_101500.jpg), and last the file's own "modified" date (marked as such, since copying can change it).
"""

import datetime as dt
import json
import os
import re
import shutil
import struct
import subprocess

PICTURE_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".tif", ".tiff", ".webp",
                      ".heic", ".heif", ".hif", ".avif"}
RAW_EXTENSIONS = {".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2", ".pef",
                  ".raf", ".srw", ".3fr", ".erf", ".kdc", ".dcr", ".mef", ".mos", ".iiq", ".rwl"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp"}
# Files that belong to a picture and move with it: edits (iPhone .AAE), XMP sidecars, thumbnails.
COMPANION_EXTENSIONS = {".xmp", ".aae", ".thm"}
HEIF_EXTENSIONS = {".heic", ".heif", ".hif", ".avif"}
RAW_READ_BYTES = 4 * 1024 * 1024         # the start of a RAW file holds its details; read the whole file if not
SKIP_FOLDERS = {"$recycle.bin", "@eadir", "system volume information", ".thumbnails"}

GPS_IFD, EXIF_IFD = 0x8825, 0x8769
DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])"
                     r"(?:[ _T-]?([01]\d|2[0-3])[-.:_]?([0-5]\d)[-.:_]?([0-5]\d))?(?!\d)")


class Photo:
    """One picture or video and what is known about it.

    path: the file; kind: "picture" or "video"; lat, lon: its GPS position in degrees (None if it has none);
    altitude: metres above sea level (None if not recorded); taken: when it was taken (a datetime, local time as
    the camera wrote it; None if nothing says); date_source: "camera", "gps", "file name" or "file date";
    location_source: "gps" (its own GPS), "guess" (from photos taken around the same time: "probably") or "" (no
    location); guessed_from: the photo the guess came from; companions: files that move with it (sidecars, a Live
    Photo's video); error: why it could not be read ("" if it could)."""

    def __init__(self, path, kind="picture"):
        """An empty Photo for path (read_photo fills it in)."""
        self.path = path
        self.kind = kind
        self.lat = self.lon = self.altitude = None
        self.taken = None
        self.date_source = ""
        self.location_source = ""
        self.guessed_from = ""
        self.companions = []
        self.error = ""

    @property
    def has_location(self):
        """True if a position is known (its own GPS or a guess)."""
        return self.lat is not None and self.lon is not None

    @property
    def probably(self):
        """True if the position is a guess from neighbours in time (said as "probably")."""
        return self.location_source == "guess"

    def __repr__(self):
        """For test messages."""
        return f"Photo({os.path.basename(self.path)!r}, {self.lat}, {self.lon}, {self.taken})"


def kind_of(path):
    """"picture", "video" or "" (not a file this program sorts), from the file name's ending."""
    ext = os.path.splitext(path)[1].lower()
    if ext in PICTURE_EXTENSIONS or ext in RAW_EXTENSIONS:
        return "picture"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return ""


def find_photos(folder, subfolders=True, videos=True):
    """[Photo] (not read yet) for every picture (and, with videos, video) in folder and, with subfolders, in every
    folder inside it, sorted by path. Hidden and system folders are skipped. A sidecar (IMG_1.xmp, IMG_1.AAE,
    IMG_1.JPG.xmp) and a Live Photo's video (IMG_1.MOV beside IMG_1.HEIC) are the picture's companions: they move
    with it and are not sorted on their own."""
    found = []
    for here, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in SKIP_FOLDERS)
        files = sorted(files, key=str.lower)
        pictures = {}
        for f in files:
            if kind_of(f) == "picture":
                pictures.setdefault(os.path.splitext(f)[0].lower(), []).append(f)
        taken_as_companion = set()
        items = []
        for f in files:
            k = kind_of(f)
            if not k or (k == "video" and not videos and os.path.splitext(f)[0].lower() not in pictures):
                continue
            stem = os.path.splitext(f)[0].lower()
            if k == "video" and stem in pictures:
                taken_as_companion.add(f)           # a Live Photo's video goes with its picture
                continue
            items.append(Photo(os.path.join(here, f), k))
        for p in items:
            name = os.path.basename(p.path)
            stem = os.path.splitext(name)[0].lower()
            for f in files:
                low = f.lower()
                ext = os.path.splitext(low)[1]
                if f == name:
                    continue
                if (ext in COMPANION_EXTENSIONS and os.path.splitext(low)[0] in (stem, name.lower())) or \
                        (f in taken_as_companion and os.path.splitext(low)[0] == stem and p.kind == "picture"):
                    p.companions.append(os.path.join(here, f))
        found.extend(items)
        if not subfolders:
            break
    return found


# ---------------------------------------------------------------- EXIF values

def _ratio(value):
    """A number from an EXIF rational (IFDRational, a (numerator, denominator) pair or a plain number)."""
    if isinstance(value, tuple) and len(value) == 2:
        return value[0] / value[1] if value[1] else 0.0
    return float(value)


def dms_to_degrees(dms, ref):
    """Degrees from EXIF's (degrees, minutes, seconds) and its N/S/E/W letter: ((36,1),(2,1),(24,1)), "N" -> 36.04.
    None for a value that cannot be read."""
    try:
        if isinstance(dms, (int, float)) or (hasattr(dms, "numerator") and not isinstance(dms, tuple)):
            deg = _ratio(dms)
        else:
            parts = [_ratio(v) for v in dms] + [0.0, 0.0]
            deg = parts[0] + parts[1] / 60 + parts[2] / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if isinstance(ref, bytes):
        ref = ref.decode("ascii", "ignore")
    if str(ref or "").strip().upper()[:1] in ("S", "W"):
        deg = -deg
    return deg


def parse_exif_date(text):
    """A datetime from EXIF's "2005:07:04 10:15:00" (also with "-" or "/" and without the time); None for an empty
    or zero date ("0000:00:00 00:00:00")."""
    if isinstance(text, bytes):
        text = text.decode("ascii", "ignore")
    m = re.match(r"\s*(\d{4})[:/-](\d{1,2})[:/-](\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?", str(text or ""))
    if not m:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h, mi, s = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
        if y < 1800:
            return None
        return dt.datetime(y, mo, d, min(h, 23), min(mi, 59), min(s, 59))
    except ValueError:
        return None


def date_in_name(name):
    """A datetime from a date in a file name ("IMG_20050704_101500.jpg", "2005-07-04 beach.jpg"); None if none."""
    m = DATE_RE.search(os.path.splitext(os.path.basename(name))[0])
    if not m:
        return None
    try:
        return dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0),
                           int(m.group(5) or 0), int(m.group(6) or 0))
    except ValueError:
        return None


def apply_exif(photo, exif):
    """Fill photo's position, height and date from a Pillow Exif object (IFD0 with its GPS and Exif IFDs)."""
    try:
        gps = exif.get_ifd(GPS_IFD) or {}
    except Exception:  # noqa: BLE001 - damaged GPS block
        gps = {}
    try:
        ex = exif.get_ifd(EXIF_IFD) or {}
    except Exception:  # noqa: BLE001 - damaged Exif block
        ex = {}
    apply_gps(photo, gps)
    for value in (ex.get(0x9003), ex.get(0x9004), exif.get(0x0132)):
        taken = parse_exif_date(value)
        if taken:
            photo.taken, photo.date_source = taken, "camera"
            break


def apply_gps(photo, gps):
    """Fill photo's position, height and (if it has no date yet) date from a GPS IFD {tag: value}."""
    if 2 in gps and 4 in gps:
        lat = dms_to_degrees(gps[2], gps.get(1, "N"))
        lon = dms_to_degrees(gps[4], gps.get(3, "E"))
        # 0,0 is what some cameras write when they have no fix; positions outside the earth are damage.
        if lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180 and (lat, lon) != (0.0, 0.0):
            photo.lat, photo.lon = lat, lon
            photo.location_source = "gps"
    if 6 in gps:
        try:
            alt = _ratio(gps[6])
            ref = gps.get(5, 0)
            if isinstance(ref, bytes):
                ref = ref[:1] == b"\x01"
            photo.altitude = -alt if ref in (1, True) else alt
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if photo.taken is None and 29 in gps:
        day = parse_exif_date(gps[29])
        if day:
            try:
                h, m, s = (int(_ratio(v)) for v in gps.get(7, (0, 0, 0)))
                day = day.replace(hour=min(h, 23), minute=min(m, 59), second=min(s, 59))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            photo.taken, photo.date_source = day, "gps"


def exif_from_bytes(data):
    """A Pillow Exif object from an EXIF block ("Exif\\0\\0" + TIFF, or TIFF); None if it cannot be read.
    Panasonic (IIU) and Olympus (IIRO, IIRS) TIFF headers are read as ordinary TIFF."""
    from PIL import Image
    if data.startswith(b"Exif\x00\x00"):
        data = data[6:]
    if data[:4] in (b"IIU\x00", b"IIRO", b"IIRS"):
        data = b"II*\x00" + data[4:]
    if data[:4] not in (b"II*\x00", b"MM\x00*"):
        return None
    exif = Image.Exif()
    try:
        exif.load(data)
    except Exception:  # noqa: BLE001 - damaged
        return None
    return exif


# ---------------------------------------------------------------- HEIF (HEIC, AVIF)

def _boxes(data, start, end):
    """(type, payload start, payload end) for each ISO base media box between start and end of data."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        head = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            head = 16
        elif size == 0:
            size = end - pos
        if size < head or pos + size > end:
            return
        yield kind.decode("latin-1"), pos + head, pos + size
        pos += size


def _uint(data, pos, size):
    """An unsigned big-endian number of size bytes (0, 4 or 8) at pos, and the position after it."""
    if size == 0:
        return 0, pos
    return int.from_bytes(data[pos:pos + size], "big"), pos + size


def read_heif_exif(path, max_bytes=64 * 1024 * 1024):
    """The EXIF block of a HEIC/HEIF/AVIF file (bytes starting with the TIFF header), or None. The file's meta box
    lists its items (iinf); the item of type "Exif" is found in the item locations (iloc), in the file or in the
    meta box's own data (idat). Its first 4 bytes say where the TIFF header starts."""
    with open(path, "rb") as f:
        head = f.read(1024 * 1024)
        data = head
        size = os.fstat(f.fileno()).st_size
    meta = None
    for kind, a, b in _boxes(data, 0, len(data)):
        if kind == "meta":
            meta = (a + 4, b)                       # a full box: version and flags first
            break
    if meta is None:
        return None
    exif_ids, locations, idat = set(), {}, None
    for kind, a, b in _boxes(data, *meta):
        if kind == "iinf":
            version = data[a]
            pos = a + 4 + (2 if version == 0 else 4)
            for k2, a2, b2 in _boxes(data, pos, b):
                if k2 != "infe":
                    continue
                v = data[a2]
                if v < 2:
                    continue
                p = a2 + 4
                item_id, p = _uint(data, p, 2 if v == 2 else 4)
                p += 2                              # item_protection_index
                if data[p:p + 4] == b"Exif":
                    exif_ids.add(item_id)
        elif kind == "idat":
            idat = a
        elif kind == "iloc":
            version = data[a]
            p = a + 4
            offset_size, length_size = data[p] >> 4, data[p] & 15
            base_size, index_size = data[p + 1] >> 4, (data[p + 1] & 15) if version in (1, 2) else 0
            p += 2
            count, p = _uint(data, p, 2 if version < 2 else 4)
            for _ in range(count):
                item_id, p = _uint(data, p, 2 if version < 2 else 4)
                method = 0
                if version in (1, 2):
                    method, p = _uint(data, p, 2)
                    method &= 15
                p += 2                              # data_reference_index
                base, p = _uint(data, p, base_size)
                extents, p = _uint(data, p, 2)
                spans = []
                for _ in range(extents):
                    if index_size:
                        _, p = _uint(data, p, index_size)
                    off, p = _uint(data, p, offset_size)
                    length, p = _uint(data, p, length_size)
                    spans.append((base + off, length))
                locations[item_id] = (method, spans)
    for item_id in exif_ids:
        if item_id not in locations:
            continue
        method, spans = locations[item_id]
        chunks = []
        for off, length in spans:
            if method == 1 and idat is not None:
                chunks.append(data[idat + off: idat + off + length])
            elif method == 0:
                if length == 0 or off + length > size or length > max_bytes:
                    continue
                with open(path, "rb") as f:
                    f.seek(off)
                    chunks.append(f.read(length))
        blob = b"".join(chunks)
        if len(blob) < 8:
            continue
        start = 4 + struct.unpack(">I", blob[:4])[0]
        body = blob[start:]
        if body[:4] not in (b"II*\x00", b"MM\x00*"):     # some writers point at "Exif\0\0"; find the header
            m = re.search(rb"II\*\x00|MM\x00\*", blob[4:])
            body = blob[4 + m.start():] if m else b""
        if body:
            return body
    return None


# ---------------------------------------------------------------- RAW

def read_raw_exif(path):
    """A Pillow Exif object for a RAW file, or None. TIFF-based RAW (DNG, CR2, NEF, ARW, ORF, RW2, PEF ...) is read
    from its start (the whole file if the details lie further in); RAF and others from their "Exif" block; CR3 from
    its CMT1 (main details), CMT2 (Exif: the date) and CMT4 (GPS) boxes."""
    with open(path, "rb") as f:
        data = f.read(RAW_READ_BYTES)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cr3":
        return _cr3_exif(data)
    exif = exif_from_bytes(data)
    if exif is not None:
        try:
            exif.get_ifd(GPS_IFD)
        except Exception:  # noqa: BLE001 - its GPS block lies past what was read: read it all
            with open(path, "rb") as f:
                exif = exif_from_bytes(f.read())
        return exif
    i = data.find(b"Exif\x00\x00")
    if i >= 0:
        return exif_from_bytes(data[i:])
    return None


class _Cr3Exif:
    """Stands in for a Pillow Exif object for a Canon CR3 file: its main details and its Exif and GPS blocks
    (get_ifd), each read from its own CMT box."""

    def __init__(self, main, ex, gps):
        """main, ex, gps: Pillow Exif objects (or None) of CMT1, CMT2 and CMT4."""
        self.main, self.ex, self.gps = main, ex, gps

    def get(self, tag, default=None):
        """A tag of the main details."""
        return self.main.get(tag, default) if self.main is not None else default

    def get_ifd(self, tag):
        """The Exif or GPS block as {tag: value} (each is its CMT box's first directory)."""
        part = {EXIF_IFD: self.ex, GPS_IFD: self.gps}.get(tag)
        return dict(part) if part is not None else {}


def _cr3_exif(data):
    """_Cr3Exif from the CMT boxes in the start of a CR3 file, or None."""
    parts = {}
    for name in (b"CMT1", b"CMT2", b"CMT4"):
        i = data.find(name)
        if i >= 4:
            size = struct.unpack(">I", data[i - 4:i])[0]
            parts[name] = exif_from_bytes(data[i + 4:i - 4 + size])
    if not parts:
        return None
    return _Cr3Exif(parts.get(b"CMT1"), parts.get(b"CMT2"), parts.get(b"CMT4"))


# ---------------------------------------------------------------- videos

def ffprobe_path():
    """The ffprobe program if it is installed (on the PATH, or PLI_FFPROBE), else None."""
    return os.environ.get("PLI_FFPROBE") or shutil.which("ffprobe")


ISO6709_RE = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?")


def parse_iso6709(text):
    """(lat, lon, altitude or None) from an ISO 6709 position ("+35.9582-075.6201+005.000/"); None if unreadable."""
    m = ISO6709_RE.search(text or "")
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    return lat, lon, float(m.group(3)) if m.group(3) else None


def read_video(photo, probe=None):
    """Fill a video's position, height and date from ffprobe's tags. Without ffprobe the video stays unread
    (photo.error says so, and it is left where it is)."""
    probe = probe or ffprobe_path()
    if not probe:
        photo.error = "videos need ffprobe (not installed), so this one is left where it is"
        return photo
    try:
        flags = 0x08000000 if os.name == "nt" else 0         # CREATE_NO_WINDOW: no black window flashing up
        out = subprocess.run([probe, "-v", "quiet", "-print_format", "json", "-show_format", photo.path],
                             capture_output=True, timeout=60, creationflags=flags)
        tags = json.loads(out.stdout.decode("utf-8", "replace") or "{}").get("format", {}).get("tags", {})
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        photo.error = f"ffprobe could not read it ({e})"
        return photo
    tags = {k.lower(): v for k, v in tags.items()}
    for key in ("com.apple.quicktime.location.iso6709", "location", "location-eng"):
        if tags.get(key):
            pos = parse_iso6709(tags[key])
            if pos:
                photo.lat, photo.lon, photo.altitude = pos
                photo.location_source = "gps"
                break
    for key in ("com.apple.quicktime.creationdate", "creation_time", "date"):
        when = parse_exif_date(tags.get(key, "").replace("-", ":", 2)) if tags.get(key) else None
        if when:
            photo.taken, photo.date_source = when, "camera"
            break
    return photo


# ---------------------------------------------------------------- one photo

def read_photo(photo_or_path, probe=None):
    """Read a Photo's position, height and date (a path is made into a Photo first). Never raises: a file that
    cannot be read gets photo.error and keeps what could be found (at least the file's date)."""
    from PIL import Image
    photo = photo_or_path if isinstance(photo_or_path, Photo) else Photo(photo_or_path, kind_of(photo_or_path))
    path = photo.path
    ext = os.path.splitext(path)[1].lower()
    try:
        if photo.kind == "video":
            read_video(photo, probe)
        elif ext in HEIF_EXTENSIONS:
            block = read_heif_exif(path)
            exif = exif_from_bytes(block) if block else None
            if exif is not None:
                apply_exif(photo, exif)
        elif ext in RAW_EXTENSIONS:
            exif = read_raw_exif(path)
            if exif is not None:
                apply_exif(photo, exif)
        else:
            with Image.open(path) as img:
                apply_exif(photo, img.getexif())
    except Exception as e:  # noqa: BLE001 - one unreadable file does not stop the others
        photo.error = f"its details could not be read ({str(e).splitlines()[0] if str(e) else type(e).__name__})"
    if photo.taken is None:
        when = date_in_name(path)
        if when:
            photo.taken, photo.date_source = when, "file name"
    if photo.taken is None:
        try:
            photo.taken = dt.datetime.fromtimestamp(os.path.getmtime(path))
            photo.date_source = "file date"
        except OSError:
            pass
    return photo


def read_all(photos, progress=None, stop=None, probe=None):
    """Read every Photo in turn; progress(done, total, photo) after each; stop() True ends early. Returns the
    photos read."""
    probe = probe or ffprobe_path()
    done = []
    for i, p in enumerate(photos):
        if stop and stop():
            break
        read_photo(p, probe)
        done.append(p)
        if progress:
            progress(i + 1, len(photos), p)
    return done


def write_test_photo(path, lat=None, lon=None, when=None, altitude=None, colour=(70, 130, 180), size=(64, 48)):
    """Write a made-up picture (a block of colour) with EXIF GPS, height and date, for the tests and the smoke
    test. path's ending picks the format: .jpg, .png, .tif or .webp. lat/lon in degrees (None: no GPS); when: a
    datetime (None: no date)."""
    from PIL import Image
    exif = Image.Exif()
    if when is not None:
        stamp = when.strftime("%Y:%m:%d %H:%M:%S")
        exif[0x0132] = stamp
        exif.get_ifd(EXIF_IFD)[0x9003] = stamp
    if lat is not None and lon is not None:
        gps = exif.get_ifd(GPS_IFD)
        gps[1] = "N" if lat >= 0 else "S"
        gps[2] = _to_dms(abs(lat))
        gps[3] = "E" if lon >= 0 else "W"
        gps[4] = _to_dms(abs(lon))
        if altitude is not None:
            gps[5] = b"\x00" if altitude >= 0 else b"\x01"
            gps[6] = abs(float(altitude))
    img = Image.new("RGB", size, colour)
    ext = os.path.splitext(path)[1].lower()
    fmt = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF", ".webp": "WEBP"}.get(ext, "JPEG")
    img.save(path, fmt, exif=exif.tobytes())
    return path


def _to_dms(value):
    """(degrees, minutes, seconds) for EXIF from decimal degrees (seconds to 1/1000)."""
    from PIL.TiffImagePlugin import IFDRational
    deg = int(value)
    minutes_f = (value - deg) * 60
    minutes = int(minutes_f)
    seconds = round((minutes_f - minutes) * 60, 3)
    return (IFDRational(deg, 1), IFDRational(minutes, 1), IFDRational(int(seconds * 1000), 1000))


def heif_with_exif(tiff_exif):
    """A minimal HEIF file (bytes) whose only item is an Exif block: for the tests of read_heif_exif (no picture is
    in it, which is enough, since only the details are read)."""
    def box(kind, payload):
        """An ISO media box: its size, its four-letter kind, then payload."""
        return struct.pack(">I4s", 8 + len(payload), kind.encode()) + payload

    def full(kind, version, payload):
        """A "full" box: a box whose payload starts with a version byte and three flag bytes."""
        return box(kind, bytes([version, 0, 0, 0]) + payload)
    payload = struct.pack(">I", 6) + b"Exif\x00\x00" + tiff_exif
    ftyp = box("ftyp", b"heic" + b"\x00\x00\x00\x00" + b"mif1heic")
    hdlr = full("hdlr", 0, b"\x00" * 4 + b"pict" + b"\x00" * 12 + b"\x00")
    infe = full("infe", 2, struct.pack(">HH", 1, 0) + b"Exif" + b"\x00")
    iinf = full("iinf", 0, struct.pack(">H", 1) + infe)

    def build(offset):
        """The meta box, with the Exif item located at offset in the file."""
        iloc = full("iloc", 1, bytes([0x44, 0x00]) + struct.pack(">H", 1) + struct.pack(">HHH", 1, 0, 0) +
                    struct.pack(">H", 1) + struct.pack(">II", offset, len(payload)))
        meta = full("meta", 0, hdlr + iinf + iloc)
        return meta
    meta = build(0)
    mdat_start = len(ftyp) + len(meta) + 8
    meta = build(mdat_start)
    return ftyp + meta + box("mdat", payload)


def tiff_exif_bytes(lat=None, lon=None, when=None, altitude=None):
    """The EXIF block (TIFF bytes) write_test_photo would write, for building test HEIF and RAW files."""
    from PIL import Image
    exif = Image.Exif()
    if when is not None:
        exif.get_ifd(EXIF_IFD)[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    if lat is not None:
        gps = exif.get_ifd(GPS_IFD)
        gps[1], gps[2] = ("N" if lat >= 0 else "S"), _to_dms(abs(lat))
        gps[3], gps[4] = ("E" if lon >= 0 else "W"), _to_dms(abs(lon))
        if altitude is not None:
            gps[5], gps[6] = b"\x00", float(altitude)
    data = exif.tobytes()
    return data[6:] if data.startswith(b"Exif\x00\x00") else data
