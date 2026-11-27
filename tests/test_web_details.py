"""The business-website collector (placepacks/directories/websites.py) and its workflow. Offline: every business,
homepage and number here is made up; a stand-in web and a stand-in GitHub answer.

Covered: the schema.org data of one local business on a homepage (JSON-LD and microdata: phone and hours, never an
e-mail), several businesses or another business's name not taken, an Organization alone not taken; robots.txt
always obeyed (no homepage request when it disallows); a refusal or a challenge recorded as "blocked" for that site
while the run goes on; the choice of sites (a website, no phone or hours, not a chain's store, not a shared
website, not read within 180 days); a job and the publishing merged with the previous file; the workflow's shape."""

import datetime
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import details  # noqa: E402
from placepacks.chains import polite  # noqa: E402
from placepacks.directories import websites  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

import test_yp_lookup as ypt  # noqa: E402

TODAY = datetime.date(2026, 12, 20)
PLACE = {"key": "overture-places:w1", "name": "Pretend Bakery & Cafe", "type": "bakery", "brand": "", "lat": 44.2,
         "lon": -72.5, "website": "https://pretendbakery.example/"}


def ld(*things):
    """A homepage with JSON-LD things."""
    return "".join(f'<script type="application/ld+json">{json.dumps(t)}</script>' for t in things)


BAKERY = {"@context": "https://schema.org", "@type": "Bakery", "name": "Pretend Bakery & Cafe",
          "telephone": "(802) 555-0140", "email": "owner@pretendbakery.example",
          "openingHoursSpecification": [{"@type": "OpeningHoursSpecification",
                                         "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                                         "opens": "07:00", "closes": "15:00"}]}


def test_one_local_business_in_json_ld_gives_phone_and_hours_never_the_email():
    how, got = websites.homepage_details(ld({"@type": "WebSite", "name": "x"}, BAKERY), PLACE["name"])
    assert how == "homepage json-ld" and got == {"phone": "(802) 555-0140", "opening_hours": "Mo-Fr 07:00-15:00"}
    assert "@" not in json.dumps(got)


def test_microdata_is_read_when_there_is_no_json_ld():
    page = ('<div itemscope itemtype="https://schema.org/Restaurant"><span itemprop="name">Pretend Bakery &amp; Cafe'
            '</span><div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress"><span '
            'itemprop="streetAddress">12 Elm St</span></div><a href="tel:+18025550140" itemprop="telephone">Call us'
            '</a><meta itemprop="openingHours" content="Mo-Fr 07:00-15:00"><meta itemprop="openingHours" '
            'content="Sa 08:00-12:00"><span itemprop="email">owner@pretendbakery.example</span></div>')
    how, got = websites.homepage_details(page, PLACE["name"])
    assert how == "homepage microdata"
    assert got == {"phone": "+18025550140", "opening_hours": "Mo-Fr 07:00-15:00; Sa 08:00-12:00"}


def test_several_businesses_another_name_or_an_organization_are_not_taken():
    other = dict(BAKERY, name="Made-up Hardware Supply", telephone="802-555-0199")
    assert websites.homepage_details(ld(BAKERY, other), PLACE["name"])[1]["phone"] == "(802) 555-0140"   # ours
    assert websites.homepage_details(ld(other, dict(other, name="Made-up Paints", telephone="802-555-0198")),
                                     PLACE["name"]) == ("several businesses", {})
    assert websites.homepage_details(ld(other), PLACE["name"]) == ("another name", {})
    org = {"@type": "Organization", "name": "Made-up Web Design", "telephone": "802-555-0100"}
    assert websites.homepage_details(ld(org), PLACE["name"]) == ("no business data", {})


def site(routes, budget=20):
    """A client for websites.check over a stand-in web."""
    clock = ypt.Clock()
    web = ypt.FakeWeb(routes)
    return polite.Polite(budget, websites.PAUSE, opener=web, sleep=clock.sleep, clock=clock, waits=(),
                         agent=websites.USER_AGENT), web


def test_robots_txt_is_always_obeyed():
    c, web = site({"https://pretendbakery.example/robots.txt": "User-agent: *\nDisallow: /\n",
                   "https://pretendbakery.example/": ld(BAKERY)})
    row = websites.check(c, PLACE, TODAY)
    assert row["matched_on"] == "robots.txt disallows" and not row["phone"]
    assert [u for u, _ in web.requests] == ["https://pretendbakery.example/robots.txt"]
    c, web = site({"https://pretendbakery.example/robots.txt": "User-agent: place-packs\nDisallow: /\n"})
    assert websites.check(c, PLACE, TODAY)["matched_on"] == "robots.txt disallows"


def test_a_homepage_is_read_with_an_identified_agent():
    c, web = site({"https://pretendbakery.example/": ld(BAKERY)})          # no robots.txt (404): allowed
    row = websites.check(c, PLACE, TODAY)
    assert row == {"key": "overture-places:w1", "lat": "44.200000", "lon": "-72.500000", "phone": "802-555-0140",
                   "website": "", "opening_hours": "Mo-Fr 07:00-15:00", "matched_on": "homepage json-ld",
                   "checked": "2026-12-20"}
    assert all(h["User-agent"] == websites.USER_AGENT for _, h in web.requests)


@pytest.mark.parametrize("answer", [(403, "no"), (200, "<title>Just a moment...</title>")])
def test_a_refusing_site_is_blocked_and_left(answer):
    c, web = site({lambda u: True: answer})
    assert websites.check(c, PLACE, TODAY)["matched_on"] == "blocked"
    assert len(web.requests) == 1                                         # never tried another way


def test_the_choice_of_sites():
    base = dict(PLACE, phone="", opening_hours="")
    records = [dict(base, key="a"), dict(base, key="b", phone="802-555-0100", opening_hours="Mo 09:00-17:00"),
               dict(base, key="c", brand="Made-up Burgers", website="https://burgers.example/1"),
               dict(base, key="d", website=""), dict(base, key="e", website="https://recent.example"),
               dict(base, key="f", website="https://old.example"),
               *[dict(base, key=f"s{i}", website="https://shared.example/") for i in range(4)],
               dict(base, key="g", website="https://www.facebook.com/pretend")]
    checked = {"e": "2026-11-01", "f": "2026-01-01"}
    got = websites.candidates(records, checked, TODAY)
    assert [r["key"] for r in got] == ["a", "f"]                         # never read first, then the oldest
    assert got[0]["website"] == "https://pretendbakery.example"


def make_pack(tmp_path):
    """A made-up businesses pack with two places with websites and no hours."""
    path = str(tmp_path / "us-vermont-businesses.osmpack")
    w = PackWriter(path, 202612)
    for i, name in enumerate(("Pretend Bakery & Cafe", "Made-up Diner & Grill")):
        w.add_point(f"overture-places:w{i}", "overture-places", name, "business", "bakery", 44.20037 + i / 100,
                    -72.50037, type="bakery", contact={"website": f"https://site{i}.example/"})
    w.finish({**ypt.META, "part": "businesses"})
    return {("us-vermont", "businesses"): path}


def test_a_job_and_the_publishing(tmp_path):
    gh = ypt.FakeGitHub(str(tmp_path / "gh"), make_pack(tmp_path))
    gh.ensure_release("web-details", "", "")
    old = {"overture-places:w0": {"key": "overture-places:w0", "lat": "1", "lon": "1", "phone": "802-555-0111",
                                  "checked": "2026-01-01", "matched_on": "homepage json-ld"},
           "fsq-places:elsewhere": {"key": "fsq-places:elsewhere", "lat": "1", "lon": "1", "phone": "802-555-0112",
                                    "checked": "2026-11-01"}}
    details.write_rows(os.path.join(gh.folder, "web-details", "web-details-20261120.csv.gz"), old)
    routes = {"https://site0.example": ld(BAKERY), "https://site1.example": (403, "Forbidden")}
    clock = ypt.Clock()
    out = tmp_path / "out"
    summary = websites.collect(1, 1, str(out), budget=10, gh=gh, opener=ypt.FakeWeb(routes), sleep=clock.sleep,
                               clock=clock, today=TODAY, regions={"us-vermont": ypt.catalogue.regions()["us-vermont"]})
    assert summary["status"] == "ok" and summary["homepages"] == 2 and summary["found"] == 1
    assert summary["stats"] == {"homepage json-ld": 1, "blocked": 1}
    name, count, text = websites.publish(str(out), gh=gh, today=TODAY)
    assert name == "web-details-20261220.csv.gz" and count == 3 and "| 1 | ok | 2 |" in text
    rows = details.read_rows(os.path.join(gh.folder, "web-details", name))
    assert rows["overture-places:w0"]["phone"] == "802-555-0140"                  # the new reading wins
    assert rows["overture-places:w1"]["matched_on"] == "blocked"
    assert "fsq-places:elsewhere" in rows                                          # kept from the previous file
    assert sorted(os.listdir(os.path.join(gh.folder, "web-details"))) == ["web-details-20261120.csv.gz", name]


def test_the_shards_share_the_regions():
    one, two = websites.shard_regions(1, 2), websites.shard_regions(2, 2)
    assert one[0] == "us-california-los-angeles" and not set(one) & set(two)
    assert json.loads(json.dumps([{"shard": 1, "of": 2}])) == [{"shard": 1, "of": 2}]


def test_the_workflow_is_monthly_read_only_and_publishes_in_one_job():
    path = os.path.join(ROOT, ".github", "workflows", "web-details.yml")
    workflow_shape(path, day="20")


def workflow_shape(path, day):
    """The checks every collector workflow passes: monthly, read-only but for publish, inputs only through env,
    actions pinned to the other workflows' commits."""
    import yaml
    flow = yaml.safe_load(open(path, encoding="utf-8"))
    on = flow[True] if True in flow else flow["on"]
    assert on["schedule"][0]["cron"].split()[2] == day and "workflow_dispatch" in on
    assert flow["permissions"] == {"contents": "read"}
    jobs = flow["jobs"]
    assert jobs["collect"]["strategy"]["fail-fast"] is False
    assert all("permissions" not in j for k, j in jobs.items() if k != "publish")
    assert jobs["publish"]["permissions"] == {"contents": "write"}
    for job in jobs.values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")
    pins = set()
    for other in ("build-packs.yml", "ci.yml"):
        pins |= {line.split("uses:")[1].split("#")[0].strip()
                 for line in open(os.path.join(ROOT, ".github", "workflows", other), encoding="utf-8")
                 if "uses:" in line}
    used = {line.split("uses:")[1].split("#")[0].strip() for line in open(path, encoding="utf-8")
            if "uses:" in line}
    assert used and used <= pins
