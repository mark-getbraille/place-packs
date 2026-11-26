"""Jack in the Box: the sitemap of locations.jackinthebox.com and the schema.org Restaurant on each store page, as
All The Places' jack_in_the_box spider does (github.com/alltheplaces/alltheplaces, MIT), which reached only 96
stores in its November 2026 run.

Checked 26 November 2026: the sitemap (one file, 2,981 addresses) lists 2,089 store pages; two pages read, both
with a Restaurant (position, telephone, address and hours; the JSON-LD has an extra "}" at its end, which
jsonld.loads forgives). robots.txt: "User-agent: *" with nothing disallowed.
"""

from placepacks.chains import pages

SITEMAP = "https://locations.jackinthebox.com/sitemap.xml"
PATTERN = r"^https://locations\.jackinthebox\.com/us/\w\w/[^/]+/[^/]+$"
TAGS = {"amenity": "fast_food", "cuisine": "burger"}


def ref(url, store):
    """The store's number: its page address after the host ("us/wa/olympia/520-plum-st-se"); the pages have no
    other stable number."""
    return url.split("jackinthebox.com/", 1)[-1].strip("/")


def collect(client, stats):
    """Yield the rows of every store page."""
    yield from pages.collect(client, "jack-in-the-box", [SITEMAP], PATTERN,
                             {"Restaurant", "FastFoodRestaurant", "LocalBusiness"}, TAGS, "Jack in the Box",
                             "Q1538507", ref, name="Jack in the Box", stats=stats)
