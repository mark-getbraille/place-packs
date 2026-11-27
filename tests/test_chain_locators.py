"""The chain store-locator collectors (placepacks/chains) and their source "chain-locators". Offline: every store,
page, number and answer here is made up, and a stand-in web (FakeWeb) and a stand-in gh (FakeRelease) answer.

Covered: the polite client (an identified User-Agent, a pause per host, retries with back-off, a clean stop on a
refusal or a challenge page, the request budget); opening hours in OpenStreetMap's syntax; a JSON API collector
(Burger King's, GM's with its split searches, Ford's); a sitemap + JSON-LD collector (Jack in the Box's forgiving
reading, Budget's hours text and map link, Wyndham's position from the page); a run's CSV and summary (ok,
blocked); the release set (a failed or blocked chain keeps its previous file, too few stores is not used, the newest
two sets kept); the pack build's reading of the release (no set: skipped; the newest set read, split per region and
read with its contact details); the history not broken by a failed chain; and the workflow's shape."""

import csv
import gzip
import json
import os
import shutil
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks import catalogue, contact, fetch, split, uploaded  # noqa: E402
from placepacks import chains as chain_registry  # noqa: E402
from placepacks.chains import (avis, base, budget, burger_king, ford_dealers, gm_dealers, hours,  # noqa: E402
                               jack_in_the_box, jsonld, polite, release, run, wyndham)
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
META = {"region_id": VT, "state": "Vermont", "country": "United States", "part": "businesses"}


class Clock:
    """A pretend clock: sleep() moves it on, and every sleep is kept in .slept."""

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
    """A stand-in web: routes {url or (url, body text): answer}; an answer is a text, a dict (JSON), a (status,
    text) pair or a function of the request. Every request is kept in .requests."""

    def __init__(self, routes):
        """See the class docstring."""
        self.routes, self.requests = routes, []

    def __call__(self, request, timeout):
        """Answer one request like polite._urllib_opener."""
        url = request.full_url
        body = request.data.decode() if request.data else None
        self.requests.append((url, dict(request.header_items()), body))
        answer = self.routes.get((url, body), self.routes.get(url))
        if answer is None:
            for key, value in self.routes.items():
                if callable(key) and key(url):
                    answer = value
                    break
        if callable(answer):
            answer = answer(url, body)
        if answer is None:
            return 404, {}, b"not here"
        status, text = answer if isinstance(answer, tuple) else (200, answer)
        if isinstance(text, (dict, list)):
            text = json.dumps(text)
        return status, {"Content-Type": "text/html; charset=utf-8"}, text.encode("utf-8")


def client(routes, budget=100, pause=1.5):
    """A Polite client over a FakeWeb, with a pretend clock."""
    clock = Clock()
    web = FakeWeb(routes)
    c = polite.Polite(budget, pause, opener=web, sleep=clock.sleep, clock=clock, waits=(5, 20))
    return c, web, clock


# ------------------------------------------------------------------------------------------- the polite client

def test_requests_are_identified_paced_and_retried():
    tries = {"n": 0}

    def flaky(url, body):
        tries["n"] += 1
        return (503, "busy") if tries["n"] == 1 else "<html>ok</html>"
    c, web, clock = client({"https://a.example/1": flaky, "https://a.example/2": "two", "https://b.example/": "b"})
    assert c.fetch("https://a.example/1") == "<html>ok</html>"
    assert c.fetch("https://a.example/2") == "two"
    assert c.fetch("https://b.example/") == "b"
    agents = {h.get("User-agent") for _, h, _ in web.requests}
    assert agents == {polite.USER_AGENT} and "place-packs" in polite.USER_AGENT and "github.com" in polite.USER_AGENT
    # the 503 waited 5 s (the first back-off) and the next request to the same host waited its pause; the other
    # host was not made to wait
    assert clock.slept == [5, 1.5]
    assert c.used == 4
    # never less than a second per host, whatever a chain asks for
    assert polite.Polite(10, pause=0.1).pause == polite.MIN_PAUSE


@pytest.mark.parametrize("answer", [(403, "Forbidden"), (429, "Too many requests"),
                                    (503, "<html><head><title>Just a moment...</title></head></html>"),
                                    (200, '{"url":"https://geo.captcha-delivery.com/interstitial/?x=1"}'),
                                    (200, "<script src=\"/_Incapsula_Resource?SWJIYLWA=1\"></script>")])
def test_a_refusal_or_a_challenge_stops_at_once(answer):
    c, web, clock = client({"https://shop.example/x": answer})
    with pytest.raises(polite.Blocked):
        c.fetch("https://shop.example/x")
    assert len(web.requests) == 1                       # never tried again, never got round


def test_the_budget_and_server_errors_end_cleanly():
    c, web, _ = client({"https://a.example/": "x"}, budget=2)
    c.fetch("https://a.example/")
    c.fetch("https://a.example/")
    with pytest.raises(polite.BudgetSpent):
        c.fetch("https://a.example/")
    c, web, clock = client({"https://a.example/": (500, "down")})
    with pytest.raises(polite.RequestFailed):
        c.fetch("https://a.example/")
    assert len(web.requests) == 3 and clock.slept[:1] == [5]       # two back-offs, then given up
    c, _, _ = client({})
    with pytest.raises(polite.NotFound):
        c.fetch("https://a.example/gone")


# ------------------------------------------------------------------------------------------- hours

def test_opening_hours_in_openstreetmap_syntax():
    assert hours.from_text("Sun - Sat 7:00 AM - 8:00 PM") == "Mo-Su 07:00-20:00"
    assert hours.from_text("Mon-Fri 9am-5pm, Sat 10am-2pm") == "Mo-Fr 09:00-17:00; Sa 10:00-14:00"
    assert hours.from_text("Mo-Fr 08:00-17:00; Sa 09:00-12:00") == "Mo-Fr 08:00-17:00; Sa 09:00-12:00"
    assert hours.from_text("Open 24 hours") == "24/7"
    assert hours.from_text("call for hours") == ""
    every = [{"dayOfWeek": f"http://schema.org/{d}", "opens": "04:00 A.M.", "closes": "04:00 A.M."}
             for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    assert hours.from_spec(every) == "24/7"
    assert hours.from_spec([{"dayOfWeek": ["Saturday", "Sunday"], "opens": "10:00", "closes": "00:00"}]) == \
        "Sa,Su 10:00-24:00"
    assert hours.clock("7:30am") == "07:30" and hours.clock("noon") == "12:00" and hours.clock("25:00") == ""


# ------------------------------------------------------------------------------------------- JSON APIs

def bk_answer(nodes):
    """A made-up answer of the Burger King API."""
    return {"data": {"restaurants": {"pageInfo": {"hasNextPage": False}, "totalCount": len(nodes), "nodes": nodes}}}


def bk_node(n, lat, lon, country="USA"):
    """A made-up restaurant of the Burger King API (with an e-mail, which is never kept)."""
    week = {f"{d}Open": "06:00:00" for d in ("mon", "tue", "wed", "thr", "fri", "sat")}
    week.update({f"{d}Close": "23:00:00" for d in ("mon", "tue", "wed", "thr", "fri", "sat")})
    return {"_id": f"restaurant_{n}", "storeId": str(n), "latitude": lat, "longitude": lon,
            "phoneNumber": "8025550100", "email": f"store{n}@example.com",
            "physicalAddress": {"address1": f"{n} Made-up Rd", "city": "MADEUPTOWN", "stateProvinceShort": "VT",
                                "postalCode": "05602", "country": country}, "diningRoomHours": week}


def test_a_json_api_collector_reads_each_store_once(monkeypatch):
    monkeypatch.setattr(burger_king, "us_grid", lambda km: [(44.2, -72.5), (44.3, -72.4)])
    first = bk_answer([bk_node(1, 44.21, -72.51), bk_node(2, 44.25, -72.45)])
    second = bk_answer([bk_node(2, 44.25, -72.45), bk_node(3, 45.5, -73.6, country="CAN")])
    c, web, _ = client({(burger_king.ENDPOINT, json.dumps(burger_king.body(44.2, -72.5))): first,
                        (burger_king.ENDPOINT, json.dumps(burger_king.body(44.3, -72.4))): second})
    rows = list(burger_king.collect(c, {}))
    assert [r["key"] for r in rows] == ["burger-king:1", "burger-king:2"]       # once each; Canada left out
    r = rows[0]
    assert (r["name"], r["brand"], r["brand_wikidata"], r["main_value"], r["type"]) == (
        "Burger King", "Burger King", "Q177054", "fast_food", "burger restaurant")
    assert r["opening_hours"] == "Mo-Sa 06:00-23:00" and r["phone"] == "8025550100"
    assert r["website"] == "https://www.bk.com/store-locator/store/1" and r["city"] == "Madeuptown"
    assert "@" not in json.dumps(rows)
    assert all(h.get("X-ui-region") == "US" for _, h, _ in web.requests)


def gm_dealer(code, lat, lon):
    """A made-up dealer of GM's dealer locator."""
    return {"dealerCode": str(code), "dealerName": f"MADE-UP MOTORS {code}", "dealerUrl": "https://made-up.example",
            "address": {"addressLine1": "1 MAIN ST", "cityName": "MONTPELIER", "countryIso": "US",
                        "countrySubdivisionCode": "VT", "postalCodeFormatted": "05602"},
            "generalContact": {"phone1": "8025550111"}, "geolocation": {"latitude": lat, "longitude": lon},
            "generalOpeningHour": [{"dayOfWeek": [1, 2, 3, 4, 5], "openFrom": "08:00 AM", "openTo": "06:00 PM"},
                                   {"dayOfWeek": [6], "openFrom": "9am", "openTo": "4pm"}]}


def test_a_full_dealer_search_is_split_into_smaller_ones(monkeypatch):
    monkeypatch.setattr(gm_dealers, "us_grid", lambda km: [(44.2, -72.5)])
    monkeypatch.setattr(gm_dealers, "CAP", 3)
    full = {"payload": {"dealers": [gm_dealer(i, 44.2 + i / 100, -72.5) for i in range(3)]}}

    def answer(url, body):
        if "distance=75" in url:
            return full                                  # full: asked again in four quarters
        return {"payload": {"dealers": [gm_dealer(9, 44.3, -72.6)]}}
    c, web, _ = client({lambda u: "/quantum-dealer-locator/" in u: answer})
    rows = list(gm_dealers.collector("buick-dealers")(c, {}))
    assert len(web.requests) == 5 and sum("distance=37" in u for u, _, _ in web.requests) == 4
    assert all(h.get("Clientapplicationid") == "quantum" for _, h, _ in web.requests)
    assert sorted(r["key"] for r in rows) == ["buick-dealers:0", "buick-dealers:1", "buick-dealers:2",
                                              "buick-dealers:9"]
    r = rows[0]
    assert r["name"] == "Made-up Motors 0" and r["brand_wikidata"] == "Q27415" and r["type"] == "car dealer"
    assert r["opening_hours"] == "Mo-Fr 08:00-18:00; Sa 09:00-16:00"


def test_ford_reads_the_pages_client_id_then_each_state(monkeypatch):
    monkeypatch.setattr(ford_dealers, "STATES", ["VT"])
    page = '<script>var x = {"clientId":"0a1b2c3d-1111-2222-3333-444455556666"};</script>'
    day = [{"name": "Sunday", "closed": "true"}] + [{"name": d, "open": "09:00", "close": "18:00"} for d in
                                                    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")]
    dealers = {"Response": {"Dealer": [
        {"PACode": "01", "Name": "Made-up Ford", "Latitude": "44.26", "Longitude": "-72.58", "Phone": "(802) 555-0122",
         "URL": "https://www. made-up-ford.example", "LocationType": "P", "SalesHours": {"Day": day},
         "Address": {"Street1": "2 Main St", "City": "Montpelier", "State": "VT", "PostalCode": "05602"}},
        {"PACode": "02", "Name": "No Position Ford", "Latitude": "0.0", "Longitude": "0.0", "URL": "",
         "Address": {}}]}}
    c, web, clock = client({ford_dealers.PAGE: page,
                            lambda u: "Dealers.json" in u and "make=Ford" in u: dealers,
                            lambda u: "Dealers.json" in u and "make=Lincoln" in u: {"Response": {"Dealer": []}}},
                           pause=10)
    rows = list(ford_dealers.collect(c, {}))
    assert [r["key"] for r in rows] == ["ford-dealers:01-Ford"]          # no position: left out
    assert rows[0]["website"] == "https://www.made-up-ford.example"
    assert rows[0]["opening_hours"] == "Mo-Fr 09:00-18:00"
    assert all(h.get("Application-id") == "0a1b2c3d-1111-2222-3333-444455556666" for u, h, _ in web.requests
               if "Dealers.json" in u)
    assert set(clock.slept) == {10}                                      # ford.com's crawl delay


# ------------------------------------------------------------------------------------------- sitemaps + JSON-LD

def sitemap(urls):
    """A sitemap of urls."""
    return ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>")


def store_page(ld):
    """A store page with one JSON-LD block (text, so it may be malformed on purpose)."""
    return f'<html><head><script type="application/ld+json">{ld}</script></head><body>A store</body></html>'


JITB = "https://locations.jackinthebox.com/us/vt/madeuptown/"
JITB_LD = """{ "@context": "http://schema.org", "@type": "Restaurant", "name": "Jack in the Box",
  "openingHoursSpecification": [ {"@type": "OpeningHoursSpecification", "dayOfWeek": "http://schema.org/Monday",
     "opens": "07:00 A.M.", "closes": "11:00 P.M." }, ],
  "telephone": "802-555-0133", "email": "boss@example.com",
  "geo": {"@type": "GeoCoordinates", "latitude": "44.2601", "longitude": "-72.5801"},
  "address": {"@type": "PostalAddress", "addressCountry": "US", "addressLocality": "Madeuptown",
     "addressRegion": "VT", "postalCode": "05602", "streetAddress": "1 Made-up St"} } } }"""


def test_a_sitemap_collector_reads_each_store_page_and_forgives_its_json():
    pages = [JITB + "1-made-up-st", JITB + "9-gone-st", JITB + "5-no-data-st"]
    routes = {jack_in_the_box.SITEMAP: sitemap(["https://locations.jackinthebox.com", *pages,
                                                "https://locations.jackinthebox.com/us/vt"]),
              pages[0]: store_page(JITB_LD), pages[2]: "<html>no data here</html>"}
    c, web, _ = client(routes)
    stats = {}
    rows = list(jack_in_the_box.collect(c, stats))
    assert stats == {"pages": 3, "gone": 1, "no_store": 1}
    assert len(rows) == 1
    r = rows[0]
    assert r["key"] == "jack-in-the-box:us/vt/madeuptown/1-made-up-st" and r["website"] == pages[0]
    assert (r["lat"], r["lon"], r["phone"], r["opening_hours"]) == ("44.260100", "-72.580100", "802-555-0133",
                                                                    "Mo 07:00-23:00")
    assert "boss@example.com" not in json.dumps(r)


def test_budget_hours_text_phone_in_the_address_and_map_link():
    page = store_page(json.dumps({
        "@context": "http://schema.org/", "@type": "AutoRental", "openingHours": "Sun - Sat 7:00 AM - 8:00 PM",
        "address": {"@type": "PostalAddress", "addressLocality": "Madeuptown", "addressRegion": "Vermont",
                    "postalCode": "05602", "streetAddress": "3 Airport Rd", "telephone": "8025550144"},
        "map": "https://www.google.com/maps/?q=44.2002,-72.5622"}))
    url = "https://www.budget.com/en/locations/us/vt/madeuptown/mpv"
    c, _, _ = client({budget.SITEMAP: sitemap([url, "https://www.budget.com/en/locations/us/vt"]), url: page})
    rows = list(budget.collect(c, {}))
    assert [(r["key"], r["phone"], r["opening_hours"], r["lat"]) for r in rows] == [
        ("budget:MPV", "8025550144", "Mo-Su 07:00-20:00", "44.200200")]
    assert rows[0]["type"] == "car rental"
    url = "https://www.avis.com/en/locations/nam/us/vt/madeuptown/mp1"
    c, _, _ = client({avis.SITEMAP: sitemap([url, "https://www.avis.com/en/locations/eur/fr/paris/cdg"]),
                      url: store_page(json.dumps({"@context": "https://schema.org", "@graph": [
                          {"@type": "WebPage"}, {"@type": "AutoRental", "telephone": "(1) 802-555-0155",
                                                 "geo": {"latitude": 44.21, "longitude": -72.56}}]}))})
    assert [r["key"] for r in avis.collect(c, {})] == ["avis:MP1"]


def test_wyndham_reads_us_hotels_with_the_position_from_the_page():
    us = "https://www.wyndhamhotels.com/super-8/madeuptown-vermont/super-8-madeuptown"
    abroad = "https://www.wyndhamhotels.com/super-8/somewhere-ontario/super-8-somewhere"
    ld = json.dumps({"@context": "https://schema.org", "@type": "Hotel", "identifier": "99001",
                     "name": "Super 8 by Wyndham Madeuptown", "telephone": "+1-802-555-0166",
                     "address": {"streetAddress": "4 Made-up Way", "addressRegion": "VT", "addressCountry": "US"}})
    page = store_page(ld) + ('<div data-x="{&#34;propertyContactNumber&#34;:&#34;+1-802-555-0166&#34;,'
                             '&#34;latitude&#34;:&#34;44.2311&#34;,&#34;longitude&#34;:&#34;-72.5512&#34;}">')
    routes = {wyndham.INDEX.format(code=c): sitemap([us, abroad]) if c == "se" else sitemap([])
              for c in wyndham.GROUPS["wyndham-days-inn-super-8"]}
    routes[us + "/overview"] = page
    c, web, _ = client(routes)
    rows = list(wyndham.collector("wyndham-days-inn-super-8")(c, {}))
    assert not any(abroad in u for u, _, _ in web.requests)                # not a US hotel: never read
    assert [(r["key"], r["brand"], r["brand_wikidata"], r["main_value"], r["lat"]) for r in rows] == [
        ("wyndham-days-inn-super-8:99001", "Super 8", "Q5364003", "motel", "44.231100")]


def test_jsonld_reading_is_forgiving():
    assert jsonld.loads('{"a": 1,} }') == {"a": 1}
    assert jsonld.loads("not json") is None
    things = jsonld.find(store_page('{"@graph": [{"@type": ["Hotel", "LocalBusiness"]}, {"@type": "Thing"}]}'),
                         {"Hotel"})
    assert len(things) == 1


# ------------------------------------------------------------------------------------------- one chain's run

def test_a_run_writes_the_csv_and_its_summary(tmp_path, monkeypatch):
    monkeypatch.setitem(chain_registry.CHAINS, "jack-in-the-box",
                        dict(chain_registry.CHAINS["jack-in-the-box"], pause=1))
    page = JITB + "1-made-up-st"
    web = FakeWeb({jack_in_the_box.SITEMAP: sitemap([page]), page: store_page(JITB_LD)})
    clock = Clock()
    summary = run.run("jack-in-the-box", str(tmp_path), opener=web, sleep=clock.sleep, clock=clock)
    assert summary["status"] == "ok" and summary["rows"] == 1 and summary["requests"] == 2
    with gzip.open(tmp_path / "jack-in-the-box.csv.gz", "rt", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0])[:len(fetch.ATP_FIELDS)] == fetch.ATP_FIELDS            # the All The Places shape
    assert json.loads((tmp_path / "jack-in-the-box.json").read_text())["status"] == "ok"


def test_a_blocked_chain_is_recorded_and_writes_no_csv(tmp_path):
    web = FakeWeb({jack_in_the_box.SITEMAP: (403, "<title>Access Denied</title>")})
    clock = Clock()
    summary = run.run("jack-in-the-box", str(tmp_path), opener=web, sleep=clock.sleep, clock=clock)
    assert summary["status"] == "blocked" and "403" in summary["reason"] and summary["requests"] == 1
    assert not (tmp_path / "jack-in-the-box.csv.gz").exists()
    assert run.matrix("avis budget") == [{"chain": "avis", "timeout": chain_registry.CHAINS["avis"]["timeout_min"]},
                                         {"chain": "budget", "timeout": chain_registry.CHAINS["budget"]["timeout_min"]}]
    with pytest.raises(SystemExit, match="unknown chain"):
        run.matrix("mcdonalds")


def test_every_chain_is_described_and_individual_offices_are_never_collected():
    for cid, spec in chain_registry.CHAINS.items():
        assert spec["budget"] > 0 and spec["pause"] >= polite.MIN_PAUSE and spec["expected"] > 0, cid
        assert spec["endpoint"] and spec["robots"] and 0 < spec["timeout_min"] <= 330, cid
    assert "allstate" not in " ".join(chain_registry.CHAINS)
    assert base.make_row("x", "1", "Made-up Cover", {"office": "insurance"}, 44.2, -72.5) is None
    assert base.make_row("x", "1", "Alice Example", {"shop": "car"}, 44.2, -72.5) is None
    assert base.make_row("x", "1", "Made-up Cars", {"shop": "car"}, 48.85, 2.35) is None      # not in the US
    assert base.make_row("x", "1", "Made-up Cars", {"shop": "car"}, 44.2, -72.5)["key"] == "x:1"
    assert 300 < len(base.us_grid(170)) < 800


# ------------------------------------------------------------------------------------------- the release

class FakeRelease:
    """A stand-in for gh over a folder: api listing (id, then assets), release view/create/upload/download and
    delete-asset. Every call is kept in .calls."""

    def __init__(self, folder):
        """folder: the release's files (missing: no release yet)."""
        self.folder, self.calls = folder, []

    def __call__(self, args, timeout=1800):
        """Answer like gh."""
        self.calls.append(args)
        exists = os.path.isdir(self.folder)
        if args[0] == "api":
            if not exists:
                return 1, "", "gh: Not Found (HTTP 404)"
            if "/releases/tags/" in args[1]:
                return 0, "5\n", ""
            return 0, "".join(f"{n}\t{os.path.getsize(os.path.join(self.folder, n))}\n"
                              for n in sorted(os.listdir(self.folder))), ""
        if args[:2] == ["release", "view"]:
            return (0, "", "") if exists else (1, "", "release not found")
        if args[:2] == ["release", "create"]:
            os.makedirs(self.folder)
            return 0, "", ""
        if args[:2] == ["release", "upload"]:
            shutil.copy(args[3], os.path.join(self.folder, os.path.basename(args[3])))
            return 0, "", ""
        if args[:2] == ["release", "delete-asset"]:
            os.remove(os.path.join(self.folder, args[3]))
            return 0, "", ""
        if args[:2] == ["release", "download"]:
            name, target = args[args.index("--pattern") + 1], args[args.index("--dir") + 1]
            if not os.path.exists(os.path.join(self.folder, name)):
                return 1, "", "no assets match"
            shutil.copy(os.path.join(self.folder, name), os.path.join(target, name))
            return 0, "", ""
        return 1, "", f"unknown {args}"


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """The stand-in release (none yet), in place of gh, and a fresh file-list cache."""
    fake = FakeRelease(str(tmp_path / "release"))
    monkeypatch.setattr(uploaded, "run_gh", fake)
    monkeypatch.setattr(uploaded.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/place-packs")
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(tmp_path))
    return fake


def chain_result(folder, chain, status, stores, date):
    """What one chain's job leaves: its summary and, when ok, its CSV of made-up stores (Vermont)."""
    os.makedirs(folder, exist_ok=True)
    rows = [base.make_row(chain, str(i), f"Made-up {chain} {i}", {"shop": "car"}, 44.2 + i / 1000, -72.5,
                          brand=f"Made-up {chain}", phone="802-555-0177", website=f"https://{chain}.example/{i}",
                          opening_hours="Mo-Fr 09:00-17:00") for i in range(stores)]
    if status == "ok":
        with gzip.open(os.path.join(folder, f"{chain}.csv.gz"), "wt", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=base.FIELDS)
            w.writeheader()
            w.writerows(rows)
    with open(os.path.join(folder, f"{chain}.json"), "w", encoding="utf-8") as f:
        json.dump({"chain": chain, "status": status, "reason": "" if status == "ok" else "HTTP 403",
                   "rows": stores if status == "ok" else 0, "date": date, "expected": 10}, f)


def publish(tmp_path, date, results, ran=("avis", "budget")):
    """Publish a month: results is {chain: (status, stores)}."""
    folder = tmp_path / f"results-{date}"
    for chain, (status, stores) in results.items():
        chain_result(str(folder), chain, status, stores, date)
    os.remove(uploaded._cache_path(release.TAG)) if os.path.exists(uploaded._cache_path(release.TAG)) else None
    return release.publish(str(folder), date, set(ran), sleep=lambda s: None)


def test_a_failed_or_blocked_chain_keeps_its_previous_file(gh, tmp_path):
    first = publish(tmp_path, "2026-11-28", {"avis": ("ok", 4), "budget": ("ok", 6)})
    assert [c for c in gh.calls if c[:2] == ["release", "create"]]           # made on the first publish
    assert {f["chain"]: (f["status"], f["rows"]) for f in first["files"]} == {"avis": ("new", 4), "budget": ("new", 6)}
    uploads = [os.path.basename(c[3]) for c in gh.calls if c[:2] == ["release", "upload"]]
    assert uploads[-1] == "chain-locators-2026-11-28.json"                    # the list last
    # next month: Avis blocked, Budget found far fewer stores (a broken site?): both keep last month's file
    second = publish(tmp_path, "2026-12-28", {"avis": ("blocked", 0), "budget": ("ok", 2)})
    got = {f["chain"]: (f["status"], f["rows"], f["collected"]) for f in second["files"]}
    assert got == {"avis": ("carried", 4, "2026-11-28"), "budget": ("carried", 6, "2026-11-28")}
    assert second["runs"]["avis"]["status"] == "blocked" and "fewer" not in second["runs"]["avis"]["why"]
    assert "stores against" in second["runs"]["budget"]["why"]
    assert "blocked" in release.table(second) and "(from 2026-11-28)" in release.table(second)
    # a third month: only Avis is run (by hand) and works; Budget is kept, not counted as a failure
    third = publish(tmp_path, "2027-01-28", {"avis": ("ok", 5)}, ran=("avis",))
    got = {f["chain"]: (f["status"], f["rows"], f["carried"]) for f in third["files"]}
    assert got == {"avis": ("new", 5, 0), "budget": ("kept", 6, 1)}
    # the newest two sets are kept
    names = sorted(os.listdir(gh.folder))
    assert not any("2026-11-28" in n for n in names)
    assert "chain-locators-2027-01-28.json" in names and "chain-locators-2026-12-28.json" in names


def test_a_chain_carried_too_long_is_dropped(gh, tmp_path):
    publish(tmp_path, "2026-08-28", {"avis": ("ok", 4), "budget": ("ok", 6)})
    for i, month in enumerate(("2026-09-28", "2026-10-28", "2026-11-28", "2026-12-28")):
        listing = publish(tmp_path, month, {"avis": ("ok", 4), "budget": ("failed", 0)})
    chains_in = {f["chain"] for f in listing["files"]}
    assert chains_in == {"avis"} and "too old" in listing["runs"]["budget"]["why"]


# ------------------------------------------------------------------------------------------- the pack build

def entry():
    """The catalogue's chain-locators entry (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == "chain-locators")))


def test_the_catalogue_entry_is_a_contact_source_beside_all_the_places():
    e = entry()
    assert e["part"] == "businesses" and e["kind"] == "businesses" and e["fetch"]["method"] == "release_csv"
    assert "chain-locators" in contact.CONTACT_SOURCES and "chain-locators" in contact.HOURS_SOURCES
    atp = next(x for x in catalogue.load()["accepted"] if x["id"] == "alltheplaces")
    for field in ("columns", "type_column", "brand_column", "brand_wikidata_column", "contact_columns"):
        assert e[field] == atp[field]
    assert e["dedupe_against"] == ["alltheplaces"]
    assert catalogue.check() == []
    assert contact.clean("chain-locators", "Made-up Burgers", None, "8025550100", None, "Mo-Su 06:00-23:00") == {
        "phone": "802-555-0100", "opening_hours": "Mo-Su 06:00-23:00"}


def test_no_set_yet_skips_the_source_with_a_reason(gh, tmp_path):
    region = catalogue.regions()[VT]
    got = fetch._fetch_one(entry(), region, catalogue.load(), str(tmp_path / "w"), None, True)
    assert got["status"] == "skipped" and got["reason"] == release.WAITING
    fetch.prepare_release(entry(), str(tmp_path / "national"))
    assert (tmp_path / "national" / "chain-locators" / fetch.FAILED).read_text() == release.WAITING
    got = fetch._fetch_one(entry(), region, catalogue.load(), str(tmp_path / "w"), str(tmp_path / "national"), False)
    assert got["status"] == "skipped"


def pack_of(tmp_path, national, month, previous=None):
    """Prepare the newest set, split it, fetch Vermont's slice and build its businesses pack (chain-locators only)."""
    shutil.rmtree(national, ignore_errors=True)
    os.remove(uploaded._cache_path(release.TAG)) if os.path.exists(uploaded._cache_path(release.TAG)) else None
    fetch.prepare(str(national), cat={"accepted": [entry()]})
    out = tmp_path / f"split-{month}"
    shutil.rmtree(out, ignore_errors=True)
    regions = {VT: catalogue.regions()[VT]}
    counts = split.split_tabular(entry(), str(national / "chain-locators"), str(out), regions)
    got = fetch.fetch_source(entry(), catalogue.regions()[VT], {}, str(tmp_path / "work"), str(out / VT))
    assert got["ok"] and got["version"].startswith("chain-locators/chain-locators-")
    path = str(tmp_path / f"chain-{month}.osmpack")
    w = PackWriter(path, month)
    read_tabular(got["path"], entry(), dict(catalogue.regions()[VT]), w)
    w.finish(META, previous=previous)
    return path, counts


def test_the_newest_set_is_read_split_and_carries_contact_details(gh, tmp_path):
    publish(tmp_path, "2026-11-28", {"avis": ("ok", 2), "budget": ("ok", 1)})
    path, counts = pack_of(tmp_path, tmp_path / "national", 202612)
    assert counts == {VT: 3}
    with open(tmp_path / "national" / "chain-locators" / "chain-locators.csv", newline="", encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 3
    details = PackReader(path).details_of("chain-locators:avis:0")
    assert details == {"phone": "802-555-0177", "website": "https://avis.example/0",
                       "opening_hours": "Mo-Fr 09:00-17:00"}
    con = sqlite3.connect(path)
    assert {r[0] for r in con.execute("SELECT key FROM points WHERE source = 'chain-locators'")} == {
        "chain-locators:avis:0", "chain-locators:avis:1", "chain-locators:budget:0"}
    con.close()


def test_the_history_is_not_broken_by_a_failed_chain(gh, tmp_path):
    publish(tmp_path, "2026-11-28", {"avis": ("ok", 2), "budget": ("ok", 1)})
    first, _ = pack_of(tmp_path, tmp_path / "national", 202612)
    publish(tmp_path, "2026-12-28", {"avis": ("ok", 2), "budget": ("blocked", 0)})     # Budget blocked
    second, _ = pack_of(tmp_path, tmp_path / "national", 202701, previous=first)
    con = sqlite3.connect(second)
    rows = dict(con.execute("SELECT key, last FROM points WHERE source = 'chain-locators'").fetchall())
    con.close()
    assert rows == {"chain-locators:avis:0": 202701, "chain-locators:avis:1": 202701,
                    "chain-locators:budget:0": 202701}                       # still open: not closed at 202612


def test_a_brand_that_looks_like_a_person_is_kept_with_its_details(tmp_path):
    import zipfile
    feats = [{"type": "Feature", "id": f"f{i}", "geometry": {"type": "Point", "coordinates": [-72.5, 44.2 + i / 100]},
              "properties": dict({"@spider": "pretend", "ref": str(i), "amenity": "fast_food"}, **tags)}
             for i, tags in enumerate([{"brand": "Pretend Burgers", "phone": "802-555-0188"},
                                       {"name": "Alice Example"}])]
    run_zip = tmp_path / "run.zip"
    with zipfile.ZipFile(run_zip, "w") as z:
        z.writestr("output/pretend.geojson", json.dumps({"type": "FeatureCollection", "features": feats}))
    rows = list(fetch.iter_atp(str(run_zip), [(-73.5, 42.7, -71.4, 45.1)]))
    assert [(r["skip"], r.get("name")) for r in rows] == [("", "Pretend Burgers"), ("noname", None)]
    assert contact.clean("chain-locators", "Pretend Burgers", None, "8025550188", brand="Pretend Burgers") == {
        "phone": "802-555-0188"}
    # Without a brand, "Pretend Burgers" is still not a person (no first name); "Mary Jones" is.
    assert contact.clean("chain-locators", "Pretend Burgers", None, "8025550188") == {"phone": "802-555-0188"}
    assert contact.clean("chain-locators", "Mary Jones", None, "8025550188") == {}
    assert base.make_row("x", "1", "Pretend Burgers", {"amenity": "fast_food"}, 44.2, -72.5,
                         brand="Pretend Burgers")["name"] == "Pretend Burgers"


def test_split_keeps_all_the_places_contact_columns():
    atp = next(x for x in catalogue.load()["accepted"] if x["id"] == "alltheplaces")
    assert {"phone", "website", "opening_hours"} <= split.needed_columns(atp)


# ------------------------------------------------------------------------------------------- the workflow

def test_the_workflow_is_monthly_read_only_and_publishes_in_one_job():
    import yaml
    path = os.path.join(ROOT, ".github", "workflows", "chain-locators.yml")
    flow = yaml.safe_load(open(path, encoding="utf-8"))
    on = flow[True] if True in flow else flow["on"]
    assert on["schedule"][0]["cron"].split()[2] == "28"
    assert "chains" in on["workflow_dispatch"]["inputs"]
    assert flow["permissions"] == {"contents": "read"}
    jobs = flow["jobs"]
    collect = jobs["collect"]
    assert collect["strategy"]["fail-fast"] is False and "matrix.timeout" in str(collect["timeout-minutes"])
    assert "permissions" not in collect and "permissions" not in jobs["plan"]
    assert jobs["publish"]["permissions"] == {"contents": "write"}
    text = open(path, encoding="utf-8").read()
    # inputs reach the scripts through env only
    for job in jobs.values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step.get("name")
    # actions pinned to the same commits as the other workflows
    pins = set()
    for other in ("build-packs.yml", "ci.yml"):
        pins |= {line.split("uses:")[1].split("#")[0].strip()
                 for line in open(os.path.join(ROOT, ".github", "workflows", other), encoding="utf-8")
                 if "uses:" in line}
    used = {line.split("uses:")[1].split("#")[0].strip() for line in text.splitlines() if "uses:" in line}
    assert used and used <= pins
