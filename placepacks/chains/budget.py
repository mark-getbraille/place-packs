"""Budget (US car rental): the US sitemap of www.budget.com and the schema.org AutoRental on each location page.
All The Places has no Budget spider; this follows its avis spider (the same company and the same kind of pages).

Checked 26 November 2026: the sitemap index names all-us-locations.xml (2,761 addresses, 1,656 of them location
pages); one page read had an AutoRental with the address, the telephone (inside the address), the hours as text
("Sun - Sat 7:00 AM - 8:00 PM") and the position only in its map link ("?q=lat,lon"). robots.txt disallows
/association/ and /corporate/ only.
"""

from placepacks.chains import pages

SITEMAP = "https://www.budget.com/all-us-locations.xml"
PATTERN = r"^https://www\.budget\.com/en/locations/us/[a-z]{2}/[^/]+/[a-z0-9]{2,6}$"
TAGS = {"amenity": "car_rental"}


def ref(url, store):
    """The location code at the end of the address ("ktn")."""
    return url.rstrip("/").rsplit("/", 1)[-1].upper()


def collect(client, stats):
    """Yield the rows of every US location page."""
    yield from pages.collect(client, "budget", [SITEMAP], PATTERN, {"AutoRental"}, TAGS, "Budget", "Q1001437", ref,
                             name="Budget", stats=stats)
