"""Several businesses at one address (a strip mall): GPS is good to 5-15 m, so the lookup does not guess one tenant.
It names the plaza holding them, else the address, else the street; the candidates go to Result.others (never
spoken); past and future tenants are left out first; the same business from several sources is one place. Every
name here is made up."""

import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from placepacks.lookup import Finder, PackReader, Result, merge_same_business, normal_name  # noqa: E402
from placepacks.writer import PackWriter  # noqa: E402

REGION = {"region_id": "us-vermont", "state": "Vermont", "country": "United States"}
SPOT = (44.0006, -71.9981)
M = 1 / 111320                     # one metre of latitude in degrees


def build(path, month, tenants, plaza=False, address=False, previous=None):
    """A pack: tenants [(key, source, name, metres north of SPOT, first, last)], a named plaza area around them,
    an address point at SPOT."""
    w = PackWriter(str(path), month)
    for key, source, name, north, first, last in tenants:
        w.add_point(key, source, name, "business", "t", SPOT[0] + north * M, SPOT[1], first, last)
    if plaza:
        lat, lon = SPOT
        ring = [(lat - 0.0005, lon - 0.0007), (lat - 0.0005, lon + 0.0007), (lat + 0.0005, lon + 0.0007),
                (lat + 0.0005, lon - 0.0007), (lat - 0.0005, lon - 0.0007)]
        w.add_area("osm:plaza", "osm", "Riverside Plaza", "business", "mall", [ring])
    if address:
        w.add_address("nad", "123", "Main St", "Testville", SPOT[0], SPOT[1])
    w.finish(REGION, previous=previous)
    return Finder(packs=[PackReader(str(path))], water=False)


STRIP = [("n1", "osm", "Made-up Nails", 0, None, None), ("n2", "osm", "Invented Pizza", 6, None, None),
         ("n3", "osm", "Pretend Laundromat", 12, None, None)]


def test_three_tenants_in_a_named_plaza_give_the_plaza(tmp_path):
    r = build(tmp_path / "a.osmpack", 202611, STRIP, plaza=True).lookup(*SPOT)
    assert r.name == "Riverside Plaza"
    assert sorted(o["name"] for o in r.others) == ["Invented Pizza", "Made-up Nails", "Pretend Laundromat"]
    assert all("Made-up Nails" not in r.phrase(d) for d in ("area", "street", "address"))


def test_three_tenants_without_a_plaza_give_the_address(tmp_path):
    r = build(tmp_path / "b.osmpack", 202611, STRIP, address=True).lookup(*SPOT, detail="address")
    assert (r.kind, r.name, r.house_number, r.street) == ("address", "", "123", "Main St")
    assert len(r.others) == 3 and r.phrase("address").startswith("near 123 Main St")


def test_a_2005_picture_with_one_tenant_then_gives_that_tenant(tmp_path):
    tenants = [("n1", "osm", "Made-up Nails", 0, 200001, None),
               ("n2", "osm", "Invented Pizza", 6, 201001, None),        # opened later
               ("n3", "osm", "Pretend Laundromat", 12, 199001, 200212)]  # closed before
    f = build(tmp_path / "c.osmpack", 202611, tenants, plaza=False, address=True)
    r = f.lookup(*SPOT, when="2005-06-01")
    assert r.name == "Made-up Nails" and r.others == []
    assert f.lookup(*SPOT, when="2015-06-01").others          # in 2015 two tenants: unclear again


def test_one_clearly_nearest_business_is_taken(tmp_path):
    tenants = [("n1", "osm", "Made-up Nails", 0, None, None), ("n2", "osm", "Invented Pizza", 30, None, None)]
    f = build(tmp_path / "d.osmpack", 202611, tenants)
    assert f.lookup(*SPOT).name == "Made-up Nails"
    assert f.lookup(*SPOT, accuracy=40).name == ""           # a phone that says it is only good to 40 m


def test_the_same_business_from_several_sources_is_one_place(tmp_path):
    tenants = [("osm1", "osm", "The Corner Cafe", 0, 201801, None),
               ("ov1", "overture-places", "Corner Cafe, LLC", 4, 201501, None),
               ("lic1", "sf-registered-businesses", "CORNER CAFE", 8, 200301, 202001)]
    r = build(tmp_path / "e.osmpack", 202611, tenants).lookup(*SPOT)
    assert r.name == "The Corner Cafe" and r.others == []
    assert r.first == 200301 and r.last is None or r.last >= 202611
    assert normal_name("The Corner Café, LLC") == normal_name("corner café")
    rows = [{"key": k, "name": n, "d": d, "lat": SPOT[0] + d * M, "lon": SPOT[1]} for k, _, n, d, _, _ in tenants]
    assert len(merge_same_business(rows)) == 1


def test_others_are_never_spoken():
    for name, fn in inspect.getmembers(Result, inspect.isfunction):
        if name != "__init__":
            assert "self.others" not in inspect.getsource(fn), name
