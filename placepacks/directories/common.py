"""What the local-directory collectors share (placepacks/directories): the privacy filters, name and address
matching, robots.txt, and the category words that give a listing its OpenStreetMap-style tags (so the pack build
gives it a class and a fine type, as for the chain stores).

Privacy (the owner's rules of 26 November 2026, notes/helper-rules.txt): keep only facts about a business (its
name, street address, position, phone, website, opening hours, category, accessibility notes). Never an e-mail
address, a contact or representative's name, a description, a photo, a review or a rating. A one-person or home
business is left out (home_business): no street address, a post office box only, a name that is a person's, or a
category such as "Individuals" or "home-based".
Only the Python standard library is used.
"""

import difflib
import re
import urllib.robotparser

from placepacks.contact import PERSON_NAME, PERSONAL_TYPES, phone_digits
from placepacks.geocode import NO_HOUSE, split_address

# Category words of a one-person or home business, or of members who are people, not businesses.
HOME_CATEGORIES = re.compile(r"\b(individuals?|home[- ]based|home business|in[- ]home|mobile service|retirees?|"
                             r"friends of the chamber|government[- ]education[- ]individuals)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
# Words that do not tell two businesses apart ("The Corner Cafe, LLC" and "Corner Cafe").
_FILLER = {"the", "a", "an", "and", "of", "inc", "llc", "ltd", "co", "corp", "corporation", "company", "pllc", "pc",
           "dba", "lp", "llp"}


def no_email(text):
    """Text with every e-mail address taken out."""
    return " ".join(EMAIL.sub("", str(text or "")).split())


def person_name(name):
    """True when a business name is a person's ("Alice Example", "Jane Q. Doe Jr."): such a listing is left out,
    as its details would be a person's."""
    return bool(PERSON_NAME.match(" ".join(str(name or "").split())))


def home_business(name, street, category=""):
    """True when a listing is a one-person or home business (see the module docstring): no street address or one
    without a house number (a post office box, a rural route), a person's name as the business name, a category
    of individuals or home-based work, or an individual's own office (an insurance or estate agent, a lawyer, an
    accountant: placepacks/contact.py PERSONAL_TYPES)."""
    line = " ".join(str(street or "").split())
    if not line or NO_HOUSE.match(re.sub(r"[.,]", " ", line.upper()).strip()) or not split_address(line):
        return True
    if person_name(name):
        return True
    return bool(category and (HOME_CATEGORIES.search(category) or PERSONAL_TYPES.search(category)))


def plain_name(name):
    """A business name made plain for comparing: lower case, "&" as "and", no punctuation, no filler words."""
    text = str(name or "").lower().replace("&", " and ").replace("'", "")
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", text).split() if w not in _FILLER]
    return " ".join(words)


def name_similarity(a, b):
    """How alike two business names are, 0 to 1: the better of the letters' likeness and the words' overlap
    ("Joe's Diner" and "Joes Diner" 1.0; "Corner Cafe" and "The Corner Cafe LLC" 1.0; "Main Street Pizza" and
    "Main Street Hardware" well under 0.85)."""
    x, y = plain_name(a), plain_name(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    letters = difflib.SequenceMatcher(None, x, y).ratio()
    wx, wy = set(x.split()), set(y.split())
    words = len(wx & wy) / max(len(wx), len(wy))
    return max(letters, words)


def same_street_address(a, b):
    """True when two street address lines are the same house on the same street, written either way ("184 Main
    Street" and "184 MAIN ST, Suite 2")."""
    x, y = split_address(a), split_address(b)
    return bool(x and y and x == y)


def same_phone(a, b):
    """True when two phone numbers are the same number (the last 10 digits of a North American one)."""
    x, y = phone_digits(a), phone_digits(b)
    return bool(x and len(x) >= 10 and x == y)


class Robots:
    """A site's robots.txt, read once through a polite client and kept: allowed(url) for our User-Agent;
    crawl_delay(); sitemaps(); text (as read, for the record); base (the site's address). A robots.txt that
    cannot be read (404) allows everything, as the standard says; a refusal (403, a challenge page) is raised (the
    site is blocked)."""

    def __init__(self, client, base, agent="place-packs"):
        """Read base + "/robots.txt" with client (placepacks.chains.polite.Polite)."""
        from placepacks.chains.polite import NotFound, RequestFailed
        self.agent, self.text, self.base = agent, "", base.rstrip("/")
        try:
            self.text = client.fetch(base.rstrip("/") + "/robots.txt")
        except (NotFound, RequestFailed):
            self.text = ""
        self.parser = urllib.robotparser.RobotFileParser()
        self.parser.parse(self.text.splitlines())

    def allowed(self, url):
        """True when robots.txt lets our User-Agent read url."""
        return self.parser.can_fetch(self.agent, url)

    def crawl_delay(self):
        """The Crawl-delay robots.txt asks of us, in seconds, or None."""
        try:
            value = self.parser.crawl_delay(self.agent)
        except (AttributeError, ValueError):
            return None
        return float(value) if value else None

    def sitemaps(self):
        """The Sitemap: lines of robots.txt."""
        return re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", self.text)


# Category words -> OpenStreetMap-style tags (the first that matches wins; the pack build's types.json turns the
# tags into a fine type such as "restaurant" or "hotel"). Kept short: a category that matches none keeps its own
# words as the fine type (tags_of).
CATEGORY_TAGS = [
    (r"coffee|espresso|cafe|café", {"amenity": "cafe"}),
    (r"brew(ery|eries|pub)|craft beer", {"craft": "brewery"}),
    (r"winer(y|ies)|vineyard", {"craft": "winery"}),
    (r"distiller", {"craft": "distillery"}),
    (r"\bbars?\b|pubs?\b|tavern|nightlife|night club|lounge|cocktail", {"amenity": "bar"}),
    (r"bakery|bakeries", {"shop": "bakery"}),
    (r"ice cream|frozen yogurt|dessert", {"amenity": "ice_cream"}),
    (r"pizza", {"amenity": "restaurant", "cuisine": "pizza"}),
    (r"restaurant|dining|food|\beat(s|ing|eries|ery)?\b|grill|diner|bistro|barbecue|bbq|seafood|steak|catering",
     {"amenity": "restaurant"}),
    (r"bed (and|&) breakfast|b&b", {"tourism": "guest_house"}),
    (r"campground|camping|rv park|rv resort", {"tourism": "camp_site"}),
    (r"hotel|motel|lodging|accommodation|\binns?\b|resort|vacation rental|cabin", {"tourism": "hotel"}),
    (r"museum|historic site|history", {"tourism": "museum"}),
    (r"galler(y|ies)|art center|arts center", {"tourism": "gallery"}),
    (r"\bzoos?\b|aquarium|wildlife park", {"tourism": "zoo"}),
    (r"theat(er|re)|performing arts|concert|music venue|amphitheat", {"amenity": "theatre"}),
    (r"cinema|movie", {"amenity": "cinema"}),
    (r"golf", {"leisure": "golf_course"}),
    (r"spa\b|spas\b|salon|barber|beauty|nail", {"shop": "beauty"}),
    (r"fitness|gym|yoga|health club", {"leisure": "fitness_centre"}),
    (r"bowling", {"leisure": "bowling_alley"}),
    (r"marina|boat", {"leisure": "marina"}),
    (r"park\b|parks\b|garden|nature|trail", {"leisure": "park"}),
    (r"visitor (center|centre|information)|welcome center", {"tourism": "information"}),
    (r"attraction|amusement|entertainment|family fun|\btours?\b", {"tourism": "attraction"}),
    (r"auto(motive)? (repair|service)|car repair|tire|oil change|body shop|collision", {"shop": "car_repair"}),
    (r"car dealer|auto dealer|automotive|automobile", {"shop": "car"}),
    (r"pharmac|drug store", {"amenity": "pharmacy"}),
    (r"dentist|dental", {"amenity": "dentist"}),
    (r"veterinar|animal hospital|pet care", {"amenity": "veterinary"}),
    (r"hospitals?\b", {"amenity": "hospital"}),          # not "Hospitality" (Louisville's business network)
    (r"health|medical|clinic|chiropract|optometr|physical therapy|urgent care", {"amenity": "clinic"}),
    (r"bank|credit union", {"amenity": "bank"}),
    (r"grocer|supermarket|\bmarkets?\b|\bdeli\b|delicatessen", {"shop": "supermarket"}),
    (r"florist|flower", {"shop": "florist"}),
    (r"hardware|home improvement|lumber", {"shop": "hardware"}),
    (r"\bbook(s|store|stores|shop|shops)?\b", {"shop": "books"}),
    (r"cloth|apparel|boutique|fashion", {"shop": "clothes"}),
    (r"jewel", {"shop": "jewelry"}),
    (r"furniture", {"shop": "furniture"}),
    (r"antique", {"shop": "antiques"}),
    (r"gift|souvenir", {"shop": "gift"}),
    (r"shop|store|retail|outlet|mall", {"shop": "yes"}),
    (r"library", {"amenity": "library"}),
    (r"child ?care|day ?care|preschool", {"amenity": "childcare"}),
    (r"school|college|university|education", {"amenity": "school"}),
    (r"church|worship|religious", {"amenity": "place_of_worship"}),
    (r"gas station|fuel|convenience", {"amenity": "fuel"}),
]
_COMPILED = [(re.compile(p, re.I), t) for p, t in CATEGORY_TAGS]


def tags_of(*categories):
    """The tags of a listing's categories (the first category that matches a rule wins), or {}."""
    for category in categories:
        for pattern, tags in _COMPILED:
            if category and pattern.search(category):
                return dict(tags)
    return {}
