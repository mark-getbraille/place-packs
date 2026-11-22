"""Fixes found by trying the Vermont packs (22 November 2026): mailboxes are not post offices, a church whose name
gives its denomination counts for that denomination, and the arrival line never says "on your ahead"."""

from placepacks import find


def test_mailboxes_are_not_post_offices():
    for name in ("USPS Collection Point", "USPS Collection Box", "Drop Box", "Blue Box"):
        assert find.NOT_A_POST_OFFICE.search(name), name
    for name in ("Post Office-Montpelier", "USPS", "East Montpelier Post Office"):
        assert not find.NOT_A_POST_OFFICE.search(name), name


def test_arrival_wording():
    import inspect
    from placepacks import route
    text = inspect.getsource(route)
    assert 'f"on your {side}" if side in ("left", "right")' in text and '"straight ahead"' in text
