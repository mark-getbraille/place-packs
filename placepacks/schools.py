"""School and college DETAILS: the phone number, website and a short note (grades, type, and for colleges the
admissions, disability services and financial aid pages) of the schools and colleges already in the packs (the
owner's request of 27 November 2026, notes/helper-rules.txt; source "nces-details").

The places themselves are already in the extra part: public schools (nces-schools, keyed by the 12-digit NCES school
id), private schools (nces-private-schools, keyed by the PSS id "PPIN") and colleges (nces-postsecondary, keyed by
the IPEDS UNITID). This source adds no places: it is read after them (reader "key_details") and gives each place,
found by its key, the details it lacks (PackWriter.fill_details, cleaned by placepacks/contact.py as an institution's:
INSTITUTION_SOURCES).

What is read, once a month by the prepare job (convert "nces_details", placepacks/gov_details.py), all from the
National Center for Education Statistics (US Department of Education, public domain):

  CCD school directory (the newest "ccd_sch_029" file, found through the CCD file list's own API) and the CCD
      school characteristics file ("ccd_sch_129", for virtual schools): PHONE, WEBSITE, GSLO/GSHI (grades),
      SCH_TYPE_TEXT (regular, special education, career and technical, alternative), CHARTER_TEXT, VIRTUAL. A school
      whose name says it is a state school for the blind or the deaf is noted so. Magnet status is no longer in the
      CCD files (2024-25), so it is not given.
  PSS private schools (the newest "pssYYYY_pu_csv.zip"): PPHONE, the grades (LOGR/HIGR) are not used (their codes
      are survey-specific), and TYPOLOGY (Catholic, other religious, nonsectarian, special education).
  IPEDS institutional characteristics (the newest "HDYYYY.zip"): GENTELE (the main phone), WEBADDR, ADMINURL
      (admissions), FAIDURL (financial aid), DISAURL (the disability services office's page, important for blind
      students), SECTOR (public or private, 4-year, 2-year or less), TRIBAL, HBCU. Trade and vocational schools,
      community colleges and tribal colleges are all in IPEDS and are noted by their sector.

Never read: any person's name (IPEDS's chief administrator CHFNM and title CHFTITLE, principals), e-mail addresses,
enrolment or staff figures. Only the columns named in this module are taken.

The CSV written (FIELDS): key (the place's pack key, "nces-schools:010000500870"), state, phone, website,
opening_hours (empty: the files have none), note ("Grades: PK-5; Type: special education school; ..."), matched_on
("NCES id"), checked (the file's school year). No positions: the reader finds the place by its key.
Only the Python standard library is used.
"""

import csv
import datetime
import io
import json
import os
import re
import time
import zipfile

FIELDS = ["key", "state", "phone", "website", "opening_hours", "note", "matched_on", "checked"]
CCD_API = "https://nces.ed.gov/ccd/datatables/api/"
PSS_LISTING = "https://nces.ed.gov/surveys/pss/pssdata.asp"
PSS_BASE = "https://nces.ed.gov/surveys/pss/"
IPEDS_HD = "https://nces.ed.gov/ipeds/datacenter/data/HD{year}.zip"
PAUSE = 2
SOURCES = {"public": "nces-schools", "private": "nces-private-schools", "college": "nces-postsecondary"}

# IPEDS SECTOR codes (the IPEDS data dictionary).
SECTORS = {"1": "public 4-year college or university", "2": "private nonprofit 4-year college or university",
           "3": "private for-profit 4-year college or university",
           "4": "public 2-year college (community or technical college)",
           "5": "private nonprofit 2-year college", "6": "private for-profit 2-year college",
           "7": "public trade or vocational school (less than 2 years)",
           "8": "private nonprofit trade or vocational school (less than 2 years)",
           "9": "private for-profit trade or vocational school (less than 2 years)"}
# PSS TYPOLOGY codes (the nine-category typology of the Private School Universe Survey).
TYPOLOGY = {"1": "Catholic parochial school", "2": "Catholic diocesan school", "3": "Catholic private school",
            "4": "Christian school", "5": "religious school (affiliated)", "6": "religious school (unaffiliated)",
            "7": "nonsectarian school", "8": "nonsectarian special emphasis school",
            "9": "nonsectarian special education school"}
GRADES = {"PK": "PK", "KG": "K", "UG": "ungraded", "AE": "adult education", "M": ""}
BLIND = re.compile(r"\b(school|academy|institute|center)s?\b.*\bfor the blind\b|\bblind\b.*\bschool\b", re.I)
DEAF = re.compile(r"\b(school|academy|institute|center)s?\b.*\bfor the deaf\b|\bdeaf\b.*\bschool\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")


# ------------------------------------------------------------------------------------------------ making the notes

def grade(code):
    """A CCD grade code as said ("PK", "K", "05" -> "5"), or ""."""
    code = str(code or "").strip().upper()
    if code in GRADES:
        return GRADES[code]
    if code.isdigit():
        return str(int(code))
    return ""


def special_school(name):
    """"state school for the blind", "state school for the deaf", both, or "" from a school's name."""
    blind, deaf = bool(BLIND.search(name or "")), bool(DEAF.search(name or ""))
    if blind and deaf:
        return "school for the deaf and the blind"
    return "school for the blind" if blind else "school for the deaf" if deaf else ""


def url(value):
    """A web address from the files (they often leave out "http://"), cleaned by placepacks/contact.py; ""."""
    from placepacks import contact
    text = " ".join(str(value or "").split())
    if not text or "@" in text:
        return ""
    if not re.match(r"https?://", text, re.I):
        text = "https://" + text.lstrip("/")
    return contact.website(text)


def note_of(parts):
    """A note from labelled parts (gov_details.note_of: e-mail addresses out, at most 1,200 characters)."""
    from placepacks.gov_details import note_of as join
    return join(parts)


def public_row(d, virtual=""):
    """The CSV row of one CCD directory record (a dict of its columns), or None for a closed school or one
    without an id. virtual: the characteristics file's VIRTUAL code for the school (FULLVIRTUAL: exclusively
    virtual; FACEVIRTUAL: primarily virtual; supplemental virtual courses are not noted)."""
    sid = (d.get("NCESSCH") or "").strip()
    if not sid or (d.get("SY_STATUS") or "").strip() in ("2", "6", "7"):    # closed, inactive, future
        return None
    lo, hi = grade(d.get("GSLO")), grade(d.get("GSHI"))
    grades = lo if lo and lo == hi else f"{lo}-{hi}" if lo and hi else ""
    kind = (d.get("SCH_TYPE_TEXT") or "").strip().lower()
    kinds = [kind + (" school" if kind and "school" not in kind else "")] if kind and kind != "regular school" else []
    if (d.get("CHARTER_TEXT") or "").strip().lower() == "yes":
        kinds.append("charter school")
    v = (virtual or "").strip().upper()
    if v == "FULLVIRTUAL":
        kinds.append("virtual school (exclusively virtual)")
    elif v == "FACEVIRTUAL":
        kinds.append("primarily virtual school")
    special = special_school(d.get("SCH_NAME"))
    if special:
        kinds.append(special)
    return {"key": f"{SOURCES['public']}:{sid}", "state": (d.get("ST") or "").strip(),
            "phone": d.get("PHONE", ""), "website": url(d.get("WEBSITE")),
            "note": note_of([("Grades", grades), ("Type", ", ".join(kinds))]), "matched_on": "NCES id"}


def private_row(d):
    """The CSV row of one PSS record, or None."""
    pid = (d.get("PPIN") or "").strip()
    if not pid:
        return None
    phone = re.sub(r"\D", "", d.get("PPHONE") or "")
    kind = TYPOLOGY.get((d.get("TYPOLOGY") or "").strip(), "")
    special = special_school(d.get("PINST"))
    return {"key": f"{SOURCES['private']}:{pid}", "state": (d.get("PSTABB") or "").strip(),
            "phone": phone if len(phone) == 10 else "", "website": "",
            "note": note_of([("Type", ", ".join(x for x in ("private " + kind if kind else "", special) if x))]),
            "matched_on": "NCES id"}


def college_row(d):
    """The CSV row of one IPEDS HD record, or None (a closed institution: CYACTIVE 2 or a closing date)."""
    uid = (d.get("UNITID") or "").strip()
    if not uid or (d.get("CYACTIVE") or "1").strip() not in ("1", "3") or \
            (d.get("CLOSEDAT") or "-2").strip() not in ("-2", ""):
        return None
    kinds = [SECTORS.get((d.get("SECTOR") or "").strip(), "")]
    if (d.get("TRIBAL") or "").strip() == "1":
        kinds.append("tribal college")
    if (d.get("HBCU") or "").strip() == "1":
        kinds.append("historically Black college or university")
    special = special_school(d.get("INSTNM"))
    if special:
        kinds.append(special)
    return {"key": f"{SOURCES['college']}:{uid}", "state": (d.get("STABBR") or "").strip(),
            "phone": d.get("GENTELE", ""), "website": url(d.get("WEBADDR")),
            "note": note_of([("Type", ", ".join(k for k in kinds if k)),
                             ("Disability services", url(d.get("DISAURL"))),
                             ("Admissions", url(d.get("ADMINURL"))),
                             ("Financial aid", url(d.get("FAIDURL")))]),
            "matched_on": "IPEDS UNITID"}


# ------------------------------------------------------------------------------------------------ reading the files

def _csv_in_zip(path, prefix=""):
    """A csv.DictReader over the first .csv member of a .zip (whose name starts with prefix), its header's
    byte-order mark taken out (IPEDS's files start with one)."""
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if n.lower().endswith(".csv") and os.path.basename(n).lower().startswith(prefix)]
    if not names:
        raise ValueError(f"{os.path.basename(path)} holds no CSV file")
    text = io.TextIOWrapper(z.open(names[0]), encoding="utf-8-sig", errors="replace", newline="")
    return csv.DictReader(text)


def rows_from_files(ccd=None, ccd_chars=None, pss=None, hd=None, checked=""):
    """Every CSV row from the downloaded files (each may be None: that part is left out)."""
    virtual = {}
    if ccd_chars:
        for d in _csv_in_zip(ccd_chars):
            virtual[(d.get("NCESSCH") or "").strip()] = d.get("VIRTUAL") or ""
    for path, make, prefix in ((ccd, None, ""), (pss, private_row, ""), (hd, college_row, "")):
        if not path:
            continue
        for d in _csv_in_zip(path, prefix):
            row = public_row(d, virtual.get((d.get("NCESSCH") or "").strip(), "")) if make is None else make(d)
            if row and (row.get("phone") or row.get("website") or row.get("note")):
                row["checked"] = checked
                yield row


def write_rows(target, rows):
    """Write rows (FIELDS) through a .partial file. Returns the number written."""
    n = 0
    with open(target + ".partial", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") or "" for k in FIELDS})
            n += 1
    os.replace(target + ".partial", target)
    return n


# ------------------------------------------------------------------------------------------------ finding the files

def _get(url, opener=None):
    """The body of a GET request (bytes), with the project's User-Agent (placepacks.fetch.request)."""
    from placepacks import fetch
    if opener:
        return opener(url)
    with fetch.request(url) as r:
        return r.read()


def ccd_files(get, years=4):
    """(directory .zip URL, characteristics .zip URL or "", school year text) of the newest CCD school year that has
    a directory file, through the CCD file list's API (the same calls its own web page makes)."""
    lookup = json.loads(get(CCD_API + "Lookup/"))
    ids = sorted((y for y in lookup.get("schoolYears") or [] if y.get("id")), key=lambda y: -int(y["id"]))
    for year in ids[:years]:
        answer = json.loads(get(f"{CCD_API}File/0/7/{year['id']}/0/0/0"))
        urls = re.findall(r'"fileURL"\s*:\s*"([^"]+\.zip)"', json.dumps(answer))
        directory = next((u for u in urls if "/ccd_sch_029_" in u), "")
        if directory:
            chars = next((u for u in urls if "/ccd_sch_129_" in u), "")
            return directory, chars, year.get("name", "")
        time.sleep(PAUSE)
    raise ValueError("the CCD file list names no school directory file")


def pss_file(get):
    """The URL of the newest PSS public-use CSV .zip from its data page."""
    page = get(PSS_LISTING).decode("utf-8", "replace")
    found = sorted(set(re.findall(r'zip/pss(\d{4})_pu_csv\.zip', page)), key=lambda y: (int(y[:2]), y))
    if not found:
        raise ValueError("the PSS data page links no CSV file")
    return f"{PSS_BASE}zip/pss{found[-1]}_pu_csv.zip"


def prepare(entry, folder, today=None, downloader=None, get=None):
    """The prepare job's step (convert "nces_details"): find and download the newest CCD, PSS and IPEDS files into
    folder, write folder/<id>.csv. A file that cannot be found or downloaded leaves its part out (the others still
    go in); nothing at all raises. Returns the number of rows. downloader(url, target) and get(url) are for tests."""
    from placepacks import fetch
    download = downloader or (lambda u, t: fetch.download(u, t, pause=PAUSE))
    get = get or _get
    today = today or datetime.date.today()
    os.makedirs(folder, exist_ok=True)
    got, checked = {}, []
    try:
        directory, chars, year = ccd_files(get)
        got["ccd"] = os.path.join(folder, "ccd_directory.zip")
        download(directory, got["ccd"])
        checked.append(f"CCD {year}")
        if chars:
            got["ccd_chars"] = os.path.join(folder, "ccd_characteristics.zip")
            download(chars, got["ccd_chars"])
    except Exception as e:  # noqa: BLE001 - this part is left out, the others go on
        print(f"{entry['id']}: the CCD school directory is left out ({str(e)[:160]})", flush=True)
    try:
        pss = pss_file(get)
        got["pss"] = os.path.join(folder, "pss.zip")
        download(pss, got["pss"])
        checked.append("PSS " + re.search(r"pss(\d{4})", pss).group(1))
    except Exception as e:  # noqa: BLE001
        print(f"{entry['id']}: the PSS private schools are left out ({str(e)[:160]})", flush=True)
    for year in range(today.year, today.year - 4, -1):
        try:
            got["hd"] = os.path.join(folder, "ipeds_hd.zip")
            download(IPEDS_HD.format(year=year), got["hd"])
            checked.append(f"IPEDS HD{year}")
            break
        except Exception:  # noqa: BLE001 - not published yet: the year before
            got.pop("hd", None)
            continue
    if not got:
        raise ValueError("none of the NCES files could be downloaded")
    target = os.path.join(folder, entry["id"] + ".csv")
    count = write_rows(target, rows_from_files(got.get("ccd"), got.get("ccd_chars"), got.get("pss"), got.get("hd"),
                                               "; ".join(checked)))
    for path in got.values():
        if os.path.exists(path):
            os.remove(path)                 # the large downloads are not kept (the CSV is small)
    with open(target + ".version", "w", encoding="utf-8") as f:
        f.write("; ".join(checked))
    return count


# ------------------------------------------------------------------------------------------------ the build's reader

def _register():
    """Register the "key_details" reader (placepacks/readers/__init__.py imports this module)."""
    from placepacks.readers import reader

    @reader("key_details")
    def read(path, entry, region, writer):
        """Give the places of the pack the details of a key-only details source (this module's CSV: key, state,
        phone, website, opening_hours, note): the rows of the region's state (entry "filter"), each to the place
        listed now under its key, filling only what the place lacks. Returns the number of places that got
        something."""
        from placepacks.readers.tabular import _get as cell, open_texts, region_values
        flt = entry.get("filter") or {}
        want = flt.get("equals", "").format(**region_values(region)).upper() if flt else ""
        count = 0
        for text in open_texts(path, entry.get("member", "*.csv"), "utf-8-sig"):
            for row in csv.DictReader(text):
                if want and cell(row, flt["column"]).upper() != want:
                    continue
                key = row.get("key")
                contact = {f: row.get(f, "") for f in ("phone", "website", "opening_hours") if row.get(f)}
                note = _EMAIL.sub("", row.get("note") or "").strip() or None
                if key and (contact or note) and writer.fill_details(entry["id"], key, contact, note):
                    count += 1
        return count
    return read


read = _register()
