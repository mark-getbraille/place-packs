"""Trips, smart area naming (the Outer Banks across years), the other place details, guessing by time, My places,
water and air, templates, and the plan as a whole, with the stand-in finder."""

import datetime as dt

import pytest

from conftest import DUCK, HATTERAS, JOCKEYS, KDH, NAGS, WB
from pli import grouping as g
from pli import myplaces as mp
from pli.photos import Photo
from pli.places import Area, PlaceInfo, Places, info_from_result, resolve_admin


def P(pos, when, name="x.jpg", source="gps"):
    """A Photo already read: position pos ((lat, lon) or None) at when ("2005-07-02 10:00")."""
    p = Photo(name)
    p.taken = dt.datetime.strptime(when, "%Y-%m-%d %H:%M")
    p.date_source = "camera"
    if pos:
        p.lat, p.lon = pos
        p.location_source = source
    return p


def plan_for(finder, photos, **opts):
    """make_plan over photos with the stand-in finder."""
    return g.make_plan("/album", photos, Places(finder=finder), g.options(**opts))


def folders(plan):
    """The folder names of a plan."""
    return [x.folder for x in plan.groups]


# ---------------------------------------------------------------- trips

def test_trips_split_after_the_gap():
    """A new trip starts when more than gap_days pass without a photo."""
    photos = [P(KDH, "2005-07-01 10:00"), P(KDH, "2005-07-03 09:00"), P(KDH, "2005-07-06 10:00")]
    assert [len(t.photos) for t in g.make_trips(photos, 2)] == [2, 1]
    assert [len(t.photos) for t in g.make_trips(photos, 4)] == [3]


def test_trips_split_when_the_place_changes(finder):
    """With "also when the place changes", Outer Banks then Wrightsville Beach the next day are two trips."""
    photos = [P(KDH, "2005-07-01 10:00"), P(NAGS, "2005-07-01 15:00"), P(WB, "2005-07-02 09:00")]
    plan = plan_for(finder, photos, time="trip", split_on_place=True)
    assert [x.place for x in plan.groups] == ["Outer Banks", "Wrightsville Beach"]
    assert len(plan_for(finder, photos, time="trip").groups) == 1


# ---------------------------------------------------------------- smart naming

def test_outer_banks_two_years_get_the_same_name(finder):
    """The owner's case: a week in Kill Devil Hills and Nags Head in 2005 and a week in Duck only in 2006 are both
    "Outer Banks": 2005 is spread over two towns (pass 1), 2006 is unified with it (pass 2)."""
    photos = [P(KDH, "2005-07-02 10:00"), P(NAGS, "2005-07-04 12:00"), P(KDH, "2005-07-08 09:30"),
              P(DUCK, "2006-07-01 10:00"), P(DUCK, "2006-07-05 16:00"),
              P(WB, "2007-08-01 10:00"), P(WB, "2007-08-02 11:00")]
    plan = plan_for(finder, photos)
    assert folders(plan) == ["Outer Banks 2005", "Outer Banks 2006", "Wrightsville Beach 2007"]


def test_pass_one_names_a_spread_trip_by_its_area_and_a_town_trip_by_its_town(finder):
    """Alone, a trip in one town is named by the town; a spread trip by the smallest named area around it."""
    places = Places(finder=finder)
    one = g.Trip([P(DUCK, "2006-07-01 10:00"), P(DUCK, "2006-07-02 10:00")])
    two = g.Trip([P(KDH, "2005-07-01 10:00"), P(NAGS, "2005-07-02 10:00")])
    for t in (one, two):
        for p in t.photos:
            p.info = places.lookup(p.lat, p.lon, p.taken)
        g.name_trip(t)
    assert (one.name, one.kind) == ("Duck", "town")
    assert (two.name, two.kind) == ("Outer Banks", "named")


def test_trips_with_the_same_town_keep_it(finder):
    """Nags Head every year stays "Nags Head 2005", "Nags Head 2006": nothing to unify."""
    photos = [P(NAGS, "2005-07-02 10:00"), P(NAGS, "2006-07-02 10:00")]
    assert folders(plan_for(finder, photos)) == ["Nags Head 2005", "Nags Head 2006"]


def test_a_smaller_named_area_is_unified_into_the_larger_one(finder):
    """A trip on Hatteras (in the national seashore, outside the towns) and a trip to Kill Devil Hills and Nags Head
    are both "Outer Banks"."""
    photos = [P(HATTERAS, "2005-07-02 10:00"), P((35.31, -75.56), "2005-07-03 10:00"),
              P(KDH, "2006-07-02 10:00"), P(NAGS, "2006-07-03 10:00")]
    assert folders(plan_for(finder, photos)) == ["Outer Banks 2005", "Outer Banks 2006"]


def test_hatteras_alone_is_named_by_the_seashore(finder):
    """A trip outside any town, with no other trip there, is named by the smallest named area around it."""
    photos = [P(HATTERAS, "2005-07-02 10:00"), P((35.31, -75.56), "2005-07-03 10:00")]
    assert folders(plan_for(finder, photos)) == ["Cape Hatteras National Seashore 2005"]


def test_time_none_puts_every_year_together(finder):
    """Time None: one folder per area."""
    photos = [P(KDH, "2005-07-02 10:00"), P(NAGS, "2005-07-04 12:00"), P(DUCK, "2006-07-01 10:00")]
    plan = plan_for(finder, photos, time="none")
    assert folders(plan) == ["Outer Banks"] and len(plan.groups[0].photos) == 3


def test_time_trip_keeps_each_trip_with_its_dates(finder):
    """Time Trip: two trips to the same area in one year are two folders, told apart by their dates."""
    photos = [P(KDH, "2005-06-01 10:00"), P(NAGS, "2005-06-02 12:00"), P(KDH, "2005-08-10 10:00"),
              P(NAGS, "2005-08-12 10:00")]
    assert folders(plan_for(finder, photos, time="trip")) == ["Outer Banks 2005 (2005-06-01 to 2005-06-02)",
                                                              "Outer Banks 2005 (2005-08-10 to 2005-08-12)"]
    assert folders(plan_for(finder, photos, time="trip", template="{place} {dates}")) == \
        ["Outer Banks 2005-06-01 to 2005-06-02", "Outer Banks 2005-08-10 to 2005-08-12"]


@pytest.mark.parametrize("detail, expected", [
    ("place", ["Jockey's Ridge State Park 2005", "Kill Devil Hills 2005"]),
    ("town", ["Nags Head 2005", "Kill Devil Hills 2005"]),
    ("county", ["Dare County 2005"]),
    ("state", ["North Carolina 2005"]),
    ("country", ["United States 2005"]),
])
def test_other_place_details(finder, detail, expected):
    """Place, town, county, state and country (a photo outside any place falls back to its town)."""
    photos = [P(JOCKEYS, "2005-07-02 10:00"), P(KDH, "2005-07-03 10:00")]
    assert folders(plan_for(finder, photos, detail=detail)) == expected


def test_year_and_month(finder):
    """Time Year and month with the template "{year}-{month} {place}"."""
    photos = [P(KDH, "2005-07-30 10:00"), P(KDH, "2005-08-01 10:00")]
    assert folders(plan_for(finder, photos, detail="town", time="month", template="{year}-{month} {place}")) == \
        ["2005-07 Kill Devil Hills", "2005-08 Kill Devil Hills"]


# ---------------------------------------------------------------- locations

def test_guessing_by_time_marks_probably(finder):
    """A photo without GPS taken an hour after one with GPS gets its place, marked probably; one taken the next day,
    or with only a file date, is not guessed."""
    a = P(KDH, "2005-07-02 10:00", "a.jpg")
    b = P(None, "2005-07-02 11:00", "b.jpg")
    c = P(None, "2005-07-03 11:00", "c.jpg")
    d = P(None, "2005-07-02 10:30", "d.jpg")
    d.date_source = "file date"
    plan = plan_for(finder, [a, b, c, d], unknown="guess", detail="town")
    assert folders(plan) == ["Kill Devil Hills 2005"]
    assert plan.groups[0].photos == [a, b] and b.probably and b.guessed_from == "a.jpg"
    assert "1 probably" in plan.groups[0].describe()
    assert [p.path for p, _ in plan.left] == ["c.jpg", "d.jpg"]


def test_unknown_place_folder_or_leave(finder):
    """Photos without a location go to "Unknown place", or stay where they are."""
    photos = [P(KDH, "2005-07-02 10:00"), P(None, "2005-07-02 11:00", "n.jpg"), P((10.0, 10.0), "2005-07-02 12:00",
                                                                                   "nowhere.jpg")]
    plan = plan_for(finder, photos, unknown="unknown")
    assert folders(plan) == ["Kill Devil Hills 2005", "Unknown place"]
    assert {p.path for p in plan.groups[1].photos} == {"n.jpg", "nowhere.jpg"}
    plan = plan_for(finder, photos, unknown="leave")
    assert folders(plan) == ["Kill Devil Hills 2005"]
    assert dict((p.path, r) for p, r in plan.left) == {"n.jpg": "no location in it",
                                                       "nowhere.jpg": "no place name was found for its position"}


def test_my_places_come_first(finder):
    """A photo within 200 m of "Grandma's house" is named by it, at the trip area and town details."""
    places = Places(finder=finder, my_places=mp.MyPlaces([mp.MyPlace("Grandma's house", 34.2101, -77.8001)]))
    photos = [P(WB, "2007-08-01 10:00"), P(WB, "2007-08-01 12:00"), P(KDH, "2008-07-01 10:00")]
    for detail in ("trip-area", "town"):
        plan = g.make_plan("/album", photos, places, g.options(detail=detail))
        assert folders(plan) == ["Grandma's house 2007", "Kill Devil Hills 2008"]
        assert "My places" in plan.groups[0].describe()
    plan = g.make_plan("/album", photos, places, g.options(detail="county"))
    assert folders(plan)[0] == "New Hanover County 2007"


def test_water_and_air(finder):
    """Off a coast and over an ocean come from the finder's water layer."""
    photos = [P((41.32, -70.6), "2010-07-01 10:00"), P((30.0, -140.0), "2011-01-01 10:00")]
    assert folders(plan_for(finder, photos)) == ["Off Martha's Vineyard 2010", "Over the Pacific Ocean 2011"]


def test_admin_areas_are_sorted_into_levels():
    """placepacks' "admin" areas become the town, county or state by name and size; others are not used."""
    info = PlaceInfo(town="Kill Devil Hills", state="North Carolina",
                     areas=[Area("Kill Devil Hills", "admin", 4e7), Area("Atlantic Township", "admin", 1e8),
                            Area("Dare County", "admin", 7e9), Area("North Carolina", "admin", 1.3e11)])
    resolve_admin(info)
    assert [a.level for a in info.areas] == ["town", "skip", "county", "state"]
    info = PlaceInfo(state="Ontario", areas=[Area("Some Township", "admin", 3e8), Area("Big Area", "admin", 9e8)])
    resolve_admin(info)
    assert [a.level for a in info.areas] == ["skip", "county"]


def test_info_from_an_older_placepacks_without_areas():
    """Without areas_at, the Result's own named area, town, region and country are used."""
    from pli.places import FakeResult
    info = info_from_result(FakeResult(kind="place", name="Outer Banks", cls="region", town="Duck",
                                       region="North Carolina", country="United States"))
    assert [a.name for a in info.areas] == ["Outer Banks", "Duck"]
    assert (info.town, info.state, info.name_at("county")) == ("Duck", "North Carolina", "North Carolina")


# ---------------------------------------------------------------- templates

@pytest.mark.parametrize("template, expected", [
    ("{place} {year}", "Outer Banks 2005"),
    ("{year}\\{place}", "2005\\Outer Banks"),
    ("{place}/{year}", "Outer Banks\\2005"),
    ("{year}-{month} {place}", "2005-07 Outer Banks"),
    ("{place} - {monthname} {year}", "Outer Banks - July 2005"),
    ("{place}: {state}?", "Outer Banks North Carolina"),
    ("{unknown} {place}", "Outer Banks"),
])
def test_templates(template, expected):
    """Templates make folder names (unknown tokens dropped, Windows characters cleaned, \\ or / nest)."""
    grp = g.Group("Outer Banks")
    p = P(KDH, "2005-07-02 10:00")
    p.info = PlaceInfo(town="Kill Devil Hills", state="North Carolina")
    grp.photos = [p]
    assert g.render(template, grp, "month") == expected


def test_template_without_the_time_gets_it_added(finder):
    """"{place}" with Time Year would put two years in one name: the year is added to keep them apart."""
    photos = [P(NAGS, "2005-07-02 10:00"), P(NAGS, "2006-07-02 10:00")]
    assert folders(plan_for(finder, photos, template="{place}")) == ["Nags Head 2005", "Nags Head 2006"]
    assert folders(plan_for(finder, photos, template="{place}", time="none")) == ["Nags Head"]


def test_time_none_drops_the_year_from_the_template():
    """{year} is empty with Time None, and the separators around it go too."""
    grp = g.Group("Outer Banks")
    grp.photos = [P(KDH, "2005-07-02 10:00")]
    assert g.render("{year}\\{place}", grp, "none") == "Outer Banks"
    assert g.render("{place} - {year}", grp, "none") == "Outer Banks"


def test_clean_names_and_examples():
    """Reserved and unsafe names are made safe; the preview shows examples."""
    assert g.clean_part("CON") == "_CON" and g.clean_part('a<b>c. ') == "a b c"
    assert g.preview_examples("{place} {year}") == ["Outer Banks 2005", "Outer Banks 2006", "Grandma's house 2007"]
    assert g.date_range_words(dt.datetime(2005, 6, 28), dt.datetime(2005, 7, 3)) == "28 June to 3 July 2005"


def test_review_rename_and_merge(finder):
    """The review's Rename cleans the name; Merge puts one folder's photos into another."""
    photos = [P(NAGS, "2005-07-02 10:00"), P(DUCK, "2006-07-02 10:00"), P(WB, "2007-07-02 10:00")]
    plan = plan_for(finder, photos, detail="town")
    assert folders(plan) == ["Nags Head 2005", "Duck 2006", "Wrightsville Beach 2007"]
    plan.rename(plan.groups[0], "Beach week: 2005")
    plan.merge(plan.groups[0], plan.groups[1])
    assert folders(plan) == ["Beach week 2005", "Wrightsville Beach 2007"]
    assert len(plan.groups[0].photos) == 2
    with pytest.raises(ValueError):
        plan.rename(plan.groups[0], "  ?? ")


def test_bad_options():
    """Choices that do not exist are refused."""
    with pytest.raises(ValueError):
        g.options(detail="street")
    with pytest.raises(ValueError):
        g.options(time="decade")
