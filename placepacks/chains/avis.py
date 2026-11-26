"""Avis (US car rental): the sitemap of www.avis.com and the schema.org AutoRental on each US location page, as
All The Places' avis spider does (github.com/alltheplaces/alltheplaces, MIT), which gave 66 US locations in its
November 2026 run.

Checked 26 November 2026: the sitemap (one file, 10,268 addresses) lists 1,918 US location pages
(/en/locations/nam/us/<state>/<city>/<code>); one page read had an AutoRental with position, telephone and
address (no hours); another location code now opens its city's page, which has no position, and is skipped.
robots.txt disallows /web/, /car-rental/, /content/avis/*.html and the corporate pages, not the location pages.
"""

from placepacks.chains import pages

SITEMAP = "https://www.avis.com/sitemap.xml"
PATTERN = r"^https://www\.avis\.com/en/locations/nam/us/[a-z]{2}/[^/]+/[a-z0-9]{2,6}$"
TAGS = {"amenity": "car_rental"}


def ref(url, store):
    """The location code at the end of the address ("dhn")."""
    return url.rstrip("/").rsplit("/", 1)[-1].upper()


def collect(client, stats):
    """Yield the rows of every US location page."""
    yield from pages.collect(client, "avis", [SITEMAP], PATTERN, {"AutoRental"}, TAGS, "Avis", "Q791136", ref,
                             name="Avis", stats=stats)
