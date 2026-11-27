"""Hospital and clinic accessibility (placepacks/health_access): insurers' public FHIR provider directories
(Location records only: accessibility extensions of both profiles, hours, phone, NPI; practitioners' own offices,
address-only names and records without accessibility or hours left out; paging on the payer's own hosts; robots.txt
obeyed), hospitals' own accessibility pages (a fixed list of facts and the accessibility desk's phone, never the
page's text or a person's name), and the pack build tying the rows to the hospitals and clinics already in the pack.
Offline: every insurer answer, hospital, page, id and number here is made up."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, features  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.health_access import fhir, hospital_pages  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

from test_map_vendors import TODAY, Web, client  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402

VT = "us-vermont"


def location(lid, name, lat=44.01, lon=-72.01, access=True, hours=True, org=None, npi=None):
    """A made-up Plan-Net Location resource."""
    res = {"resourceType": "Location", "id": lid, "status": "active", "name": name,
           "telecom": [{"system": "fax", "value": "8025550199"}, {"system": "phone", "value": "8025550100",
                                                                  "use": "work"}],
           "address": {"line": ["1 Hospital Dr"], "city": "Testville", "state": "VT", "postalCode": "05001"},
           "position": {"latitude": lat, "longitude": lon}}
    if access:
        res["extension"] = [
            {"url": "http://hl7.org/fhir/us/davinci-pdex-plan-net/StructureDefinition/accessibility",
             "valueCodeableConcept": {"coding": [{"code": "handiaccess", "display": "handicap accessible"}]}},
            {"extension": [{"url": "http://hl7.org/fhir/uv/vhdir/StructureDefinition/accessibility",
                            "valueCodeableConcept": {"coding": [{"code": "ASL", "display": "American Sign Language"},
                                                                {"code": "TTY"}], "text": "Hearing Impaired"}}]}]
    if hours:
        res["hoursOfOperation"] = [{"daysOfWeek": ["mon", "tue", "wed", "thu", "fri"], "openingTime": "08:00:00",
                                    "closingTime": "17:00:00"}, {"daysOfWeek": ["sat"], "openingTime": "09:00:00",
                                                                 "closingTime": "12:00:00"}]
    if org:
        res["managingOrganization"] = {"display": org}
    if npi:
        res["identifier"] = [{"system": "http://hl7.org/fhir/sid/us-npi", "value": npi}]
    return res


def directory_web():
    """A made-up insurer directory of two pages; the next link of the second points to another host (not
    followed)."""
    base = fhir.PAYERS["fhir-humana"]["base"]
    first = {"resourceType": "Bundle", "link": [{"relation": "next", "url": base + "/Location?page=2"}], "entry": [
        {"resource": location("L1", "Madeup General Hospital", npi="1999999901")},
        {"resource": location("L2", "Alice Example MD")},
        {"resource": location("L3", "12 MAIN ST-TESTVILLE-VT-05001")},
        {"resource": location("L4", "Madeup Clinic", access=False, hours=False)},
        {"resource": location("L5", "12 MAIN ST-TESTVILLE-VT-05001", org="Madeup Family Health Center")}]}
    second = {"resourceType": "Bundle", "link": [{"relation": "next", "url": "https://elsewhere.example/Location"}],
              "entry": [{"resource": location("L6", "Madeup General Hospital")}]}
    return Web({"https://fhir.humana.com/robots.txt": (404, ""),
                base + "/Location?_count=500": (200, first), base + "/Location?page=2": (200, second)})


def test_fhir_rows():
    """Accessibility phrases from both profiles, TTY, hours in OpenStreetMap syntax, the work phone, the NPI; a
    practitioner's own office, an address-only name and a record with nothing to say left out; the managing
    organisation's name when the Location's is an address; the same place once; another host's page not read."""
    web = directory_web()
    stats = {}
    rows = list(fhir.collect(client(web), "fhir-humana", stats))
    assert [r["name"] for r in rows] == ["Madeup General Hospital", "Madeup Family Health Center"]
    h = rows[0]
    assert h["npi"] == "1999999901" and h["phone"] == "8025550100" and h["opening_hours"] == \
        "Mo-Fr 08:00-17:00; Sa 09:00-12:00"
    assert h["notes"] == ("Accessibility (Humana provider directory): handicap accessible; Hearing Impaired: "
                          "American Sign Language, TTY")
    assert h["kind"] == "site" and h["address"] == "1 Hospital Dr, Testville, VT 05001"
    assert not any("elsewhere" in u for u in web.asked) and stats["pages"] == 2 and stats["kept"] == 2
    assert "Alice" not in json.dumps(rows)


FACT_PAGE = """<html><body><nav>x</nav><h1>Accessibility</h1>
<p>Wheelchairs are available at the main entrance. Free sign language interpreters are provided for patients who
are deaf. We offer documents in braille and large print. Service animals are welcome.</p>
<p>For accessibility services, call our ADA coordinator Jane Doe at (802) 555-0177 or jane@madeup.example.</p>
<p>Accessible parking is in Garage B. Call 802-555-0100 for directions.</p><script>var x = "braille";</script>
</body></html>"""


def hospital_web():
    """A made-up hospital site with an accessibility page, and one whose robots.txt disallows everything."""
    return Web({"https://www.madeuphospital.example/robots.txt": (200, "User-agent: *\nAllow: /\n"),
                "https://www.madeuphospital.example/": (200, '<a href="/patients-visitors/accessibility">Accessibility'
                                                             ' services</a><a href="/careers">Careers</a>'),
                "https://www.madeuphospital.example/patients-visitors/accessibility": (200, FACT_PAGE),
                "https://www.closed.example/robots.txt": (200, "User-agent: *\nDisallow: /\n")})


def test_hospital_pages():
    """Only the facts and the accessibility desk's phone; never the coordinator's name or e-mail; robots.txt
    obeyed."""
    org = {"org": "Madeup General Hospital", "homepage": "https://www.madeuphospital.example",
           "place_key": "wikidata:Q999901", "lat": "44.01", "lon": "-72.01"}
    row, status = hospital_pages.scan_hospital(client(hospital_web()), org)
    assert status == "ok"
    assert row["notes"].startswith("Accessibility (hospital's website): wheelchairs available; sign language "
                                   "interpreters; language interpreters; braille materials; large print materials; "
                                   "service animals welcome; accessible parking; accessibility services phone "
                                   "802-555-0177; page https://www.madeuphospital.example/patients-visitors/")
    assert "Jane" not in row["notes"] and "@" not in row["notes"]
    assert row["key"] == "hospital-pages:Q999901" and row["place_key"] == "wikidata:Q999901"
    web = hospital_web()
    row, status = hospital_pages.scan_hospital(client(web), {**org, "homepage": "https://www.closed.example"})
    assert row is None and status == "robots" and web.asked == ["https://www.closed.example/robots.txt"]


def test_build_ties_rows_to_places(tmp_path):
    """health-access: the hospital already in the pack (by the same name nearby) gets the phone, hours and note;
    a clinic the pack does not have adds nothing (no site row); health-access-businesses gives an NPPES clinic its
    details by NPI and writes no features."""
    rows = list(fhir.collect(client(directory_web()), "fhir-humana", {}))
    rows.append({**rows[1], "key": "fhir-humana:L9", "site": "fhir-humana:L9", "name": "Unknown Clinic",
                 "site_name": "Unknown Clinic", "lat": 44.05, "lon": -72.05})
    path = tmp_path / "health-access.csv"
    features.write_csv(str(path), rows)
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    region = dict(catalogue.regions()[VT])
    w = PackWriter(str(tmp_path / "extra.osmpack"))
    w.add_point("hrsa-site-dashboard:77", "hrsa-site-dashboard", "MADEUP GENERAL HOSPITAL", "public", "hospital",
                44.0102, -72.0101)
    features.read(str(path), cat["health-access"], region, w)
    w.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "extra.osmpack"))
    assert pack.details_of("hrsa-site-dashboard:77") == {"phone": "802-555-0100",
                                                          "opening_hours": "Mo-Fr 08:00-17:00; Sa 09:00-12:00"}
    assert "American Sign Language" in pack.notes_for("hrsa-site-dashboard:77")[0]
    assert pack.features_near(44.05, -72.05, metres=500) == []
    pack.close()
    w = PackWriter(str(tmp_path / "biz.osmpack"))
    w.add_point("cms-nppes-organisations:1999999901", "cms-nppes-organisations", "Madeup Gen Hosp Outpatient",
                "business", "clinic", 44.02, -72.02)
    features.read(str(path), cat["health-access-businesses"], region, w)
    w.finish({"part": "businesses", "region_id": VT})
    pack = PackReader(str(tmp_path / "biz.osmpack"))
    assert pack.details_of("cms-nppes-organisations:1999999901")["phone"] == "802-555-0100"
    assert not pack.has_features
    pack.close()


def test_run_catalogue_and_workflow(tmp_path):
    """The collection "healthaccess" (FHIR units and hospital shards), a run writing its CSV, the catalogue entries
    and the workflow's shape."""
    spec = dirrun.collections()["healthaccess"]
    assert {"fhir-cigna", "fhir-humana", "fhir-molina", "hospital-pages-1"} <= set(spec["units"])
    summary = dirrun.run("healthaccess", "fhir-humana", str(tmp_path), opener=directory_web(),
                         sleep=lambda s: None, today=TODAY)
    assert summary["status"] == "ok" and summary["rows"] == 2
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    assert cat["health-access"]["keep_unmatched_sites"] is False and cat["health-access-businesses"]["features"] is \
        False and cat["health-access-businesses"]["part"] == "businesses"
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "health-access.yml"), "10")


def test_odd_hospital_links_never_fail_the_shard():
    """"&amp;" in a link is unescaped and its space encoded when asked for; a broken IPv6 link is skipped without a
    request; one hospital's unexpected error is counted and the next hospital is read."""
    home = "https://www.oddlinks.example"
    page = ('<a href="http://[broken/accessibility">Accessibility</a>'
            '<a href="/armc/getpage.php?name=Admissions&amp;sub=For Patients">For Patients</a>'
            '<a href="mailto:x@oddlinks.example">Accessibility office</a>')
    links = hospital_pages.access_links(page, home, home)
    assert links == [home + "/armc/getpage.php?name=Admissions&sub=For Patients"]
    web = Web({home + "/robots.txt": (404, ""), home + "/": (200, page),
               home + "/armc/getpage.php?name=Admissions&sub=For%20Patients": (200, FACT_PAGE),
               "https://www.madeuphospital.example/robots.txt": (200, "User-agent: *\nAllow: /\n"),
               "https://www.madeuphospital.example/": (200, '<a href="/patients-visitors/accessibility">'
                                                            'Accessibility</a>'),
               "https://www.madeuphospital.example/patients-visitors/accessibility": (200, FACT_PAGE)})
    orgs = [{"org": "Madeup Broken Host", "homepage": "http://[::1", "place_key": "wikidata:Q999900",
             "lat": "44.0", "lon": "-72.0"},
            {"org": "Madeup Odd Links Hospital", "homepage": home, "place_key": "wikidata:Q999902",
             "lat": "44.02", "lon": "-72.02"},
            {"org": "Madeup Error Hospital", "homepage": None, "place_key": None, "lat": "x", "lon": "y"},
            {"org": "Madeup General Hospital", "homepage": "https://www.madeuphospital.example",
             "place_key": "wikidata:Q999901", "lat": "44.01", "lon": "-72.01"}]
    stats = {}
    rows = list(hospital_pages.collect(client(web), "hospital-pages-1", stats, orgs=orgs))
    assert [r["key"] for r in rows] == ["hospital-pages:Q999902", "hospital-pages:Q999901"]
    assert stats["ok"] == 2 and stats["failed"] + stats["error"] == 2
    assert not any("[" in u for u in web.asked)


def test_a_shard_out_of_time_ends_with_the_hospitals_read():
    """The budget running out ends the shard with the rows found (stats["stopped"]), not an exception."""
    web = hospital_web()
    org = {"org": "Madeup General Hospital", "homepage": "https://www.madeuphospital.example",
           "place_key": "wikidata:Q999901", "lat": "44.01", "lon": "-72.01"}
    orgs = [org, {**org, "place_key": "wikidata:Q999903"}]
    stats = {}
    rows = list(hospital_pages.collect(client(web, budget=4), "hospital-pages-1", stats, orgs=orgs))
    assert len(rows) == 1 and "budget" in stats["stopped"]
