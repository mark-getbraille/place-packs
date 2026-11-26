# The pack format (version 2)

A pack is one SQLite file. Coordinates are whole microdegrees. Months are YYYYMM numbers (202611). Every record has
`first` and `last`: the months it was first and last seen (see the README, "History").

| Table | Columns | What |
|---|---|---|
| meta | key, value | format (`digital-accessibility-toolkit-osm-place-pack`), version (2), region_id, region_name, country, part (core, extra, names, businesses or addresses), parent (a sub-region's parent region, else empty), combined_from (a parent's pack put together from its sub-regions: their ids), built_month, builds (every build month, comma-separated), history_start, bounds (south,west,north,east), counts, notice, sources_used, sources_missing |
| sources | id, name, short, kind, part, licence, licence_url, attribution, url, version, date, history_start, history_note | one row per source of the pack |
| points | id, key, source, name, cls, tag, lat, lon, cell, ccell, first, last | named points |
| areas | id, key, source, name, cls, tag, minlat, minlon, maxlat, maxlon, size (m²), rings, first, last | named areas; rings: int32 (lat, lon) pairs, rings separated by (0, 0); even-odd rule |
| lines | id, key, source, name, cls, tag, minlat, minlon, maxlat, maxlon, pts, first, last | named streets and paths |
| ranges | id, key, source, name (street), cls, lfrom, lto, rfrom, rto, zip, minlat..maxlon, pts, first, last | address ranges (TIGER/Line) |
| address_cells | cell, streets, data | address points of one fine cell: streets is a JSON list of "street\|town\|source"; data is zlib-compressed records `<HHHHH` (dlat, dlon from the cell's south-west corner, street index, first and last as months since January 2000) followed by the house number (a length byte and UTF-8) |
| grid | level, cell, what, id | which areas (a), lines (l) and ranges (r) touch each fine (level 1, 1/100 degree) or coarse (level 0, 1/10 degree) cell |
| removals | key, reason, date | records removed for a licence problem or a takedown |
| types | id, name | the fine type phrases of the pack, each once ("pizza restaurant", "hardware store", "catholic church", "lighthouse"); since November 2026, absent in older packs |
| point_types | id, type | a point's fine type: points.id -> types.id (only typed points have a row) |
| area_types | id, type | an area's fine type: areas.id -> types.id |
| brands | id, name, wikidata | the chain brands of the pack, each once ("Made-up Burgers", "Q9999901"; wikidata may be ""); since November 2026, absent in older packs |
| point_brands | id, brand | a chain location's brand: points.id -> brands.id |
| biz_details | id, phone, website, opening_hours | only in the businesses part, since November 2026 (absent in older packs): a business's contact details, points.id -> its phone, web address and opening hours ("Business contact details") |
| notes | id, text | short notes about places, each once ("filming location of ..."); data only, never spoken |
| point_notes | id, note | a point's note: points.id -> notes.id |
| labels | key, lang, name | only in the optional "names" part: a place's name in another language, by the key of the place in the main packs ("wikidata:Q42", "fr", "Lac Champlain") |
| svc_* | (below) | only in the optional "services" part: offices and services, NWS zones and NOAA Weather Radio ("The services part") |
| nav_* | (below) | only in the optional "navigation" part: the street network, crossings, accessibility details and transit timetables ("The navigation part") |

Fine cell: `floor((lat + 90) * 100) * 36000 + floor((lon + 180) * 100)`. Coarse cell: the same with 10 and 3600.
Classes (`cls`): park, cemetery, landmark, campus, water, nature, neighbourhood, region, admin, town, county, zip,
street, building, business, public, transit, settlement, variant, airspace, note. (airspace: FAA special use airspace,
data only, never spoken; note: a row that only carries a note for the place with the same key, never a place
itself; cemetery since November 2026: cemeteries were park
before; county: the Newberry atlas's dated county versions; variant: a former or other name of a feature (GNIS),
kept for name search and never said as a place's name.) Lines have the class street (streets), trail, water
(rivers), rail, byway (National Scenic Byways) or geoline (the Equator, tropics, polar circles and date line: data
only, never spoken); a lookup names a trail, river or railway within 60 m ("on the Appalachian Trail", "beside the
Deerfield River") only when nothing nearer names the place.

## Fine types (added November 2026, still version 2)

Besides its coarse class (`cls`), a point or an area may have a fine type: a short, lower-case English phrase such as
"pizza restaurant", "hardware store", "elementary school", "catholic church", "lighthouse" or "winery". The phrases
come from each source's own type field (OpenStreetMap's amenity, shop, cuisine, craft, tourism, leisure,
healthcare, man_made, historic, religion and denomination tags; Overture's and Foursquare's categories; NAICS codes
and licence categories; the FSA's business types; GNIS classes; Wikidata's class labels) through the tables in
`placepacks/types.json`. Each phrase is stored once in `types`; `point_types` and `area_types` link rows to it, so a
typed point costs about 11 bytes (about 5% of a pack that is mostly points).

The types are in separate tables on purpose: the points and areas tables keep exactly the columns of version 2, so
readers and pack merges made before types existed (they select the columns they know, and copy rows between packs
by the new pack's columns) read and update new packs unchanged; the pack version stays 2. Readers that know types
join the links (`SELECT p.*, t.name FROM points p LEFT JOIN point_types l ON l.id = p.id LEFT JOIN types t ON
t.id = l.type`); a pack without the tables has no types.

Each dated row keeps its own type: a spot that was "Tony's Pizza" (pizza restaurant) in 2005 and "Sally's Ice
Cream" (ice cream shop) in 2020 has two rows, each with its type. Where several sources describe the same place, a
lookup gives the most specific of their types ("pizza restaurant" over "restaurant").

## Brands (added November 2026, still version 2)

A chain's location may carry its brand: the brand's name and its Wikidata id (from OpenStreetMap's `brand` and
`brand:wikidata` tags, Overture's brand fields, All The Places and the licence lists that give one). As with types,
each brand is stored once in `brands` and linked from `point_brands`, so the points table keeps its version 2
columns and older readers and merges are unaffected. The brand is data for future programs: no phrase or
description uses it (a lookup says the store's own name, "Made-up Burgers Main Street").

## Several businesses at one address (lookup rule, November 2026)

No pack change: the lookup counts only the businesses valid at the picture's date, treats the same normalised name
(or the same brand) within 50 m as one business from several sources (with the earliest first and latest last
month), and, when two or more are within 15 m of each other with none clearly nearest (or within the picture's GPS
accuracy), names the mall, plaza, campus or building area holding them, else the address, else the street. The
candidates are in `Result.others` (name, type, brand, distance), data only, never spoken.

## Notes on places (added November 2026, still version 2)

A point may carry a short note, stored once in `notes` and linked from `point_notes` like the types and brands.
Wikidata's filming locations ("filming location of A; B; C") are written as rows of class `note` with the place's own
key (`wikidata:Q...`), so a lookup that names the place gives `Result.note`; the note is data for future programs,
never spoken. Some sources put a note on their own points (the tabular reader's "note_column"): the accessibility
descriptions of BLM's accessible recreation sites ("Accessibility: accessible vault toilet; firm gravel path ...")
and the access descriptions of New York's career centers. E-mail addresses and telephone numbers are taken out of
every such note, and it is cut to about 1,200 characters.

## Business contact details (added November 2026, still version 2)

The businesses part may have a table `biz_details (id INTEGER PRIMARY KEY, phone TEXT, website TEXT,
opening_hours TEXT)`: the contact details of a business point, by its `points.id` (like `point_types`). A column a
source does not give is NULL; a point without any details has no row; a pack in which no point has any has no
table. Written by `placepacks/writer.py` (`PackWriter.add_point(..., contact=...)`, cleaned by
`placepacks/contact.py`), read by `PackReader.details_of(key)` and by the "nearest" lookups (`placepacks.find`,
`placepacks.local`), which join it to the points.

Only the business directories give details (`contact.CONTACT_SOURCES`), and only these fields:

| Source | phone | website | opening_hours |
|---|---|---|---|
| All The Places (`alltheplaces`) | `phone` (or `contact:phone`) | `website` (or `contact:website`) | `opening_hours` (OpenStreetMap syntax) |
| Chain store locators (`chain-locators`, `placepacks/chains`) | `phone` | `website` (the store's own page) | `opening_hours` (OpenStreetMap syntax) |
| Overture places (`overture-places`) | the first of `phones` | the first of `websites` | none |
| Foursquare OS Places (`fsq-places`) | `tel` | `website` | none |

Never kept: e-mail addresses (no source's e-mail column is read; a value with "@" is dropped), social-media accounts
(Overture's `socials`, Foursquare's `facebook_id`, `instagram`, `twitter`, and a website that is a social-media
page), and any detail of a licence, permit or inspection list (their phone numbers are often an owner's personal
number: the writer ignores details from any other source). A record the readers leave out (All The Places'
individuals' offices and person names; a chain's own brand, such as "Burger King", is not taken for a person's name)
has nothing; a record of Overture or Foursquare whose name looks like a
person's ("Alice Example") or whose type is an individual's own office (insurance or estate agent, lawyer, financial
adviser, accountant) is kept as a place but without details.

How values are made small: the first phone number only, without "tel:" or an extension, 7 to 15 digits, a North
American number written "802-555-0100" (other numbers keep their own spacing); the first web address only, http or
https, at most 200 characters, without its "#" part or a lone trailing "/", and dropped when its query has a
tracking key (`utm_...`, `fbclid`, `gclid` and the like) or it holds a user name; opening hours trimmed to 255
characters. When a lesser source lists the same business (the same name in lower case, within about 100 m in the same
fine cell) with the same value as a better one (All The Places, then the chain store locators, then Overture, then
Foursquare), its copy is left
out, since a lookup takes each detail from the best source.

History: details belong to the record listed now. Only this month's records get a row; an older row kept as history
(a business renamed, moved or closed) is copied without its details, so "Tony's Pizza (now Sally's Ice Cream)" has
Sally's phone only, and a business no longer listed has none. `details_of(key)` reads the newest row of the key.

Older readers and packs: the points table keeps its version 2 columns, so readers and merges made before
`biz_details` read new packs unchanged (they do not see the table), and new readers read older packs (no table: no
details). The pack version stays 2, as for the types, brands and notes: a reader refuses any other version, so a
new version would stop every installed program from reading the new packs.

When several sources list one place, a lookup takes each detail from the best source that has it: OpenStreetMap's
own (the services part's `svc_details` and office details), then All The Places, the chain store locators, Overture
and Foursquare
(`lookup.join_details`). Size: about 50 bytes for each business of the directories on average (measured on a
made-up pack with 70% phones, 55% web addresses and All The Places' hours; most of it is the web address), so a
businesses part grows by about a quarter; the licence lists' points add nothing.

## Utility service areas (November 2026, no pack change)

The extra part has the service areas of community water systems (EPA, `epa-water-service-areas`) and the retail
territories of electric utilities (`electric-retail-territories`) as areas of class `region` with the fine types
"water utility service area" and "electric utility service area". Like every `region` area, they are never said as
the name of a place; `Finder.areas_at(lat, lon)` lists them, so a program can say which water utility and which
electric company serve a place. EPA's water areas are partly modelled, so they are estimates.

## Parts: core, extra, names, businesses and addresses

A region has up to seven packs, each with the same tables (the navigation and services parts add their own, below):

| Part | File and key | What | Downloaded |
|---|---|---|---|
| core | `us-vermont.osmpack`, `us-vermont` | OpenStreetMap (towns, streets, landmarks) and the Census areas; no address points | always |
| extra | `us-vermont-extra.osmpack`, `us-vermont-extra` | history and the smaller lists: Wikidata, GNIS, public facilities, landmarks, transit, trails, historic areas | always |
| businesses | `us-vermont-businesses.osmpack` | Overture places, All the Places, the IRS's exempt organizations and every business list (inspections, licences, bank branches, the UK's food hygiene ratings) | when needed |
| addresses | `us-vermont-addresses.osmpack` | address points (NAD, ODA, OpenAddresses, BAN, BAG, LINZ, ...) and address ranges (TIGER/Line, NRN), with their history | when needed |
| names | `us-vermont-names.osmpack` | other-language names (below) | on request |
| navigation | `us-vermont-navigation.osmpack` | the street network, crossings, accessibility details and transit timetables (below) | on request |
| services | `us-vermont-services.osmpack` | offices and services, weather zones and NOAA Weather Radio (below) | on request |

A program downloads core and extra (`fmt.DEFAULT_PARTS`); businesses and addresses (`fmt.DETAIL_PARTS`) only when a
lookup needs them, at the detail "address" or for the exact place in a picture's name, or when the user asks for full
detail (`download.parts_for(detail, full)`, `download.ensure_packs(region, detail=...)`). A lookup works with whatever
parts are there: without the businesses and the addresses it names the landmark, the street or the town. Programs
made before businesses and addresses existed know only core and extra and leave the other entries of packs.json
out.

Where they are published: core and extra in the release `packs` (with packs.json); the names, businesses and
addresses of each publish in a release of their own, `packs-detail-YYYYMMDD` (GitHub allows 1000 files in one
release). Each packs.json entry names its file (`name`, dated: `us-vermont-addresses-20261102.osmpack`) and its
`release` (`manifest.release_for`; an entry without one is in `packs`); `download.Catalogue.url_for` gives the
address. packs.json is at most 4 MB (`manifest.LIMIT`): it is written compact, and only the core entry lists every
source of its region; the other parts list only their own.

### Sub-regions

A region whose core and extra together would be larger than about 300 MB is built as sub-regions (regions.json
"children"): England's nine regions (`gb-england-south-east`), Australia's states and territories
(`au-new-south-wales`), groups of counties of Texas, California, New York and Florida (`us-texas-gulf-coast`), parts of
Ontario and Quebec (`ca-ontario-toronto`), and the provinces or counties of the Netherlands, Sweden, Norway and
Finland, put in two groups each (`nl-netherlands-west`). Each child has its own packs of every part, and meta `parent`. Every
position of the parent's own land (and the water next to it) belongs to exactly one child (its grid cells,
`regions.in_region`); a position in a neighbour, even inside the parent's box, belongs to none; a pack also keeps
what lies within about 2 km of its border (`writer.CLIP_MARGIN`) and every street or area that crosses it, so a
lookup near a border works with either pack, and `regions.regions_near` gives both. The parent id is still accepted:
`download.ensure_pack("gb-england")` downloads the children's packs. packs.json also keeps a core and an extra pack
under the parent's own keys, the children's packs put together (`placepacks.combine`, meta `combined_from`), for
programs that know only the parent.

### The names part

The names part (`us-vermont-names.osmpack`, key `us-vermont-names` in packs.json)
holds only the `labels` table: the names of the region's Wikidata places in French, Spanish, German, Italian, Dutch,
Japanese and Chinese. A program downloads it only when its user turns on other languages
(`download.ensure_pack(region, part="names")`) and reads it with `PackReader.labels(key)`; the core and extra packs do
not change size. The names are data only.


### The navigation part (added November 2026, still version 2)

The navigation part (`us-vermont-navigation.osmpack`, key `us-vermont-navigation`) is for getting around on foot
and by transit. It is downloaded only on request (`download.ensure_pack(region, part="navigation")`, or
`download.parts_for("navigation")`), like the names part, and is in the detail release of its publish. It has the
usual meta and sources tables (and empty places tables, so every reader opens it) and these tables of its own,
written by `placepacks/navigation.py` and read by `placepacks/navigate.py`. It has no history: each build writes the
network and the timetables as they are (`build.previous_files` gives none).

From the region's OpenStreetMap extract (source `osm-navigation`, the same file as the core part's; ODbL 1.0, like
the core part's OpenStreetMap layer):

| Table | Columns | What |
|---|---|---|
| nav_ways | id, key ("w123"), name (or route number), kind (OSM highway value), tags (JSON), minlat, minlon, maxlat, maxlon, pts | street and path segments: every highway a person can walk or that has a name, without unnamed driveways and parking aisles, tracks, private roads and roads being built; tags keep the walking details (sidewalk, sidewalk:left/right/both, footway, surface, smoothness, lit, incline, width, wheelchair, tactile_paving, step_count, handrail, ramp, kerb, crossing tags on crossing ways, maxspeed, lanes, oneway, bridge, tunnel) |
| nav_grid | level, cell, way | which segments touch each fine (level 1) or coarse (level 0) cell |
| nav_nodes | node (OSM node id), lat, lon, cell | the routing graph's nodes: where segments meet, and their ends |
| nav_edges | id, a, b (nav_nodes), way (nav_ways id), length (metres), b1, b2 (bearings in degrees: leaving a, arriving at b) | the routing graph: each segment split where it meets another (placepacks/route.py searches it) |
| nav_intersections | id, key ("n123"), lat, lon, cell, streets (JSON list, sorted), signals (1 when the node has traffic signals) | where streets with different names meet (footpaths and steps do not count as cross streets) |
| nav_features | id, key, kind, name, lat, lon, cell, tags (JSON), streets (JSON list of the ways the node lies on) | crossing, traffic signals, kerb (curb cuts: kerb=lowered or flush), tactile paving, steps, ramp, elevator, entrance (wheelchair, door, automatic_door), bus stop and tram stop (shelter, bench, bin, lit, tactile_paving, departures_board), platform, accessible place (a named place with wheelchair=*); the tags keep crossing, crossing:markings, crossing:signals, crossing:island, button_operated and the accessible pedestrian signal tags (traffic_signals:sound, :vibration, :arrow, :minimap) |

From the region's open GTFS feeds (source `gtfs-navigation`, the same feeds as the extra part's transit stops, each
under its own open licence, recorded in nav_feeds):

| Table | Columns | What |
|---|---|---|
| nav_feeds | feed, provider, licence_url, timezone, start, end | one row per feed: the agency, its licence address, its time zone (the times below are its local time) and the dates its timetables cover (YYYYMMDD) |
| nav_stops | id, key ("gtfs:feed:stop"), feed, stop_id, name, code, lat, lon, cell, wheelchair (GTFS wheelchair_boarding: 0 unknown, 1 yes, 2 no), location_type (0 stop, 1 station), parent, platform | stops and stations in the region |
| nav_routes | id, feed, route_id, short_name, long_name, type (GTFS route_type), agency | routes |
| nav_services | id, feed, service_id, days (bit 0 Monday ... bit 6 Sunday), start, end | the days each timetable runs |
| nav_service_dates | service, date, added (1 added, 0 removed) | calendar_dates.txt exceptions |
| nav_trips | id, route, service, headsign, direction, wheelchair (GTFS wheelchair_accessible), bikes | trips |
| nav_times | stop, time (seconds after the timetable day's midnight; over 86400 after midnight), trip | every departure (WITHOUT ROWID, by stop and time) |

The lookups (`placepacks.navigate.Navigator`): `nearest_intersection(lat, lon)`, `crossing_here(lat, lon)` (the
crossing's type, the street it crosses, signals, push button, accessible pedestrian signal, tactile paving, kerb,
island), `street_here(lat, lon)` (sidewalks, surface, lighting, steps), `features_near(lat, lon, metres, kinds)`,
`nearest_stops(lat, lon)`, `stop_amenities(lat, lon)` and `next_buses(lat, lon, when)` (the next departures from the
nearest stop with service, wheelchair boarding and each trip's wheelchair access). Each returns the facts and a
plain sentence ("phrase"); where the map does not say, the fact is None and nothing is said.

### The services part (added November 2026, still version 2)

The services part (`us-vermont-services.osmpack`, key `us-vermont-services`) holds what a person needs to find a
public office or to follow a weather emergency. Like the navigation part it is downloaded only on request
(`download.ensure_pack(region, part="services")`), is in the detail release, and has no history. Written by
`placepacks/services.py`, read by `placepacks/local.py`.

| Table | Columns | What |
|---|---|---|
| svc_places | id, key, source, kind, name, lat, lon, cell, ccell, details (JSON: phone, opening_hours, website, addr:*, wheelchair, operator, description) | offices and services from OpenStreetMap (source `osm-services`, ODbL): Social Security office, Service Canada centre, motor vehicle office, veterans office, courthouse, post office, library, pharmacy, food bank, soup kitchen, shelter, social services, hospital, clinic, police, fire station, town hall, government office, community centre, defibrillator (`services.SERVICE_KINDS`) |
| svc_zones | id, key, source, kind ("county" or "forecast zone"), code (county FIPS, or the zone "VTZ006"), name, state, office (the NWS forecast office), minlat, minlon, maxlat, maxlon, rings | the National Weather Service county areas and public forecast zones of the region's state (public domain) |
| svc_details | key ("n123", the key of the place's point in the core part), phone, opening_hours, website, wheelchair | what OpenStreetMap says about any named shop, amenity, craft, office or the like, for every search (placepacks/find.py) |
| svc_polling | id, key, source, election_date (YYYY-MM-DD), election ("general election"), county, jurisdiction, precinct, name, address, lat, lon (null when the address could not be located), ccell, located ("address", "street" or "not located") | polling places of the newest past election the Center for Public Integrity's lists have for the state (CC BY 4.0), located by the offline geocoder; always said with the election's date |
| svc_radio | id, call_sign, frequency (MHz), site, site_state, lat, lon, power (watts), status, office, same (the county's SAME code, "050007"), county, state, remarks | every NOAA Weather Radio transmitter covering each county of the region's state (the county coverage list, public domain) |

The lookups (`placepacks.local.LocalServices`): `nearest(lat, lon, kind)` (a kind or a plain word such as "DMV" or
"Social Security"; it also searches the core and extra parts' places of the same type, such as the IMLS libraries
and the HRSA health centres, and gives a place listed by several sources once), `weather_zone(lat, lon)` (the
county, its SAME code, the forecast zone and office) and `weather_radio(lat, lon)` (the transmitters covering the
county, nearest first, with their frequencies and status).

### Finding places and directions (November 2026, no pack change beyond the tables above)

`placepacks.find.find_nearest(kind, start, mode="walk")` finds the nearest place of a kind from a start (a position,
"Main Street and Elm Street", or "12 Main Street, Town") in every downloaded pack: by the fine types of the core,
extra and businesses parts (plain words and synonyms: "hardware store" also finds home improvement stores,
"drugstore" pharmacies, "grocery" supermarkets; "Catholic church", "Baptist church", "mosque", "synagogue" by the
religion and denomination types), the services part's offices ("Social Security", "DMV") and its polling places
(said with their election date and a warning that polling places change). The phone, opening hours, website and
wheelchair access come from svc_details where OpenStreetMap has them, else from the businesses part's biz_details
("Business contact details"). It then asks `placepacks.route.directions`
for the way there: our own A* search over nav_nodes and nav_edges (no routing library; a small cost for each turn,
so the directions have fewer turns), described in plain speech: the street and direction, the distance in blocks
and feet, the cross street reached, each street crossed with its crossing's signal, push button, accessible signal,
tactile paving and curb cut, the turns, and on which side the place is. mode "drive" keeps to roads and respects
one-way streets; mode "transit" gives the first direct ride (no transfer) from a stop near the start to a stop near
the place, with the walks to and from the stops.
