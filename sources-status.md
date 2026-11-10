# Place packs status, 2026-11-10

10 packs published, 0.37 GB in all. Each pack is a collective database; see LICENSES.md for the licences and attributions.

| Pack | Built | Size (MB) | History from | Sources |
|---|---|---|---|---|
| gb-wales | 2026-11 | 37.8 | 2026-11 | fsa-hygiene, geonames, osm, overture-places |
| gb-wales-extra | 2026-11 | 76.1 | 55-01 | fsa-hygiene, geonames, osm, overture-places |
| us-delaware | 2026-11 | 11.7 | 2026-11 | census-cousub, census-places, census-zcta, delaware-food-inspections, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-delaware-extra | 2026-11 | 69.9 | 1638-01 | census-cousub, census-places, census-zcta, delaware-food-inspections, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-district-of-columbia | 2026-11 | 5.6 | 2026-11 | census-cousub, census-places, census-zcta, dc-business-licences, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-district-of-columbia-extra | 2026-11 | 25.4 | 1763-01 | census-cousub, census-places, census-zcta, dc-business-licences, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-rhode-island | 2026-11 | 11.4 | 2026-11 | census-cousub, census-places, census-zcta, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-rhode-island-extra | 2026-11 | 42.3 | 1637-01 | census-cousub, census-places, census-zcta, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, va-national-cemeteries, wikidata |
| us-vermont | 2026-11 | 23.5 | 2026-11 | census-cousub, census-places, census-zcta, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, usfs-recreation-sites, va-national-cemeteries, wikidata |
| us-vermont-extra | 2026-11 | 64.9 | 1666-01 | census-cousub, census-places, census-zcta, faa-airports, fdic-branches, fuds, gnis, imls-libraries, military-installations, nad, nbi-bridges, nces-postsecondary, nces-private-schools, nces-schools, nid-dams, nps-poi, nrhp, ntad-amtrak, ntad-ferry-terminals, osm, overture-places, padus, tiger-addrfeat, usfs-recreation-sites, va-national-cemeteries, wikidata |

## Sources of each pack

Each source of the last build of each pack: ok (with its rows), skipped (why) or failed (why).

| Pack | Source | Status | Rows or reason |
|---|---|---|---|
| gb-wales | os-open-names | skipped | needs a hand-supplied file in inputs/os-open-names |
| gb-wales | osm | ok | 2026-11-08T21:21:00Z |
| gb-wales-extra | fsa-hygiene | ok | 38937 |
| gb-wales-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| gb-wales-extra | geonames | ok | 7267 |
| gb-wales-extra | overture-places | ok | 274461 |
| gb-wales-extra | wikidata | failed | HTTP Error 504: Gateway Timeout |
| us-delaware | census-cousub | ok | 27 |
| us-delaware | census-places | ok | 79 |
| us-delaware | census-zcta | ok | 153 |
| us-delaware | nad | failed | could not be read: That compression method is not supported |
| us-delaware | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-delaware |
| us-delaware | osm | ok | 2026-11-08T21:21:00Z |
| us-delaware-extra | delaware-food-inspections | ok | 3663 |
| us-delaware-extra | faa-airports | ok | 22 |
| us-delaware-extra | fdic-branches | ok | 249 |
| us-delaware-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-delaware-extra | fuds | ok | 79 |
| us-delaware-extra | gnis | ok | 254 |
| us-delaware-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-delaware-extra | imls-libraries | ok | 33 |
| us-delaware-extra | military-installations | ok | 5 |
| us-delaware-extra | nbi-bridges | ok | 357 |
| us-delaware-extra | nces-postsecondary | ok | 19 |
| us-delaware-extra | nces-private-schools | ok | 90 |
| us-delaware-extra | nces-schools | ok | 378 |
| us-delaware-extra | newberry-counties | skipped | could not be downloaded: <urlopen error [Errno 110] Connection timed out> |
| us-delaware-extra | nid-dams | ok | 229 |
| us-delaware-extra | nps-poi | failed | read, but no rows matched (columns, filter or box) |
| us-delaware-extra | nrhp | ok | 1289 |
| us-delaware-extra | ntad-amtrak | ok | 10 |
| us-delaware-extra | ntad-ferry-terminals | ok | 8 |
| us-delaware-extra | overture-places | ok | 161160 |
| us-delaware-extra | padus | failed | ArcGIS error: Unable to perform operation. Too many large geometry non-cacheable requests. |
| us-delaware-extra | tiger-addrfeat | ok | 63274 |
| us-delaware-extra | uscg-light-list | skipped | could not be downloaded: HTTP Error 403: Forbidden |
| us-delaware-extra | usfs-recreation-sites | skipped | no record of the layer is in the region |
| us-delaware-extra | va-national-cemeteries | ok | 5 |
| us-delaware-extra | wikidata | ok | 1504 |
| us-district-of-columbia | census-cousub | ok | 1 |
| us-district-of-columbia | census-places | ok | 1 |
| us-district-of-columbia | census-zcta | ok | 105 |
| us-district-of-columbia | nad | failed | could not be read: That compression method is not supported |
| us-district-of-columbia | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-district-of-columbia |
| us-district-of-columbia | osm | ok | 2026-11-08T21:21:00Z |
| us-district-of-columbia-extra | dc-business-licences | ok | 13803 |
| us-district-of-columbia-extra | faa-airports | ok | 3 |
| us-district-of-columbia-extra | fdic-branches | ok | 178 |
| us-district-of-columbia-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-district-of-columbia-extra | fuds | ok | 69 |
| us-district-of-columbia-extra | gnis | ok | 94 |
| us-district-of-columbia-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-district-of-columbia-extra | imls-libraries | ok | 27 |
| us-district-of-columbia-extra | military-installations | ok | 12 |
| us-district-of-columbia-extra | nbi-bridges | ok | 99 |
| us-district-of-columbia-extra | nces-postsecondary | ok | 25 |
| us-district-of-columbia-extra | nces-private-schools | ok | 93 |
| us-district-of-columbia-extra | nces-schools | ok | 346 |
| us-district-of-columbia-extra | newberry-counties | skipped | could not be downloaded: <urlopen error [Errno 110] Connection timed out> |
| us-district-of-columbia-extra | nid-dams | ok | 4 |
| us-district-of-columbia-extra | nps-poi | ok | 73 |
| us-district-of-columbia-extra | nrhp | ok | 668 |
| us-district-of-columbia-extra | ntad-amtrak | ok | 2 |
| us-district-of-columbia-extra | ntad-ferry-terminals | ok | 4 |
| us-district-of-columbia-extra | overture-places | ok | 72288 |
| us-district-of-columbia-extra | padus | ok | 128 |
| us-district-of-columbia-extra | tiger-addrfeat | ok | 13355 |
| us-district-of-columbia-extra | uscg-light-list | skipped | could not be downloaded: HTTP Error 403: Forbidden |
| us-district-of-columbia-extra | usfs-recreation-sites | skipped | no record of the layer is in the region |
| us-district-of-columbia-extra | va-national-cemeteries | ok | 2 |
| us-district-of-columbia-extra | wikidata | ok | 963 |
| us-rhode-island | census-cousub | ok | 40 |
| us-rhode-island | census-places | ok | 36 |
| us-rhode-island | census-zcta | ok | 124 |
| us-rhode-island | nad | failed | could not be read: That compression method is not supported |
| us-rhode-island | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-rhode-island |
| us-rhode-island | osm | ok | 2026-11-08T21:21:00Z |
| us-rhode-island-extra | faa-airports | ok | 9 |
| us-rhode-island-extra | fdic-branches | ok | 248 |
| us-rhode-island-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-rhode-island-extra | fuds | ok | 80 |
| us-rhode-island-extra | gnis | ok | 976 |
| us-rhode-island-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-rhode-island-extra | imls-libraries | ok | 71 |
| us-rhode-island-extra | military-installations | ok | 9 |
| us-rhode-island-extra | nbi-bridges | ok | 148 |
| us-rhode-island-extra | nces-postsecondary | ok | 23 |
| us-rhode-island-extra | nces-private-schools | ok | 109 |
| us-rhode-island-extra | nces-schools | ok | 395 |
| us-rhode-island-extra | newberry-counties | skipped | could not be downloaded: <urlopen error [Errno 110] Connection timed out> |
| us-rhode-island-extra | nid-dams | ok | 365 |
| us-rhode-island-extra | nps-poi | ok | 1 |
| us-rhode-island-extra | nrhp | ok | 759 |
| us-rhode-island-extra | ntad-amtrak | ok | 3 |
| us-rhode-island-extra | ntad-ferry-terminals | ok | 42 |
| us-rhode-island-extra | overture-places | ok | 66066 |
| us-rhode-island-extra | padus | ok | 925 |
| us-rhode-island-extra | tiger-addrfeat | ok | 62681 |
| us-rhode-island-extra | uscg-light-list | skipped | could not be downloaded: HTTP Error 403: Forbidden |
| us-rhode-island-extra | usfs-recreation-sites | skipped | no record of the layer is in the region |
| us-rhode-island-extra | va-national-cemeteries | failed | read, but no rows matched (columns, filter or box) |
| us-rhode-island-extra | wikidata | ok | 632 |
| us-vermont | census-cousub | ok | 256 |
| us-vermont | census-places | ok | 180 |
| us-vermont | census-zcta | ok | 449 |
| us-vermont | nad | failed | could not be read: That compression method is not supported |
| us-vermont | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-vermont |
| us-vermont | osm | ok | 2026-11-08T21:21:00Z |
| us-vermont-extra | faa-airports | ok | 33 |
| us-vermont-extra | fdic-branches | ok | 219 |
| us-vermont-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-vermont-extra | fuds | ok | 10 |
| us-vermont-extra | gnis | ok | 1983 |
| us-vermont-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-vermont-extra | imls-libraries | ok | 186 |
| us-vermont-extra | military-installations | ok | 7 |
| us-vermont-extra | nbi-bridges | ok | 276 |
| us-vermont-extra | nces-postsecondary | ok | 16 |
| us-vermont-extra | nces-private-schools | ok | 164 |
| us-vermont-extra | nces-schools | ok | 561 |
| us-vermont-extra | newberry-counties | skipped | could not be downloaded: <urlopen error [Errno 110] Connection timed out> |
| us-vermont-extra | nid-dams | ok | 796 |
| us-vermont-extra | nps-poi | ok | 2 |
| us-vermont-extra | nrhp | ok | 1082 |
| us-vermont-extra | ntad-amtrak | ok | 19 |
| us-vermont-extra | ntad-ferry-terminals | ok | 8 |
| us-vermont-extra | overture-places | ok | 72931 |
| us-vermont-extra | padus | ok | 1755 |
| us-vermont-extra | tiger-addrfeat | ok | 89718 |
| us-vermont-extra | uscg-light-list | skipped | could not be downloaded: HTTP Error 403: Forbidden |
| us-vermont-extra | usfs-recreation-sites | ok | 253 |
| us-vermont-extra | va-national-cemeteries | ok | 2 |
| us-vermont-extra | wikidata | ok | 1200 |
