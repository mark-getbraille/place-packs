"""The local-directory collectors: tourism boards' Simpleview listings (placepacks/directories/simpleview.py) and
chambers' classic ChamberMaster directories (placepacks/directories/chambermaster.py), their runs and sets
(placepacks/directories/run.py) and their reading by the pack build. Offline: every site, listing, member and number
here is made up; a stand-in web and a stand-in gh answer.

Covered: a listing page (JSON-LD and the embedded listing data: position, phone, website, category, hours and
accessibility; never the e-mail or the description), listings without a street address or with a person's name
left out, robots.txt obeyed (its Crawl-delay kept between 2 and 5 s; a disallowed listing never asked for), a
sitemap index followed; a run's CSV and summary, a blocked site; the chambers found from the US Chamber's page, v2
directories told apart by their 51-byte robots.txt and never asked for a page, classic directories read through
their public-facing quick links, members filtered (post office boxes, people, insurance agents, the chamber
itself), a refusing chamber left while the state goes on; the set published and read, a listing matched to an
existing place by its phone carrying its details there, a chamber member placed by the geocoder with home
addresses left out; and the workflows' shape."""

import csv
import gzip
import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, fetch, split, uploaded  # noqa: E402
from placepacks.chains import polite, release  # noqa: E402
from placepacks.directories import chambermaster as cm  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.directories import simpleview as sv  # noqa: E402
from placepacks.directories import tempest  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

import test_yp_lookup as ypt  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402

VT = "us-vermont"
HOME = "https://visitdenver.com"


def listing_page(recid, title, street, lat=44.4759, lon=-73.2121, phone="(802) 555-0130", hours="7:30am-10:00pm",
                 category=("Restaurants", "Cafes")):
    """A made-up Simpleview listing page: JSON-LD and the embedded listing data."""
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "Visit Madeup", "telephone": "802-555-0000"},
        {"@type": "Restaurant", "@id": f"{HOME}/listing/x/{recid}/#localbusiness", "name": title,
         "description": "A long made-up description that must never be kept.", "email": "owner@cafe.example",
         "telephone": phone, "address": {"@type": "PostalAddress", "streetAddress": street,
                                         "addressLocality": "Burlington", "addressRegion": "VT",
                                         "postalCode": "05401"},
         "geo": {"@type": "GeoCoordinates", "latitude": lat, "longitude": lon}}]}
    data = {"latitude": lat, "longitude": lon, "recid": recid, "title": title, "address1": street, "phone": phone,
            "email": "owner@cafe.example", "description": "Never kept either.", "weburl": "https://cafe.example/",
            "primaryCategory": {"catname": category[0], "subcatname": category[1]},
            "amenityTree": [{"amenitytabname": "General", "groups": [{"amenitygroupname": "General", "fields": [
                {"label": "Hours of Operation", "doc": {"value_string": hours}},
                {"label": "Blocks to CCC", "doc": {"value_string": "9"}}]}]},
                {"amenitytabname": "Accessibility", "groups": [{"amenitygroupname": "ADA / Accessibility",
                                                                "fields": [
                    {"label": "Wheelchair Accessible Entrance", "doc": {"value_string": "Yes"}},
                    {"label": "Accessible Parking Spaces", "doc": {"value_string": "4"}},
                    {"label": "Braille Menus", "doc": {"value_string": "No"}}]}]}]}
    return (f'<html><script type="application/ld+json">{json.dumps(ld)}</script><script>var data = '
            f'{json.dumps(data)};</script></html>')


def test_a_listing_page_gives_facts_hours_and_accessibility_only():
    row = sv.listing(listing_page(31, "Made-up Coffee & Bakery", "184 Main Street"), "visitdenver",
                     f"{HOME}/listing/made-up-coffee/31/")
    assert row["key"] == "visitdenver:31" and row["name"] == "Made-up Coffee & Bakery"
    assert (row["lat"], row["lon"]) == ("44.475900", "-73.212100")
    assert row["phone"] == "(802) 555-0130" and row["website"] == "https://cafe.example/"
    assert row["opening_hours"] == "Mo-Su 07:30-22:00" or row["note"].startswith("Hours:")
    assert row["main_value"] == "cafe" and row["category"] == "Restaurants / Cafes"
    assert "Accessibility: Wheelchair Accessible Entrance, Accessible Parking Spaces 4" in row["note"]
    assert "Braille" not in row["note"] and "Blocks" not in row["note"]
    everything = json.dumps(row)
    assert "@" not in everything and "description" not in everything.lower() and "Never kept" not in everything


def test_listings_without_a_street_or_with_a_persons_name_are_left_out():
    url = f"{HOME}/listing/x/1/"
    assert sv.listing(listing_page(1, "Made-up Walking Tours & Co", ""), "visitdenver", url) is None
    assert sv.listing(listing_page(2, "Made-up Tours & Co", "PO Box 12"), "visitdenver", url) is None
    assert sv.listing(listing_page(3, "Alice Example", "12 Elm St"), "visitdenver", url) is None
    assert sv.listing(listing_page(4, "Made-up Inn & Suites", "12 Elm St", lat=51.5, lon=-0.1), "visitdenver",
                      url) is None                                         # not in the US


def fake(routes, budget=100):
    """A polite client over a stand-in web, with its clock."""
    clock = ypt.Clock()
    web = ypt.FakeWeb(routes)
    return polite.Polite(budget, sv.PAUSE, opener=web, sleep=clock.sleep, clock=clock, waits=(5,),
                         agent=sv.USER_AGENT), web, clock


def site_routes(robots="User-agent: *\nDisallow: /plugins/crm/count/\nDisallow: /listing/secret-spa/\n"
                       "Crawl-delay: 9\nSitemap: https://visitdenver.com/sitemap-index.xml\n"):
    """A made-up Simpleview site: robots.txt, a sitemap index, two sitemaps, three listings (one disallowed)."""
    return {f"{HOME}/robots.txt": robots,
            f"{HOME}/sitemap-index.xml": f"<sitemapindex><sitemap><loc>{HOME}/sitemap-listings.xml</loc></sitemap>"
                                         f"<sitemap><loc>{HOME}/sitemap-pages.xml</loc></sitemap></sitemapindex>",
            f"{HOME}/sitemap-listings.xml": "<urlset>" + "".join(
                f"<url><loc>{HOME}/listing/{s}/{n}/</loc></url>" for s, n in (("made-up-cafe", 31),
                                                                              ("made-up-inn", 32),
                                                                              ("secret-spa", 33))) + "</urlset>",
            f"{HOME}/listing/made-up-cafe/31/": listing_page(31, "Made-up Cafe & Deli", "184 Main St"),
            f"{HOME}/listing/made-up-inn/32/": listing_page(32, "Made-up Inn & Suites", "12 Elm St",
                                                            phone="802-555-0132",
                                                            category=("Hotels & Lodging", "Hotels")),
            f"{HOME}/listing/secret-spa/33/": listing_page(33, "Secret Spa & Salon", "1 Oak St")}


def test_a_site_is_read_through_its_sitemap_obeying_robots_txt():
    client, web, clock = fake(site_routes())
    stats = {}
    rows = list(sv.collect(client, "visitdenver", stats))
    assert [r["key"] for r in rows] == ["visitdenver:31", "visitdenver:32"]
    assert rows[1]["main_value"] == "hotel"
    assert not any("secret-spa" in u for u, _ in web.requests)              # disallowed: never asked for
    assert client.pause == sv.MAX_PAUSE                                      # Crawl-delay 9: at most 5 s
    assert stats["listings"] == 2 and all(h["User-agent"] == sv.USER_AGENT for _, h in web.requests)
    client, _, _ = fake(site_routes(robots="User-agent: *\nCrawl-delay: 1\n"))
    list(sv.collect(client, "visitdenver", {}))
    assert client.pause == sv.MIN_PAUSE                                     # at least 2 s


def test_a_run_writes_its_csv_or_records_a_block(tmp_path):
    clock = ypt.Clock()
    summary = dirrun.run("simpleview", "visitdenver", str(tmp_path), opener=ypt.FakeWeb(site_routes()),
                         sleep=clock.sleep, clock=clock)
    assert summary["status"] == "ok" and summary["rows"] == 2
    with gzip.open(tmp_path / "visitdenver.csv.gz", "rt", encoding="utf-8") as f:
        assert [r["key"] for r in csv.DictReader(f)] == ["visitdenver:31", "visitdenver:32"]
    routes = dict(site_routes(), **{f"{HOME}/listing/made-up-inn/32/": (403, "<title>Access Denied</title>")})
    summary = dirrun.run("simpleview", "visitdenver", str(tmp_path), opener=ypt.FakeWeb(routes), sleep=clock.sleep,
                         clock=clock)
    assert summary["status"] == "blocked" and not (tmp_path / "visitdenver.csv.gz").exists()
    assert dirrun.matrix("simpleview", "visitdenver iloveny") == [
        {"unit": "group-01", "units": "iloveny visitdenver", "timeout": 321}]
    assert dirrun.matrix("chambermaster", "vt")[0] == {"unit": "vt", "timeout": 300}
    with pytest.raises(SystemExit):
        dirrun.matrix("simpleview", "visitnowhere")


def test_the_sites_are_the_simpleview_states_and_cities_and_the_blocked_are_not():
    assert len(sv.SITES) == 12 + len(sv.CITY_SITES) and len(sv.CITY_SITES) >= 70
    hosts = " ".join(s["home"] for s in list(sv.SITES.values()) + list(tempest.SITES.values()))
    assert not any(b in hosts for b in list(sv.BLOCKED) + list(sv.CITY_BLOCKED) + sv.NOT_STRUCTURED)
    assert not set(sv.SITES) & set(tempest.SITES)
    assert all(s["state"] in tempest.STATE_CODES.values() for s in tempest.SITES.values())


def test_the_sites_run_in_matrix_groups_within_githubs_limits():
    for collection in ("simpleview", "tempest"):
        jobs = dirrun.matrix(collection)
        units = [u for j in jobs for u in j["units"].split()]
        assert sorted(units) == sorted(dirrun.collections()[collection]["units"])     # every site once
        assert len(jobs) <= 256 and all(j["timeout"] <= 350 for j in jobs)
        spec = dirrun.collections()[collection]
        for j in jobs:
            members = j["units"].split()
            assert len(members) == 1 or sum(dirrun.expected_minutes(spec["units"][u]) for u in members) <= 300


def test_a_group_runs_its_sites_one_after_another(tmp_path):
    clock = ypt.Clock()
    routes = dict(site_routes())
    routes.update({"https://www.iloveny.com/robots.txt": (403, "<title>Just a moment...</title>")})
    got = dirrun.run_units("simpleview", ["iloveny", "visitdenver"], str(tmp_path), total_minutes=350,
                           opener=ypt.FakeWeb(routes), sleep=clock.sleep, clock=clock)
    assert [s["status"] for s in got] == ["blocked", "ok"]
    assert (tmp_path / "visitdenver.csv.gz").exists() and (tmp_path / "iloveny.json").exists()
    got = dirrun.run_units("simpleview", ["visitdenver"], str(tmp_path / "late"), total_minutes=5,
                           opener=ypt.FakeWeb(routes), sleep=clock.sleep, clock=clock)
    assert got[0]["status"] == "incomplete" and got[0]["requests"] == 0


# ------------------------------------------------------------------------------------------------ Tempest

TEMPEST = "https://www.visitmadeup.example"


def tempest_page(listing_id, name, address, phone="(802) 555-0140", category="Craft Cocktails",
                 amenities=("Outdoor Seating", "Wheelchair Accessible")):
    """A made-up Tempest listing page: the listing's and the board's own JSON-LD, the page data and amenities."""
    ld = {"@context": "http://schema.org", "@graph": [
        {"@type": "LocalBusiness", "address": address, "description": "Never kept.", "latitude": "44.4760",
         "longitude": "-73.2125", "name": name, "telephone": phone, "url": "https://bar.example/",
         "email": "owner@bar.example"},
        {"@id": f"{TEMPEST}#identity", "@type": "TouristInformationCenter", "name": "Visit Madeup",
         "telephone": "802-555-0000", "address": {"@type": "PostalAddress", "streetAddress": "1 Board St"}}]}
    items = "".join(f"<li>{a}</li>" for a in amenities)
    return (f'<html><script type="application/ld+json">{json.dumps(ld)}</script>'
            f'<main data-dms-partner-id="9{listing_id}" data-dms-category-name="{category}" '
            f'data-dms-listing-id="{listing_id}"><ul class="text--content detail__amenities">{items}</ul></main>'
            f'</html>')


def tempest_routes():
    """A made-up Tempest board: robots.txt, the Craft sitemap index, a partner sitemap and three listings."""
    return {f"{TEMPEST}/robots.txt": f"User-agent: *\nDisallow: /directory/private-club/\n"
                                     f"Sitemap: {TEMPEST}/sitemaps-1-sitemap.xml\n",
            f"{TEMPEST}/sitemaps-1-sitemap.xml": "<sitemapindex>" + "".join(
                f"<sitemap><loc>{TEMPEST}/sitemaps-1-section-{s}-1-sitemap.xml</loc></sitemap>"
                for s in ("blogDirectory", "partnerDirectory")) + "</sitemapindex>",
            f"{TEMPEST}/sitemaps-1-section-partnerDirectory-1-sitemap.xml": "<urlset>" + "".join(
                f"<url><loc>{TEMPEST}/directory/{s}/</loc></url>" for s in ("made-up-lounge", "made-up-tours",
                                                                            "private-club")) + "</urlset>",
            f"{TEMPEST}/directory/made-up-lounge/": tempest_page(31, "Made-up Lounge &amp; Bar",
                                                                 "184 Main Street Burlington, Vermont 05401"),
            f"{TEMPEST}/directory/made-up-tours/": tempest_page(32, "Made-up Walking Tours", "Burlington, VT 05401"),
            f"{TEMPEST}/directory/private-club/": tempest_page(33, "Private Club", "1 Oak St Burlington, VT 05401")}


def test_a_tempest_listing_gives_facts_and_accessibility_only():
    row = tempest.listing(tempest_page(31, "Made-up Lounge &amp; Bar", "184 Main Street Burlington, Vermont 05401"),
                          "visitmadeup", f"{TEMPEST}/directory/made-up-lounge/")
    assert row["key"] == "visitmadeup:31" and row["name"] == "Made-up Lounge & Bar"
    assert (row["street"], row["city"], row["state"], row["postcode"]) == ("184 Main Street", "Burlington", "VT",
                                                                          "05401")
    assert row["phone"] == "(802) 555-0140" and row["website"] == "https://bar.example/"
    assert row["main_value"] == "bar" and row["category"] == "Craft Cocktails"
    assert row["note"] == "Accessibility: Wheelchair Accessible"            # not "Outdoor Seating"
    assert "owner@" not in json.dumps(row) and "Never kept" not in json.dumps(row)
    assert tempest.listing(tempest_page(4, "Alice Example", "12 Elm St Burlington, VT 05401"), "x",
                           f"{TEMPEST}/directory/a/") is None              # a person's name


def tempest_bare_page(path, name, body, kind="LocalBusiness", category="Restaurants", extra=None):
    """A made-up Tempest listing whose JSON-LD has no address, position or telephone (as on Albany's, Salem's,
    Louisville's and Pittsburgh's pages on 27 November 2026): those are in the page itself (body)."""
    graph = [{"@type": kind, "mainEntityOfPage": path, "name": name, "url": f"{TEMPEST}{path}"},
             {"@id": f"{TEMPEST}#identity", "@type": "Organization", "name": "Visit Madeup",
              "telephone": "802-555-0000"}] + list(extra or [])
    return (f'<html><script type="application/ld+json">{json.dumps({"@graph": graph})}</script>'
            f'<h1>{name}</h1><main data-dms-partner-id="77" data-dms-category-name="{category}">{body}</main>'
            f'<footer><a href="tel:802-555-0000">Visit Madeup</a><p>1 Board St, Burlington, VT 05401</p></footer>'
            f'</html>')


def test_a_tempest_listing_without_json_ld_facts_reads_them_from_the_page():
    """The first GitHub run (27 November 2026) left out every listing of 10 boards: their JSON-LD has no
    position (and some no address or telephone), or types the listing "TouristInformationCenter". The page's map
    button, its "maps?q=" link, its detail address block (the business's name before the street at Pittsburgh),
    the "Contact Information" list (Minneapolis), the telephone link after the address (never the board's own
    number) and the "Website" button are read instead."""
    path = "/directory/made-up-diner/"
    body = ('<button data-imap-point="1" data-marker-lat="44.4761" data-marker-lng="-73.2126" '
            'data-marker-title="Made-up Diner &amp;amp; Grill"></button>'
            '<div class="detail__address links"><div class="detail__address-title">Made-up Diner &amp; Grill</div>'
            '<p>12 Church St<br>Burlington, Vermont 05401</p></div>'
            '<ul class="detail__info"><li><a href="tel:+1-802-555-0141">(802) 555-0141</a></li></ul>'
            '<a class="btn" href="http://diner.example" data-dms-partner-detail-website-click>Website</a>'
            '<button data-marker-lat="40.1" data-marker-lng="-75.1" data-marker-title="An event elsewhere">')
    row = tempest.listing(tempest_bare_page(path, "Made-up Diner &amp; Grill", body, "TouristInformationCenter"),
                          "visitmadeup", f"{TEMPEST}{path}")
    assert row["key"] == "visitmadeup:77" and (row["lat"], row["lon"]) == ("44.476100", "-73.212600")
    assert (row["street"], row["city"], row["state"], row["postcode"]) == ("12 Church St", "Burlington", "VT",
                                                                          "05401")
    assert row["phone"] == "+1-802-555-0141" and row["website"] == "http://diner.example"
    assert row["main_value"] == "restaurant"
    contact = ('<a href="https://www.google.com/maps?q=44.4762,-73.2127">Directions</a>'
               '<h3 class="h3">Contact Information</h3><ul class="list links"><li>Made-up Brewery</li>'
               '<li><a href="mailto:beer@brewery.example">beer@brewery.example</a></li><li>520 Pine St</li>'
               '<li> Burlington, Vermont 05401</li></ul>')
    row = tempest.listing(tempest_bare_page("/directory/made-up-brewery/", "Made-up Brewery", contact,
                                            category="Uniquely Madeup"),
                          "visitmadeup", f"{TEMPEST}/directory/made-up-brewery/")
    assert row["street"] == "520 Pine St" and row["city"] == "Burlington" and row["lat"] == "44.476200"
    assert row["phone"] == "" and "beer@" not in json.dumps(row)            # the footer's board number is not it
    # A listing the board says nothing more about (no street anywhere) is still left out.
    assert tempest.listing(tempest_bare_page("/directory/x/", "Made-up Tours", ""), "visitmadeup",
                           f"{TEMPEST}/directory/x/") is None
    # "Hospitality" is not a hospital.
    assert tempest.tags_of("Hospitality Business Network") == {}


def test_a_destinationcore_board_listing_and_its_sitemap():
    """Providence moved from Tempest to DestinationCore (seen 27 November 2026): its "businessDirectory" sitemap
    lists "/listing/<name>" pages whose page entry has no address; a second entry of the same name has the
    address (all in streetAddress), telephone and position. The board's own listing page is not the website."""
    extra = [{"@type": "LodgingBusiness", "name": "Made-up Inn",
              "address": {"@type": "PostalAddress", "streetAddress": "32 Exchange Terrace, Burlington, VT 05401"},
              "telephone": "(802) 555-0150", "geo": {"@type": "GeoCoordinates", "latitude": 44.47,
                                                     "longitude": -73.21}}]
    page = tempest_bare_page("/listing/made-up-inn", "Made-up Inn", "", "LodgingBusiness", category="", extra=extra)
    page = page.replace('data-dms-partner-id="77" ', "")
    row = tempest.listing(page, "visitmadeup", f"{TEMPEST}/listing/made-up-inn")
    assert row["key"] == "visitmadeup:made-up-inn" and row["main_value"] == "hotel"
    assert (row["street"], row["city"], row["state"], row["postcode"]) == ("32 Exchange Terrace", "Burlington",
                                                                          "VT", "05401")
    assert row["phone"] == "(802) 555-0150" and row["website"] == "" and row["lat"] == "44.470000"
    assert tempest.PARTNER_MAP.search("sitemaps-1-section-businessDirectory-1-sitemap.xml")
    assert not tempest.PARTNER_MAP.search("sitemaps-1-section-businessDirectoryHome-1-sitemap.xml")
    assert not tempest.PARTNER_MAP.search("sitemaps-1-section-blogDirectory-1-sitemap.xml")


def test_tempest_sites_have_their_own_size():
    """Each board has its own expected size (so its request budget and time share fit; the first run gave every
    board 800, and Detroit and Pittsburgh ran out of requests)."""
    assert tempest.SITES["visitpittsburgh"]["expected"] >= 3300
    assert tempest.SITES["visitpittsburgh"]["budget"] > 3300 * 1.4
    assert tempest.SITES["visitcasper"]["expected"] < 800


def test_a_tempest_site_is_read_through_its_partner_sitemaps(monkeypatch):
    monkeypatch.setitem(tempest.SITES, "visitmadeup", tempest._site("Visit Madeup", TEMPEST, "VT"))
    client, web, _ = fake(tempest_routes())
    stats = {}
    rows = list(tempest.collect(client, "visitmadeup", stats))
    assert [r["key"] for r in rows] == ["visitmadeup:31"]                  # the tour operator has no street
    assert stats == {"listings": 2, "gone": 0, "left_out": 1, "failed": 0}
    asked = [u for u, _ in web.requests]
    assert not any("private-club" in u or "blogDirectory" in u for u in asked)
    routes = dict(tempest_routes())
    routes[f"{TEMPEST}/sitemaps-1-sitemap.xml"] = "<sitemapindex><sitemap><loc>x/pages.xml</loc></sitemap></sitemapindex>"
    client, _, _ = fake(routes)
    with pytest.raises(tempest.NotTempest):
        list(tempest.collect(client, "visitmadeup", {}))


# ------------------------------------------------------------------------------------------------ ChamberMaster

US_CHAMBER_DIR = "<html>" + "".join(f'<a href="https://www.uschamber.com/co/chambers/{s}">x</a>'
                                    for s in ("vermont", "new-york")) + "</html>"
VT_PAGE = ('<ul data-cy="chamber-list">'
           '<li data-cy="chamber-card"><h3 class="x">Madeup Valley Chamber of Commerce</h3><p>Address</p>'
           '<p>Website</p><a href="https://madeupvalley.example" target="_blank">madeupvalley.example</a></li>'
           '<li data-cy="chamber-card"><h3>Pretend Area Chamber</h3><p>Website</p>'
           '<a href="https://pretendarea.example">x</a></li>'
           '<li data-cy="chamber-card"><h3>Refusing Chamber</h3><p>Website</p><a href="https://refusing.example">x</a>'
           '</li><li data-cy="chamber-card"><h3>No Website Chamber</h3></li></ul>')
CLASSIC_ROBOTS = ("User-agent: *\nDisallow: /contact$\nDisallow: /*?rendermode=*\nDisallow: /list/search\n"
                  "Sitemap: https://business.madeupvalley.example/SiteMap.xml\n")
V2_ROBOTS = "User-agent: *\r\nDisallow: /\r\nDisallow: */TellAFriend"     # 51 bytes, no sitemap
B = "https://business.madeupvalley.example"


def card(memid, name, street, phone, city="Madeup", state="VT"):
    """A made-up member card of a classic directory page."""
    return (f'<div class="card gz-results-card" data-memid="{memid}"><h5 class="card-title" itemprop="name">'
            f'<a href="{B}/list/member/x-{memid}">{name}</a></h5><span class="gz-member-repname">Alice Example'
            f'</span><li class="gz-card-address"><span class="gz-street-address" itemprop="streetAddress">{street}'
            f'</span><div itemprop="citystatezip"><span class="gz-address-city">{city}</span><span>{state}</span>'
            f'<span>05999</span></div></li><li class="gz-card-phone"><a href="tel:{phone}">x</a></li>'
            f'<li class="gz-card-website"><a href="https://member{memid}.example">Visit Website</a></li></div>')


def chamber_routes():
    """The stand-in web of a state: the US Chamber's pages, one classic chamber, one v2 chamber, one refusing."""
    return {cm.DIRECTORY: US_CHAMBER_DIR,
            "https://www.uschamber.com/co/chambers/vermont": VT_PAGE,
            "https://madeupvalley.example": f'<a href="{B}/list/">Member directory</a>',
            "https://pretendarea.example": '<a href="https://members.pretendarea.example/list/">Directory</a>',
            "https://members.pretendarea.example/robots.txt": V2_ROBOTS,
            "https://refusing.example": (403, "<title>Just a moment...</title>"),
            f"{B}/robots.txt": CLASSIC_ROBOTS,
            f"{B}/SiteMap.xml": "<urlset>" + "".join(f"<url><loc>{B}/list/{p}</loc></url>" for p in (
                "QL/restaurants-food-beverages-22.htm", "QL/government-education-individuals-8.htm",
                "QL/finance-insurance-10.htm", "member/x-1.htm", "category/pizza-12")) + "</urlset>",
            f"{B}/list/QL/restaurants-food-beverages-22.htm": "".join([
                card(1, "Made-up Pizza Kitchen", "10 Madeup St", "8025550101"),
                card(2, "Alice Example", "12 Madeup St", "8025550102"),
                card(3, "Pretend Insurance Agency", "14 Madeup St", "8025550103"),
                card(4, "Made-up Bakery & Cafe", "PO Box 4", "8025550104"),
                card(5, "Madeup Valley Chamber of Commerce", "1 Main St", "8025550105"),
                card(6, "Made-up Diner & Grill", "5 Invented Rd", "8025550106"),
                card(7, "Made-up Diner & Grill", "5 Invented Rd", "8025550106")])}


def test_the_chambers_are_found_and_only_classic_directories_are_read():
    client, web, _ = fake(chamber_routes(), budget=200)
    stats = {}
    rows = list(cm.collect(client, "vt", stats))
    assert [(r["key"], r["name"], r["main_value"]) for r in rows] == [
        ("business-madeupvalley-example:1", "Made-up Pizza Kitchen", "restaurant"),
        ("business-madeupvalley-example:6", "Made-up Diner & Grill", "restaurant")]
    assert rows[0]["street"] == "10 Madeup St" and rows[0]["postcode"] == "05999" and rows[0]["state"] == "VT"
    assert rows[0]["phone"] == "8025550101" and rows[0]["website"] == "https://member1.example"
    assert stats["chambers"] == 3 and stats["classic"] == 1 and stats["v2"] == 1 and stats["blocked"] == 1
    asked = [u for u, _ in web.requests]
    assert not any("members.pretendarea.example/list" in u for u in asked)    # v2: only its robots.txt
    assert not any("government-education" in u or "finance-insurance" in u for u in asked)
    assert "Alice Example" not in json.dumps(rows)                            # representatives never kept
    assert client.pause == cm.PAUSE and 5 <= cm.PAUSE <= 10


def test_robots_txt_tells_the_directory_platforms_apart():
    from placepacks.directories.common import Robots
    def robots(text):
        """A Robots of a made-up host with this robots.txt."""
        client, _, _ = fake({"https://h.example/robots.txt": text})
        return Robots(client, "https://h.example")
    assert len(V2_ROBOTS.encode()) == 51 and cm.classify(robots(V2_ROBOTS)) == "v2"
    assert cm.classify(robots("User-agent: *\nDisallow: / \nNoMoreMisterRoboto\n")) == "closed"
    assert cm.classify(robots("User-agent: *\nDisallow: /list/\nSitemap: https://h.example/SiteMap.xml\n")) == \
        "closed"
    assert cm.classify(robots(CLASSIC_ROBOTS.replace("business.madeupvalley", "h"))) == "classic"


def test_a_refusal_of_the_us_chambers_page_stops_the_state(tmp_path):
    routes = dict(chamber_routes(), **{"https://www.uschamber.com/co/chambers/vermont": (429, "slow down")})
    clock = ypt.Clock()
    summary = dirrun.run("chambermaster", "vt", str(tmp_path), opener=ypt.FakeWeb(routes), sleep=clock.sleep,
                         clock=clock)
    assert summary["status"] == "blocked"
    summary = dirrun.run("chambermaster", "vt", str(tmp_path), opener=ypt.FakeWeb(chamber_routes()),
                         sleep=clock.sleep, clock=clock)
    assert summary["status"] == "ok" and summary["rows"] == 2 and (tmp_path / "vt.csv.gz").exists()
    assert set(cm.STATES) >= {"vt", "ny", "dc", "pr"} and cm.STATES["ny"]["slug"] == "new-york"


# ------------------------------------------------------------------------------------------------ sets and the build

def entry_of(source):
    """A catalogue entry (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source)))


def test_the_catalogue_entries():
    for source in ("simpleview-listings", "tempest-listings", "chambermaster-listings"):
        e = entry_of(source)
        assert e["part"] == "businesses" and e["fetch"]["method"] == "release_csv" and e["licence"] == "directory-facts"
        assert e["dedupe_phone"] and e["dedupe_carry"] and e["dedupe_m"] == 75
        assert "overture-places" in e["dedupe_against"] and "alltheplaces" in e["dedupe_against"]
        assert "owner" in e["notes"].lower() and "blocked" in e["notes"].lower()
    assert entry_of("chambermaster-listings")["geocode"]["skip_homes"] is True
    assert catalogue.check() == []


@pytest.fixture
def gh(tmp_path, monkeypatch):
    """The stand-in releases, in place of gh (as in the chain tests), and a fresh file-list cache."""
    import test_chain_locators as chains_test
    fake_release = chains_test.FakeRelease(str(tmp_path / "release"))
    monkeypatch.setattr(uploaded, "run_gh", fake_release)
    monkeypatch.setattr(uploaded.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/place-packs")
    monkeypatch.setenv("PLACEPACKS_SCRATCH", str(tmp_path))
    return fake_release


def test_a_simpleview_set_is_published_read_and_matched_by_phone(gh, tmp_path):
    clock = ypt.Clock()
    out = tmp_path / "results"
    dirrun.run("simpleview", "visitdenver", str(out), opener=ypt.FakeWeb(site_routes()), sleep=clock.sleep,
               clock=clock)
    listing = dirrun.publish("simpleview", str(out), "2026-12-25", {"visitdenver"}, sleep=lambda s: None)
    assert [f["name"] for f in listing["files"]] == ["simpleview-listings-2026-12-25-visitdenver.csv.gz"]
    assert "Tourism boards" in release.table(listing)
    e = entry_of("simpleview-listings")
    national = tmp_path / "national"
    fetch.prepare(str(national), cat={"accepted": [e]})
    counts = split.split_tabular(e, str(national / "simpleview-listings"), str(tmp_path / "split"),
                                 {VT: catalogue.regions()[VT]})
    assert counts == {VT: 2}
    got = fetch.fetch_source(e, catalogue.regions()[VT], {}, str(tmp_path / "work"), str(tmp_path / "split" / VT))
    assert got["ok"] and got["version"] == "simpleview-listings/simpleview-listings-2026-12-25"
    # the build: an Overture place with the cafe's phone number 100 m away, under another name
    path = str(tmp_path / "b.osmpack")
    w = PackWriter(path, 202612)
    w.add_point("overture-places:o1", "overture-places", "Made-up Coffee Shop & Deli", "business", "cafe",
                44.4768, -73.2121, contact={"phone": "+1 802 555 0130"})
    assert read_tabular(got["path"], e, dict(catalogue.regions()[VT]), w) == 2
    assert w.drop_duplicates(e["id"], e["dedupe_against"], e["dedupe_m"], carry=True, phone=True) == 1
    w.finish({**ypt.META, "part": "businesses"})
    pack = PackReader(path)
    assert pack.details_of("overture-places:o1")["website"] == "https://cafe.example"   # carried from the listing
    keys = {r[0] for r in pack.con.execute("SELECT key FROM points")}
    assert keys == {"overture-places:o1", "simpleview-listings:visitdenver:32"}


def test_a_chamber_member_is_placed_by_the_geocoder_and_homes_are_left_out(tmp_path):
    rows = [{"key": "h:1", "name": "Made-up Pizza Kitchen", "main_key": "amenity", "main_value": "restaurant",
             "type": "restaurant", "phone": "8025550101", "website": "https://member1.example", "street":
             "10 Madeup St", "city": "Testville", "state": "VT", "postcode": "05000"},
            {"key": "h:2", "name": "Made-up Crafts & Gifts", "main_key": "shop", "main_value": "gift",
             "type": "gift shop", "phone": "8025550102", "street": "12 Madeup St", "city": "Testville", "state": "VT", "postcode": "05000"}]
    path = tmp_path / "chambermaster-listings.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cm.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    nad = tmp_path / "nad.txt"
    nad.write_text("AddNo_Full,StNam_Full,Post_City,Inc_Muni,State,Zip_Code,Addr_Type,Latitude,Longitude\n"
                   "10,MADEUP ST,Testville,,VT,05000,Commercial,44.0001,-72.0001\n"
                   "12,MADEUP ST,Testville,,VT,05000,Residential,44.0003,-72.0003\n", encoding="utf-8")
    region = dict(catalogue.regions()[VT])
    region["_inputs"] = {"nad": str(nad)}
    pack = str(tmp_path / "c.osmpack")
    writer = PackWriter(pack, 202612)
    assert read_tabular(str(path), entry_of("chambermaster-listings"), region, writer) == 1
    got = writer.db.execute("SELECT key, name, cls, lat, lon FROM points").fetchall()
    assert got == [("chambermaster-listings:h:1", "Made-up Pizza Kitchen", "business", 44000100, -72000100)]
    assert shutil and gzip


def test_the_workflows_are_monthly_read_only_and_publish_in_one_job():
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "simpleview-listings.yml"), day="25")
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "tempest-listings.yml"), day="26")
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "chambermaster-listings.yml"), day="15")
