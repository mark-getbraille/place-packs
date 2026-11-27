"""Tourism boards' visitor listings on the Simpleview platform (the source "simpleview-listings"; the monthly
simpleview-listings workflow).

What: state tourism offices and city tourism boards (destination marketing organisations) that run Simpleview list
the restaurants, shops, attractions, hotels and venues of their area. Research of 26 November 2026 (notes/
US-LOCAL-BUSINESS-DIRECTORIES.md) found 11 state sites on Simpleview that answered without a challenge (DE, FL, IN,
KS, NM, NY, PA, RI, TX, VA, WY) and tested Visit Denver; the city and county boards found on 27 November 2026 (76
more, CITY_SITES) were added after one robots.txt request each. SITES lists them all. The 20 state sites and the
city boards that answered with an anti-bot challenge or a plain 403 are not collected (BLOCKED, CITY_BLOCKED), and
never tried another way. The monthly workflow runs the sites in matrix groups (placepacks/directories/run.py).

How, per site (collect()):
  1. robots.txt (obeyed: every listing page is checked; its Crawl-delay is kept, at least 2 and at most 5 seconds
     between requests, PAUSE when it names none);
  2. the sitemap (robots.txt's Sitemap line, else /sitemap.xml; a sitemap index is followed into the sitemaps whose
     address names listings, or all of them): every "/listing/<name>/<number>/" page;
  3. each listing page: its schema.org JSON-LD (the LocalBusiness object: name, telephone, PostalAddress, geo) and
     the page's embedded listing data ("var data = {...}": recid, title, latitude, longitude, address1, phone,
     weburl, primaryCategory, and the amenity groups, of which only the hours and the accessibility fields are
     read). Never kept: the e-mail, the description, photos, social links, reviews, the booking links, the
     account's own fields.
A listing is left out when it has no street address (a tour operator or a home business: common.home_business), a
name that is a person's, or no position in the US. Its category gives its OpenStreetMap-style tags (common.tags_of)
and so its class and fine type in the packs; hours that read as OpenStreetMap syntax become its opening hours,
other hours text and the accessibility fields its note ("Hours: ...; Accessibility: ADA Accessible Rooms 5").

In the packs (businesses part): a new place, unless another business source already lists it, matched by the same
phone number within 500 m first, then the same name within 75 m (dedupe_phone, dedupe_m 75, dedupe_carry): then
the listing's phone, website, hours and note go to that place instead (PackWriter.drop_duplicates).
Only the Python standard library is used.
"""

import html
import re

from placepacks.chains import hours as oh
from placepacks.chains import jsonld
from placepacks.chains.base import FIELDS as CHAIN_FIELDS
from placepacks.chains.base import make_row
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.directories.common import Robots, home_business, no_email, tags_of

FIELDS = CHAIN_FIELDS + ["category", "note"]
USER_AGENT = "place-packs-simpleview/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
PAUSE = 3.0                     # seconds between requests when robots.txt names no Crawl-delay
MIN_PAUSE, MAX_PAUSE = 2.0, 5.0
LISTING = re.compile(r"/listing/[^/?#]+/(\d+)/?$")
_DATA = re.compile(r"var\s+data\s*=\s*")
HOURS_LABEL = re.compile(r"^(hours|hours of operation|operating hours|business hours|opening hours)$", re.I)
ACCESS_LABEL = re.compile(r"\bada\b|accessib|wheelchair|hearing loop|braille|service animal", re.I)


def _site(title, home, expected, timeout_min=300):
    """One entry of SITES: the site's name, its home address, about how many listings were seen, the job's time."""
    return {"title": title, "home": home, "expected": expected, "budget": int(expected * 1.5) + 200,
            "timeout": timeout_min}


# The sites (checked 26 November 2026: the platform seen on the homepage; listing numbers where the sitemap was read).
SITES = {
    "visitdelaware": _site("Visit Delaware", "https://www.visitdelaware.com", 800),
    "visitflorida": _site("Visit Florida", "https://www.visitflorida.com", 1725),
    "visitindiana": _site("Visit Indiana", "https://visitindiana.com", 1500),
    "travelks": _site("Travel Kansas", "https://www.travelks.com", 1500),
    "newmexico": _site("New Mexico True", "https://www.newmexico.org", 1500),
    "iloveny": _site("I LOVE NY", "https://www.iloveny.com", 2000),
    "visitpa": _site("Visit Pennsylvania", "https://www.visitpa.com", 2000),
    "visitrhodeisland": _site("Visit Rhode Island", "https://www.visitrhodeisland.com", 1000),
    "traveltexas": _site("Travel Texas", "https://www.traveltexas.com", 480),
    "virginia": _site("Virginia Is For Lovers", "https://www.virginia.org", 2000),
    "travelwyoming": _site("Travel Wyoming", "https://travelwyoming.com", 1000),
    "visitdenver": _site("Visit Denver", "https://visitdenver.com", 1833),
}
# City and county tourism boards found on Simpleview (27 November 2026): one robots.txt request each, whose
# "Disallow: /plugins/crm/count/" line is Simpleview's own; candidates from the boards named by Simpleview's
# customer pages and the "Visit <city>" boards of the 200 largest US cities and main tourist towns (Destinations
# International's member list answered with a Cloudflare challenge, and Wikipedia/Wikidata with "too many requests",
# so neither was used). id, title, home, state, about how many listings (1000, or 2000 for a big destination).
CITY_SITES = [
    ('visithoustontexas', 'Houston, TX tourism board (visithoustontexas.com)', 'https://www.visithoustontexas.com', 'TX', 2000),
    ('fortworth', 'Fort Worth, TX tourism board (fortworth.com)', 'https://www.fortworth.com', 'TX', 2000),
    ('visitsanantonio', 'San Antonio, TX tourism board (visitsanantonio.com)', 'https://www.visitsanantonio.com', 'TX', 2000),
    ('visitaustin', 'Austin, TX tourism board (visitaustin.org)', 'https://www.austintexas.org', 'TX', 2000),
    ('visitphoenix', 'Phoenix, AZ tourism board (visitphoenix.com)', 'https://www.visitphoenix.com', 'AZ', 2000),
    ('visittucson', 'Tucson, AZ tourism board (visittucson.org)', 'https://www.visittucson.org', 'AZ', 2000),
    ('visitalbuquerque', 'Albuquerque, NM tourism board (visitalbuquerque.org)', 'https://www.visitalbuquerque.org', 'NM', 2000),
    ('visitsaltlake', 'Salt Lake City, UT tourism board (visitsaltlake.com)', 'https://www.visitsaltlake.com', 'UT', 2000),
    ('visitoakland', 'Oakland, CA tourism board (visitoakland.com)', 'https://www.visitoakland.com', 'CA', 2000),
    ('visitsacramento', 'Sacramento, CA tourism board (visitsacramento.com)', 'https://www.visitsacramento.com', 'CA', 2000),
    ('visitanaheim', 'Anaheim, CA tourism board (visitanaheim.org)', 'https://www.visitanaheim.org', 'CA', 2000),
    ('visitlasvegas', 'Las Vegas, NV tourism board (visitlasvegas.com)', 'https://www.visitlasvegas.com', 'NV', 2000),
    ('traveltacoma', 'Tacoma, WA tourism board (traveltacoma.com)', 'https://www.visitpiercecounty.com', 'WA', 1000),
    ('experiencecolumbus', 'Columbus, OH tourism board (experiencecolumbus.com)', 'https://www.experiencecolumbus.com', 'OH', 2000),
    ('cincinnatiusa', 'Cincinnati, OH tourism board (cincinnatiusa.com)', 'https://www.visitcincy.com', 'OH', 2000),
    ('experiencegr', 'Grand Rapids, MI tourism board (experiencegr.com)', 'https://www.experiencegr.com', 'MI', 1000),
    ('visitmilwaukee', 'Milwaukee, WI tourism board (visitmilwaukee.org)', 'https://www.visitmilwaukee.org', 'WI', 2000),
    ('catchdesmoines', 'Des Moines, IA tourism board (catchdesmoines.com)', 'https://www.catchdesmoines.com', 'IA', 1000),
    ('visitomaha', 'Omaha, NE tourism board (visitomaha.com)', 'https://www.visitomaha.com', 'NE', 2000),
    ('visitwichita', 'Wichita, KS tourism board (visitwichita.com)', 'https://www.visitwichita.com', 'KS', 1000),
    ('visittulsa', 'Tulsa, OK tourism board (visittulsa.com)', 'https://www.visittulsa.com', 'OK', 2000),
    ('visitokc', 'Oklahoma City, OK tourism board (visitokc.com)', 'https://www.visitokc.com', 'OK', 2000),
    ('visitknoxville', 'Knoxville, TN tourism board (visitknoxville.com)', 'https://www.visitknoxville.com', 'TN', 1000),
    ('chattanoogafun', 'Chattanooga, TN tourism board (chattanoogafun.com)', 'https://www.visitchattanooga.com', 'TN', 1000),
    ('visitlex', 'Lexington, KY tourism board (visitlex.com)', 'https://www.visitlex.com', 'KY', 1000),
    ('neworleans', 'New Orleans, LA tourism board (neworleans.com)', 'https://www.neworleans.com', 'LA', 2000),
    ('visitorlando', 'Orlando, FL tourism board (visitorlando.com)', 'https://www.visitorlando.com', 'FL', 2000),
    ('visittampabay', 'Tampa, FL tourism board (visittampabay.com)', 'https://www.visittampabay.com', 'FL', 2000),
    ('visitlauderdale', 'Fort Lauderdale, FL tourism board (visitlauderdale.com)', 'https://www.visitlauderdale.com', 'FL', 1000),
    ('visitraleigh', 'Raleigh, NC tourism board (visitraleigh.com)', 'https://www.visitraleigh.com', 'NC', 1000),
    ('experiencecolumbiasc', 'Columbia, SC tourism board (experiencecolumbiasc.com)', 'https://www.experiencecolumbiasc.com', 'SC', 1000),
    ('visitgreenvillesc', 'Greenville, SC tourism board (visitgreenvillesc.com)', 'https://www.visitgreenvillesc.com', 'SC', 1000),
    ('visitrichmondva', 'Richmond, VA tourism board (visitrichmondva.com)', 'https://www.visitrichmondva.com', 'VA', 1000),
    ('visitrochester', 'Rochester, NY tourism board (visitrochester.com)', 'https://www.visitrochester.com', 'NY', 1000),
    ('bostonusa', 'Boston, MA tourism board (bostonusa.com)', 'https://www.meetboston.com', 'MA', 1000),
    ('discovernewport', 'Newport, RI tourism board (discovernewport.org)', 'https://www.discovernewport.org', 'RI', 1000),
    ('visitwilmingtonde', 'Wilmington, DE tourism board (visitwilmingtonde.com)', 'https://www.visitwilmingtonde.com', 'DE', 1000),
    ('visithersheyharrisburg', 'Hershey, PA tourism board (visithersheyharrisburg.org)', 'https://www.visithersheyharrisburg.org', 'PA', 1000),
    ('visitbloomington', 'Bloomington, IN tourism board (visitbloomington.com)', 'https://www.visitbloomington.com', 'IN', 1000),
    ('visitfortwayne', 'Fort Wayne, IN tourism board (visitfortwayne.com)', 'https://www.visitfortwayne.com', 'IN', 1000),
    ('visitevansville', 'Evansville, IN tourism board (visitevansville.com)', 'https://www.exploreevansville.com', 'IN', 1000),
    ('visitmadison', 'Madison, WI tourism board (visitmadison.com)', 'https://www.visitmadison.com', 'WI', 1000),
    ('greenbay', 'Green Bay, WI tourism board (greenbay.com)', 'https://www.greenbay.com', 'WI', 1000),
    ('experiencerochestermn', 'Rochester, MN tourism board (experiencerochestermn.com)', 'https://www.experiencerochestermn.com', 'MN', 1000),
    ('visitcheyenne', 'Cheyenne, WY tourism board (visitcheyenne.org)', 'https://www.cheyenne.org', 'WY', 1000),
    ('visitftcollins', 'Fort Collins, CO tourism board (visitftcollins.com)', 'https://www.visitftcollins.com', 'CO', 1000),
    ('bouldercoloradousa', 'Boulder, CO tourism board (bouldercoloradousa.com)', 'https://www.bouldercoloradousa.com', 'CO', 1000),
    ('santafe', 'Santa Fe, NM tourism board (santafe.org)', 'https://www.santafe.org', 'NM', 1000),
    ('visitlascruces', 'Las Cruces, NM tourism board (visitlascruces.com)', 'https://www.visitlascruces.com', 'NM', 1000),
    ('visitamarillo', 'Amarillo, TX tourism board (visitamarillo.com)', 'https://www.visitamarillo.com', 'TX', 1000),
    ('visitcorpuschristi', 'Corpus Christi, TX tourism board (visitcorpuschristi.com)', 'https://www.visitcorpuschristi.com', 'TX', 1000),
    ('irvingtexas', 'Irving, TX tourism board (irvingtexas.com)', 'https://www.irvingtexas.com', 'TX', 1000),
    ('experiencescottsdale', 'Scottsdale, AZ tourism board (experiencescottsdale.com)', 'https://www.experiencescottsdale.com', 'AZ', 2000),
    ('playfresno', 'Fresno, CA tourism board (playfresno.com)', 'https://www.visitfresnocounty.org', 'CA', 1000),
    ('visitgreaterpalmsprings', 'Palm Springs, CA tourism board (visitgreaterpalmsprings.com)', 'https://www.visitgreaterpalmsprings.com', 'CA', 1000),
    ('visitnapavalley', 'Napa, CA tourism board (visitnapavalley.com)', 'https://www.visitnapavalley.com', 'CA', 1000),
    ('eugenecascadescoast', 'Eugene, OR tourism board (eugenecascadescoast.org)', 'https://www.eugenecascadescoast.org', 'OR', 1000),
    ('visitbellevuewa', 'Bellevue, WA tourism board (visitbellevuewa.com)', 'https://www.visitbellevue.com', 'WA', 1000),
    ('traveljuneau', 'Juneau, AK tourism board (traveljuneau.com)', 'https://www.traveljuneau.com', 'AK', 1000),
    ('explorefairbanks', 'Fairbanks, AK tourism board (explorefairbanks.com)', 'https://www.explorefairbanks.com', 'AK', 1000),
    ('unmistakablylawrence', 'Lawrence, KS tourism board (unmistakablylawrence.com)', 'https://www.explorelawrence.com', 'KS', 1000),
    ('shreveportbossier', 'Shreveport, LA tourism board (shreveport-bossier.org)', 'https://www.visitshreveportbossier.org', 'LA', 1000),
    ('lafayettetravel', 'Lafayette, LA tourism board (lafayettetravel.com)', 'https://www.lafayettetravel.com', 'LA', 1000),
    ('mobile', 'Mobile, AL tourism board (mobile.org)', 'https://www.mobile.org', 'AL', 1000),
    ('huntsville', 'Huntsville, AL tourism board (huntsville.org)', 'https://www.huntsville.org', 'AL', 1000),
    ('visitwilliamsburg', 'Williamsburg, VA tourism board (visitwilliamsburg.com)', 'https://www.visitwilliamsburg.com', 'VA', 1000),
    ('fxva', 'Fairfax County, VA tourism board (fxva.com)', 'https://www.fxva.com', 'VA', 1000),
    ('visitloudoun', 'Loudoun County, VA tourism board (visitloudoun.org)', 'https://www.visitloudoun.org', 'VA', 1000),
    ('visitannapolis', 'Annapolis, MD tourism board (visitannapolis.org)', 'https://www.visitannapolis.org', 'MD', 1000),
    ('visitfrederick', 'Frederick, MD tourism board (visitfrederick.org)', 'https://www.visitfrederick.org', 'MD', 1000),
    ('ococean', 'Ocean City, MD tourism board (ococean.com)', 'https://www.ococean.com', 'MD', 1000),
    ('atlanticcitynj', 'Atlantic City, NJ tourism board (atlanticcitynj.com)', 'https://www.visitatlanticcity.com', 'NJ', 1000),
    ('visitrapidcity', 'Rapid City, SD tourism board (visitrapidcity.com)', 'https://www.visitrapidcity.com', 'SD', 1000),
    ('visiteauclaire', 'Eau Claire, WI tourism board (visiteauclaire.com)', 'https://www.visiteauclaire.com', 'WI', 1000),
    ('visitstillwater', 'Stillwater, OK tourism board (visitstillwater.org)', 'https://www.visitstillwater.org', 'OK', 1000),
    ('visitlincoln', 'Lincoln, NE tourism board (visitlincoln.com)', 'https://www.visitlincoln.com', 'NE', 1000),
]
for _id, _title, _home, _state, _expected in CITY_SITES:
    SITES[_id] = _site(_title, _home, _expected)

# State tourism sites that answered with an anti-bot challenge or a plain 403 (26 November 2026): not collected.
BLOCKED = {"travelalaska.com": "Cloudflare", "visitarizona.com": "Cloudflare", "colorado.com": "Cloudflare",
           "exploregeorgia.org": "Cloudflare", "gohawaii.com": "Cloudflare", "visitidaho.org": "Cloudflare",
           "explorelouisiana.com": "Cloudflare", "visitmaine.com": "Cloudflare", "visitmaryland.org": "Cloudflare",
           "visitma.com": "Cloudflare", "michigan.org": "Cloudflare", "exploreminnesota.com": "Cloudflare",
           "visitmississippi.org": "plain 403", "visitnebraska.com": "Cloudflare", "travelnevada.com": "Cloudflare",
           "visitnh.gov": "Cloudflare", "visitnj.org": "Incapsula", "ndtourism.com": "Cloudflare",
           "travelsouthdakota.com": "Cloudflare", "ohio.org": "404 to programs"}
# City and county boards that refused our one robots.txt request (27 November 2026), or did not answer: not collected,
# never tried another way (no browser, no other address); a person may check them again later.
CITY_BLOCKED = {
    'nycgo.com': 'no answer',  # New York City, NY
    'sftravel.com': 'refused (HTTP 403 or an anti-bot page)',  # San Francisco, CA
    'sandiego.org': 'refused (HTTP 403 or an anti-bot page)',  # San Diego, CA
    'visitanchorage.net': 'robots.txt not found (404): the address may have changed',  # Anchorage, AK
    'memphistravel.com': 'refused (HTTP 403 or an anti-bot page)',  # Memphis, TN
    'visitmusiccity.com': 'refused (HTTP 403 or an anti-bot page)',  # Nashville, TN
    'visitsavannah.com': 'refused (HTTP 403 or an anti-bot page)',  # Savannah, GA
    'visitstpeteclearwater.com': 'refused (HTTP 403 or an anti-bot page)',  # St. Petersburg, FL
    'visitwinstonsalem.com': 'refused (HTTP 403 or an anti-bot page)',  # Winston-Salem, NC
    'exploreasheville.com': 'refused (HTTP 403 or an anti-bot page)',  # Asheville, NC
    'charlestoncvb.com': 'refused (HTTP 403 or an anti-bot page)',  # Charleston, SC
    'visitvirginiabeach.com': 'refused (HTTP 403 or an anti-bot page)',  # Virginia Beach, VA
    'visitspringfieldillinois.com': 'robots.txt not found (404): the address may have changed',  # Springfield, IL
    'visitpeoria.org': 'no answer',  # Peoria, IL
    'visitsiouxfalls.com': 'robots.txt not found (404): the address may have changed',  # Sioux Falls, SD
    'visitelpaso.com': 'no answer',  # El Paso, TX
    'santabarbaraca.com': 'refused (HTTP 403 or an anti-bot page)',  # Santa Barbara, CA
    'visittopekaks.com': 'no answer',  # Topeka, KS
    'visitsarasota.com': 'refused (HTTP 403 or an anti-bot page)',  # Sarasota, FL
    'visitmyrtlebeach.com': 'refused (HTTP 403 or an anti-bot page)',  # Myrtle Beach, SC
}
# City boards that answered but run neither Simpleview nor Tempest (mostly WordPress sites with their own listings
# pages): no common structured platform, so not collected here (the business-website collector may still read
# each business's own homepage).
NOT_STRUCTURED = [
    'choosechicago.com',  # Chicago, IL
    'visitphilly.com',  # Philadelphia, PA
    'discoverlosangeles.com',  # Los Angeles, CA
    'visitseattle.org',  # Seattle, WA
    'travelportland.com',  # Portland, OR
    'sanjose.org',  # San Jose, CA
    'visitrenotahoe.com',  # Reno, NV
    'visitboise.com',  # Boise, ID
    'visitkc.com',  # Kansas City, MO
    'explorestlouis.com',  # St. Louis, MO
    'thisiscleveland.com',  # Cleveland, OH
    'inbirmingham.com',  # Birmingham, AL
    'discoveratlanta.com',  # Atlanta, GA
    'miamiandbeaches.com',  # Miami, FL
    'thepalmbeaches.com',  # Palm Beach County, FL
    'charlottesgotalot.com',  # Charlotte, NC
    'visitgreensboronc.com',  # Greensboro, NC
    'visitnorfolk.com',  # Norfolk, VA
    'washington.org',  # Washington, DC
    'baltimore.org',  # Baltimore, MD
    'visitbuffaloniagara.com',  # Buffalo, NY
    'visitportland.com',  # Portland, ME
    'visitduluth.com',  # Duluth, MN
    'visitbillings.com',  # Billings, MT
    'visitlubbock.org',  # Lubbock, TX
    'visitplano.com',  # Plano, TX
    'arlington.org',  # Arlington, TX
    'visitfrisco.com',  # Frisco, TX
    'wacoheartoftexas.com',  # Waco, TX
    'tempetourism.com',  # Tempe, AZ
    'flagstaffarizona.org',  # Flagstaff, AZ
    'santacruz.org',  # Santa Cruz, CA
    'seemonterey.com',  # Monterey, CA
    'sonomacounty.com',  # Sonoma County, CA
    'visitbend.com',  # Bend, OR
    'greaterzion.com',  # St. George, UT
    'visitcolumbiamo.com',  # Columbia, MO
    'springfieldmo.org',  # Springfield, MO
    'experiencefayetteville.com',  # Fayetteville, AR
    'hotsprings.org',  # Hot Springs, AR
    'visitingmontgomery.com',  # Montgomery, AL
    'visittuscaloosa.com',  # Tuscaloosa, AL
    'visitgainesville.com',  # Gainesville, FL
    'visittallahassee.com',  # Tallahassee, FL
    'paradisecoast.com',  # Naples, FL
    'visitfortmyers.com',  # Fort Myers, FL
    'visitalexandria.com',  # Alexandria, VA
]


def listing_data(page):
    """The embedded listing data of a page ("var data = {...}"), or {}."""
    m = _DATA.search(page or "")
    if not m:
        return {}
    value = jsonld.loads(page[m.end():])
    return value if isinstance(value, dict) else {}


def amenities(data):
    """(hours text, [accessibility facts]) of a listing's amenity groups. Only fields labelled as hours, and fields
    whose label or group names accessibility (ADA, accessible, wheelchair ...), are read; a "No" is left out."""
    hours, access = "", []
    for tab in data.get("amenityTree") or []:
        for group in (tab or {}).get("groups") or []:
            group_name = str(group.get("amenitygroupname") or "")
            for field in group.get("fields") or []:
                label = " ".join(str(field.get("label") or "").split())
                value = " ".join(str(((field.get("doc") or {}).get("value_string")) or "").split())
                if not label or not value or value.lower() in ("no", "false", "0"):
                    continue
                if HOURS_LABEL.match(label) and not hours:
                    hours = value
                elif ACCESS_LABEL.search(label) or ACCESS_LABEL.search(group_name):
                    access.append(label if value.lower() in ("yes", "true") else f"{label} {value}")
    return hours, access


def listing(page, site, url):
    """One listing page as a row (FIELDS), or None (see the module docstring)."""
    data = listing_data(page)
    found = {}
    for thing in jsonld.find(page, {"LocalBusiness", "Hotel", "Restaurant", "TouristAttraction", "Store",
                                    "LodgingBusiness", "FoodEstablishment", "Museum", "ProfessionalService",
                                    "ArtGallery", "EntertainmentBusiness", "SportsActivityLocation", "Place"}):
        if "#localbusiness" in str(thing.get("@id") or "") or not found:
            found = jsonld.store(thing, need_position=False) or {}
    m = LISTING.search(url)
    recid = str(data.get("recid") or (m.group(1) if m else ""))
    name = html.unescape(str(data.get("title") or found.get("name") or ""))
    street = str(data.get("address1") or found.get("street") or "")
    cat = data.get("primaryCategory") or {}
    category = " / ".join(str(cat.get(k)) for k in ("catname", "subcatname") if cat.get(k))
    if not recid or home_business(name, street, category):
        return None
    lat = data.get("latitude") if data.get("latitude") not in (None, "", 0) else found.get("lat")
    lon = data.get("longitude") if data.get("longitude") not in (None, "", 0) else found.get("lon")
    hours_text, access = amenities(data)
    hours = oh.from_text(hours_text) if hours_text else ""
    tags = tags_of(str(cat.get("subcatname") or ""), str(cat.get("catname") or ""))
    phone = data.get("phone") or found.get("phone") or ""
    website = str(data.get("weburl") or "").strip()
    row = make_row(site, recid, name, tags, lat, lon, phone=phone, website=website, opening_hours=hours,
                   street=street, city=found.get("city") or data.get("city") or "",
                   state=found.get("state") or data.get("state") or "",
                   postcode=found.get("postcode") or data.get("zip") or "")
    if row is None:
        return None
    if not row["type"] and cat.get("subcatname"):
        row["type"] = " ".join(str(cat["subcatname"]).lower().split())
    note = []
    if hours_text and not hours:
        note.append(f"Hours: {hours_text[:200]}")
    if access:
        note.append("Accessibility: " + ", ".join(access)[:600])
    row["category"] = category
    row["note"] = no_email("; ".join(note))
    return row


def listing_pages(client, robots, home):
    """The listing page addresses of a site's sitemap(s), each once, in sitemap order."""
    from placepacks.chains.base import sitemap
    maps = robots.sitemaps() or [home.rstrip("/") + "/sitemap.xml"]
    found, seen, todo, read = [], set(), list(maps), set()
    while todo and len(read) < 30:
        url = todo.pop(0)
        if url in read:
            continue
        read.add(url)
        try:
            locs = sitemap(client, url)
        except NotFound:
            continue
        children = [u for u in locs if re.search(r"\.xml(\.gz)?(\?|$)", u)]
        if children and len(children) == len(locs):            # a sitemap index
            named = [u for u in children if "listing" in u.lower()]
            todo += named or children
            continue
        for loc in locs:
            if LISTING.search(loc) and loc not in seen and robots.allowed(loc):
                seen.add(loc)
                found.append(loc)
    return found


def collect(client, unit, stats):
    """Yield the rows of one site (see the module docstring). client: a polite client (its pause is set from
    robots.txt here); stats gets "listings", "gone", "left_out" and "failed" counts."""
    spec = SITES[unit]
    robots = Robots(client, spec["home"], ROBOTS_AGENT)
    delay = robots.crawl_delay()
    client.pause = max(MIN_PAUSE, min(MAX_PAUSE, delay if delay else PAUSE))
    pages = listing_pages(client, robots, spec["home"])
    stats.update(listings=len(pages), gone=0, left_out=0, failed=0)
    seen = set()
    for url in pages:
        try:
            page = client.fetch(url)
        except NotFound:
            stats["gone"] += 1
            continue
        except RequestFailed:
            stats["failed"] += 1
            if stats["failed"] > max(20, len(pages) // 20):
                raise
            continue
        row = listing(page, unit, url)
        if row is None or row["key"] in seen:
            stats["left_out"] += 1
            continue
        seen.add(row["key"])
        yield row
