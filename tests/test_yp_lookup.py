"""The Yellow Pages lookups (placepacks/directories/yellowpages.py, tools/yp_lookup.py) and the "details only"
sources' plumbing (placepacks/details.py, PackWriter.fill_details). Offline: every business, page, number and
answer here is made up; a stand-in web and a stand-in GitHub answer.

Covered: reading a results page (facts only: never a rating, a review or a description), the matching rules (a
like name AND the same street address, or coordinates within 75 m; never a home business or a person's name; two
phone numbers is no answer), a listing page read for hours only within the day's share, social pages dropped, a
block page stopping the run (exit 3, "blocked", the results uploaded, no new start), the work list from a
businesses pack and an addresses pack (one place per business, those already complete left out), resuming where it
stopped, the day's limit, the upload merging with the previous file (keeping two), and the pack build reading the
newest file into biz_details, filling only what a place lacks."""

import csv
import datetime
import gzip
import json
import os
import re
import shutil
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from placepacks import catalogue, contact, details, fetch, split, uploaded  # noqa: E402
from placepacks.chains import polite  # noqa: E402
from placepacks.directories import packs_input  # noqa: E402
from placepacks.directories import yellowpages as yp  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

import yp_lookup  # noqa: E402

VT = "us-vermont"
TODAY = datetime.date(2026, 12, 3)


class Clock:
    """A pretend clock: sleep() moves it on; every sleep is kept."""

    def __init__(self):
        """Start at 1000 s."""
        self.now, self.slept = 1000.0, []

    def __call__(self):
        """The time now."""
        return self.now

    def sleep(self, seconds):
        """Move the clock on."""
        self.slept.append(round(seconds, 3))
        self.now += seconds


class FakeWeb:
    """A stand-in web: {url or a function of the url: answer (text, or (status, text))}; requests kept."""

    def __init__(self, routes):
        """See the class docstring."""
        self.routes, self.requests = routes, []

    def __call__(self, request, timeout):
        """Answer like polite._urllib_opener."""
        url = request.full_url
        self.requests.append((url, dict(request.header_items())))
        answer = self.routes.get(url)
        if answer is None:
            answer = next((v for k, v in self.routes.items() if callable(k) and k(url)), None)
        if callable(answer):
            answer = answer(url)
        if answer is None:
            return 404, {}, b"not here"
        status, text = answer if isinstance(answer, tuple) else (200, answer)
        return status, {"Content-Type": "text/html; charset=utf-8"}, text.encode("utf-8")


def client(routes, budget=50):
    """A polite client over a FakeWeb with a pretend clock."""
    clock = Clock()
    web = FakeWeb(routes)
    return (polite.Polite(budget, yp.PAUSE, opener=web, sleep=clock.sleep, clock=clock, waits=(5,),
                          agent=yp.USER_AGENT), web, clock)


def result(ypid, name, street, phone, hours=None, town="Madeup", website=None, rating=True):
    """One made-up result: its JSON-LD object and its card's HTML."""
    thing = {"@type": "LocalBusiness", "@context": "https://schema.org", "name": name,
             "url": f"https://www.yellowpages.com/madeup-vt/mip/{re.sub('[^a-z]+', '-', name.lower())}-{ypid}",
             "address": {"@type": "PostalAddress", "streetAddress": street, "addressLocality": town,
                         "addressRegion": "VT", "postalCode": "05999"}, "telephone": phone}
    if hours:
        thing["openingHours"] = hours
    if rating:
        thing["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": 2, "reviewCount": 9}
    link = (f'<div class="links"><a class="track-visit-website" href="{website}" rel="nofollow">Website</a></div>'
            if website else "")
    card = (f'<div class="result" id="lid-{ypid}"><h2 class="n"><a class="business-name"><span>{name}</span></a>'
            f'</h2>{link}<div class="snippet"><p class="body">A made-up review that must never be kept.</p></div>'
            f'<div class="phones phone primary">{phone}</div></div>')
    return thing, card


def page(*results):
    """A made-up results page of results."""
    ld = json.dumps([t for t, _ in results])
    return (f'<html><head><script type="application/ld+json">{ld}</script></head><body>'
            + "".join(c for _, c in results) + "</body></html>")


RECORD = {"key": "overture-places:abc", "name": "Pretend Cafe & Deli", "type": "cafe", "brand": "", "lat": 44.2,
          "lon": -72.5, "town": "Madeup", "addresses": ["12 Elm Street"]}


# ------------------------------------------------------------------------------------------------ one lookup

def test_a_results_page_gives_facts_only():
    got = yp.parse_results(page(result(11, "Pretend Cafe & Deli", "12 Elm St", "(802) 555-0101", ["Mo-Fr 07:00-15:00"],
                                       website="https://pretendcafe.example/")))
    assert got == [{"name": "Pretend Cafe & Deli", "street": "12 Elm St", "city": "Madeup", "state": "VT",
                    "postcode": "05999", "phone": "(802) 555-0101", "opening_hours": "Mo-Fr 07:00-15:00",
                    "url": "https://www.yellowpages.com/madeup-vt/mip/pretend-cafe-deli-11",
                    "website": "https://pretendcafe.example/", "lat": None, "lon": None}]
    assert not any("review" in str(v).lower() or "rating" in str(v).lower() for v in got[0].values())


def test_the_matching_rules():
    same = result(1, "The Pretend Cafe &amp; Deli LLC", "12 ELM ST", "802-555-0101")[0]
    other_street = result(2, "Pretend Cafe & Deli", "99 Oak Street", "802-555-0102")[0]
    other_name = result(3, "Pretend Hardware", "12 Elm St", "802-555-0103")[0]
    home = result(4, "Pretend Cafe & Deli", "", "802-555-0104")[0]
    as_result = lambda t: yp.parse_results(page((t, "")))  # noqa: E731
    assert yp.choose(RECORD, as_result(same))[1] == "name+address"
    assert yp.choose(RECORD, as_result(other_street)) == (None, "no match")
    assert yp.choose(RECORD, as_result(other_name)) == (None, "no match")
    assert yp.choose(RECORD, as_result(home)) == (None, "no match")          # no street: a home business
    assert yp.choose(RECORD, []) == (None, "no results")
    person = yp.parse_results(page(result(5, "Alice Example", "12 Elm St", "802-555-0105")))
    assert yp.choose({**RECORD, "name": "Alice Example"}, person) == (None, "no match")
    # coordinates within 75 m count when Yellow Pages gives them; farther do not
    near = dict(as_result(other_street)[0], lat=44.2004, lon=-72.5)
    far = dict(near, lat=44.21)
    assert yp.choose(RECORD, [near])[1] == "name+distance" and yp.choose(RECORD, [far])[0] is None
    # two matching results with different phone numbers: no answer
    twin = dict(as_result(same)[0], phone="802-555-0199")
    assert yp.choose(RECORD, as_result(same) + [twin]) == (None, "ambiguous")


def test_a_lookup_takes_phone_website_and_hours():
    c, web, _ = client({lambda u: "search?" in u: page(result(1, "Pretend Cafe & Deli", "12 Elm St", "(802) 555-0101",
                                                              ["Mo-Fr 07:00-15:00"],
                                                              website="https://pretendcafe.example/?utm_source=yp"))})
    row, extra = yp.lookup(c, RECORD, "VT", today=TODAY)
    assert row == {"key": "overture-places:abc", "lat": "44.200000", "lon": "-72.500000", "phone": "802-555-0101",
                   "website": "https://pretendcafe.example", "opening_hours": "Mo-Fr 07:00-15:00",
                   "matched_on": "name+address", "checked": "2026-12-03"}
    assert extra == 0 and len(web.requests) == 1
    url, headers = web.requests[0]
    assert "search_terms=Pretend+Cafe+%26+Deli" in url and "geo_location_terms=Madeup%2C+VT" in url
    assert headers["User-agent"] == yp.USER_AGENT and "place-packs" in yp.USER_AGENT


def test_the_listing_page_is_read_for_hours_only_when_allowed_and_socials_are_dropped():
    listing = ('<script type="application/ld+json">{"@type": "Restaurant", "openingHoursSpecification": '
               '[{"dayOfWeek": "Monday", "opens": "08:00", "closes": "16:00"}]}</script>')
    routes = {lambda u: "search?" in u: page(result(7, "Pretend Cafe & Deli", "12 Elm St", "802-555-0101",
                                                    website="https://www.facebook.com/pretendcafe")),
              "https://www.yellowpages.com/madeup-vt/mip/pretend-cafe-deli-7": listing}
    c, web, _ = client(routes)
    row, extra = yp.lookup(c, RECORD, "VT", today=TODAY)
    assert (row["opening_hours"], row["website"], extra, len(web.requests)) == ("Mo 08:00-16:00", "", 1, 2)
    c, web, _ = client(routes)
    row, extra = yp.lookup(c, RECORD, "VT", allow_detail=False, today=TODAY)
    assert (row["opening_hours"], extra, len(web.requests)) == ("", 0, 1)


def test_people_and_offices_are_never_looked_up():
    c, web, _ = client({})
    row, _ = yp.lookup(c, {**RECORD, "name": "Alice Example"}, "VT", today=TODAY)
    assert row["matched_on"].startswith("skipped") and not web.requests
    row, _ = yp.lookup(c, {**RECORD, "name": "Pretend Insurance", "type": "insurance agency"}, "VT", today=TODAY)
    assert row["matched_on"].startswith("skipped") and not web.requests
    row, _ = yp.lookup(c, {**RECORD, "town": ""}, "VT", today=TODAY)
    assert row["matched_on"] == "skipped: no town known" and not web.requests


@pytest.mark.parametrize("answer", [(403, "Forbidden"), (429, "slow down"),
                                    (200, "<html><title>Just a moment...</title>cf-chl-</html>")])
def test_a_block_page_raises(answer):
    c, _, _ = client({lambda u: True: answer})
    with pytest.raises(polite.Blocked):
        yp.lookup(c, RECORD, "VT", today=TODAY)


# ------------------------------------------------------------------------------------------------ the job

class FakeGitHub:
    """A stand-in for placepacks.directories.github.GitHub: releases are folders; packs.json lists the packs."""

    def __init__(self, folder, packs=None):
        """packs: {(region, part): path of a made-up pack}."""
        self.folder, self.packs, self.calls = folder, packs or {}, []
        os.makedirs(folder, exist_ok=True)

    def _dir(self, tag):
        """The folder of a release."""
        return os.path.join(self.folder, tag)

    def ensure_release(self, tag, title, notes):
        """Make the release folder."""
        os.makedirs(self._dir(tag), exist_ok=True)
        return {"id": tag, "tag_name": tag}

    def release(self, tag):
        """The release, or None."""
        return {"id": tag, "tag_name": tag} if os.path.isdir(self._dir(tag)) else None

    def assets(self, rel):
        """Its files."""
        return [{"id": n, "name": n} for n in sorted(os.listdir(self._dir(rel["id"])))]

    def download(self, asset, path):
        """Copy a file out of the 'release' (the release is found from the file's folder)."""
        for tag in os.listdir(self.folder):
            src = os.path.join(self.folder, tag, asset["name"])
            if os.path.exists(src):
                shutil.copy(src, path)
                return path
        raise RuntimeError("no such file")

    def upload(self, rel, path, name):
        """Copy a file into the release."""
        self.calls.append(("upload", name))
        shutil.copy(path, os.path.join(self._dir(rel["id"]), name))

    def delete(self, asset):
        """Delete a file."""
        self.calls.append(("delete", asset["name"]))
        for tag in os.listdir(self.folder):
            p = os.path.join(self.folder, tag, asset["name"])
            if os.path.exists(p):
                os.remove(p)

    def packs_of(self, folder):
        """{(region, part): info} of the made-up packs."""
        return {k: {"name": os.path.basename(p), "path": p, "release": "packs"} for k, p in self.packs.items()}

    def download_pack(self, info, folder):
        """Copy the made-up pack."""
        return shutil.copy(info["path"], os.path.join(folder, info["name"]))


META = {"region_id": VT, "state": "Vermont", "country": "United States"}


def make_packs(tmp_path):
    """A made-up businesses pack (Overture and Foursquare listing the same cafe, a complete chain store, a person's
    name, a shop with a phone but no hours) and an addresses pack around them."""
    biz = str(tmp_path / "us-vermont-businesses.osmpack")
    w = PackWriter(biz, 202612)
    cafe = "Pretend Cafe & Deli"
    w.add_point("overture-places:cafe", "overture-places", cafe, "business", "cafe", 44.20037, -72.50037, type="cafe")
    w.add_point("fsq-places:cafe", "fsq-places", cafe, "business", "cafe", 44.20067, -72.50037, type="cafe")
    w.add_point("alltheplaces:x:1", "alltheplaces", "Made-up Burgers", "business", "fast_food", 44.21037, -72.50037,
                type="fast food", brand=("Made-up Burgers", ""),
                contact={"phone": "802-555-0177", "opening_hours": "Mo-Su 06:00-23:00"})
    w.add_point("overture-places:person", "overture-places", "Alice Example", "business", "shop", 44.22037, -72.50037)
    w.add_point("overture-places:shop", "overture-places", "Pretend Books & Gifts", "business", "books", 44.23037,
                -72.50037,
                type="book shop", contact={"phone": "802-555-0166"})
    w.finish({**META, "part": "businesses"})
    addr = str(tmp_path / "us-vermont-addresses.osmpack")
    w = PackWriter(addr, 202612)
    w.add_address("nad", "12", "Elm St", "Madeup", 44.20047, -72.50037)
    w.add_address("nad", "40", "Oak St", "Madeup", 44.23047, -72.50037)
    w.finish({**META, "part": "addresses"})
    return {(VT, "businesses"): biz, (VT, "addresses"): addr}


def test_the_businesses_pack_gives_the_places_and_their_details(tmp_path):
    packs = make_packs(tmp_path)
    got = {p["key"]: p for p in packs_input.places(packs[(VT, "businesses")])}
    assert set(got) == {"overture-places:cafe", "fsq-places:cafe", "alltheplaces:x:1", "overture-places:person",
                        "overture-places:shop"}
    assert got["alltheplaces:x:1"]["opening_hours"] == "Mo-Su 06:00-23:00"
    assert got["overture-places:shop"]["type"] == "book shop" and got["overture-places:shop"]["phone"]
    close, town = packs_input.Addresses(packs[(VT, "addresses")]).near(44.20037, -72.50037)
    assert close == ["12 Elm St"] and town == "Madeup"


def test_the_work_list_has_one_place_per_business_phones_first(tmp_path):
    packs = make_packs(tmp_path)
    addresses = packs_input.Addresses(packs[(VT, "addresses")])
    records = []
    for p in packs_input.places(packs[(VT, "businesses")]):
        p["addresses"], p["town"] = addresses.near(p["lat"], p["lon"])
        records.append(p)
    rows = yp_lookup.work_list(records)
    assert [(r["key"], r["need"]) for r in rows] == [("overture-places:cafe", "phone"),
                                                     ("overture-places:person", "phone"),
                                                     ("overture-places:shop", "hours")]
    assert rows[0]["addresses"] == "12 Elm St" and rows[0]["town"] == "Madeup"
    assert [r["key"] for r in yp_lookup.work_list(records, skip={"overture-places:cafe"})][0] == "fsq-places:cafe"


def answers(block_on=None):
    """The stand-in Yellow Pages: the cafe and the bookshop are found; block_on: a name whose search is refused."""
    def search(url):
        """A results page for the search in url."""
        if block_on and block_on.replace(" ", "+") in url:
            return 403, "Forbidden"
        if "Pretend+Cafe+%26+Deli" in url:
            return page(result(1, "Pretend Cafe & Deli", "12 Elm St", "802-555-0101", ["Mo-Fr 07:00-15:00"]))
        if "Pretend+Books+%26+Gifts" in url:
            return page(result(2, "Pretend Books & Gifts", "40 Oak Street", "802-555-0166", ["Tu-Sa 10:00-18:00"]))
        return page()
    return {lambda u: "search?" in u: search}


def run_job(tmp_path, gh, routes, day_limit=100, today=TODAY):
    """Run the job once over the made-up packs; returns (exit code, progress, web)."""
    progress = yp_lookup.Progress(str(tmp_path / "progress"))
    clock = Clock()
    web = FakeWeb(routes)
    code = yp_lookup.run(progress, gh, str(tmp_path / "work"), day_limit=day_limit, opener=web, sleep=clock.sleep,
                         clock=clock, today=today, regions={VT: catalogue.regions()[VT]}, jitter=lambda a, b: 0.5)
    return code, progress, web


def release_rows(gh):
    """{key: row} of the newest yp-lookups file in the stand-in release."""
    folder = os.path.join(gh.folder, "uploaded-sources")
    names = sorted(n for n in os.listdir(folder) if n.startswith("yp-lookups-"))
    return names, details.read_rows(os.path.join(folder, names[-1])) if names else {}


def test_the_job_looks_up_resumes_and_uploads(tmp_path):
    gh = FakeGitHub(str(tmp_path / "gh"), make_packs(tmp_path))
    # a day's limit of one request: the cafe is looked up, then the day ends
    code, progress, web = run_job(tmp_path, gh, answers(), day_limit=1)
    assert code == 0 and len(web.requests) == 1
    names, rows = release_rows(gh)
    assert names == ["yp-lookups-20261203.csv.gz"]
    assert rows["overture-places:cafe"]["phone"] == "802-555-0101"
    assert rows["overture-places:cafe"]["matched_on"] == "name+address"
    assert not os.path.exists(progress.pending)                       # emptied by the upload
    assert progress.region(VT)["index"] == 1 and progress.data["requests_today"] == 1
    # the next day it goes on where it stopped (the person is skipped without a request, then the bookshop)
    code, progress, web = run_job(tmp_path, gh, answers(), today=TODAY + datetime.timedelta(days=1))
    assert code == 0 and [u for u, _ in web.requests] and all("Pretend+Books+%26+Gifts" in u for u, _ in web.requests)
    names, rows = release_rows(gh)
    assert names == ["yp-lookups-20261203.csv.gz", "yp-lookups-20261204.csv.gz"]       # the newest two kept
    assert rows["overture-places:shop"]["opening_hours"] == "Tu-Sa 10:00-18:00"
    assert rows["overture-places:person"]["matched_on"].startswith("skipped")
    assert "overture-places:cafe" in rows                              # merged with the previous file
    assert progress.region(VT)["status"] == "done"
    # a waiting pause of 3 to 4 seconds between requests
    assert yp.PAUSE == 3.0


def test_a_block_page_stops_the_run_and_uploads_what_was_found(tmp_path):
    gh = FakeGitHub(str(tmp_path / "gh"), make_packs(tmp_path))
    code, progress, web = run_job(tmp_path, gh, answers(block_on="Pretend Books"))
    assert code == 3 and "403" in progress.data["blocked"]["reason"]
    names, rows = release_rows(gh)
    assert "overture-places:cafe" in rows and "overture-places:shop" not in rows
    assert progress.region(VT)["index"] == 2                           # the bookshop is still to do
    status = json.load(open(progress.path, encoding="utf-8"))
    assert status["blocked"]["region"] == VT


def test_a_region_without_packs_is_passed_over(tmp_path):
    gh = FakeGitHub(str(tmp_path / "gh"), {})
    code, progress, web = run_job(tmp_path, gh, answers())
    assert code == 0 and not web.requests
    assert progress.region(VT)["status"] == "passed over" and "no businesses pack" in progress.region(VT)["note"]


def test_the_states_go_by_population():
    order = yp_lookup.region_order()
    codes = [c for _, c in order]
    assert codes[0] == "CA" and codes.index("TX") < codes.index("FL") < codes.index("NY") < codes.index("VT")
    assert ("us-california-los-angeles", "CA") in order and ("us-california", "CA") not in order


# ------------------------------------------------------------------------------------------------ the build

def detail_entry(source="yp-lookups"):
    """The catalogue entry of a details-only source (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source)))


def test_the_catalogue_entries_are_details_sources_last_in_line():
    for source in ("yp-lookups", "business-websites"):
        e = detail_entry(source)
        assert e["reader"] == "details" and e["part"] == "businesses" and e["fetch"]["method"] == "release_latest"
        assert source in contact.CONTACT_SOURCES and source in contact.HOURS_SOURCES
        assert contact.CONTACT_SOURCES.index(source) > contact.CONTACT_SOURCES.index("fsq-places")
    assert contact.CONTACT_SOURCES[-1] == "yp-lookups"
    assert detail_entry()["fetch"]["release"] == "uploaded-sources"
    assert catalogue.check() == []
    from placepacks import lookup, writer
    assert lookup.DETAIL_ORDER == writer.CONTACT_ORDER == contact.CONTACT_SOURCES


def test_fill_details_fills_only_what_a_place_lacks(tmp_path):
    path = str(tmp_path / "p.osmpack")
    w = PackWriter(path, 202612)
    w.add_point("alltheplaces:x:1", "alltheplaces", "Made-up Burgers", "business", "fast_food", 44.2, -72.5,
                brand=("Made-up Burgers", ""), contact={"phone": "802-555-0177"})
    w.add_point("ny-liquor-licences:9", "ny-liquor-licences", "Pretend Tavern & Grill", "business", "bar", 44.3, -72.5)
    w.add_point("overture-places:p", "overture-places", "Alice Example", "business", "shop", 44.4, -72.5)
    assert w.fill_details("yp-lookups", "alltheplaces:x:1", {"phone": "802-555-0999", "website": "https://b.example",
                                                             "opening_hours": "Mo-Su 06:00-23:00"})
    assert w.fill_details("yp-lookups", "ny-liquor-licences:9", {"phone": "8025550123"})
    assert not w.fill_details("yp-lookups", "overture-places:p", {"phone": "802-555-0111"})    # a person
    assert not w.fill_details("yp-lookups", "overture-places:gone", {"phone": "802-555-0111"})  # not in the pack
    assert not w.fill_details("yp-lookups", "alltheplaces:x:1", {"phone": "802-555-0100"})      # nothing lacking
    w.finish({**META, "part": "businesses"})
    pack = PackReader(path)
    assert pack.details_of("alltheplaces:x:1") == {"phone": "802-555-0177", "website": "https://b.example",
                                                   "opening_hours": "Mo-Su 06:00-23:00"}
    assert pack.details_of("ny-liquor-licences:9") == {"phone": "802-555-0123"}
    assert pack.details_of("overture-places:p") == {}


def publish_file(gh_fake, name, rows):
    """Put a made-up details file in the stand-in release (as gh would show it)."""
    os.makedirs(gh_fake.folder, exist_ok=True)
    details.write_rows(os.path.join(gh_fake.folder, name), {r["key"]: r for r in rows})


class FakeRelease:
    """A stand-in for gh with one release folder (placepacks.uploaded.run_gh)."""

    def __init__(self, folder):
        """See the class docstring."""
        self.folder = folder

    def __call__(self, args, timeout=0):
        """Answer like gh."""
        if args[0] == "api":
            if not os.path.isdir(self.folder):
                return 1, "", "gh: Not Found (HTTP 404)"
            if "/releases/tags/" in args[1]:
                return 0, "5\n", ""
            return 0, "".join(f"{n}\t1\n" for n in sorted(os.listdir(self.folder))), ""
        if args[:2] == ["release", "download"]:
            name, target = args[args.index("--pattern") + 1], args[args.index("--dir") + 1]
            shutil.copy(os.path.join(self.folder, name), os.path.join(target, name))
            return 0, "", ""
        return 1, "", "unknown"


def test_the_build_reads_the_newest_file_into_biz_details(tmp_path, monkeypatch):
    fake = FakeRelease(str(tmp_path / "release"))
    monkeypatch.setattr(uploaded, "run_gh", fake)
    monkeypatch.setattr(uploaded.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(tmp_path))
    region = catalogue.regions()[VT]
    entry = detail_entry()
    # no file yet: skipped with a reason
    got = fetch._fetch_one(entry, region, catalogue.load(), str(tmp_path / "w"), None, True)
    assert got["status"] == "skipped" and "waiting for the first yp-lookups file" in got["reason"]
    row = {"key": "overture-places:cafe", "lat": "44.2", "lon": "-72.5", "phone": "802-555-0101", "website": "",
           "opening_hours": "Mo-Fr 07:00-15:00", "matched_on": "name+address", "checked": "2026-12-03"}
    publish_file(fake, "yp-lookups-20261101.csv.gz", [dict(row, phone="802-555-0000")])
    publish_file(fake, "yp-lookups-20261203.csv.gz", [row, dict(row, key="overture-places:none", phone="",
                                                                opening_hours="", matched_on="no match"),
                                                      dict(row, key="overture-places:far", lat="40.7", lon="-74.0")])
    os.remove(uploaded._cache_path("uploaded-sources")) if os.path.exists(uploaded._cache_path("uploaded-sources")) \
        else None
    national = tmp_path / "national"
    fetch.prepare(str(national), cat={"accepted": [entry]})
    with open(national / "yp-lookups" / "yp-lookups.csv", newline="", encoding="utf-8") as f:
        assert [r["key"] for r in csv.DictReader(f)] == ["overture-places:cafe", "overture-places:far"]
    counts = split.split_tabular(entry, str(national / "yp-lookups"), str(tmp_path / "split"), {VT: region})
    assert counts == {VT: 1}
    got = fetch.fetch_source(entry, region, {}, str(tmp_path / "work"), str(tmp_path / "split" / VT))
    assert got["ok"] and got["version"] == "uploaded-sources/yp-lookups-20261203.csv.gz"
    # the build: an Overture cafe without details, then the details source (read last)
    from placepacks import build
    from placepacks.readers import load_all
    overture = next(e for e in catalogue.load()["accepted"] if e["id"] == "overture-places")
    load_all()
    path = str(tmp_path / "b.osmpack")
    w = PackWriter(path, 202612)
    w.add_point("overture-places:cafe", "overture-places", "Pretend Cafe & Deli", "business", "cafe", 44.2, -72.5)
    from placepacks.readers import READERS
    assert READERS["details"](got["path"], entry, dict(region), w) == 1
    w.finish({**META, "part": "businesses"})
    assert PackReader(path).details_of("overture-places:cafe") == {"phone": "802-555-0101",
                                                                   "opening_hours": "Mo-Fr 07:00-15:00"}
    assert overture["part"] == entry["part"] and build is not None


def test_the_build_reads_details_sources_last():
    import inspect
    from placepacks import build
    assert 'e.get("reader") == "details"' in inspect.getsource(build.build)


def test_merge_keeps_found_details_over_a_later_empty_lookup():
    old = {"k": {"key": "k", "phone": "802-555-0101", "website": "", "opening_hours": "", "checked": "2026-06-01"}}
    new = {"k": {"key": "k", "phone": "", "website": "", "opening_hours": "", "checked": "2026-12-01"},
           "j": {"key": "j", "phone": "802-555-0102", "checked": "2026-12-01"}}
    got = details.merge(old, new)
    assert got["k"]["phone"] == "802-555-0101" and got["k"]["checked"] == "2026-12-01" and got["j"]["phone"]


def test_sqlite_is_closed_after_reading_places(tmp_path):
    packs = make_packs(tmp_path)
    list(packs_input.places(packs[(VT, "businesses")]))
    os.remove(packs[(VT, "businesses")])                    # not held open
    assert not os.path.exists(packs[(VT, "businesses")]) and sqlite3 and gzip
