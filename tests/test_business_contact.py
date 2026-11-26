"""Business contact details (placepacks/contact.py, the businesses part's biz_details table): the phone, website
and opening hours of a business, from the business-directory sources only (All The Places, Overture's places,
Foursquare's Open Source Places). Covered: each source's fields are carried; an e-mail address is never carried;
individuals' offices and person names get no details; a licence list's phone is never kept; values are cleaned and
deduplicated; the details belong to the record listed now (history); a pack made before the table still reads; the
"find the nearest" and "local services" lookups give them. Offline: every place, number and address is made up."""

import csv
import json
import os
import sqlite3
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from placepacks import atp_history, catalogue, contact, fetch  # noqa: E402
from placepacks.find import Finder  # noqa: E402
from placepacks.local import LocalServices  # noqa: E402
from placepacks.lookup import PackReader  # noqa: E402
from placepacks.readers.tabular import read as read_tabular  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

VT = "us-vermont"
SPOT = (44.0006, -71.9981)
META = {"region_id": VT, "state": "Vermont", "country": "United States", "part": "businesses"}


def entry_of(source_id):
    """A catalogue entry by id (a copy)."""
    return json.loads(json.dumps(next(e for e in catalogue.load()["accepted"] if e["id"] == source_id)))


def everything_in(path):
    """Every text value of every table of a pack, joined: to show something is nowhere in it."""
    con = sqlite3.connect(path)
    out = []
    for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        for row in con.execute(f"SELECT * FROM {table}"):
            out += [str(v) for v in row if isinstance(v, str)]
    con.close()
    return "\n".join(out)


def biz(path):
    """{key: (phone, website, opening_hours)} of a pack's biz_details."""
    con = sqlite3.connect(path)
    rows = con.execute("SELECT p.key, d.phone, d.website, d.opening_hours FROM biz_details d JOIN points p ON "
                       "p.id = d.id").fetchall()
    con.close()
    return {r[0]: r[1:] for r in rows}


# ------------------------------------------------------------------------------------------- cleaning

def test_phone_numbers_are_cleaned_lightly():
    assert contact.phone("+18025550100") == "802-555-0100"
    assert contact.phone("tel:(802) 555-0100 ext. 12") == "802-555-0100"
    assert contact.phone("802.555.0100; 802-555-0199") == "802-555-0100"
    assert contact.phone(["", "+1 802 555 0100"]) == "802-555-0100"
    assert contact.phone("+44 20 7946 0000") == "+44 20 7946 0000"
    assert contact.phone("owner@example.com") == ""                 # never an e-mail
    assert contact.phone("call us") == "" and contact.phone("12") == ""


def test_web_addresses_are_http_only_without_tracking_or_socials():
    assert contact.website("HTTPS://Made-Up-Burgers.Example/") == "https://made-up-burgers.example"
    assert contact.website("https://made-up-burgers.example/store/12#map") == \
        "https://made-up-burgers.example/store/12"
    assert contact.website("https://made-up-burgers.example/store?id=12") == \
        "https://made-up-burgers.example/store?id=12"
    assert contact.website("https://made-up-burgers.example/?utm_source=maps") == "https://made-up-burgers.example"
    assert contact.website("https://made-up-burgers.example/store?id=7&fbclid=x") == "https://made-up-burgers.example/store?id=7"
    assert contact.website("https://made-up-burgers.example/?fbclid=abc") == "https://made-up-burgers.example"
    assert contact.website("mailto:owner@example.com") == ""
    assert contact.website("owner@example.com") == ""
    assert contact.website("ftp://made-up.example/") == ""
    assert contact.website("www.made-up.example") == ""
    assert contact.website("https://www.facebook.com/madeupburgers") == ""
    assert contact.website("https://user:secret@made-up.example/") == ""
    assert contact.website("https://made-up.example/" + "a" * 300) == ""


def test_hours_and_who_may_have_details():
    assert contact.hours("  Mo-Fr 08:00-18:00;  Sa 09:00-12:00 ") == "Mo-Fr 08:00-18:00; Sa 09:00-12:00"
    assert contact.hours("24/7") == "24/7" and contact.hours("ask inside") == ""
    assert contact.allowed("overture-places", "Made-up Burgers", "burger restaurant")
    assert not contact.allowed("vt-liquor-licences", "Made-up Burgers")       # a licence list: never
    assert not contact.allowed("overture-places", "Alice Example")            # a person's name
    assert not contact.allowed("fsq-places", "Pretend Cover", "insurance agency")
    assert not contact.allowed("overture-places", "Made-up Realty", "real estate agent")
    # hours only from All The Places (OpenStreetMap syntax)
    assert contact.clean("overture-places", "Made-up Cafe", None, "8025550100", None, "Mo 08:00-12:00") == {
        "phone": "802-555-0100"}


# ------------------------------------------------------------------------------------------- All The Places

def atp_run(path):
    """A made-up All The Places run with a store's phone, website, hours and e-mail, the "contact:" form, an
    individual's office and a person's name."""
    def feat(spider, ref, dlat, **tags):
        return {"type": "Feature", "id": f"{spider}-{ref}", "geometry": {"type": "Point", "coordinates": [
            SPOT[1], SPOT[0] + dlat]}, "properties": dict({"@spider": spider, "ref": ref}, **tags)}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("output/made_up_burgers.geojson", json.dumps({"type": "FeatureCollection", "features": [
            feat("made_up_burgers", "1", 0, name="Made-up Burgers", brand="Made-up Burgers", amenity="fast_food",
                 phone="+1 802-555-0100", website="https://made-up-burgers.example/store/1",
                 opening_hours="Mo-Su 06:00-23:00", email="manager1@example.com"),
            feat("made_up_burgers", "2", 0.01, name="Made-up Burgers", amenity="fast_food",
                 **{"contact:phone": "(802) 555-0102", "contact:website": "https://made-up-burgers.example/2",
                    "contact:email": "manager2@example.com"})]}))
        z.writestr("output/pretend_agents.geojson", json.dumps({"type": "FeatureCollection", "features": [
            feat("pretend_agents", "7", 0.02, name="Pretend Cover - Alice Example", office="insurance",
                 phone="802-555-0177", email="alice@example.com"),
            feat("pretend_agents", "8", 0.03, name="Bob Example", shop="gift", phone="802-555-0188")]}))
    return str(path)


def atp_pack(tmp_path, csv_path, month=202611, previous=None, name="atp"):
    """A businesses pack of All The Places from the CSV."""
    entry = dict(entry_of("alltheplaces"), regions=[VT])
    out = str(tmp_path / f"{name}-{month}.osmpack")
    w = PackWriter(out, month)
    read_tabular(str(csv_path), entry, dict(catalogue.regions()[VT]), w)
    w.finish(META, previous=previous)
    return out


def test_all_the_places_carries_phone_website_and_hours_never_email(tmp_path):
    csv_path = tmp_path / "atp.csv"
    assert fetch.atp_to_csv(atp_run(tmp_path / "run.zip"), str(csv_path), [(-73.5, 42.7, -71.4, 45.1)]) == 2
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "email" not in rows[0] and "contact:email" not in rows[0]
    assert [r["phone"] for r in rows] == ["+1 802-555-0100", "(802) 555-0102"]
    pack = atp_pack(tmp_path, csv_path)
    assert biz(pack) == {
        "alltheplaces:made_up_burgers:1": ("802-555-0100", "https://made-up-burgers.example/store/1",
                                           "Mo-Su 06:00-23:00"),
        "alltheplaces:made_up_burgers:2": ("802-555-0102", "https://made-up-burgers.example/2", None)}
    text = everything_in(pack)
    assert "@" not in text                                       # no e-mail anywhere
    for gone in ("Alice", "Bob Example", "555-0177", "555-0188"):   # individuals: left out with their details
        assert gone not in text
    assert "contact" not in [r[1] for r in sqlite3.connect(pack).execute("PRAGMA table_info(points)")]
    assert PackReader(pack).details_of("alltheplaces:made_up_burgers:1") == {
        "phone": "802-555-0100", "website": "https://made-up-burgers.example/store/1",
        "opening_hours": "Mo-Su 06:00-23:00"}


def test_the_history_seed_keeps_the_details_of_stores_listed_now(tmp_path):
    from test_chain_history import BOX, feature, make_seed, write_run
    seed = make_seed(tmp_path)
    target = tmp_path / "atp.csv"
    fetch.atp_to_csv(write_run(tmp_path / "latest.zip", {"made_up_mart": [
        feature("made_up_mart", "1", 0, name="Made-up Mart", shop="convenience", phone="802-555-0111")]}),
        str(target), BOX)
    assert atp_history.apply(str(target), seed) is not None
    with open(target, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["phone"] for r in rows if r["key"] == "made_up_mart:1"] == ["802-555-0111"]
    assert all(r["phone"] == "" for r in rows if r["key"] != "made_up_mart:1")     # closed stores: none


# ------------------------------------------------------------------------------------------- Overture, Foursquare

duckdb_needed = pytest.mark.skipif(not __import__("importlib").util.find_spec("duckdb"), reason="needs duckdb")


@duckdb_needed
def test_overture_carries_its_first_phone_and_website_never_emails_or_socials(tmp_path):
    import duckdb
    from placepacks.readers.parquet import read as read_parquet
    src = tmp_path / "overture.parquet"
    duckdb.connect().execute(f"""COPY (SELECT * FROM (VALUES
        ('g1', {{'primary': 'Made-up Cafe'}}, 'cafe', {{'xmin': {SPOT[1]}, 'ymin': {SPOT[0]}}}, 0.9, 'open',
         ['+18025550120', '+18025550121'], ['https://made-up-cafe.example/'], ['cafe@example.com'],
         ['https://www.facebook.com/madeupcafe']),
        ('g2', {{'primary': 'Alice Example'}}, 'cafe', {{'xmin': {SPOT[1]}, 'ymin': {SPOT[0] + 0.01}}}, 0.9, 'open',
         ['+18025550122'], ['https://alice.example/'], NULL, NULL),
        ('g3', {{'primary': 'Made-up Diner'}}, 'diner', {{'xmin': {SPOT[1]}, 'ymin': {SPOT[0] + 0.02}}}, 0.9,
         'open', NULL, ['https://made-up-diner.example/?utm_source=maps'], NULL, NULL))
        t(id, names, basic_category, bbox, confidence, operating_status, phones, websites, emails, socials))
        TO '{src}' (FORMAT PARQUET)""")
    out = str(tmp_path / "o.osmpack")
    w = PackWriter(out, 202611)
    read_parquet(str(src), entry_of("overture-places"), dict(catalogue.regions()[VT]), w)
    w.finish(META)
    assert biz(out) == {"overture-places:g1": ("802-555-0120", "https://made-up-cafe.example", None),
                        "overture-places:g3": (None, "https://made-up-diner.example", None)}   # tracking part gone
    text = everything_in(out)
    assert "@" not in text and "facebook" not in text and "555-0122" not in text


@duckdb_needed
def test_foursquare_carries_tel_and_website_never_email(tmp_path):
    import duckdb
    from placepacks.readers.parquet import read as read_parquet
    src = tmp_path / "fsq.parquet"
    duckdb.connect().execute(f"""COPY (SELECT * FROM (VALUES
        ('f1', 'Made-up Bakery', ['Dining and Drinking > Bakery'], {SPOT[0]}, {SPOT[1]}, DATE '2015-01-01',
         NULL::DATE, '(802) 555-0130', 'http://made-up-bakery.example/', 'baker@example.com', 'madeupbakery'))
        t(fsq_place_id, name, fsq_category_labels, latitude, longitude, date_created, date_closed, tel, website,
          email, instagram)) TO '{src}' (FORMAT PARQUET)""")
    out = str(tmp_path / "f.osmpack")
    w = PackWriter(out, 202611)
    read_parquet(str(src), entry_of("fsq-places"), dict(catalogue.regions()[VT]), w)
    w.finish(META)
    assert biz(out) == {"fsq-places:f1": ("802-555-0130", "http://made-up-bakery.example", None)}
    assert "@" not in everything_in(out) and "madeupbakery" not in everything_in(out)


def test_the_catalogue_reads_contact_columns_only_from_the_directories():
    cat = catalogue.load()
    assert catalogue.check(cat) == []
    for e in cat["accepted"]:
        text = json.dumps({k: e.get(k) for k in ("query", "local_query", "prepare_query", "columns", "pick",
                                                 "contact_columns")})
        assert "email" not in text.lower() and "socials" not in text and "instagram" not in text, e["id"]
        if e.get("contact_columns") or "phones" in text or "{tel}" in text:
            assert e["id"] in contact.CONTACT_SOURCES, e["id"]


# ------------------------------------------------------------------------------------------- the writer

def test_a_licence_list_never_gets_details_and_lesser_copies_are_left_out(tmp_path):
    out = str(tmp_path / "w.osmpack")
    w = PackWriter(out, 202611)
    phone = {"phone": "802-555-0140", "website": "https://made-up-pizza.example/"}
    w.add_point("vt-licences:9", "vt-licences", "Made-up Pizza", "business", "t", *SPOT, contact=phone)
    w.add_point("alltheplaces:p:1", "alltheplaces", "Made-up Pizza", "business", "t", *SPOT,
                contact=dict(phone, opening_hours="Mo-Su 11:00-22:00"))
    w.add_point("overture-places:g9", "overture-places", "MADE-UP PIZZA".title(), "business", "t", SPOT[0] + 1e-4,
                SPOT[1], contact={"phone": "+1 (802) 555-0140", "website": "https://made-up-pizza.example/menu"})
    w.add_point("fsq-places:f9", "fsq-places", "Made-up Pizza", "business", "t", SPOT[0] + 0.02, SPOT[1],
                contact={"phone": "802-555-0140"})                     # 2 km away: another shop, kept
    w.finish(META)
    assert biz(out) == {
        "alltheplaces:p:1": ("802-555-0140", "https://made-up-pizza.example", "Mo-Su 11:00-22:00"),
        "overture-places:g9": (None, "https://made-up-pizza.example/menu", None),     # same phone: left out
        "fsq-places:f9": ("802-555-0140", None, None)}
    # a pack of a part without any directory has no table at all
    other = str(tmp_path / "x.osmpack")
    w = PackWriter(other, 202611)
    w.add_point("vt-licences:9", "vt-licences", "Made-up Pizza", "business", "t", *SPOT, contact=phone)
    w.finish(META)
    assert not PackReader(other).has_details and "555-0140" not in everything_in(other)


def test_details_belong_to_the_record_listed_now(tmp_path):
    """A renamed business: the old name's row keeps no details; a business no longer listed loses them."""
    def month(m, rows, previous=None):
        out = str(tmp_path / f"h{m}.osmpack")
        w = PackWriter(out, m)
        for key, name, ph in rows:
            w.add_point(key, "overture-places", name, "business", "t", *SPOT, type="pizza restaurant",
                        contact={"phone": ph})
        w.finish(META, previous=previous)
        return out
    old = month(202605, [("overture-places:g1", "Tony's Pizza", "802-555-0150"),
                         ("overture-places:g2", "Gone Grill", "802-555-0151")])
    new = month(202611, [("overture-places:g1", "Sally's Ice Cream", "802-555-0160")], previous=old)
    con = sqlite3.connect(new)
    rows = con.execute("SELECT p.name, d.phone FROM points p LEFT JOIN biz_details d ON d.id = p.id ORDER BY "
                       "p.name").fetchall()
    assert rows == [("Gone Grill", None), ("Sally's Ice Cream", "802-555-0160"), ("Tony's Pizza", None)]
    assert PackReader(new).details_of("overture-places:g1") == {"phone": "802-555-0160"}
    assert PackReader(new).details_of("overture-places:g2") == {}


def test_a_pack_made_before_the_table_still_reads(tmp_path):
    out = str(tmp_path / "old.osmpack")
    w = PackWriter(out, 202611)
    w.add_point("overture-places:g1", "overture-places", "Made-up Pharmacy", "business", "t", *SPOT,
                type="pharmacy", contact={"phone": "802-555-0170"})
    w.finish(META)
    con = sqlite3.connect(out)
    con.execute("DROP TABLE biz_details")
    con.commit()
    con.close()
    reader = PackReader(out)
    assert not reader.has_details and reader.details_of("overture-places:g1") == {}
    got = Finder(packs=[reader]).nearest("pharmacy", *SPOT)
    assert got[0]["name"] == "Made-up Pharmacy" and got[0]["phone"] == ""
    assert LocalServices(packs=[reader]).nearest(*SPOT, "pharmacy")["places"][0]["phone"] == ""
    # and a new pack builds on it
    w = PackWriter(str(tmp_path / "new.osmpack"), 202612)
    w.add_point("overture-places:g1", "overture-places", "Made-up Pharmacy", "business", "t", *SPOT,
                type="pharmacy", contact={"phone": "802-555-0171"})
    w.finish(META, previous=out)
    assert PackReader(str(tmp_path / "new.osmpack")).details_of("overture-places:g1") == {"phone": "802-555-0171"}


# ------------------------------------------------------------------------------------------- the lookups

def test_find_and_local_services_give_the_details_best_source_first(tmp_path):
    out = str(tmp_path / "b.osmpack")
    w = PackWriter(out, 202611)
    w.add_point("fsq-places:f1", "fsq-places", "Made-up Pharmacy", "business", "t", *SPOT, type="pharmacy",
                contact={"phone": "802-555-0181", "website": "https://fsq-copy.example/"})
    w.add_point("alltheplaces:rx:1", "alltheplaces", "Made-up Pharmacy", "business", "t", SPOT[0] + 2e-4, SPOT[1],
                type="pharmacy", contact={"phone": "802-555-0180", "opening_hours": "Mo-Fr 09:00-19:00"})
    w.finish(META)
    reader = PackReader(out)
    place = Finder(packs=[reader]).nearest("drugstore", *SPOT)[0]
    assert (place["phone"], place["website"], place["opening_hours"]) == (
        "802-555-0180", "https://fsq-copy.example", "Mo-Fr 09:00-19:00")   # each detail from the best source
    assert place["sources"] == ["alltheplaces", "fsq-places"]
    assert Finder(packs=[reader]).details("alltheplaces:rx:1")["phone"] == "802-555-0180"
    near = LocalServices(packs=[reader]).nearest(*SPOT, "pharmacy")
    assert near["places"][0]["phone"] == "802-555-0180" and "Phone 802-555-0180." in near["phrase"]
