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

Fine cell: `floor((lat + 90) * 100) * 36000 + floor((lon + 180) * 100)`. Coarse cell: the same with 10 and 3600.
Classes (`cls`): park, landmark, campus, water, nature, neighbourhood, region, admin, town, zip, street, building,
business, public, transit, settlement.
