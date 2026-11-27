"""Business contact details (phone, website, opening hours) from the business-directory sources, made small and
safe before they go into the businesses part (FORMAT.md, "Business contact details").

Only these sources may give them (CONTACT_SOURCES): All The Places (the chains' own store locators), the chain
stores this project reads itself from big chains' store locators (chain-locators, placepacks/chains), the
government sources of public offices and sites (GOVERNMENT_SOURCES: Social Security offices, the Forest Service's
and the National Park Service's sites, Recreation.gov's facilities, placepacks/gov_details.py; cities' and counties'
public places, placepacks/directories/city_facilities.py), Overture's places
and Foursquare's Open Source Places, then the local directories this project reads itself (DIRECTORY_SOURCES:
tourism boards' Simpleview and Tempest listings, chambers of commerce's ChamberMaster directories and Hotfrog's
business listings, placepacks/directories) and, last, the two "details only" sources that add nothing but details to businesses already in the packs
(DETAIL_ONLY_SOURCES: the business's own homepage, and Yellow Pages lookups; placepacks/details.py). The licence
and inspection lists never do: their phone numbers are often an owner's personal number. PackWriter.add_point
ignores contact details from any other source.

What is kept, and how it is cleaned:
  - phone: the first number only, without "tel:" and without an extension; 7 to 15 digits; a North American number
    is written "802-555-0100" (Overture's "+18025550100" would be read aloud as one huge number); other numbers
    keep their own spacing. Anything with "@" in it is not a phone number and is dropped.
  - website: the first address only, http or https only, at most 200 characters, without a "#" part; an address
    with a tracking query (utm_..., fbclid, gclid and the like) loses just those parts; a social-media page is dropped (socials are
    not kept) or an address with a user name or password in it.
  - opening_hours: All The Places, chain-locators, the government sources, the Simpleview listings and the two
    details-only sources only (HOURS_SOURCES), in OpenStreetMap's syntax ("Mo-Fr 08:00-18:00"), at most 255
    characters.
  - never an e-mail address, and nothing at all for a place whose name looks like a person's ("Alice Example";
    a chain's own brand, such as "Burger King", is not taken for a person's name) or
    whose type is an individual's own office (an insurance or estate agent, a lawyer, a financial adviser, an
    accountant): those are a person's details, not a business's.
Only the Python standard library is used.
"""

import re
import urllib.parse

# Government sources whose offices' and sites' phone, website and hours are kept (placepacks/gov_details.py): the
# public numbers and hours of Social Security offices, Forest Service and National Park Service sites,
# Recreation.gov's facilities, and cities' and counties' own public places. They are public offices, so the
# person-name and personal-office checks below do not apply to them (a campground called "Lost Lake Campground"
# looks like a person's name to PERSON_NAME).
GOVERNMENT_SOURCES = ("ssa-field-offices", "nps-places", "usfs-recreation-sites", "ridb-recreation",
                      "city-facilities")
# Schools, colleges and the sites of the campus map platforms (27 November 2026): public and private schools'
# and colleges' own phone numbers and websites from the NCES directories (placepacks/schools.py), and the
# organisations' details from their campus maps and GIS layers (placepacks/mapvendors). Institutions, not people:
# like the government sources, the person-name check does not apply ("Mary Lee Elementary" is a school), and
# opening hours are kept. Also the malls' and airports' own details from their directories (placepacks/indoor:
# "Christiana Mall" is a mall, not a person).
# Since queue item Q4: Amtrak stations' accessibility and hours and the transit agencies' stations
# (placepacks/street_access), the GTFS stops' wheelchair boarding (placepacks/readers/gtfs_stations.py) and museums'
# accessibility (placepacks/museum_access.py): stations and museums, not people.
INSTITUTION_SOURCES = ("nces-details", "map-vendors", "mall-directories", "airport-directories", "street-access",
                       "gtfs-station-features", "museum-access")
# Hospitals' and clinics' accessibility details from health insurers' public provider directories and hospitals'
# own pages (placepacks/health_access): an organisation's phone and hours, but the person-name and personal-office
# checks DO apply (a practice listed under a doctor's own name gets nothing).
HEALTH_SOURCES = ("health-access", "health-access-businesses")
# The sources whose phone, website and hours are kept, best first (the order a lookup prefers when several sources
# list the same business; OpenStreetMap's own svc_details come before all of them).
# The local directories read by placepacks/directories (tourism boards' Simpleview and Tempest listings, chambers of
# commerce's ChamberMaster directories, Hotfrog's listings): new places of their own, and details for the places
# they match.
DIRECTORY_SOURCES = ("simpleview-listings", "tempest-listings", "chambermaster-listings", "hotfrog-listings")
# Sources that give only details (phone, website, hours) to businesses already in the packs, by their key: the
# business's own homepage (schema.org data) and Yellow Pages lookups. Last of all: they only fill what the
# business's own sources lack (PackWriter.fill_details).
DETAIL_ONLY_SOURCES = ("business-websites", "yp-lookups")
# The stores and restaurants inside malls and airports that have their own phone or hours, read from the malls' and
# airports' own directories (placepacks/indoor): new places of their own in the businesses part (the person-name
# and personal-office checks apply).
INDOOR_SOURCES = ("mall-directories-businesses", "airport-directories-businesses")
CONTACT_SOURCES = (("alltheplaces", "chain-locators") + GOVERNMENT_SOURCES + INSTITUTION_SOURCES + HEALTH_SOURCES
                   + ("overture-places", "fsq-places") + DIRECTORY_SOURCES + INDOOR_SOURCES + DETAIL_ONLY_SOURCES)
# The sources whose opening hours are kept (the chains' own store locators, the government sources, the tourism
# boards' listings and the details-only sources, in OpenStreetMap's syntax).
HOURS_SOURCES = (("alltheplaces", "chain-locators") + GOVERNMENT_SOURCES + INSTITUTION_SOURCES + HEALTH_SOURCES
                 + ("simpleview-listings",) + INDOOR_SOURCES + DETAIL_ONLY_SOURCES)
CONTACT_FIELDS = ("phone", "website", "opening_hours")

# A name that is a person's: "Alice Example", "Jane Q. Doe Jr." -- the shape of a name AND a known first name
# (placepacks/person.py; "Golden Corral" or "Muddy Waters" are not people). Also used for All The Places.
from placepacks.person import PERSON as PERSON_NAME  # noqa: E402
# Fine types that are an individual's own office (as fetch.ATP_PERSONAL, in the words of Overture and Foursquare).
PERSONAL_TYPES = re.compile(r"insurance|estate agent|real estate|realtor|lawyer|attorney|law office|legal service|"
                            r"financial advis|financial planner|tax advis|tax prepar|accountant|notary", re.I)
# Query keys that only follow who clicked: an address carrying one is dropped.
TRACKING = re.compile(r"^(utm_\w*|fbclid|gclid|dclid|gbraid|wbraid|msclkid|mc_cid|mc_eid|yclid|igshid|_ga|_gl|"
                      r"y_source|ref_src|srsltid|cmpid|affiliate|aff_id)$", re.I)
# Social-media pages: socials are not kept.
SOCIAL = re.compile(r"(^|\.)(facebook|fb|instagram|twitter|x|tiktok|linkedin|pinterest|youtube|yelp|snapchat|"
                    r"threads)\.com$|(^|\.)fb\.me$|(^|\.)wa\.me$", re.I)
NANP = re.compile(r"^(?:\+?1[\s.-]?)?\(?([2-9]\d\d)\)?[\s.-]?([2-9]\d\d)[\s.-]?(\d{4})$")
MAX_URL, MAX_HOURS = 200, 255


def is_brand_name(name, brand):
    """True when a place's name is its chain's brand ("Burger King", or "Taco Bell Cantina" for the brand "Taco
    Bell"): a chain's brand is not a person's name, even when it looks like one (two capitalised words)."""
    name, brand = " ".join((name or "").split()).lower(), " ".join((brand or "").split()).lower()
    return bool(brand) and (name == brand or name.startswith(brand + " "))


def allowed(source, name, kind=None, brand=None):
    """True when a record may carry contact details: a business-directory source (CONTACT_SOURCES), a name that is
    not a person's (a chain's own brand never counts as one: is_brand_name), and a type that is not an individual's
    own office."""
    if source not in CONTACT_SOURCES:
        return False
    if source in GOVERNMENT_SOURCES or source in INSTITUTION_SOURCES:
        return True                     # a public office, a school or a campus, never a person's details
    if PERSON_NAME.match((name or "").strip()) and not is_brand_name(name, brand):
        return False
    return not (kind and PERSONAL_TYPES.search(kind))


def first_of(value, commas=False):
    """The first text of a value that may be a list (Overture's phones and websites) or "a; b" text (commas: "a, b"
    too, for phone numbers; a web address may hold a comma)."""
    if isinstance(value, (list, tuple)):
        value = next((v for v in value if v and str(v).strip()), "")
    text = str(value or "").strip()
    split = r"\s*[;,|]\s*|\s+or\s+" if commas else r"\s*[;|]\s*|\s+or\s+|\s+"
    return re.split(split, text)[0].strip() if text else ""


def phone(value):
    """A phone number made plain (see the module docstring), or ""."""
    text = first_of(value, commas=True)
    if not text or "@" in text:
        return ""
    text = re.sub(r"^(tel|phone|ph)\s*[:.]?\s*", "", text, flags=re.I)
    text = re.split(r"\s*(?:ext\.?|extension|x|#)\s*\d+\s*$", text, flags=re.I)[0]
    if re.search(r"[^\d\s()+./-]", text):
        return ""                                       # letters or other signs: not a number we can trust
    text = " ".join(text.split()).strip(" -./")
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        return ""
    m = NANP.match(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return text


def phone_digits(text):
    """The digits of a phone number, for telling two writings of one number apart ("+1 802-555-0100" and
    "(802) 555-0100" are the same: the last 10 digits of a North American number)."""
    digits = re.sub(r"\D", "", text or "")
    return digits[-10:] if len(digits) == 11 and digits.startswith("1") else digits


def website(value):
    """A web address made plain (see the module docstring), or ""."""
    text = first_of(value)
    if not text or len(text) > MAX_URL * 2:
        return ""
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    host = parts.hostname.lower()
    if SOCIAL.search(host) or "." not in host:
        return ""
    # Tracking parts of the address (utm_..., fbclid ...) are taken out; the rest of the address is kept.
    query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                                    if not TRACKING.match(k)])
    netloc = host + (f":{parts.port}" if parts.port else "")
    path = parts.path if parts.path not in ("", "/") else ""
    url = urllib.parse.urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    if "@" in url or len(url) > MAX_URL or any(c.isspace() for c in url):
        return ""
    return url


def hours(value):
    """Opening hours in OpenStreetMap's syntax, trimmed, or "" (text without a time, a day or "24/7" is not
    hours)."""
    text = " ".join(str(value or "").split())
    if not text or len(text) > MAX_HOURS or "@" in text or "http" in text.lower():
        return ""
    if not re.search(r"\d|24/7|\b(Mo|Tu|We|Th|Fr|Sa|Su|PH|off|closed)\b", text, re.I):
        return ""
    return text


def clean(source, name, kind=None, phone_value=None, website_value=None, hours_value=None, brand=None):
    """{"phone", "website", "opening_hours"} made plain for a record (only the fields that have a value), or {}
    when the record may not carry contact details (allowed; brand: the chain's brand name, if any). Opening hours
    are kept from HOURS_SOURCES only."""
    if not allowed(source, name, kind, brand):
        return {}
    out = {"phone": phone(phone_value), "website": website(website_value),
           "opening_hours": hours(hours_value) if source in HOURS_SOURCES else ""}
    return {k: v for k, v in out.items() if v}
