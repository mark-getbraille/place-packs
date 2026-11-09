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

Fine cell: `floor((lat + 90) * 100) * 36000 + floor((lon + 180) * 100)`. Coarse cell: the same with 10 and 3600.
Classes (`cls`): park, cemetery, landmark, campus, water, nature, neighbourhood, region, admin, town, county, zip,
street, building, business, public, transit, settlement. (cemetery since November 2026: cemeteries were park before;
county: the Newberry atlas's dated county versions.)

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
