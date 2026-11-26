"""Business contact details (phone, website, opening hours) from the business-directory sources, made small and
safe before they go into the businesses part (FORMAT.md, "Business contact details").

Only three sources may give them (CONTACT_SOURCES): All The Places (the chains' own store locators), Overture's
places and Foursquare's Open Source Places. The licence and inspection lists never do: their phone numbers are often
an owner's personal number. PackWriter.add_point ignores contact details from any other source.

What is kept, and how it is cleaned:
  - phone: the first number only, without "tel:" and without an extension; 7 to 15 digits; a North American number
    is written "802-555-0100" (Overture's "+18025550100" would be read aloud as one huge number); other numbers
    keep their own spacing. Anything with "@" in it is not a phone number and is dropped.
  - website: the first address only, http or https only, at most 200 characters, without a "#" part; an address
    with a tracking query (utm_..., fbclid, gclid and the like) is dropped, as is a social-media page (socials are
    not kept) or an address with a user name or password in it.
  - opening_hours: All The Places only, in OpenStreetMap's syntax ("Mo-Fr 08:00-18:00"), at most 255 characters.
  - never an e-mail address, and nothing at all for a place whose name looks like a person's ("Alice Example") or
    whose type is an individual's own office (an insurance or estate agent, a lawyer, a financial adviser, an
    accountant): those are a person's details, not a business's.
Only the Python standard library is used.
"""

import re
import urllib.parse

# The sources whose phone, website and hours are kept, best first (the order a lookup prefers when several sources
# list the same business; OpenStreetMap's own svc_details come before all of them).
CONTACT_SOURCES = ("alltheplaces", "overture-places", "fsq-places")
CONTACT_FIELDS = ("phone", "website", "opening_hours")

# A name that is a person's: "Alice Example", "Jane Q. Doe Jr." (as fetch._PERSON, used for All The Places).
PERSON_NAME = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.?)?(?: [A-Z][a-z'-]+){1,2}(?:,? (?:Jr|Sr|II|III)\.?)?$")
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


def allowed(source, name, kind=None):
    """True when a record may carry contact details: a business-directory source (CONTACT_SOURCES), a name that is
    not a person's, and a type that is not an individual's own office."""
    if source not in CONTACT_SOURCES:
        return False
    if PERSON_NAME.match((name or "").strip()):
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
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if any(TRACKING.match(k) for k, _ in query):
        return ""
    netloc = host + (f":{parts.port}" if parts.port else "")
    path = parts.path if parts.path not in ("", "/") else ""
    url = urllib.parse.urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))
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


def clean(source, name, kind=None, phone_value=None, website_value=None, hours_value=None):
    """{"phone", "website", "opening_hours"} made plain for a record (only the fields that have a value), or {}
    when the record may not carry contact details (allowed). Opening hours are kept from All The Places only."""
    if not allowed(source, name, kind):
        return {}
    out = {"phone": phone(phone_value), "website": website(website_value),
           "opening_hours": hours(hours_value) if source == "alltheplaces" else ""}
    return {k: v for k, v in out.items() if v}
