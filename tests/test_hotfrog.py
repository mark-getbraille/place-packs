"""Hotfrog (placepacks/directories/hotfrog.py): the Yellow Pages job's fallback lookups (tools/yp_lookup.py) and the
monthly town-by-town collection (source hotfrog-listings). Offline: every business, page, town and number here is
made up; a stand-in web answers.

Covered: a results page gives facts only (name, street address, the tel: phone, website, categories; never the
description's own number, tags or reviews); a lookup matches by a like name AND the same street address; the
fallback is tried only when Yellow Pages found no match, and a refusing fallback is switched off for good while the
Yellow Pages job goes on; the towns come from the Census population file, biggest first; the collection obeys
robots.txt, leaves out home businesses, people and offices, and stops at a refusal; the catalogue entry and the
workflow's shape."""

import csv
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, contact  # noqa: E402
from placepacks.chains import polite  # noqa: E402
from placepacks.directories import hotfrog as hf  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402

import test_yp_lookup as ypt  # noqa: E402
import yp_lookup  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402


def card(cid, name, address, phone="+18025550180", website="https://shop.example/", categories=("Restaurants",)):
    """A made-up Hotfrog result card (with a description holding another number, never read)."""
    cats = "".join(f'<span data-category="x">{c}</span>' for c in categories)
    web = f'<a class="btn has-icon--website" data-entity-metric="website" href="{website}" rel="nofollow"></a>' \
        if website else ""
    return (f'<div class="surface entity serp"><div class="entity-data"><h3 class="entity-title ">'
            f'<a href="/company/{cid}/x/madeup/restaurants">    {name}\n  </a></h3>'
            f'<div class="entity-categories"><span class="csv-list">{cats}</span></div>'
            f'<p class="entity-address has-icon--map"><span>\n {address}\n </span></p>'
            f'<section class="entity-description"><p>Call us on 802 555 0999 or mail owner@shop.example</p>'
            f'</section><span>Pizza</span><span>Salads</span>'
            f'<a class="btn has-icon--phone" href="tel:{phone}" rel="nofollow"></a>{web}</div></div>')


def results(*cards):
    """A made-up Hotfrog results page."""
    return "<html><title>Results</title><main>" + "".join(cards) + "</main></html>"


def test_a_results_page_gives_facts_only():
    got = hf.parse_results(results(card("AAA1", "Pretend Cafe &amp; Deli", "12 Elm Street, 05999-1234\n Madeup, VT")))
    assert got == [{"id": "AAA1", "name": "Pretend Cafe & Deli", "street": "12 Elm Street", "city": "Madeup",
                    "state": "VT", "postcode": "05999", "phone": "+18025550180", "website": "https://shop.example/",
                    "categories": ["Restaurants"], "lat": None, "lon": None}]
    assert hf.search_url("Pretend Cafe & Deli", "Madeup", "VT") == \
        "https://www.hotfrog.com/search/Madeup%2C%20VT/Pretend%20Cafe%20%26%20Deli"


def test_a_lookup_matches_by_name_and_street_address():
    url = hf.search_url(ypt.RECORD["name"], "Madeup", "VT")
    c, web, _ = ypt.client({url: results(card("AAA1", "Pretend Cafe & Deli", "12 Elm St, 05999 Madeup, VT"),
                                         card("AAA2", "Pretend Cafe & Deli", "99 Far Rd, 05999 Madeup, VT",
                                              phone="+18025550181"))})
    row = hf.lookup(c, ypt.RECORD, "VT", today=ypt.TODAY)
    assert row["phone"] == "802-555-0180" and row["website"] == "https://shop.example"
    assert row["matched_on"] == "hotfrog name+address" and row["checked"] == "2026-12-03"
    c, _, _ = ypt.client({url: results(card("AAA3", "Pretend Cafe & Deli", "PO Box 4, 05999 Madeup, VT"))})
    assert hf.lookup(c, ypt.RECORD, "VT")["matched_on"] == "hotfrog no match"      # no street address
    c, web, _ = ypt.client({})
    assert hf.lookup(c, {**ypt.RECORD, "name": "Alice Example", "type": ""}, "VT")["matched_on"].startswith(
        "hotfrog skipped") and not web.requests                                    # a person: never looked up


def test_the_fallback_is_tried_only_without_a_yellow_pages_match_and_stops_at_a_refusal():
    base = {"key": "k", "lat": "44.2", "lon": "-72.5", "phone": "", "website": "", "opening_hours": "",
            "checked": "2026-12-03"}
    asked = []

    def finds(client, record, code, today=None):
        asked.append(record["key"])
        return {**base, "phone": "802-555-0180", "matched_on": "hotfrog name+address"}

    def refuses(client, record, code, today=None):
        raise polite.Blocked("www.hotfrog.com refused the request (HTTP 403)")

    state = {}
    found = {**base, "phone": "802-555-0100", "matched_on": "name+address"}
    assert yp_lookup.fallback(None, ypt.RECORD, "VT", found, state, fallbacks={"hotfrog": finds}) is found
    assert not asked                                                    # Yellow Pages matched: not asked
    got = yp_lookup.fallback(None, ypt.RECORD, "VT", {**base, "matched_on": "no match"}, state,
                             fallbacks={"hotfrog": finds})
    assert got["phone"] == "802-555-0180" and got["matched_on"] == "hotfrog name+address"
    got = yp_lookup.fallback(None, ypt.RECORD, "VT", {**base, "matched_on": "no results"}, state,
                             fallbacks={"hotfrog": refuses})
    assert got["matched_on"] == "no results" and "hotfrog" in state["fallbacks_blocked"]
    asked.clear()
    got = yp_lookup.fallback(None, ypt.RECORD, "VT", {**base, "matched_on": "no match"}, state,
                             fallbacks={"hotfrog": finds})
    assert not asked and got["matched_on"] == "no match"                # switched off for good
    assert set(yp_lookup.FALLBACKS) == {"hotfrog"}


CENSUS = ("SUMLEV,STATE,COUNTY,PLACE,COUSUB,CONCIT,PRIMGEO_FLAG,FUNCSTAT,NAME,STNAME,POPESTIMATE2023,POPESTIMATE2024\n"
          "040,50,000,00000,00000,00000,0,A,Vermont,Vermont,647000,648000\n"
          "162,50,000,00001,00000,00000,0,A,Madeup city,Vermont,44000,45000\n"
          "162,50,000,00002,00000,00000,0,A,Pretendville town,Vermont,30000,26000\n"
          "162,50,000,00003,00000,00000,0,A,Tinytown village,Vermont,900,950\n"
          "061,50,007,00000,10675,00000,0,A,Bigtown town,Vermont,99000,99000\n"
          "162,33,000,00004,00000,00000,0,A,Otherstate city,New Hampshire,90000,90000\n")


def test_the_towns_come_from_the_census_file_biggest_first():
    assert hf.cities(CENSUS, "Vermont") == ["Madeup", "Pretendville"]
    assert hf.cities(CENSUS, "Vermont", minimum=100) == ["Madeup", "Pretendville", "Tinytown"]


def collection_routes(refuse=False):
    """The stand-in web of one state's collection."""
    routes = {hf.SITE + "/robots.txt": "User-agent: *\nDisallow: /search/ankh/\n", hf.CITIES_URL: CENSUS}
    routes[hf.search_url("restaurants", "Madeup", "VT")] = results(
        card("R1", "Made-up Pizza Kitchen", "10 Madeup St, 05999 Madeup, VT"),
        card("R2", "Alice Example", "12 Madeup St, 05999 Madeup, VT"),
        card("R3", "Pretend Insurance Agency", "14 Madeup St, 05999 Madeup, VT", categories=("Insurance Agents",)),
        card("R4", "Made-up Catering", "PO Box 9, 05999 Madeup, VT"),
        card("R5", "Elsewhere Diner", "1 Main St, 03000 Otherstate, NH"))
    routes[hf.search_url("pharmacies", "Madeup", "VT")] = results(
        card("R1", "Made-up Pizza Kitchen", "10 Madeup St, 05999 Madeup, VT"),
        card("P1", "Pretend Drug Store", "20 Madeup St, 05999 Madeup, VT", categories=("Pharmacies",)))
    if refuse:
        routes[hf.search_url("restaurants", "Pretendville", "VT")] = (403, "<title>Just a moment...</title>")
    return routes


def test_a_state_is_collected_town_by_town():
    clock = ypt.Clock()
    web = ypt.FakeWeb(collection_routes())
    client = polite.Polite(100, hf.PAUSE, opener=web, sleep=clock.sleep, clock=clock, waits=(5,),
                           agent=hf.USER_AGENT)
    stats = {}
    rows = list(hf.collect(client, "vt", stats, categories=["restaurants", "pharmacies"]))
    assert [(r["key"], r["main_value"]) for r in rows] == [("hotfrog:R1", "restaurant"), ("hotfrog:P1", "pharmacy")]
    assert rows[0]["phone"] == "+18025550180" and rows[0]["street"] == "10 Madeup St"
    assert "0999" not in str(rows) and "owner@" not in str(rows)
    assert stats["towns"] == 2 and client.pause >= hf.PAUSE
    assert all(h["User-agent"] == hf.USER_AGENT for _, h in web.requests)


def test_a_refusal_stops_the_states_run(tmp_path, monkeypatch):
    monkeypatch.setattr(hf, "CATEGORIES", ["restaurants", "pharmacies"])
    clock = ypt.Clock()
    summary = dirrun.run("hotfrog", "vt", str(tmp_path), opener=ypt.FakeWeb(collection_routes(refuse=True)),
                         sleep=clock.sleep, clock=clock)
    assert summary["status"] == "blocked" and not (tmp_path / "vt.csv.gz").exists()


def test_the_catalogue_entry_and_the_workflow():
    e = next(x for x in catalogue.load()["accepted"] if x["id"] == "hotfrog-listings")
    assert e["fetch"]["method"] == "release_csv" and e["licence"] == "directory-facts"
    assert e["geocode"]["skip_homes"] is True and e["dedupe_phone"] and e["dedupe_m"] == 75
    assert "owner" in e["notes"].lower() and "blocked" in e["notes"].lower()
    assert "hotfrog-listings" in contact.DIRECTORY_SOURCES and "hotfrog-listings" not in contact.HOURS_SOURCES
    rejected = " ".join(r["name"] for r in catalogue.load()["rejected"])
    for name in ("Manta", "Cylex", "EZlocal", "MerchantCircle", "Superpages", "Brownbook", "Whitepages"):
        assert name in rejected
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "hotfrog-listings.yml"), day="12")
    assert dirrun.collections()["hotfrog"]["units"]["vt"]["budget"] <= 5000
    assert csv and io and pytest
