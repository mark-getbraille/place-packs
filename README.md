# place-packs

Free, offline place-name packs for photos: what is at a position, as it was named when the picture was taken.
Each pack covers one region: a US state, a Canadian province, or a Geofabrik region of Western Europe, Australia,
New Zealand or Japan; the largest (England, Texas, California, New York, Florida, Ontario, Quebec, Australia,
the Netherlands, Sweden, Norway, Finland) are split into sub-regions, such as England's nine regions and Australia's states. Programs download
a region's pack the first time a picture from there needs it. After that, nothing is sent anywhere when a place is
looked up.

The packs are built from OpenStreetMap and other open data: national address databases, government names and
facilities, Overture Maps and Foursquare Open Source Places, Wikidata, GeoNames and public transit feeds, and dated
business records: restaurant inspections, liquor and business licences, bank and credit union branches, health
care organisations (pharmacies, clinics, dentists, opticians), fuel and charging stations, the UK's food hygiene
ratings and Victoria's Sands & McDougall directories (1896–1974), and US federal layers: historic places, parks
and protected areas, bridges, dams, airports, stations, schools, libraries, government offices and health
facilities (VA, USDA Service Centers, certified hospitals and nursing homes), braille and talking-book
libraries, recreation sites of the BLM, Reclamation and the TVA (with BLM's accessibility descriptions), fire
departments, federal prisons, border crossings, locks and bike-share stations, the water and electric utility
serving each place, and the county boundaries of every date since the 1600s. Each source is
listed with its licence in [SOURCES.md](SOURCES.md). The packs are made for the
[Digital Accessibility Toolkit](https://getbraille.com)'s picture describer and the Photo Location Identifier
(`photo-location-identifier/`), and anyone may use them under their licences.

A photo on a trail or beside a river with nothing nearer named gets the line: "on the Long Trail", "beside the
Missisquoi River" (Forest Service and park trails, Wild and Scenic Rivers). Address-only lists (the IRS's exempt
organizations, credit union offices, health care organisations, the Texas, Florida, Pennsylvania and Connecticut
licence lists) are placed by an offline geocoder at
build time, against the state's own address points (or, in Maryland, which the NAD leaves out, along the street's
address range); an organization at a home address is placed on its street, never at the house.

Every place can also carry a fine type beside its class, such as "pizza restaurant", "hardware store", "catholic
church" or "lighthouse" (`type` in a lookup's result; `search_names(..., type="bakery")`). See FORMAT.md.

## What a lookup says

- "at Riverside Park, West 120th Street, New York"
- "near 120 Main Street, Springfield", from an address point
- "at about 120 Main Street", estimated from the street's address range
- "next to Riverside Library", or "next to a business listed as Tony's Pizza (now Sally's Ice Cream)"
- "at Riverside Plaza" or "near 123 Main St" when several shops share one spot and the phone's position cannot
  tell which (the shops are kept in `Result.others`, never spoken)
- "on Vineyard Sound, about 3 miles south of Edgartown", "on Lake Champlain"
- "in the air, about 35,000 feet (10,700 m) over the Pacific Ocean, about 400 miles northeast of Hilo"
- "near Boston Logan International Airport", in the air shortly after take-off
- "The nearest pharmacy is Made-up Pharmacy, 300 feet north. Phone 802-555-0180. Hours: Mo-Fr 09:00-19:00." when
  asked for the nearest place of a kind (`placepacks.find`, `placepacks.local`): the phone, website and opening
  hours come from OpenStreetMap where it has them, else (since November 2026) from the business directories in the
  businesses part: All The Places (phone, website and hours from the chains' own store locators), the chain store
  locators this project reads itself for big US chains All The Places misses (phone, store page and hours), Overture
  (phone and website) and Foursquare (phone and website), the tourism boards' and chambers' listings (phone, website,
  some hours), and last the details-only sources that fill what a business still lacks: its own homepage's
  schema.org data (phone and hours) and Yellow Pages lookups (phone, website and hours). Never from a licence or
  inspection list (their numbers are often
  an owner's own), never an e-mail address, and nothing for an individual's office or a place under a person's
  name. `PackReader.details_of(key)` gives one business's details; only the business as listed now has them, not
  its older names (FORMAT.md, "Business contact details").

Water, coastlines and the air work without any pack, from the small global layer in `placepacks/data/`
(Natural Earth and OurAirports, both public domain; Marine Regions' bays and gulfs, CC BY 4.0).

Names in other languages (French, Spanish, German, Italian, Dutch, Japanese, Chinese) are in an optional third pack
per region, the "names" part, downloaded only when a program's user turns other languages on.

## History: names as they were

Packs never forget. Every record (a place, a business, a street, an address) has the months it was first and
last seen. Each monthly build is merged with the history published before:

- a record still there continues;
- a record that is renamed, closed or moved keeps its old row (closed at the last month it was seen);
- the new name starts a new row.

So "Tony's Pizza" is still Tony's Pizza for a photo taken before it became "Sally's Ice Cream". A street renamed
in 2015 is "Main St" for older photos. Rows are deleted only for a licence problem or a takedown request
(`removals.json`).

Records are matched across months by the source's own stable id: OpenStreetMap's id, Overture's GERS id,
Foursquare's id, the TIGER edge id, the GNIS id or the Wikidata Q-id. Without an id, they are matched by position
within a few metres and the same name and class.

How far back each layer goes:

| Layer | History |
|---|---|
| OpenStreetMap | From the first build (November 2026). Full OpenStreetMap history would need about 150 GB, or an OpenStreetMap login for per-state history extracts, so it is not used. |
| US street names and address ranges (TIGER/Line) | Seeded from the yearly releases of 2011, 2016 and 2021 (ADDRFEAT starts in 2011), then every build. This catches street renames, new streets and changed ranges. TIGER's point and area landmarks and military installations are seeded the same way. |
| US address points (NAD) | From the first build. Earlier NAD releases are added if USDOT keeps them openly downloadable. The NAD is downloaded again only when USDOT publishes a new file (data.transportation.gov). |
| Restaurant inspections (New York City and State, Austin, Delaware, Montgomery County MD, Boulder County, Cincinnati, Baton Rouge, San Francisco 2016–2019) | Each establishment from its first to its last inspection, one record per permit and name, so a renamed restaurant keeps its old name with its own dates. New York State's go back to 2005. |
| Liquor licences (New York State, Colorado), New York City storefront licences, San Francisco and Los Angeles business locations | Each licence's issue and expiry dates, or each business location's start and end dates (San Francisco's go back to the 1960s). Only storefront businesses, under their trade names. |
| State licence and tax lists (since November 2026): Texas sales-tax outlets, mixed beverage, tobacco and hotel permits; Florida food service, alcohol and tobacco licences; Pennsylvania sales-tax and tobacco licences; New York food stores, tobacco and cannabis retailers, DMV facilities and salons; Connecticut premises licences and car dealers | Texas outlets from their first sale (back to the 1960s) to their out-of-business date; Florida alcohol licences and Connecticut and New York licences from their issue dates; the others from the first build. Only storefront types, under their trade names; a sole proprietor trading under their own name, or from home, is left out (each source's rule is in SOURCES.md). |
| City and county lists (since November 2026): Baton Rouge businesses, New Orleans licences and alcohol outlets, San Diego County food facilities, Sacramento County licences, Baltimore liquor licences (from 2002), Wake County restaurants, Cambridge, Washington DC liquor licences, Sioux Falls, Arlington TX | Each place's own opening, licence or inspection dates where the list has them; otherwise from the first build. |
| FDIC bank branches | Each branch under its bank's name since the bank took it over, or since it opened. |
| Credit union offices (NCUA), since November 2026 | From the first build (the quarterly branch file has no opening dates; its older quarters, back to the 1990s, could seed earlier years later). Each office under its credit union's name. |
| Health care organisations (CMS NPPES), since November 2026: pharmacies, clinics and urgent care, dentists, optometrists and opticians, hearing aid shops, physical therapy, chiropractors, laboratories, medical supply stores | Each organisation from the date it got its NPI (2005 at the earliest), closed when its NPI is deactivated. Organisations only, never individual providers; hospitals and federally qualified health centres come from other layers. |
| SNAP grocery and convenience stores (USDA), since November 2026 | Each store from its SNAP authorization date to its end date (every store authorized in the past 20 years, back to the 1990s for long-standing ones); the file is renewed once a year. |
| Government offices and health facilities, since November 2026: VA medical centers, clinics and vet centers; VA benefits offices (with the owner's key); certified hospitals, nursing homes, dialysis centers and rural health clinics (HRSA Site Dashboard); USDA Service Centers; Pennsylvania state offices, New York DMV offices, Washington DC agencies | VA health sites from their opening dates (back to the 1920s); the others from the first build. |
| Federal and state lists of the 26 November 2026 pass: NLS braille and talking-book libraries, Medicare medical equipment suppliers (pharmacies, opticians, medical supply), BLM, Reclamation and TVA recreation sites, HUD housing authorities, fire departments and stations, federal prisons, border crossings, locks, bike-share stations, stadiums, hospital and police heliports; New York and Florida lottery retailers, licensed child care centres (Texas, Pennsylvania, Connecticut, Delaware, Colorado, Michigan; centres only, never homes), New York, Iowa, Hawaii and Connecticut health facilities, Kentucky, Utah and Connecticut outdoor places | Border crossings from their first month of traffic (1996 on) to their last; locks from the year they opened (1800s on); stadiums, Medicare suppliers, New York health facilities, Iowa facilities, Texas and Connecticut child care centres and Pennsylvania dispensaries from their opening, participation or first licence dates (Connecticut's closed centres end at their last licence); bike-share stations by the yearly listings (2015 on); Connecticut nursing homes by reporting year under each former name; closed public airports at the FAA's last report; the others from the first build. |
| Fuel and charging stations (DOE Alternative Fuels Data Center), since November 2026 | Each public station from its open date; the charging network (ChargePoint, Tesla, EVgo, Electrify America ...) as its brand. |
| UK food hygiene ratings (FSA) | Each business from its latest rating date, then month by month. |
| Victoria, Australia: Sands & McDougall directories | The directory years 1896–1974 each business was listed in. |
| US counties (Newberry Library's Atlas of Historical County Boundaries) | Every version of every county since the 1600s with its exact dates: a lookup gives the county as it was on the picture's date (`county` in the result). |
| National Register of Historic Places, bridges (FHWA), dams (USACE), public airports (FAA), PA historical markers | From the listing date, the year built or completed, the activation date or the dedication date. |
| PAD-US parks and protected areas, NPS points of interest, Forest Service recreation sites, ferry terminals, Amtrak stations, military installations, libraries, private schools and colleges | From the first build (PAD-US also from the year an area was established). All read from the agencies' own public services and files each month, with no hand step. |
| Lighthouses (USCG Light List), former military sites (FUDS), VA national cemeteries | The lights and sites listed now, from the first build; lighthouses, forts, military and Coast Guard bases and national cemeteries also come from Wikidata with their founding and closing dates, so a 1960 picture at a base closed in 1995 gets the base. Cemeteries have their own class (cemetery). |
| OpenHistoricalMap (US and Canada) | Each feature's own start and end dates (old businesses, buildings, stations, forts, mills), often a century or more back. |
| Toronto food premises (DineSafe), Boston food licences, StatCan facilities, Aboriginal lands of Canada, US tribal areas | Inspection and licence dates where the source has them; otherwise from the first build. |
| IRS exempt organizations (churches, schools, museums, clubs, foundations) | Each organization from its IRS ruling date; closed when it leaves the file. |
| Museums (IMLS), battlefields (NPS), federal buildings (GSA), beaches (EPA), BC and Ontario provincial parks, trails, Wild and Scenic Rivers, GNIS variant names | From the first build (Ontario parks from their protection date, rivers from their designation); variant names are kept for search only. |
| Washington DC business licences, Minneapolis food inspections | Licence issue and end dates; first and last inspections. |
| Overture places | From the first build. Past monthly releases (for example one a quarter) can be merged first while Overture still keeps them. |
| All The Places (chain stores) | Seeded once from its archived past runs, the largest run of each quarter since April 2018 (the archive's 2017 runs are listed without their files): each store from the first quarter it was listed in to the last, and a store that closed since is kept, closed at its last quarter. Then month by month. Stores are matched by the chain's own store reference; when a reference changes (a spider renamed, a locator renumbered), by the same name or brand within about 100 m. About 16 GB of archives are read once (`seed_chain_history`), and the small result is kept in the "seeds" release for every later build. |
| Chain store locators (big US chains missing from All The Places), since November 2026 | From the first monthly set (collected on the 28th), month by month, matched by the chain and its own store number. A chain whose collection is blocked or fails one month keeps its previous month's stores (up to three months running), so a failed run never closes stores. |
| Tourism boards' Simpleview and Tempest listings and chambers' ChamberMaster directories, since November 2026 | From the first monthly set, month by month, keyed by the site (or the chamber's directory) and the listing's own number. A site or state whose collection is blocked or fails one month keeps its previous month's listings (up to three months running). |
| Foursquare Open Source Places | Foursquare's own creation and closing dates. |
| Wikidata | Its start and end dates, often decades back (a mill from 1923 to 1998). |
| France (BAN), Netherlands (BAG), New Zealand (LINZ) | From the first build. Their published archives and change sets can seed earlier years. |
| Everything else | From the first build. |

A lookup uses the photo's date: the camera's date, else the file's date (less certain). A date older than the data
uses the oldest record and says "no older record". Without a date it uses the newest records, "as listed now". A
date range (an old scanned photo, 1950–1960) gives the names valid in that range, said "probably".

## Using the packs

The `placepacks` package (MIT) reads packs with the Python standard library only:

```python
from placepacks.download import ensure_packs
from placepacks.lookup import Finder
from placepacks.regions import regions_near

for region in regions_near(44.26, -72.58):      # ["us-vermont"] (and a neighbour within 2 km of its border)
    ensure_packs(region)                         # core and extra, once; detail="address" adds businesses and
                                                 # addresses; ask= and progress= are optional
f = Finder()
r = f.lookup(44.26, -72.58, when=(2005, 2006), detail="street", altitude=None)
print(r.phrase(units="miles"), "|", r.short("street"), "|", r.details())
print(f.areas_at(44.26, -72.58))                 # every named area holding the point, smallest first,
                                                 # with the water and electric utility serving it
```

The API:

- `placepacks.lookup`: `Finder(folder=None, packs=None, water=None, nearest=None)`, with `.lookup(lat, lon,
  when=None, detail="street", altitude=None)` returning a `Result`, and `.areas_at(lat, lon, when=None)`.
  Also `search_names(text, folder=None, regions=None, when=None, limit=20)` and `PackReader(path)`.
- `Result`: `kind`, `name`, `cls`, `house_number`, `street`, `street_now`, `town`, `neighbourhood`, `zip_area`,
  `water_name`, `distance_m`, `bearing`, `over`, `airport`, `first`, `last`, `now_name`, `listed`, `probably`,
  `as_listed_now`, `no_older_record`, `sources`, `source_names`, `attributions`. Its methods are `phrase(detail,
  units)`, `short(detail)`, `details()` and `source_text()`.
- `placepacks.when`: `When.parse(None | YYYYMM | date | "YYYY-MM" | (start, end))`.
- `placepacks.regions`: `REGIONS`, `regions_for(lat, lon, resolver=None)`, `regions_near(lat, lon, km=2)`,
  `region_label(id)`, `tree()`, `expand(id)` (a parent's sub-regions) and `parent_of(id)`.
- `placepacks.download`: `PUBLIC_RELEASE`, `Catalogue()`, `ensure_pack(region, part="core", folder=None,
  ask=None, progress=None)` (a parent id downloads its sub-regions' packs), `ensure_packs(region, parts=None,
  detail=None, full=False)`, `parts_for(detail=None, full=False)`, `updates_available()`, `installed()`,
  `remove_pack(key)` and `add_pack_file(path)`.
- `placepacks.water`: `WaterLayer().describe(lat, lon, altitude=None, nearest=None)`.

Each region has these parts:

- **core** (`us-vermont.osmpack`): OpenStreetMap, Census towns and ZIP areas: the towns, streets and landmarks.
  No address points.
- **extra** (`us-vermont-extra.osmpack`): the history and the smaller lists: public facilities, landmarks, transit
  stops, trails, historic areas and Wikidata.
- **businesses** (`us-vermont-businesses.osmpack`): Overture Maps places, All the Places, the IRS's exempt
  organizations and the business lists (inspections, licences, bank branches, food hygiene ratings).
- **addresses** (`us-vermont-addresses.osmpack`): address points and address ranges, with their history.
- **names** (`us-vermont-names.osmpack`, optional): other-language names.
- **navigation** (`us-vermont-navigation.osmpack`, optional, since November 2026): for getting around. The street
  network with its intersections (named cross streets) and segments, and the pedestrian details: crossings and
  their type, traffic signals and accessible pedestrian signals, tactile paving, kerbs and curb cuts, sidewalks,
  steps, ramps, elevators, entrances with wheelchair access, and bus stops with their shelter, bench and tactile
  paving (OpenStreetMap); and the open transit feeds' stops, routes and timetables with wheelchair boarding.
  `placepacks.navigate.Navigator` answers "what is the nearest intersection" (`nearest_intersection`), "how do I
  cross here" (`crossing_here`) and "the next bus from the nearest stop" (`next_buses`), each with a plain
  sentence. Download it with `ensure_pack(region, part="navigation")`. FORMAT.md, "The navigation part".
- **Finding places and directions** (`placepacks.find.find_nearest("hardware store", start=(lat, lon))`): the
  nearest place of any kind (every shop, craft and amenity type, with plain words and synonyms; places of worship by
  religion and denomination; offices; past polling places with their election date) with its phone, website and
  hours (OpenStreetMap's, else the business directories' of the businesses part), and
  offline turn-by-turn walking directions that name the cross streets and each crossing's signal, push button and
  tactile paving (driving and a direct transit ride too). The routing is this repository's own A* search over the
  navigation part's network. FORMAT.md, "Finding places and directions".
- **services** (`us-vermont-services.osmpack`, optional, since November 2026): local services and weather
  emergencies. Offices and services from OpenStreetMap (Social Security, motor vehicle and veterans offices,
  courthouses, post offices, libraries, pharmacies, food banks, shelters, hospitals, police and fire stations,
  defibrillators ...), the National Weather Service county and forecast zones and the NOAA Weather Radio
  transmitters of every county. `placepacks.local.LocalServices` answers "the nearest Social Security office"
  (`nearest`, which also searches the core and extra parts' libraries, health centres and post offices), "my
  forecast zone" (`weather_zone`) and "my NOAA Weather Radio frequency" (`weather_radio`). What could not be used
  (the SSA office locator, the VA Facilities API without a key, SAMHSA's locator, 211, FEMA's shelters) is in
  sources.json "rejected", with the reason.

Core and extra are files of the release `packs`. The names, businesses and addresses of each publish are in a
release of their own, `packs-detail-YYYYMMDD` (GitHub allows 1000 files in one release); each entry of `packs.json`
says its release, and `Catalogue.url_for` gives the address. When a pack has been replaced since the program last
read `packs.json` (the old file is gone), the program reads the list again and downloads the newer pack.

Programs download core and extra. They get businesses and addresses only when a lookup needs them (the detail
"address", or the exact place in a picture's name) or the user turns on full detail. A lookup never fails without
them: it names the landmark, the street or the town instead. Programs made before these parts existed still find
the towns and streets in core and extra.

**Sub-regions.** A region whose core and extra together would be over about 300 MB is built as sub-regions:
England's nine regions (`gb-england-london`, `gb-england-south-east`, ...), Australia's states and territories
(`au-new-south-wales`, ...), groups of counties of Texas (`us-texas-north`, `us-texas-gulf-coast`,
`us-texas-south-central`, `us-texas-west`), California (`us-california-los-angeles`, `-south`, `-bay-area`,
`-central`, `-north`), New York (`us-new-york-city`, `-downstate`, `-upstate`) and Florida (`us-florida-south`,
`-central`, `-north`), Ontario (`ca-ontario-toronto`, `-south-west`, `-east`, `-north`), Quebec
(`ca-quebec-montreal`, `-east-and-north`), the Netherlands (`nl-netherlands-west`, `-north-east-south`), Sweden
(`se-sweden-south-and-west`, `-stockholm-and-north`), Norway (`no-norway-east-and-south`, `-west-and-north`) and
Finland (`fi-finland-south`, `-centre-and-north`). A sub-region covers only its parent's own land and the water
next to it, never a neighbour's (Vermont is not in New York's). Each pack also holds
what lies within about 2 km of its border and every street that crosses it, so a lookup near a border works, and
`regions_near` gives both sub-regions there. The parent id still works: `ensure_pack("gb-england")` downloads every
sub-region's pack. For programs that know only the parent, packs.json keeps the parent's core and extra too, the
sub-regions' packs put together. The sub-regions are made by `tools/make_subregions.py`.

The file format is described in [FORMAT.md](FORMAT.md).

## Sizes

The first full build (November 2026) published 453 packs, 52 GB in all, before the parts and sub-regions; each
pack's size is in [sources-status.md](sources-status.md). Measured from those packs, the largest regions in the new
parts (MB; a sub-region's share is estimated from its population, and its packs are a few per cent larger for
the overlap at its borders):

| Region | Core | Extra | Businesses | Addresses | Core + extra of the largest sub-region |
|---|---|---|---|---|---|
| Texas (4 sub-regions) | 297 | 113 | 501 | 757 | 145 (North and East) |
| California (5) | 351 | 150 | 492 | 576 | 175 (Los Angeles Area) |
| England (9) | 573 | 18 | 843 | 0 | 97 (South East) |
| Australia (8) | 567 | 81 | 542 | 0 | about 200 (New South Wales) |
| New York (3) | 178 | 126 | 527 | 359 | about 130 (New York City) |
| Ontario (4) | 216 | 141 | 569 | 121 | about 170 (Toronto) |
| A typical US state (not split) | 60–200 | 40–110 | 100–300 | 150–450 | |

Core and extra, what a program downloads by default, stay under about 300 MB for every pack. GitHub allows release
files up to 2 GB each with no total limit. A user downloads only the regions their photos need.

## How the packs are built

[.github/workflows/build-packs.yml](.github/workflows/build-packs.yml) ("Build place packs"):

- **When it runs:**
  - **Monthly:** on the 2nd of each month at 04:17 UTC. It rebuilds only the regions whose sources changed, judged
    by their ETags, Last-Modified dates and release names recorded in `packs.json`.
  - **By hand:** Actions, "Build place packs", Run workflow. Inputs:
    - `regions`: for example `us-vermont fr-ile-de-france`; empty means all;
    - `force`: rebuild even when nothing changed;
    - `seed_history`: seed the US address-range history from older TIGER years. The finished seed of each region is kept in the "seeds" release and reused, so it is made again only when the seed years or sources change;
    - `seed_chain_history`: seed the chain stores' history from All The Places' archived runs, once (about 16 GB
      of downloads, read a few GB per job, one archive at a time, in about two to four hours). The result
      (`chain-history.json` and `chain-history-*.csv.gz`, about 1 GB) is kept in the "seeds" release; every later
      build merges it into the latest run, so the archives are never downloaded again. Run it again only to seed
      once more (for example after new countries are covered); the older seed's files are then deleted;
    - `also_from_run`: the ids of earlier runs whose publish failed, separated by spaces: their packs (kept 7 days as
      run artifacts) are published too, this run's own packs first;
    - `publish_only`: build nothing, only publish the packs of the runs in `also_from_run`.
- **What it does:**
  - It downloads the national files once and splits them per region. The CMS NPPES file (about 1 GB) waits on the
    runner's larger `/mnt` disk, is read once as a stream (organisations of the allowed kinds only) into a small
    CSV, and is deleted at once.
  - Foursquare Open Source Places is now on Hugging Face behind a free sign-in, which the build machines cannot do.
    The owner's Program Downloader copies each month's files there, unchanged, into this repository's release
    `uploaded-sources` (`fsq-<date>-<file>`, `fsq-<date>-NOTICE.txt` and, last, the manifest `fsq-<date>.json`
    with each file's SHA-256). The prepare job reads the newest complete date once, one file at a time (checked by
    its SHA-256, the raw file on the runner's larger `/mnt` disk and deleted at once), keeping only the covered
    countries and the columns the build uses, into the national slice that is split per region like the others.
    Until the first upload is there the source is skipped, "waiting for the owner's upload from Program Downloader";
    it never fails the build (`placepacks/uploaded.py`).
  - It builds each region (ten at a time; inside a region four sources at a time, at most two against one server, each stopped after its time limit), merged with its previous pack. Each part is its own pack (core, extra, businesses, addresses, names).
  - A sub-region reads its parent's slice of the national files and its parent's OpenStreetMap extract, clipped with osmium-tool. Its first build takes its history from its parent's older packs (only its own area). The publish job then puts each parent's sub-regions together again under the parent's keys (`placepacks.combine`).
  - It publishes, in this order:
    1. the new packs, under dated file names: core and extra in the release `packs`, the names, businesses and
       addresses in this publish's own release `packs-detail-YYYYMMDD`;
    2. the licences, then the previous list, as `packs-previous.json`, in `packs`;
    3. the new list, `packs.json`, last. It is written compact and must stay under 4 MB, the most the programs read
       (`manifest.LIMIT`); each part lists only its own sources (core lists all of its region's, for the plan).
  - It then deletes the pack files that neither list names, and a detail release left with no pack. A program never
    sees a list naming a file that is not there.
- **Keys:** the repository's own `GITHUB_TOKEN` (read-only, except in the jobs that change releases), and one
  optional key: the repository secret `NREL_API_KEY` (free from developer.nlr.gov/signup, sent by email), which the
  prepare step uses for the Alternative Fuels Data Center's stations. Without it the public `DEMO_KEY` is used, which
  is enough for that one request a month unless the build machine's address has used it up; then the stations are
  skipped that month and their history stays. The key is sent in a request header and never printed. A second
  optional key, the repository secret `VA_API_KEY` (free from developer.va.gov), is given only to the region fetch
  step for the VA's benefits offices (one request a state); without it that source is skipped.
- **Keep-alive:** GitHub turns off scheduled workflows in repositories with no activity for 60 days. Each run
  commits an updated `sources-status.md`, which keeps the schedule alive.

### Chain store locators

[.github/workflows/chain-locators.yml](.github/workflows/chain-locators.yml) ("Chain store locators") reads big US
chains that All The Places misses straight from their own store locators (`placepacks/chains`): Burger King, Jack in
the Box, Avis, Budget, Wyndham's hotels (Days Inn, Super 8, La Quinta, Baymont, Microtel, Travelodge, Ramada, Wingate
and others), and Buick, GMC, Ford and Lincoln dealers.

- **When it runs:** on the 28th of each month (05:41 UTC), a few days before the packs are built. By hand: Actions,
  "Chain store locators", Run workflow; the `chains` box takes chain ids separated by spaces (for example
  `avis budget`); empty means every chain. The ids are in `placepacks/chains/__init__.py`.
- **How it reads a chain:** one job per chain, four at a time. Each asks the chain's own store-locator API, or reads
  its sitemap of store pages and the schema.org details on each page, the way All The Places' open-source spiders
  do. It names this project in every request, waits at least a second between requests to one site (ten for
  ford.com, as its robots.txt asks), keeps to a set number of requests, and tries a busy site again a few times
  with growing waits. If a site refuses (403, 429 or an anti-bot check page), that chain stops at once and is marked
  "blocked": nothing is ever got round, no CAPTCHA is solved and no login is used. No e-mail address is kept, and
  individuals' offices (insurance agents and the like) are never collected. The owner decided on 26 November 2026
  to publish these chains' locations, hours and phone numbers even where a chain's terms or robots.txt say no.
- **What it keeps:** the last job puts the month's set in the release `chain-locators`, one file a chain
  (`chain-locators-<date>-<chain>.csv.gz`) and the list `chain-locators-<date>.json` last. A chain that was blocked,
  failed, ran out of time or found less than half its stores of last time keeps its previous file, so its stores
  stay open in the packs. The newest two sets are kept. The job summary has a table of each chain's result.
- **How the packs use it:** the pack build's prepare step reads the newest set once, as one national file split per
  region like All The Places. Until the first set is there the source is skipped ("waiting for the first
  chain-locators set"); a store that All The Places also lists (the same name within 100 m) is left to All The
  Places.
- **Chains that refused even a first check** (26 November 2026): McDonald's, Jersey Mike's, YMCA, Planet Fitness,
  Health Mart, Citgo, Choice Hotels, H&R Block, Best Western, the Stellantis dealers, Fastenal, Tractor Supply,
  Goodwill and Bitcoin Depot. They are listed with what each site answered in `placepacks/chains/__init__.py`.

### Business details from local directories and lookups

Four collectors add phone numbers, websites and opening hours, and some new local businesses, by the owner's
decisions of 26 November 2026 (`placepacks/directories`). The same rules hold for all four: facts only (name, street
address, position, phone, website, opening hours, category, accessibility notes), never a review, a rating, a
description, a photo, an e-mail address or a person's name; one-person and home businesses are left out (no street
address, a post office box, a person's name, an individual's office such as an insurance agent); every request names
this project; a site that refuses or sends an anti-bot check page is recorded as "blocked" and left. No CAPTCHA is
ever solved, no login used, no browser imitated (the owner declined headless browsers on 27 November 2026), no other
address or connection tried.

- **Yellow Pages lookups** (source `yp-lookups`, `tools/yp_lookup.py`): runs from the owner's cloud session, not
  from GitHub, slowly in the background (one request every 3 to 4 seconds, at most 25,000 a day, states with the most
  people first). For each business in the newest businesses packs that lacks a phone or hours, one search by name
  and town; a result is taken only when its name is at least 85% alike and its street address is an address point
  within 75 m of the place (or its coordinates are within 75 m). Results are uploaded each day to the release
  `uploaded-sources` as `yp-lookups-<YYYYMMDD>.csv.gz`, the previous file merged in. It stops at the first refusal
  and does not start again by itself. Start it with
  `nohup python3 tools/yp_lookup.py run --forever --work <a scratch folder> > yp.log 2>&1 &`; see where it is with
  `python3 tools/yp_lookup.py status` (progress in `/home/user/notes/yp-progress/`). yellowpages.com's robots.txt
  disallows its search pages for programs; the owner decided to make these lookups all the same.
- **Business websites** (source `business-websites`, [.github/workflows/web-details.yml](.github/workflows/web-details.yml),
  "Business websites"): on the 20th of each month, ten jobs read up to 30,000 homepages of businesses that have a
  website but no phone or hours; robots.txt is always obeyed (the owner's override is for chains and government
  sites only); only the schema.org data of one local business (phone and hours) is kept. Release `web-details`.
- **Tourism boards' listings** (source `simpleview-listings`,
  [.github/workflows/simpleview-listings.yml](.github/workflows/simpleview-listings.yml), "Tourism boards' listings"):
  on the 25th, the Simpleview sites (the 11 state tourism sites on Simpleview, Visit Denver and 76 city and county
  tourism boards found in November 2026) in matrix groups of about five hours each, so the run stays within
  GitHub's limits (the `units` box takes site ids such as `visitdenver iloveny`): robots.txt and its Crawl-delay
  obeyed (2 to 5 seconds), the sitemap, then each listing's name, address, position, phone, website, category,
  hours and accessibility fields. Release `simpleview-listings`. City boards that refused the one check request
  are listed in `placepacks/directories/simpleview.py` (`CITY_BLOCKED`) and never tried another way.
- **Tourism boards' Tempest listings** (source `tempest-listings`,
  [.github/workflows/tempest-listings.yml](.github/workflows/tempest-listings.yml), "Tourism boards' Tempest
  listings"): on the 26th, the 26 city and county tourism boards on the Tempest platform, in matrix groups the same
  way: robots.txt obeyed, the partner-directory sitemaps, then each listing's schema.org name, address, position,
  phone and website, its category and its accessibility amenities. Release `tempest-listings`.
- **Chambers' directories** (source `chambermaster-listings`,
  [.github/workflows/chambermaster-listings.yml](.github/workflows/chambermaster-listings.yml), "Chambers'
  directories"): on the 15th, one job per state (the `units` box takes codes such as `vt oh`). The US Chamber of
  Commerce's directory finds the chambers; only those on the older ChamberMaster directory are read (the newer
  GrowthZone v2 directories answer programs with an anti-bot check, so they are told apart by their robots.txt and
  never asked for a page), through their public-facing groups (restaurants, shops, lodging, health care, auto,
  personal services, recreation), 6 seconds apart. Members are placed by the offline NAD geocoder; home addresses
  are left out. Release `chambermaster-listings`.

In the packs (businesses part): Simpleview, Tempest and ChamberMaster listings are new places unless another business source
already lists them (the same phone number within 500 m, else the same name within 75 m); then their details go to
that place. The two details-only sources only fill what a place still lacks, after every other source. Each
workflow keeps a source's previous set when a month's run fails or is blocked, and the pack build skips a source
until its first set or file is there.

### Government places with details

Some government lists give more than a name and a position. Since November 2026 the packs carry their public
telephone numbers, opening hours (in OpenStreetMap's syntax, such as "Mo-Fr 09:00-16:00"), web pages and short
accessibility notes, so a lookup such as "the nearest Social Security office" can say the address, the phone number
and the hours (`placepacks/gov_details.py`):

- **Social Security field offices** (`ssa-field-offices`, about 1,170): named "Social Security office, <city>",
  with the address, phone number and weekday hours. ssa.gov refuses every program, so the list comes from an ArcGIS
  copy of SSA's own office list (published by Esri staff, without a licence); the owner decided on 26 November 2026
  to use it. Only the office's name, address, phone and hours are read; the copy's internal figures (costs, staff,
  leases, waiting times, local statistics, fax numbers) are never asked for.
- **Forest Service recreation sites** (`usfs-recreation-sites`): the existing sites now get their hours, season,
  fees, reservation information, accessibility and phone number from the Forest Service's Recreation Opportunities
  layer, joined by the site's id (or the same name within 300 m). No site is listed twice.
- **National Park Service** (`nps-places`): parks, visitor centers, campgrounds and places from the NPS Data API,
  with hours (including dated closures), phone and TTY numbers, web pages, campground accessibility and amenities.
  It needs the owner's free key in the repository secret `NPS_API_KEY` (sign up at nps.gov/subjects/developer);
  without it the source is skipped. A place the NPS's own points already have keeps that point and takes these
  details.
- **Recreation.gov** (`ridb-recreation`, about 15,000 places of every federal agency): campgrounds, day-use sites,
  visitor centers, recreation areas and permit entry points, with phone, a reservable flag, ADA access and the first
  sentence of the description. Included by the owner's decision of 26 November 2026, regardless of Recreation.gov's
  terms. A place an agency's own layer already has (the same name within 100 m) is not added again; the agency's
  point takes the details instead.
- **California** (`ca-health-facilities`, `ca-child-care-centers`): CDPH's licensed hospitals, clinics and nursing
  homes and CDSS's child care centres (never family child care homes), names and positions only.

Government sites that refused a single polite request on 26 November 2026 (Head Start's locator, CareerOneStop,
FDA's mammography file, the passport acceptance facility search, USCIS, ssa.gov) are recorded as blocked in
sources.json's rejected list; nothing is done to get past a refusal. No staff names, personal phone numbers or
e-mail addresses are kept from any of these lists.

To build one region yourself:

```
pip install -r requirements.txt
python -m placepacks.fetch us-rhode-island --dir work/us-rhode-island
python -m placepacks.build us-rhode-island --part core --inputs work/us-rhode-island/fetched.json --out us-rhode-island.osmpack
python -m placepacks.build us-rhode-island --part extra --inputs work/us-rhode-island/fetched.json --out us-rhode-island-extra.osmpack
python -m placepacks.build us-rhode-island --part addresses --inputs work/us-rhode-island/fetched.json --out us-rhode-island-addresses.osmpack
python -m placepacks.build us-rhode-island --part businesses --inputs work/us-rhode-island/fetched.json --out us-rhode-island-businesses.osmpack
```

Some sources need a file put in `inputs/` by hand: their downloads need an account or change address. `SOURCES.md`
says which.

## Licences

The code is under the MIT licence. Each pack is a collective database:

- its **OpenStreetMap layer** is under the **ODbL 1.0**, © OpenStreetMap contributors;
- **every other layer** is under its own open licence.

[LICENSES.md](LICENSES.md) explains the choice, and [SOURCES.md](SOURCES.md) lists every source with its licence
and attribution. When you show data from a pack, credit the sources used, for example "© OpenStreetMap
contributors".
