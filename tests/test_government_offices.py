"""The government office and facility sources of the November 2026 pass (VA health facilities and benefits offices,
HRSA's Site Dashboard of certified health facilities, USDA SNAP retailers and Service Centers, Pennsylvania's state
offices, New York's DMV offices and Washington DC's agency locations) and the json_api fetch method they brought
(pages of JSON from a web API, with an optional key from an environment variable). Every name, number and place
here is made up."""

import csv
import io
import json
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, fetch, fetch_api  # noqa: E402
from placepacks.readers import tabular  # noqa: E402

NEW = {"va-health-facilities", "va-benefits-offices", "hrsa-site-dashboard", "usda-snap-retailers",
       "usda-fsa-offices", "pa-state-offices", "ny-dmv-offices", "dc-government-locations"}
# Columns that would carry a person's details or contact numbers: never asked for.
PERSONAL = re.compile(r"phone|fax|email|e_mail|poc|contact|telephone|created_user|edited_user", re.I)


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def region(rid):
    """A region of regions.json (a copy)."""
    return dict(catalogue.regions()[rid])


class Recorder:
    """A stand-in for the pack writer: keeps every point the reader adds."""
    month = 202611

    def __init__(self):
        self.points = []

    def add_point(self, key, source, name, cls, tag, lat, lon, first, last, type=None, brand=None):
        self.points.append({"key": key, "name": name, "cls": cls, "tag": tag, "first": first, "last": last,
                            "type": type})


def write_csv(path, header, rows):
    """A small CSV file for a reader to read."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


def read(entry, path, rid):
    """The points the tabular reader keeps of a file for a region."""
    rec = Recorder()
    tabular.read(path, entry, region(rid), rec)
    return rec.points


# --- the catalogue ---------------------------------------------------------------------------------------------

def test_new_sources_are_in_the_catalogue_and_right():
    cat = catalogue.load()
    ids = {e["id"] for e in cat["accepted"]}
    assert NEW <= ids
    assert catalogue.check(cat) == []
    for sid in NEW:
        e = entry_of(sid)
        assert e["licence"] in ("US-Government-Work", "public-domain-marked", "OPEN-NY", "CC-BY-4.0")
        assert e["countries"] == ["US"]
        # No phone, fax, e-mail or contact person is ever asked for or read.
        f = e["fetch"]
        asked = " ".join([str(f.get("fields", "")), json.dumps(f.get("params", {})),
                          json.dumps(f.get("queries", [])), json.dumps(e.get("columns", {}))])
        assert not PERSONAL.search(asked), sid


def test_old_rejections_are_updated():
    names = {r["name"]: r["reason"] for r in catalogue.load()["rejected"]}
    assert "VA Facilities API (api.va.gov)" not in names           # now accepted with the owner's key
    assert "hrsa-site-dashboard" in names["CMS Hospital General Information"]
    assert "pa-state-offices" in names["State DMV office lists"]


def test_va_layer_leaves_out_mobile_and_suspended_sites():
    where = entry_of("va-health-facilities")["fetch"]["where"]
    assert "VHA_MOBILE = 0" in where and "VHA_SUSPENDED = 'N'" in where


def test_va_benefits_key_comes_from_the_environment_only():
    f = entry_of("va-benefits-offices")["fetch"]
    assert f["method"] == "json_api" and f["key_env"] == "VA_API_KEY" and f["key_header"] == "apikey"
    assert "key" not in json.dumps(f.get("params", {})).lower()


def test_workflow_gives_the_va_key_to_the_fetch_step():
    text = open(os.path.join(ROOT, ".github", "workflows", "build-packs.yml"), encoding="utf-8").read()
    assert "VA_API_KEY: ${{ secrets.VA_API_KEY }}" in text


# --- the json_api fetch method ---------------------------------------------------------------------------------

def test_page_addresses_fill_the_region_and_the_paging():
    f = {"url": "https://api.example.org/data", "params": {"filter[state]": "{code}", "column": "a,b"},
         "paging": {"style": "offset", "size": "size", "offset": "offset", "page_size": 100}}
    url = fetch_api.page_url(f, {"code": "VT"}, 2)
    assert url.startswith("https://api.example.org/data?")
    assert "filter%5Bstate%5D=VT" in url and "offset=200" in url and "size=100" in url
    f = {"url": "https://api.example.org/f", "params": {"state": "{code}"},
         "paging": {"style": "page", "page": "page", "size": "per_page", "first": 1, "page_size": 50}}
    url = fetch_api.page_url(f, {"code": "PA"}, 0)
    assert "page=1" in url and "per_page=50" in url and "state=PA" in url


def test_values_of_nested_keys_and_alternatives():
    rec = {"id": "x_1", "attributes": {"name": "Made-Up Office", "lat": 44.1, "facility_type": "old",
                                       "address": {"zip": "05001"}, "list": [1, 2]}}
    assert fetch_api.value_of(rec, "attributes.name") == "Made-Up Office"
    assert fetch_api.value_of(rec, "attributes.lat") == "44.1"
    assert fetch_api.value_of(rec, "attributes.facilityType|attributes.facility_type") == "old"
    assert fetch_api.value_of(rec, "attributes.address.zip") == "05001"
    assert fetch_api.value_of(rec, "attributes.list.1") == "2"
    assert fetch_api.value_of(rec, "attributes.missing") == ""
    assert fetch_api.column_name("attributes.name|attributes.title") == "attributes_name"
    assert fetch_api.records_of({"data": [{"a": 1}]}, "data") == [{"a": 1}]
    assert fetch_api.records_of([{"a": 1}], "") == [{"a": 1}]


class FakeAnswer(io.BytesIO):
    """A response body that works as a context manager, like urllib's."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_reads_pages_until_a_short_one_and_sends_the_key_in_a_header(tmp_path, monkeypatch):
    entry = {"id": "made-up-api", "fetch": {
        "method": "json_api", "url": "https://api.example.org/f", "params": {"state": "{code}"},
        "paging": {"style": "page", "page": "page", "size": "per_page", "first": 1, "page_size": 2},
        "records": "data", "fields": ["id", "attributes.name"], "key_env": "MADE_UP_KEY", "key_header": "apikey",
        "pause": 0}}
    asked = []

    def opener(url, headers):
        asked.append((url, dict(headers)))
        page = int(re.search(r"page=(\d+)", url).group(1))
        data = [{"id": f"o{page}{i}", "attributes": {"name": f"Office {page}{i}"}} for i in range(2 if page < 3 else 1)]
        return FakeAnswer(json.dumps({"data": data}).encode())

    monkeypatch.delenv("MADE_UP_KEY", raising=False)
    with pytest.raises(fetch.SourceUnavailable, match="MADE_UP_KEY"):
        fetch_api.fetch_json_api(entry, {"code": "VT"}, str(tmp_path), False, opener=opener, sleep=lambda s: None)
    monkeypatch.setenv("MADE_UP_KEY", "not-a-real-key")
    got = fetch_api.fetch_json_api(entry, {"code": "VT"}, str(tmp_path), False, opener=opener,
                                   sleep=lambda s: None)
    assert got["ok"] and len(asked) == 3
    assert all("not-a-real-key" not in url and h == {"apikey": "not-a-real-key"} for url, h in asked)
    rows = list(csv.DictReader(open(got["path"], encoding="utf-8")))
    assert [r["attributes_name"] for r in rows] == ["Office 10", "Office 11", "Office 20", "Office 21", "Office 30"]
    # Fingerprinting asks nothing and needs no key.
    monkeypatch.delenv("MADE_UP_KEY")
    assert fetch_api.fetch_json_api(entry, {"code": "VT"}, str(tmp_path), True, opener=None)["ok"]


def test_fetch_source_sends_json_api_entries_to_the_new_method(tmp_path, monkeypatch):
    seen = {}

    def fake(entry, values, folder, fingerprint):
        seen.update(entry=entry["id"], code=values["code"])
        return {"ok": True, "version": "2026-11", "path": "", "date": ""}

    monkeypatch.setattr(fetch_api, "fetch_json_api", fake)
    e = entry_of("va-benefits-offices")
    fetch.fetch_source(e, region("us-vermont"), catalogue.settings_for(catalogue.load(), region("us-vermont")),
                       str(tmp_path), None, fingerprint=True)
    assert seen == {"entry": "va-benefits-offices", "code": "VT"}


# --- the readers -----------------------------------------------------------------------------------------------

def test_va_health_facilities_types_and_opening_dates(tmp_path):
    e = entry_of("va-health-facilities")
    path = write_csv(tmp_path / "va.csv", ["VHA_STA_NO", "VHA_STA_NAME", "VHA_PRIM_SVC", "VHA_OPERA_DAT", "_lat", "_lon"], [
        ["999", "Made-Up VA Medical Center", "VAMC", "1938-10-01", "44.26", "-72.58"],
        ["999GA", "Invented VA Clinic", "PCCBOC", "1900-01-01", "44.27", "-72.57"],
        ["0999V", "Pretend Vet Center", "VTCR", "2001-05-01", "44.28", "-72.56"],
        ["0999MVC", "Pretend Mobile Vet Center", "MVCTR", "2009-02-26", "44.29", "-72.55"]])
    got = {p["name"]: p for p in read(e, path, "us-vermont")}
    assert set(got) == {"Made-Up VA Medical Center", "Invented VA Clinic", "Pretend Vet Center"}
    assert got["Made-Up VA Medical Center"]["type"] == "veterans medical center"
    assert got["Made-Up VA Medical Center"]["first"] == 193810
    assert got["Invented VA Clinic"]["first"] is None            # VAST's unknown date, 1900-01-01
    assert got["Pretend Vet Center"]["tag"] == "vet center"


def test_va_benefits_offices_leave_out_desks_inside_other_places(tmp_path):
    e = entry_of("va-benefits-offices")
    path = write_csv(tmp_path / "vba.csv", ["id", "attributes_name", "attributes_classification", "attributes_lat",
                                            "attributes_long"], [
        ["vba_999", "Made-Up VA Regional Benefit Office", "VA Regional Benefit Office", "44.26", "-72.58"],
        ["vba_999a", "VetSuccess on Campus at Invented College", "VetSuccess on Campus", "44.27", "-72.57"]])
    got = read(e, path, "us-vermont")
    assert [p["name"] for p in got] == ["Made-Up VA Regional Benefit Office"]
    assert got[0]["key"] == "va-benefits-offices:vba_999" and got[0]["type"] == "veterans benefits office"


SITE_HEADER = ["Site Dashboard Surrogate Key", "Site Category", "Site Name", "Grant Number", "Site Type", "Site Subtype",
               "Address", "City", "State", "Postal Code", "Telephone Number", "Longitude", "Latitude"]
CMS = "Centers for Medicare & Medicaid Services"


def test_site_dashboard_keeps_the_places_people_visit(tmp_path):
    e = entry_of("hrsa-site-dashboard")

    def row(key, cat, name, kind, sub, state="VT"):
        return [key, cat, name, "NA", kind, sub, "1 Made Up St", "Montpelier", state, "05602", "802-555-0100",
                "-72.58", "44.26"]
    path = write_csv(tmp_path / "SITE_DASHBOARD.csv", SITE_HEADER, [
        row("CMS1", CMS, "MADEUP REGIONAL HOSP", "Hospital", "Short Term"),
        row("CMS2", CMS, "Invented Critical Access Hospital", "Hospital", "Critical Access Hospitals"),
        row("CMS3", CMS, "Pretend Health and Rehab", "Skilled Nursing Facilities/Nursing Facility (Dually Certified)",
            "Title 18/19"),
        row("CMS4", CMS, "Made-Up Dialysis", "End Stage Renal Disease Facility", "End Stage Renal Disease"),
        row("RHC5", "Rural Health Clinic", "Invented Family Practice", "Rural Health Clinic", "Rural Health Clinic"),
        row("CMS6", CMS, "Made-Up Home Care", "Home Health Agency", "Home Health Agency"),
        row("CMS7", CMS, "Invented Hospice", "Hospice", "Hospice"),
        row("CMS8", CMS, "Made-Up Group Home ICF/MR", "Intermediate Care Facility for Individuals with Intellectual "
            "Disabilities", "Title 19 Only"),
        row("NHSC9", "National Health Service Corps", "Jane Doe Practice", "Private Practice", "NA"),
        row("0999V", "Veterans Health Administration", "Pretend Vet Center", "Facility", "NA"),
        row("BPS1", "Health Center Service Delivery", "Invented Health Center", "Service Site", "Freestanding"),
        row("CMS10", CMS, "Elsewhere Hospital", "Hospital", "Short Term", state="NH")])
    got = {p["name"]: p["type"] for p in read(e, path, "us-vermont")}
    assert got == {"Madeup Regional Hospital": "hospital",
                   "Invented Critical Access Hospital": "critical access hospital",
                   "Pretend Health and Rehab": "nursing home", "Made-Up Dialysis": "dialysis center",
                   "Invented Family Practice": "rural health clinic"}


def test_snap_retailers_dates_types_and_store_numbers(tmp_path):
    e = entry_of("usda-snap-retailers")
    header = ["Record ID", "Store Name", "Store Type", "Street Number", "Street Name", "Additional Address", "City",
              "State", "Zip Code", "Zip4", "County", "Latitude", "Longitude", "Authorization Date", "End Date"]
    path = write_csv(tmp_path / "snap.csv", header, [
        ["1", "MADEUP MART 1234", "Convenience Store", "1", "Main St", " ", "Montpelier", "VT", "05602", "", "",
         "44.26", "-72.58", "5/8/2006", "3/1/2016"],
        ["2", "Invented Grocers #58", "Supermarket", "2", "Main St", " ", "Montpelier", "VT", "05602", "", "",
         "44.27", "-72.57", "2/2/1999", " "],
        ["3", "Pretend Delivery", "Delivery Route", "3", "Main St", "", "Montpelier", "VT", "05602", "", "",
         "44.28", "-72.56", "1/1/2010", ""],
        ["4", "Doe, Jane", "Farmers' Market", "4", "Main St", "", "Montpelier", "VT", "05602", "", "",
         "44.29", "-72.55", "1/1/2012", ""],
        ["5", "Elsewhere Market", "Supermarket", "5", "Main St", "", "Concord", "NH", "03301", "", "",
         "44.25", "-72.59", "1/1/2012", ""]])
    got = {p["name"]: p for p in read(e, path, "us-vermont")}
    assert set(got) == {"Madeup Mart", "Invented Grocers"}
    assert got["Madeup Mart"]["first"] == 200605 and got["Madeup Mart"]["last"] == 201603
    assert got["Madeup Mart"]["type"] == "convenience store" and got["Madeup Mart"]["cls"] == "business"
    assert got["Invented Grocers"]["last"] is None and got["Invented Grocers"]["type"] == "supermarket"


def test_fsa_service_center_names(tmp_path):
    e = entry_of("usda-fsa-offices")
    path = write_csv(tmp_path / "fsa.csv", ["site_id", "site_name", "office_type", "_lat", "_lon"], [
        ["1", "MADEUP JCTN SERVICE CENTER", "Service Center", "44.26", "-72.58"],
        ["2", "INVENTED FSA AND NRCS STATE OFFICES", "State Office", "44.27", "-72.57"]])
    got = {p["name"]: p["type"] for p in read(e, path, "us-vermont")}
    assert got == {"Madeup Junction USDA Service Center": "USDA service center",
                   "Invented FSA and NRCS State Offices": "USDA state office"}


def test_pennsylvania_office_names_and_kinds(tmp_path):
    e = entry_of("pa-state-offices")
    path = write_csv(tmp_path / "pa.csv", ["name", "kind", "point"], [
        ["MADEUP CAO", "County Assistance Office", "POINT (-76.88 40.27)"],
        ["Invented County AAA", "Area Agencies on Aging", "POINT (-76.87 40.28)"],
        ["Pretendville D.O.", "Parole Office Locations", "POINT (-76.86 40.29)"],
        ["PENNSYLVANIA STATE POLICE MADEUP STATION", "State Police Station", "POINT (-76.85 40.30)"],
        ["Made-Up Child Care", "Child Care Provider", "POINT (-76.84 40.31)"]])
    got = {p["name"]: p["type"] for p in read(e, path, "us-pennsylvania")}
    assert got == {"Madeup County Assistance Office": "social services office",
                   "Invented County Area Agency on Aging": "area agency on aging",
                   "Pretendville District Parole Office": "parole office",
                   "Pennsylvania State Police Madeup Station": "police station"}


def test_new_york_dmv_office_names(tmp_path):
    e = entry_of("ny-dmv-offices")
    path = write_csv(tmp_path / "ny.csv", ["key", "name", "kind", "point"], [
        ["COUNTY OFFICE MADEUPVILLE", "MADEUPVILLE", "COUNTY OFFICE", "POINT (-73.75 42.65)"],
        ["TVB OFFICE INVENTED TVB", "INVENTED TVB", "TVB OFFICE", "POINT (-73.76 42.66)"]])
    got = {p["name"]: p["type"] for p in read(e, path, "us-new-york")}
    assert got == {"Madeupville DMV Office": "motor vehicle office",
                   "Invented Traffic Violations Bureau": "traffic violations bureau"}


def test_dc_dmv_names_and_kiosks(tmp_path):
    e = entry_of("dc-government-locations")
    path = write_csv(tmp_path / "dc.csv", ["GLOBALID", "NAME", "ABBREV", "_lat", "_lon"], [
        ["{1}", "Made-Up Service Center", "DMV", "38.90", "-77.03"],
        ["{2}", "Self-Service Vehicle Emissions Inspection Kiosk - Invented", "DMV", "38.91", "-77.02"],
        ["{3}", "Office of Pretend Affairs", "OPA", "38.92", "-77.01"]])
    got = {p["name"]: p["type"] for p in read(e, path, "us-district-of-columbia")}
    assert got == {"Made-Up DMV Service Center": "motor vehicle office",
                   "Office of Pretend Affairs": "government office"}
