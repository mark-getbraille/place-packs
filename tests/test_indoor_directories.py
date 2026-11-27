"""Mall and airport directories (placepacks/indoor, placepacks/mapvendors/atrius.py): one stand-in web per collector
type (a JSON directory: Tanger's page data, Brookfield's Fusion cache and Westfield's streamed data; a schema.org
page: an independent mall and an airport's dining page; a vendor embed: an airport's public Atrius map), the mapping
into site features and businesses in a pack, the privacy filters (people's names, e-mail addresses, an amenity a
mall's answer denies), block handling (an operator, a not-read operator, an airport and a mall that refuse), and the
wiring (runner, catalogue, contact lists, workflows). Offline: every mall, airport, store, phone number and address
here is made up."""

import csv
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import catalogue, contact, features, indoor, lookup, writer  # noqa: E402
from placepacks.directories import run as dirrun  # noqa: E402
from placepacks.indoor import airports, common, malls, seeds  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.mapvendors import atrius, registry  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

from test_map_vendors import Web, client  # noqa: E402
from test_web_details import workflow_shape  # noqa: E402

TODAY = datetime.date(2026, 12, 5)
VT = "us-vermont"
ROBOTS_OK = (200, "User-agent: *\nAllow: /\n")
# The made-up malls' seeds (as Wikidata gives them): positions in Vermont, so the pack test can use the region.
SEEDS = [{"org": "Madeup Outlets Testville", "homepage": "https://www.madeup-outlets.example/testville",
          "place_key": "wikidata:Q9990001", "lat": "44.01", "lon": "-72.01"},
         {"org": "Madeup Mall", "homepage": "https://www.madeupmall.example", "place_key": "wikidata:Q9990002",
          "lat": "44.02", "lon": "-72.02"},
         {"org": "Sample Town Center", "homepage": "https://www.sampletowncenter.example",
          "place_key": "w9990003", "lat": "44.03", "lon": "-72.03"}]


def test_new_kinds_and_words():
    """The kinds added for malls and airports exist and the category words find them."""
    for kind in ("family restroom", "pet relief area", "accessibility service", "ground transport", "concourse"):
        assert kind in features.KINDS
    assert features.kind_of("Restroom - Family") == "family restroom"
    assert features.kind_of("Service Animal Relief Area") == "pet relief area"
    assert features.kind_of("Wheelchair Assistance") == "accessibility service"
    assert features.kind_of("Taxi stand") == "ground transport"
    assert features.kind_of("Concourse B") == "concourse"
    assert features.kind_of("Accessible Restroom") == "accessible restroom"
    assert features.kind_of("Gate B12") == "gate"


def test_privacy_filters():
    """A store named like a person is left out; an e-mail address never reaches a note; a sentence naming a person
    is not kept; an amenity a mall's answer denies is left out, one it confirms keeps the answer."""
    assert common.store_name("Alice Example") == ""
    assert common.store_name("Madeup Shoes") == "Madeup Shoes"
    assert common.feature_row("s", "s:1", "store", "Alice Example", 44, -72) is None
    assert "@" not in common.note("Ask at guest services or write to help@madeupmall.example.")
    assert common.note("Please ask for manager Jane Sample at the desk.") == ""
    text = ("Are wheelchairs available at Madeup Mall? Yes, wheelchairs are available at Guest Services near "
            "Madeup Department Store. Are scooters available to rent? No, scooters are not available. Where are "
            "the family restrooms? The family restrooms are located at the food court.")
    found = {label: (kind, note) for kind, label, note in common.amenities_of([text])}
    assert found["Wheelchairs"][1].startswith("Yes, wheelchairs are available at Guest Services")
    assert "Mobility scooters" not in found
    assert found["Family restrooms"][0] == "family restroom"


# ------------------------------------------------------------------------------------------------ JSON directories

def tanger_web():
    """A stand-in Tanger: the sitemap, one US centre's stores page (Next.js data) and its visitor info."""
    centre = {"name": "Testville", "centerPhoneNumber": "(802) 555-0100",
              "fullAddressCS": [{"country": "United States"}],
              "hours": [{"day_index": i, "open": "10:00", "close": "21:00" if i < 6 else "18:00"} for i in range(7)],
              "storeCards": [{"cardId": 11, "heading": "Madeup Shoes", "categories": ["Footwear"],
                              "storeSuite": "SUITE 100", "storeHours": []},
                             {"cardId": 12, "heading": "Sample Pretzels", "categories": ["Food & drink"],
                              "storeSuite": "SUITE 200",
                              "storeHours": [{"day": "Monday", "hours": "9:00AM - 5:00PM"}]},
                             {"cardId": 13, "heading": "Alice Example", "categories": ["Specialty"]}]}
    page = ('<html><script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"center": centre}}}) + "</script></html>")
    base = "https://www.tanger.com"
    return Web({f"{base}/robots.txt": ROBOTS_OK,
                f"{base}/sitemap.xml": (200, f"<sitemapindex><sitemap><loc>{base}/sitemap-0.xml</loc></sitemap>"
                                             "</sitemapindex>"),
                f"{base}/sitemap-0.xml": (200, f"<urlset><url><loc>{base}/testville/stores</loc></url>"
                                               f"<url><loc>{base}/testville/deals</loc></url></urlset>"),
                f"{base}/testville/stores": (200, page),
                f"{base}/testville/visitor-info": (200, "<p>Complimentary wheelchairs are available at the "
                                                        "Security Office in the food court.</p>")})


def test_tanger_json_directory():
    """Tanger: the centre (phone, weekly hours from day_index 0 = Monday), its stores (category, suite, own hours;
    the restaurant as dining and a business), a person-named card left out, the amenity from visitor info."""
    seeds_ = [dict(SEEDS[0], homepage="https://www.tanger.com/testville")]
    stats = {}
    rows = list(malls.collect(client(tanger_web()), "tanger", stats, mall_seeds=seeds_))
    by = {r["key"]: r for r in rows}
    site = by["mall:tanger:testville"]
    assert site["kind"] == "site" and site["phone"] == "802-555-0100" and site["place_key"] == "wikidata:Q9990001"
    assert site["opening_hours"] == "Mo-Sa 10:00-21:00; Su 10:00-18:00"
    shoes = by["mall:tanger:testville:store:11"]
    assert shoes["kind"] == "store" and shoes["unit"] == "SUITE 100" and shoes["business"] == ""
    assert shoes["notes"] == "In Tanger Outlets Testville, SUITE 100" and float(shoes["lat"]) == 44.01
    pretzels = by["mall:tanger:testville:store:12"]
    assert pretzels["kind"] == "dining" and pretzels["opening_hours"] == "Mo 09:00-17:00"
    assert pretzels["business"] == "1" and pretzels["main_value"] == "restaurant"
    assert not any("Alice" in r["name"] for r in rows)
    assert by["mall:tanger:testville:amenity:wheelchairs"]["kind"] == "accessibility service"
    assert stats["malls"] == 1


def brookfield_page(stores, hours):
    """A made-up Brookfield mall directory page: Fusion.contentCache with the mall's info and its stores."""
    cache = {"brookfield-mall-info": {"x": {"data": {"content": {"name": "Madeup Mall", "regMallHours": hours}}}},
             "brookfield-store": {"y": {"data": [{"content": s} for s in stores]}}}
    return f"<html><script>Fusion.deployment='1';Fusion.contentCache={json.dumps(cache)};</script></html>"


def test_tanger_centre_found_by_its_outlets_name_and_state():
    """A Tanger centre whose seed has no website (an OpenStreetMap mall) is found by the name "Tanger Outlets
    <centre>" in its own state; a same-named centre in another state is not used (first GitHub run: 33 of 36
    centres had no position)."""
    web = tanger_web()
    page = web.pages["https://www.tanger.com/testville/stores"][1].replace(
        '"fullAddressCS": [{"country": "United States"}]',
        '"fullAddressCS": [{"country": "United States", "county": "Vermont"}]')
    web.pages["https://www.tanger.com/testville/stores"] = (200, page)
    elsewhere = {"org": "Tanger Outlets Testville", "homepage": "", "place_key": "n1", "lat": "30.1",
                 "lon": "-90.1", "state": "LA"}
    here = {"org": "Tanger Outlets Testville", "homepage": "", "place_key": "w2", "lat": "44.3", "lon": "-72.3",
            "state": "VT"}
    stats = {}
    rows = list(malls.collect(client(web), "tanger", stats, mall_seeds=[elsewhere, here]))
    site = next(r for r in rows if r["kind"] == "site")
    assert site["name"] == "Tanger Outlets Testville" and site["place_key"] == "w2" and "no_position" not in stats


def test_independent_malls_go_on_after_a_broken_link_and_keep_rows_when_time_runs_out(monkeypatch):
    """A script template ("/${getRetailerUrl(...)}") or a broken IPv6 address in a mall's links is skipped without
    a request; one mall's unexpected error is counted and the next mall is read; when the request budget runs out
    the unit ends with the rows found so far (first GitHub run: all three independent units were lost to one
    template link each)."""
    def mall_site(host, extra=""):
        return {f"{host}/robots.txt": ROBOTS_OK,
                host: (200, '<a href="/directory/">Store Directory</a>' + extra),
                f"{host}/directory/": (200, '<a href="/directory/madeup-hats/">Madeup Hats</a>'
                                            '<a href="/directory/sample-toys/">Sample Toys</a>')}
    monkeypatch.setattr(malls, "INDEPENDENT_SHARDS", 1)       # both malls in the one unit
    one, two = "https://www.madeupmall.example", "https://www.sampletowncenter.example"
    pages = {**mall_site(one, '<a href="/${getRetailerUrl(retailer)}">Shops</a>'
                              '<a href="http://[broken/stores">Stores</a>'), **mall_site(two)}
    web = Web(pages)
    stats = {}
    rows = list(malls.collect_independent(client(web), "independent-1", stats,
                                          mall_seeds=[SEEDS[1], {**SEEDS[2], "org": "Sample Town Center"}]))
    assert {r["name"] for r in rows} >= {"Madeup Mall", "Madeup Hats", "Sample Town Center", "Sample Toys"}
    assert not any("${" in u or "[broken" in u for u in web.asked) and stats["ok"] == 2
    stats = {}
    rows = list(malls.collect_independent(client(Web(pages), budget=4), "independent-1", stats,
                                          mall_seeds=[SEEDS[1], SEEDS[2]]))
    assert rows and "budget" in stats["stopped"]


def test_an_airport_with_a_bad_link_does_not_stop_the_others(monkeypatch):
    """A link with a space ("/dining at MFE.html") is read percent-encoded; an airport whose reading raises an
    unexpected error is counted as "error" and the next airport is still read (first GitHub run: airports-1 and
    airports-4, with Minneapolis-Saint Paul's Atrius map, were lost to one such link each)."""
    home = "https://www.madeup-airport.example"
    web = Web({f"{home}/robots.txt": ROBOTS_OK,
               home: (200, '<a href="/dining at MFE.html">Dining</a>'),
               f"{home}/dining%20at%20MFE.html": (200, '<script type="application/ld+json">{"@type": "Restaurant", '
                                                       '"name": "Sample Diner", "description": "Terminal A"}'
                                                       '</script>')})
    good = {"org": "Madeup Regional Airport", "faa": "MDX", "place_key": "faa-airports:MDX", "lat": "44.05",
            "lon": "-72.05", "homepage": home}
    bad = dict(good, faa="BAD")
    real = airports.read_airport

    def read(client_, airport, stats_, vendors=None):
        """read_airport, failing unexpectedly for the airport BAD."""
        if airport["faa"] == "BAD":
            raise KeyError("made-up failure")
        return real(client_, airport, stats_, vendors)
    monkeypatch.setattr(airports, "read_airport", read)
    monkeypatch.setattr(airports, "SHARDS", 1)               # both airports in the one unit
    stats = {}
    rows = list(airports.collect(client(web), "airports-1", stats, airports=[bad, good]))
    assert any(r["name"] == "Sample Diner" for r in rows) and stats["ok"] == 1 and stats["error"] == 1
    assert f"{home}/dining%20at%20MFE.html" in web.asked and "BAD: KeyError" in stats["errors"][0]


def test_brookfield_json_directory():
    """Brookfield: stores with phone, website, category and the anchor store they are near; a closed store and a
    not-yet-open one left out; the mall's weekly hours, its phone and amenities from the visit page's answers."""
    site = "https://www.madeupmall.example"
    stores = [{"storeId": 1, "displayName": "Madeup Books", "leaseStatus": "Open", "phoneNumber": "8025550111",
               "tenantWebsite": "https://books.example", "categories": [{"description": "Books"}],
               "zoneName": "Madeup Department Store", "zoneOrientation": "near"},
              {"storeId": 2, "displayName": "Gone Store", "leaseStatus": "Closed"},
              {"storeId": 3, "displayName": "Paused Store", "leaseStatus": "Open", "temporarilyClosed": "Yes"}]
    hours = [{"day": d, "openTime": "10:00 AM", "closeTime": "9:00 PM"} for d in
             ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")] + \
            [{"day": "Sunday", "openTime": "11:00 AM", "closeTime": "6:00 PM"}]
    visit = ("<p>What is Madeup Mall's phone number? Madeup Mall's phone number is 802.555.0122. "
             "Is accessible (handicapped) parking available? Yes, accessible parking is available near every "
             "entrance.</p>")
    web = Web({f"{site}/robots.txt": ROBOTS_OK, f"{site}/en/directory/": (200, brookfield_page(stores, hours)),
               f"{site}/en/visit/": (200, visit)})
    rows = malls.brookfield_mall(client(web), "Madeup Mall", site, SEEDS, {})
    by = {r["key"]: r for r in rows}
    mall_row = by["mall:brookfield:madeupmall"]
    assert mall_row["opening_hours"] == "Mo-Sa 10:00-21:00; Su 11:00-18:00" and mall_row["phone"] == "802-555-0122"
    books = by["mall:brookfield:madeupmall:store:1"]
    assert books["phone"] == "802-555-0111" and books["website"] == "https://books.example"
    assert books["notes"] == "In Madeup Mall, near Madeup Department Store" and books["business"] == "1"
    assert books["main_value"] == "books"
    assert not any(r["name"] in ("Gone Store", "Paused Store") for r in rows)
    assert by["mall:brookfield:madeupmall:amenity:accessible-parking"]["kind"] == "accessible parking"


def rsc_page(parts):
    """A made-up streamed Next.js page: its parts as numbered lines in self.__next_f.push chunks."""
    text = "\n".join(f"{k}:{json.dumps(v)}" for k, v in parts.items()) + "\n"
    return f"<html><script>self.__next_f.push([1,{json.dumps(text)}])</script></html>"


def test_westfield_streamed_directory():
    """Westfield: the centre's own position and phone, stores with category names and level, a store's own
    trading hours (its days through numbered parts; day 0 is Sunday), the centre's own schedule not repeated as a
    store's hours, and an accessibility service card with its page's description."""
    base = "https://www.westfield.com/en/united-states/madeup"
    centre = {"centre_id": "madeup", "name": "Westfield Madeup", "phone_number": "802.555.0133", "state": "VT",
              "latitude": 44.04, "longitude": -72.04}
    store_a = {"store_id": "501", "name": "Madeup Tea House", "category_ids": [7], "status": {"state": "live"},
               "locations": [{"level_description": "L2"}],
               "trading_hours": {"standard_trading": {"name": "Own", "days_of_week": "$a1"}}}
    store_b = {"store_id": "502", "name": "Sample Jeans", "category_ids": [8], "status": {"state": "live"},
               "locations": [{"level_description": "L1"}],
               "trading_hours": {"standard_trading": {"name": "Standard Trading Schedule for Centre madeup",
                                                      "days_of_week": []}}}
    parts = {"5f": centre, "6a": {"category_id": 7, "name": "Food & Drink"}, "6b": {"category_id": 8,
                                                                                  "name": "Fashion"},
             "a1": ["$a2", "$a3"], "a2": {"day_of_week": 0, "starts_at": "11:00:00", "ends_at": "17:00:00",
                                          "type": "open"},
             "a3": {"day_of_week": 1, "starts_at": "08:00:00", "ends_at": "20:00:00", "type": "open"},
             "b1": store_a, "b2": store_b}
    services = {"c1": {"title": "Wheelchairs", "slug": "wheelchairs", "__typename": "ServiceCard"},
                "c2": {"title": "Free Wi-Fi", "slug": "wifi", "__typename": "ServiceCard"}}
    detail = {"d1": {"service_id": 9, "description": "<p>Wheelchairs can be borrowed at the Security Office on "
                                                     "Level 1.</p>"}}
    web = Web({"https://www.westfield.com/robots.txt": ROBOTS_OK, f"{base}/retailers": (200, rsc_page(parts)),
               f"{base}/restaurants": (200, rsc_page({"5f": centre})), f"{base}/services": (200, rsc_page(services)),
               f"{base}/services/wheelchairs": (200, rsc_page(detail))})
    c = client(web)
    robots = malls._robots(c, malls.WESTFIELD)
    rows = malls.westfield_mall(c, robots, "madeup", SEEDS, {})
    by = {r["key"]: r for r in rows}
    assert by["mall:westfield:madeup"]["phone"] == "802-555-0133" and by["mall:westfield:madeup"]["lat"] == 44.04
    tea = by["mall:westfield:madeup:store:501"]
    assert tea["kind"] == "dining" and tea["level"] == "L2" and tea["opening_hours"] == "Mo 08:00-20:00; Su 11:00-17:00"
    jeans = by["mall:westfield:madeup:store:502"]
    assert jeans["kind"] == "store" and jeans["opening_hours"] == "" and jeans["category"] == "Fashion"
    chairs = by["mall:westfield:madeup:service:wheelchairs"]
    assert chairs["kind"] == "accessibility service" and "Security Office on Level 1" in chairs["notes"]
    assert not any("Wi-Fi" in r["name"] for r in rows)


# ------------------------------------------------------------------------------------------------ schema.org pages

def test_independent_mall_schema_org_and_store_links():
    """An independent mall: robots.txt obeyed (a disallowed page is not read), the ShoppingCenter's phone and
    hours, a Store item, the store links of its directory page, a Mappedin embed recorded, the amenities named."""
    home = "https://www.sampletowncenter.example"
    homepage = ('<script type="application/ld+json">{"@type": "ShoppingCenter", "name": "Sample Town Center", '
                '"telephone": "802-555-0144", "openingHours": "Mo-Sa 10:00-20:00"}</script>'
                '<a href="/directory/">Store Directory</a> <a href="/private/visit">Visitor info</a>'
                '<script src="https://cdn.mappedin.com/web2/release/mappedin-web.js?venue=sample-town"></script>')
    directory = ('<script type="application/ld+json">{"@type": "Store", "name": "Sample Toys", '
                 '"telephone": "802-555-0155"}</script>'
                 '<a href="/directory/madeup-hats/">Madeup Hats</a><a href="/directory/sample-toys/">View all</a>'
                 '<p>Family restrooms are located near the food court.</p>')
    web = Web({f"{home}/robots.txt": (200, "User-agent: *\nDisallow: /private/\n"), f"{home}/": (200, homepage),
               home: (200, homepage), f"{home}/directory/": (200, directory)})
    stats, vendors = {}, []
    rows = malls.independent_mall(client(web), SEEDS[2], stats, vendors)
    by = {r["name"]: r for r in rows}
    assert by["Sample Town Center"]["phone"] == "802-555-0144"
    assert by["Sample Town Center"]["opening_hours"] == "Mo-Sa 10:00-20:00"
    assert by["Sample Toys"]["business"] == "1" and by["Madeup Hats"]["kind"] == "store"
    assert "View all" not in by and by["Family restrooms"]["kind"] == "family restroom"
    assert not any("/private/" in u for u in web.asked)
    assert any(v["vendor"] == "mappedin" for v in vendors) and stats["ok"] == 1


def test_airport_schema_org_dining_page_and_amenities():
    """An airport without an Atrius map: its dining page's schema.org Restaurant and a shop card that says where,
    its accessibility page's amenities (TSA Cares, relief areas), the airport's own site row."""
    home = "https://www.madeup-airport.example"
    homepage = '<a href="/dining">Shops &amp; Dining</a><a href="/accessibility">Accessibility</a>'
    dining = ('<script type="application/ld+json">{"@type": "Restaurant", "name": "Sample Diner", '
              '"telephone": "802-555-0166", "openingHours": "Mo-Su 05:00-21:00", '
              '"description": "Terminal B, near Gate B4, after security"}</script>'
              '<h3>Filter Results</h3><p>Terminal A Terminal B</p>')
    access = ("<p>TSA Cares is a helpline for travelers with disabilities. Service animal relief areas are "
              "located after security near Gate A2.</p>")
    web = Web({f"{home}/robots.txt": ROBOTS_OK, home: (200, homepage), f"{home}/dining": (200, dining),
               f"{home}/accessibility": (200, access)})
    airport = {"org": "Madeup Regional Airport", "faa": "MDX", "place_key": "faa-airports:MDX", "lat": "44.05",
               "lon": "-72.05", "homepage": home}
    rows, status = airports.read_airport(client(web), airport, {})
    assert status == "ok"
    by = {r["name"]: r for r in rows}
    diner = by["Sample Diner"]
    assert diner["kind"] == "dining" and diner["phone"] == "802-555-0166" and diner["business"] == "1"
    assert "Gate B4" in diner["notes"] and "after security" in diner["notes"]
    assert by["TSA Cares"]["kind"] == "accessibility service"
    assert by["Service animal relief areas"]["kind"] == "pet relief area"
    assert by["Madeup Regional Airport"]["place_key"] == "faa-airports:MDX"
    assert "Filter Results" not in by


# ------------------------------------------------------------------------------------------------ vendor embed

ACCOUNT, VENUE = "A0MADEUP", "mdx"
FILES = f"https://a.locuslabs.com/accounts/{ACCOUNT}/{VENUE}/2026-12-01/v5"


def atrius_web(home="https://www.madeup-airport.example"):
    """A stand-in airport whose homepage links its public Atrius map, with the map's config and venue files."""
    pois = {
        "1": {"poiId": "1", "name": "Gate B4", "category": "gate", "isAfterSecurity": True,
              "position": {"floorId": "mdx-t1-2", "latitude": 44.0501, "longitude": -72.0501}},
        "2": {"poiId": "2", "name": "Sample Coffee", "category": "eat.coffee", "isAfterSecurity": True,
              "phone": "+1 (802) 555-0177", "operationHours": "Mo-Su 05:00-20:00", "nearbyLandmark": "Gate B4",
              "links": [{"url": "https://coffee.example", "type": "primary"}],
              "position": {"floorId": "mdx-t1-2", "latitude": 44.0502, "longitude": -72.0502}},
        "3": {"poiId": "3", "name": "Restroom - Family", "category": "restroom.family", "isAfterSecurity": False,
              "position": {"floorId": "mdx-t1-1", "latitude": 44.0503, "longitude": -72.0503}},
        "4": {"poiId": "4", "name": "Service Animal Relief Area", "category": "services.animalreliefarea",
              "isAfterSecurity": True, "description": "Outdoor relief area. Ask volunteer@madeup-airport.example.",
              "position": {"floorId": "mdx-t1-2", "latitude": 44.0504, "longitude": -72.0504}},
        "5": {"poiId": "5", "name": "Sculpture", "category": "art",
              "position": {"floorId": "mdx-t1-2", "latitude": 44.0505, "longitude": -72.0505}},
        "6": {"poiId": "6", "name": "Alice Example", "category": "shop",
              "position": {"floorId": "mdx-t1-2", "latitude": 44.0506, "longitude": -72.0506}},
    }
    venue = {VENUE: {"name": "Madeup Regional Airport", "phone": "+18025550100", "hours": "Mo-Su 00:00-23:59",
                     "website": home, "structures": {
                         "mdx-t1": {"name": "Terminal 1", "levels": {
                             "mdx-t1-1": {"name": "Level 1", "details": "Baggage Claim"},
                             "mdx-t1-2": {"name": "Level 2", "details": "All Gates"}}}}}}
    return Web({f"{home}/robots.txt": ROBOTS_OK, home: (200, f'<a href="https://maps.madeup-airport.example/?vid='
                                                              f'{VENUE}&amp;s=xyz">Airport map</a>'),
                "https://maps.madeup-airport.example/robots.txt": (404, ""),
                "https://maps.madeup-airport.example/config.json": (200, {"plugins": {"venueDataLoader": {
                    "accountId": ACCOUNT, "venueId": VENUE}}}),
                atrius.DATA.format(account=ACCOUNT): (200, {VENUE: {"files": {
                    "pois": f"{FILES}/pois-3.0-{VENUE}.json", "venueData": f"{FILES}/venueData-{VENUE}.json"}}}),
                f"{FILES}/pois-3.0-{VENUE}.json": (200, pois), f"{FILES}/venueData-{VENUE}.json": (200, venue)})


def test_atrius_vendor_map():
    """An airport's public Atrius map: the terminal, a gate, a coffee shop with its own position, level, phone,
    hours and nearby gate (a business), a family restroom, a relief area without the e-mail address of its
    description, art and a person-named shop left out; the airport's site row with its phone and 24/7 hours."""
    home = "https://www.madeup-airport.example"
    airport = {"org": "Madeup Regional Airport", "faa": "MDX", "place_key": "faa-airports:MDX", "lat": "44.05",
               "lon": "-72.05", "homepage": home}
    stats = {}
    rows, status = airports.read_airport(client(atrius_web()), airport, stats)
    assert status == "ok"
    by = {r["key"]: r for r in rows}
    site = by["airport:MDX"]
    assert site["phone"] == "802-555-0100" and site["opening_hours"] == "24/7" and site["map_id"] == VENUE
    assert by["airport:MDX:b:mdx-t1"]["kind"] == "terminal" and by["airport:MDX:b:mdx-t1"]["name"] == "Terminal 1"
    gate = by["airport:MDX:poi:1"]
    assert gate["kind"] == "gate" and gate["building"] == "airport:MDX:b:mdx-t1"
    assert gate["level"] == "Level 2 (All Gates)"
    coffee = by["airport:MDX:poi:2"]
    assert coffee["kind"] == "dining" and coffee["lat"] == 44.0502 and coffee["phone"] == "802-555-0177"
    assert coffee["opening_hours"] == "Mo-Su 05:00-20:00" and coffee["business"] == "1"
    assert "after security" in coffee["notes"] and "near Gate B4" in coffee["notes"]
    assert by["airport:MDX:poi:3"]["kind"] == "family restroom"
    relief = by["airport:MDX:poi:4"]
    assert relief["kind"] == "pet relief area" and "@" not in relief["notes"]
    assert "Outdoor relief area" in relief["notes"]
    assert "airport:MDX:poi:5" not in by and "airport:MDX:poi:6" not in by
    assert atrius.kind_of("restroom.female") == "restroom" and atrius.kind_of("art") == ""


def test_registry_knows_atrius_map_pages():
    """An Atrius map page on an airport's own host is fingerprinted by its marks; the vendor now has a collector."""
    page = "<html><title>Atrius Maps</title><script>window.LocusLabsMaps.create(config)</script></html>"
    found = registry.fingerprints(page, "https://maps.madeup-airport.example/?vid=mdx")
    assert found and found[0]["vendor"] == "locuslabs"
    assert registry.VENDORS["locuslabs"]["collector"] == "atrius" and registry.VENDORS["locuslabs"]["data"] == "public"
    assert atrius.config_url("https://maps.madeup-airport.example/?vid=mdx") == \
        "https://maps.madeup-airport.example/config.json"


# ------------------------------------------------------------------------------------------------ into the packs

def test_rows_become_site_features_and_businesses(tmp_path):
    """The airport's rows in a pack: the extra part's site features (tied to the FAA airport already in the pack,
    with its terminal, levels and kinds) and the airport's phone; the businesses part's shop with its own phone and
    note (the tabular reader takes only rows marked as businesses)."""
    home = "https://www.madeup-airport.example"
    airport = {"org": "Madeup Regional Airport", "faa": "MDX", "place_key": "faa-airports:MDX", "lat": "44.05",
               "lon": "-72.05", "homepage": home}
    rows, _ = airports.read_airport(client(atrius_web()), airport, {})
    path = tmp_path / "airports.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=indoor.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    region = dict(catalogue.regions()[VT])
    pw = PackWriter(str(tmp_path / "extra.osmpack"))
    pw.add_point("faa-airports:MDX", "faa-airports", "MADEUP REGIONAL", "transit", "airport", 44.05, -72.05)
    features.read(str(path), cat["airport-directories"], region, pw)
    pw.finish({"part": "extra", "region_id": VT})
    pack = PackReader(str(tmp_path / "extra.osmpack"))
    got = pack.features_of("faa-airports:MDX")
    kinds = {r["kind"] for r in got}
    assert {"terminal", "gate", "dining", "family restroom", "pet relief area"} <= kinds
    assert pack.details_of("faa-airports:MDX")["phone"] == "802-555-0100"
    assert [r["name"] for r in pack.features_of("faa-airports:MDX", kinds="gate")] == ["Gate B4"]
    pack.close()
    bw = PackWriter(str(tmp_path / "biz.osmpack"), 202612)
    assert read_tabular(str(path), cat["airport-directories-businesses"], region, bw) == 1
    bw.finish({"part": "businesses", "region_id": VT})
    biz = PackReader(str(tmp_path / "biz.osmpack"))
    key = "airport-directories-businesses:airport:MDX:poi:2"
    assert biz.details_of(key)["phone"] == "802-555-0177"
    assert "near Gate B4" in biz.notes_for(key)[0]
    biz.close()


# ------------------------------------------------------------------------------------------------ blocks

def test_blocks_are_recorded_never_got_round(tmp_path):
    """An operator whose site refuses stops its unit ("blocked", no file); a not-read operator's monthly check
    records "blocked" with the reason; an airport answering with an anti-bot page and a mall answering 403 are
    counted as blocked, and nothing more is asked of them."""
    listing = tmp_path / "seeds.json"
    listing.write_text(json.dumps(SEEDS))
    os.environ["MALL_SEEDS"] = str(listing)
    try:
        web = Web({"https://www.tanger.com/robots.txt": (403, "Forbidden")})
        summary = dirrun.run("malls", "tanger", str(tmp_path), opener=web, sleep=lambda s: None, today=TODAY)
        assert summary["status"] == "blocked" and not (tmp_path / "tanger.csv.gz").exists()
        web = Web({"https://www.simon.com/mall": (403, "<title>Access Denied</title>")})
        summary = dirrun.run("malls", "simon", str(tmp_path), opener=web, sleep=lambda s: None, today=TODAY)
        assert summary["status"] == "blocked" and "robots.txt" in summary["reason"]
    finally:
        del os.environ["MALL_SEEDS"]
    web = Web({"https://www.madeup-airport.example/robots.txt": ROBOTS_OK,
               "https://www.madeup-airport.example": (200, "<title>Just a moment...</title>")})
    airport = {"org": "Madeup Regional Airport", "faa": "MDX", "place_key": "faa-airports:MDX", "lat": "44.05",
               "lon": "-72.05", "homepage": "https://www.madeup-airport.example"}
    stats = {}
    assert list(airports.collect(client(web), "airports-1", stats, airports=[airport])) == []
    assert stats["blocked"] == 1 and stats["blocked_sites"] == ["MDX https://www.madeup-airport.example"]
    assert len(web.asked) == 2
    web = Web({"https://www.sampletowncenter.example/robots.txt": (403, "no")})
    stats = {}
    assert malls.independent_mall(client(web), SEEDS[2], stats, []) == [] and stats["blocked"] == 1


# ------------------------------------------------------------------------------------------------ wiring

def test_seeds_and_matching():
    """OurAirports' scheduled US airports (large first, FAA keys), a mall matched by its website host, a shared
    host matched by its path, a name match."""
    text = ("ident,type,name,latitude_deg,longitude_deg,iso_country,scheduled_service,gps_code,iata_code,local_code,"
            "home_link\n"
            "KMDX,medium_airport,Madeup Regional Airport,44.05,-72.05,US,yes,KMDX,MDX,MDX,https://madeup.example\n"
            "KSMP,large_airport,Sample International Airport,44.06,-72.06,US,yes,KSMP,SMP,SMP,\n"
            "KPRV,small_airport,Private Strip,44.07,-72.07,US,no,KPRV,,PRV,\n"
            "CXXX,large_airport,Elsewhere Airport,45,-73,CA,yes,CXXX,XXX,,\n")
    found = seeds.ourairports(text)
    assert [a["faa"] for a in found] == ["SMP", "MDX"] and found[1]["place_key"] == "faa-airports:MDX"
    assert seeds.match_mall("x", "http://madeupmall.example/", SEEDS)["place_key"] == "wikidata:Q9990002"
    assert seeds.host_root("https://www.westfield.com/en/united-states/valleyfair/") == "westfield.com/valleyfair"
    assert seeds.match_mall("Madeup Outlets Testvile", "", SEEDS)["place_key"] == "wikidata:Q9990001"
    assert seeds.match_mall("Nowhere Plaza", "", SEEDS) is None


def test_runner_catalogue_contact_and_workflows():
    """The collections "malls" and "airports" in the runner, the four catalogue entries, the contact lists (one
    order everywhere) and the two monthly workflows."""
    specs = dirrun.collections()
    assert {"tanger", "macerich", "brookfield", "westfield", "cbl", "simon", "independent-1"} <= set(
        specs["malls"]["units"])
    assert set(specs["airports"]["units"]) == {f"airports-{i}" for i in range(1, airports.SHARDS + 1)}
    assert specs["malls"]["tag"] == "malls" and specs["airports"]["tag"] == "airports"
    assert specs["malls"]["fields"][:len(features.FEATURE_FIELDS)] == features.FEATURE_FIELDS
    cat = {e["id"]: e for e in catalogue.load()["accepted"]}
    for sid, release in (("mall-directories", "malls"), ("airport-directories", "airports")):
        assert cat[sid]["reader"] == "site_features" and cat[sid]["part"] == "extra"
        assert cat[sid]["fetch"] == {"method": "release_csv", "release": release, "prefix": release}
        biz = cat[f"{sid}-businesses"]
        assert biz["part"] == "businesses" and biz["reader"] == "tabular"
        assert biz["exclude"] == {"column": "business", "values": [""]}
        assert sid in contact.INSTITUTION_SOURCES and f"{sid}-businesses" in contact.HOURS_SOURCES
    assert lookup.DETAIL_ORDER == writer.CONTACT_ORDER == contact.CONTACT_SOURCES
    assert contact.CONTACT_SOURCES[-1] == "yp-lookups"
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "malls.yml"), "5")
    workflow_shape(os.path.join(ROOT, ".github", "workflows", "airports.yml"), "22")
