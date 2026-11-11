# place-packs

Free, offline place-name packs for photos: what is at a position, as it was named when the picture was taken.
Each pack covers one region: a US state, a Canadian province, or a Geofabrik region of Western Europe, Australia,
New Zealand or Japan; the largest (England, Texas, California, New York, Florida, Ontario, Quebec, Australia,
the Netherlands, Sweden, Norway, Finland) are split into sub-regions, such as England's nine regions and Australia's states. Programs download
a region's pack the first time a picture from there needs it. After that, nothing is sent anywhere when a place is
looked up.

The packs are built from OpenStreetMap and other open data: national address databases, government names and
facilities, Overture Maps and Foursquare Open Source Places, Wikidata, GeoNames and public transit feeds, and dated
business records: restaurant inspections, liquor and business licences, bank branches, the UK's food hygiene
ratings and Victoria's Sands & McDougall directories (1896–1974), and US federal layers: historic places, parks
and protected areas, bridges, dams, airports, stations, schools, libraries and the county boundaries of every date
since the 1600s. Each source is
listed with its licence in [SOURCES.md](SOURCES.md). The packs are made for the
[Digital Accessibility Toolkit](https://getbraille.com)'s picture describer and the Photo Location Identifier
(`photo-location-identifier/`), and anyone may use them under their licences.

A photo on a trail or beside a river with nothing nearer named gets the line: "on the Long Trail", "beside the
Missisquoi River" (Forest Service and park trails, Wild and Scenic Rivers). Address-only lists (the IRS's exempt
organizations) are placed by an offline geocoder at build time, against the state's own address points; an
organization at a home address is placed on its street, never at the house.

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
| FDIC bank branches | Each branch under its bank's name since the bank took it over, or since it opened. |
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
print(f.areas_at(44.26, -72.58))                 # every named area holding the point, smallest first
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
    - `seed_history`: seed the US address-range history from older TIGER years. The finished seed of each region is kept in the "seeds" release and reused, so it is made again only when the seed years or sources change.
- **What it does:**
  - It downloads the national files once and splits them per region.
  - It builds each region (ten at a time; inside a region four sources at a time, at most two against one server, each stopped after its time limit), merged with its previous pack. Each part is its own pack (core, extra, businesses, addresses, names).
  - A sub-region reads its parent's slice of the national files and its parent's OpenStreetMap extract, clipped with osmium-tool. Its first build takes its history from its parent's older packs (only its own area). The publish job then puts each parent's sub-regions together again under the parent's keys (`placepacks.combine`).
  - It publishes to the release `packs`, in this order:
    1. the new packs, under dated file names;
    2. the previous list, as `packs-previous.json`;
    3. the new list, `packs.json`, last.
  - It then deletes files that neither list names. A program never sees a list naming a file that is not there.
- **Keys:** only the repository's own `GITHUB_TOKEN` is used.
- **Keep-alive:** GitHub turns off scheduled workflows in repositories with no activity for 60 days. Each run
  commits an updated `sources-status.md`, which keeps the schedule alive.

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
