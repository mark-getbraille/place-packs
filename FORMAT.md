# The pack format (version 2)

A pack is one SQLite file. Coordinates are whole microdegrees. Months are YYYYMM numbers (202611). Every record has
`first` and `last`: the months it was first and last seen (see the README, "History").

| Table | Columns | What |
|---|---|---|
| meta | key, value | format (`digital-accessibility-toolkit-osm-place-pack`), version (2), region_id, region_name, country, part (core or extra), built_month, builds (every build month, comma-separated), history_start, bounds (south,west,north,east), counts, notice, sources_used, sources_missing |
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
| notes | id, text | short notes about places, each once ("filming location of ..."); data only, never spoken |
| point_notes | id, note | a point's note: points.id -> notes.id |
| labels | key, lang, name | only in the optional "names" part: a place's name in another language, by the key of the place in the main packs ("wikidata:Q42", "fr", "Lac Champlain") |

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
never spoken.

## Parts: core, extra and names

A region has up to three packs: core (OpenStreetMap, addresses, address ranges, Census areas), extra (everything
else) and the optional names part (`us-vermont-names.osmpack`, key `us-vermont-names` in packs.json). The names part
holds only the `labels` table: the names of the region's Wikidata places in French, Spanish, German, Italian, Dutch,
Japanese and Chinese. A program downloads it only when its user turns on other languages
(`download.ensure_pack(region, part="names")`) and reads it with `PackReader.labels(key)`; the core and extra packs do
not change size. The names are data only.

