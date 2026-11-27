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


# ------------------------------------------------------------------ partial runs, resuming, odd links (27 Nov fix)

def paged_web(pages=4):
    """A made-up insurer directory of `pages` pages (one kept Location each), linked by stateless cursors."""
    base = fhir.PAYERS["fhir-humana"]["base"]
    routes = {"https://fhir.humana.com/robots.txt": (404, "")}
    for i in range(1, pages + 1):
        url = base + "/Location?_count=500" if i == 1 else f"{base}/Location?_count=500&_continuationToken=c{i}"
        link = [{"relation": "next", "url": f"{base}/Location?_count=500&_continuationToken=c{i + 1}"}] \
            if i < pages else []
        routes[url] = (200, {"resourceType": "Bundle", "link": link,
                             "entry": [{"resource": location(f"P{i}", f"Madeup Clinic {i}", lat=44.0 + i / 100)}]})
    return Web(routes)


def published_keys(gh_folder, name):
    """The keys of a published set file."""
    import csv
    import gzip
    with gzip.open(os.path.join(gh_folder, name), "rt", encoding="utf-8") as f:
        return [r["key"] for r in csv.DictReader(f)]


def test_a_spent_budget_publishes_the_rows_found_and_the_next_run_resumes(tmp_path, monkeypatch):
    """The first GitHub run (27 November 2026) collected 470,000 rows and published nothing. Now: a FHIR unit whose
    budget runs out writes its rows (partial) and where it stopped; the publish keeps them and the cursor; the next
    run starts at that cursor, reaches the end and its rows are merged with the earlier ones; then the cursor is
    cleared and the run after starts from the first page again."""
    import test_chain_locators as chains_test
    from placepacks import uploaded
    from placepacks.chains import release
    fake = chains_test.FakeRelease(str(tmp_path / "release"))
    monkeypatch.setattr(uploaded, "run_gh", fake)
    monkeypatch.setattr(uploaded.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/place-packs")
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(tmp_path))
    spec = dirrun.collections()["healthaccess"]
    assert spec["units"]["fhir-humana"]["resumable"] and spec["units"]["fhir-humana"]["budget"] >= 20000
    assert dirrun.resume_point("healthaccess", "fhir-humana") == ""          # no set yet: the beginning
    # Month 1: robots.txt + 2 pages, then the budget (3 requests) is spent.
    monkeypatch.setitem(spec["units"]["fhir-humana"], "budget", 3)
    out1 = tmp_path / "m1"
    s1 = dirrun.run("healthaccess", "fhir-humana", str(out1), opener=paged_web(), sleep=lambda s: None,
                    today=TODAY)
    assert s1["status"] == "incomplete" and s1["partial"] and s1["rows"] == 2
    assert s1["resume"].endswith("_continuationToken=c3") and (out1 / "fhir-humana.csv.gz").exists()
    listing = dirrun.publish("healthaccess", str(out1), "2026-12-10", {"fhir-humana"}, sleep=lambda s: None)
    entry = listing["files"][0]
    assert entry["status"] == "partial" and entry["rows"] == 2 and entry["resume"] == s1["resume"]
    assert "partial" in release.table(listing)
    # Month 2: starts at the cursor, reads pages 3 and 4 to the end; merged with month 1's rows.
    resume = dirrun.resume_point("healthaccess", "fhir-humana")
    assert resume == s1["resume"]
    monkeypatch.setitem(spec["units"]["fhir-humana"], "budget", 20000)
    web = paged_web()
    out2 = tmp_path / "m2"
    s2 = dirrun.run("healthaccess", "fhir-humana", str(out2), opener=web, sleep=lambda s: None, today=TODAY,
                    resume=resume)
    assert s2["status"] == "ok" and s2["partial"] and s2["rows"] == 2 and s2["resume"] == ""
    assert not any(u.endswith("/Location?_count=500") for u in web.asked)  # page 1 not read again
    listing = dirrun.publish("healthaccess", str(out2), "2027-01-10", {"fhir-humana"}, sleep=lambda s: None)
    entry = listing["files"][0]
    assert entry["rows"] == 4 and "resume" not in entry and listing["runs"]["fhir-humana"]["kept_from_previous"] == 2
    assert published_keys(fake.folder, entry["name"]) == [f"fhir-humana:P{i}" for i in range(1, 5)]
    assert dirrun.resume_point("healthaccess", "fhir-humana") == ""


def test_an_expired_cursor_starts_again_and_a_block_keeps_the_cursor(tmp_path):
    """A cursor that answers "gone" starts the directory again from the first page; a refusal publishes nothing
    and keeps the starting cursor, so no page is skipped next month."""
    base = fhir.PAYERS["fhir-humana"]["base"]
    stale = f"{base}/Location?_count=500&_continuationToken=c3"
    stats = {"resume_from": stale}
    gone = paged_web(pages=1)
    gone.pages[stale] = (410, "gone")
    rows = list(fhir.collect(client(gone), "fhir-humana", stats))
    assert [r["key"] for r in rows] == ["fhir-humana:P1"] and "resume_from" not in stats
    assert stats["resume_expired"].startswith(stale) and stats["resume"] == ""
    blocked = paged_web()
    blocked.pages[stale] = (403, "<title>Access Denied</title>")
    s = dirrun.run("healthaccess", "fhir-humana", str(tmp_path), opener=blocked, sleep=lambda s: None, today=TODAY,
                   resume=stale)
    assert s["status"] == "blocked" and not s["partial"] and s["resume"] == stale
    assert not (tmp_path / "fhir-humana.csv.gz").exists()
    # another host's address is never followed as a cursor
    stats = {"resume_from": "https://elsewhere.example/Location?x=1"}
    list(fhir.collect(client(paged_web(pages=1)), "fhir-humana", stats))
    assert "resume_from" not in stats and stats["resume_ignored"].startswith("https://elsewhere")


def test_a_failed_or_time_limited_unit_keeps_its_rows_generically(tmp_path, monkeypatch):
    """For every collection (run.py), a unit stopped by an error or by its collector's own stop (stats["stopped"],
    the malls' and airports' shares) after finding rows writes them as partial; with no rows, nothing."""
    def broken(client, unit, stats):
        """Two rows, then an unexpected error."""
        yield {"key": "a", "kind": "site", "name": "Madeup A"}
        yield {"key": "b", "kind": "site", "name": "Madeup B"}
        raise ValueError("Invalid IPv6 URL")

    def stopped(client, unit, stats):
        """One row, then the collector's own stop."""
        yield {"key": "c", "kind": "site", "name": "Madeup C"}
        stats["stopped"] = "the time limit of the run is reached after 1 malls with rows"

    def nothing(client, unit, stats):
        """An error before any row."""
        raise ValueError("Invalid IPv6 URL")
        yield  # noqa: unreachable - a generator

    spec = dirrun.collections()["malls"]
    unit = next(iter(spec["units"]))
    for collect, status, rows in ((broken, "failed", 2), (stopped, "incomplete", 1), (nothing, "failed", 0)):
        fake = dict(spec, collect=collect)
        monkeypatch.setattr(dirrun, "collections", lambda fake=fake: {"malls": fake})
        s = dirrun.run("malls", unit, str(tmp_path), opener=Web({}), sleep=lambda s: None, today=TODAY)
        assert (s["status"], s["rows"], s["partial"]) == (status, rows, rows > 0)
        assert (tmp_path / f"{unit}.csv.gz").exists() == (rows > 0) and "resume" not in s


def test_merge_rows_replaces_the_same_keys_and_keeps_the_rest(tmp_path):
    """release.merge_rows: this run's rows win, the previous rows not reached are kept, sorted by key."""
    import csv
    import gzip
    from placepacks.chains import release

    def write(path, rows):
        """A small .csv.gz."""
        with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["key", "name"])
            w.writeheader()
            w.writerows(rows)
    write(tmp_path / "new.csv.gz", [{"key": "b", "name": "B new"}, {"key": "c", "name": "C"}])
    write(tmp_path / "old.csv.gz", [{"key": "a", "name": "A"}, {"key": "b", "name": "B old"}])
    assert release.merge_rows(str(tmp_path / "new.csv.gz"), str(tmp_path / "old.csv.gz"),
                              str(tmp_path / "out.csv.gz")) == (3, 1)
    with gzip.open(tmp_path / "out.csv.gz", "rt", encoding="utf-8") as f:
        assert [(r["key"], r["name"]) for r in csv.DictReader(f)] == [("a", "A"), ("b", "B new"), ("c", "C")]


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
