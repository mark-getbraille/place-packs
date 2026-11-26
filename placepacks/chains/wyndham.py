"""Wyndham's hotel brands in the US (Days Inn, Super 8, La Quinta, Baymont, Microtel, Travelodge, Ramada, Wingate
and the others): the brands' English (US) sitemaps of www.wyndhamhotels.com and each hotel's page, as All The
Places' wyndham spider does (github.com/alltheplaces/alltheplaces, MIT; brand list from it), which reached 725 of
about 6,000 US hotels in November 2026.

Each hotel page has a schema.org Hotel (name, telephone, address, its number in "identifier") but no position;
the position is in the page's own map settings ("latitude" and "longitude", HTML-escaped), read by position_of.
The sitemaps also list hotels outside the US: only addresses whose city part ends in a US state's name
("ocala-florida") are read.

Three collectors (one GitHub job each, so none runs for hours): Days Inn and Super 8; La Quinta, Baymont,
Microtel, Travelodge and Howard Johnson; the other brands.

Checked 26 November 2026: the sitemap index (29 English (US) brand sitemaps); the Days Inn sitemap has 1,174 US
hotels, Super 8 1,286 and La Quinta 855; one page read (Hotel JSON-LD, position in the map settings). robots.txt
has no rule against hotel pages.
"""

import html
import re

from placepacks.chains import pages

INDEX = "https://www.wyndhamhotels.com/content/wyndham.sitemap.{code}-en-us-sitemap.xml"
GROUPS = {
    "wyndham-days-inn-super-8": ["di", "se"],
    "wyndham-la-quinta-baymont": ["lq", "bu", "mt", "tl", "hj"],
    "wyndham-other": ["aa", "ra", "wg", "hr", "gn", "gr", "tq", "ww", "re", "dx", "wt"],
}
# The brand of each address's first part, with its Wikidata id (from All The Places' wyndham spider).
BRANDS = {
    "americinn": ("AmericInn", "Q4742493"), "baymont": ("Baymont", "Q4874634"), "days-inn": ("Days Inn", "Q1047239"),
    "dolce": ("Dolce Hotels and Resorts", "Q28402655"), "hawthorn-extended-stay": ("Hawthorn Suites", "Q5685511"),
    "hojo": ("Howard Johnson", "Q5919997"), "laquinta": ("La Quinta Inn", "Q6464734"),
    "microtel": ("Microtel Inn & Suites", "Q6840402"), "ramada": ("Ramada", "Q1502859"),
    "registry-collection": ("Registry Collection", ""), "super-8": ("Super 8", "Q5364003"),
    "trademark": ("Trademark Collection", "Q112144846"), "travelodge": ("Travelodge", "Q7836087"),
    "tryp": ("TRYP", "Q6153452"), "wingate": ("Wingate", "Q8025144"),
    "wyndham-garden": ("Wyndham Garden", "Q112144847"), "wyndham-grand": ("Wyndham Grand", "Q112144849"),
    "wyndham": ("Wyndham", "Q8040120"), "echo-suites": ("ECHO Suites", ""),
}
STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho "
          "illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota "
          "mississippi missouri montana nebraska nevada new-hampshire new-jersey new-mexico new-york north-carolina "
          "north-dakota ohio oklahoma oregon pennsylvania rhode-island south-carolina south-dakota tennessee texas "
          "utah vermont virginia washington west-virginia wisconsin wyoming district-of-columbia puerto-rico").split()
PATTERN = r"^https://www\.wyndhamhotels\.com/[-\w]+/[-\w]+/[-\w]+$"
_POSITION = re.compile(r'"latitude"\s*:\s*"?(-?\d{1,2}\.\d+)"?\s*,\s*"longitude"\s*:\s*"?(-?\d{1,3}\.\d+)')


def slug(url):
    """The brand part of a hotel address ("days-inn")."""
    return url.split("wyndhamhotels.com/", 1)[-1].split("/")[0]


def in_us(url):
    """True when the hotel address's city part ends in a US state's name ("ocala-florida")."""
    parts = url.split("wyndhamhotels.com/", 1)[-1].split("/")
    return len(parts) == 3 and any(parts[1].endswith("-" + s) for s in STATES)


def brand_of(url):
    """(brand, Wikidata id) of a hotel address; an unknown brand part is made readable ("new-brand": "New Brand")."""
    s = slug(url)
    return BRANDS.get(s) or (s.replace("-", " ").title(), "")


def tags_of(url):
    """Super 8 hotels are motels; the others hotels."""
    return {"tourism": "motel" if slug(url) == "super-8" else "hotel"}


def position_of(page, url, store):
    """The store with the position from the page's map settings (None when the page has none)."""
    m = _POSITION.search(html.unescape(page))
    if not m:
        return None
    store.update(lat=float(m.group(1)), lon=float(m.group(2)))
    return store


def ref(url, store):
    """The hotel's number: the Hotel JSON-LD's "identifier" ("00359"), else its address."""
    return store.get("identifier") or url.split("wyndhamhotels.com/", 1)[-1]


def collector(group):
    """The collect function of one group of brands (GROUPS)."""
    def collect(client, stats):
        """Yield the rows of the group's US hotels."""
        yield from pages.collect(client, group, [INDEX.format(code=c) for c in GROUPS[group]], PATTERN, {"Hotel"},
                                 tags_of, brand_of, "", ref, keep=in_us, fix=position_of, stats=stats,
                                 page_of=lambda u: u + "/overview")
    return collect
