# Place packs status, 2026-11-09

4 packs published, 0.11 GB in all. Each pack is a collective database; see LICENSES.md for the licences and attributions.

| Pack | Built | Size (MB) | History from | Sources |
|---|---|---|---|---|
| us-rhode-island | 2026-11 | 11.3 | 2026-11 | census-cousub, census-places, census-zcta, gnis, nces-schools, osm, tiger-addrfeat, wikidata |
| us-rhode-island-extra | 2026-11 | 25.6 | 1637-01 | census-cousub, census-places, census-zcta, gnis, nces-schools, osm, tiger-addrfeat, wikidata |
| us-vermont | 2026-11 | 23.3 | 2026-11 | census-cousub, census-places, census-zcta, gnis, nces-schools, osm, tiger-addrfeat, wikidata |
| us-vermont-extra | 2026-11 | 45.3 | 1717-01 | census-cousub, census-places, census-zcta, gnis, nces-schools, osm, tiger-addrfeat, wikidata |

## Sources of each pack

Each source of the last build of each pack: ok (with its rows), skipped (why) or failed (why).

| Pack | Source | Status | Rows or reason |
|---|---|---|---|
| us-rhode-island | census-cousub | ok | 40 |
| us-rhode-island | census-places | ok | 36 |
| us-rhode-island | census-zcta | ok | 124 |
| us-rhode-island | nad | failed | the national file was not downloaded by the prepare job |
| us-rhode-island | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-rhode-island |
| us-rhode-island | osm | ok | 2026-11-08T21:21:00Z |
| us-rhode-island-extra | faa-airports | skipped | needs a hand-supplied file in inputs/faa |
| us-rhode-island-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-rhode-island-extra | gnis | ok | 944 |
| us-rhode-island-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-rhode-island-extra | imls-libraries | skipped | needs a hand-supplied file in inputs/imls |
| us-rhode-island-extra | nces-schools | ok | 395 |
| us-rhode-island-extra | nrhp | skipped | needs a hand-supplied file in inputs/nrhp |
| us-rhode-island-extra | ntad-amtrak | skipped | needs a hand-supplied file in inputs/ntad |
| us-rhode-island-extra | overture-places | failed | Binder Error: Referenced table "categories" not found!
Candidate tables: "read_parquet"
LINE 1: ...LECT id AS key, names.primary AS name, categories.primary AS cls, bbox.ymin AS...
                                                  ^ |
| us-rhode-island-extra | padus | skipped | needs a hand-supplied file in inputs/padus/RI |
| us-rhode-island-extra | tiger-addrfeat | ok | 62681 |
| us-rhode-island-extra | wikidata | ok | 580 |
| us-vermont | census-cousub | ok | 256 |
| us-vermont | census-places | ok | 180 |
| us-vermont | census-zcta | ok | 449 |
| us-vermont | nad | failed | the national file was not downloaded by the prepare job |
| us-vermont | openaddresses | skipped | needs a hand-supplied file in inputs/openaddresses/us-vermont |
| us-vermont | osm | ok | 2026-11-08T21:21:00Z |
| us-vermont-extra | faa-airports | skipped | needs a hand-supplied file in inputs/faa |
| us-vermont-extra | fsq-places | failed | no release found in https://fsq-os-places-us-east-1.s3.us-east-1.amazonaws.com |
| us-vermont-extra | gnis | ok | 1976 |
| us-vermont-extra | gtfs | skipped | no feed of this region in the Mobility Database lists an open licence |
| us-vermont-extra | imls-libraries | skipped | needs a hand-supplied file in inputs/imls |
| us-vermont-extra | nces-schools | ok | 561 |
| us-vermont-extra | nrhp | skipped | needs a hand-supplied file in inputs/nrhp |
| us-vermont-extra | ntad-amtrak | skipped | needs a hand-supplied file in inputs/ntad |
| us-vermont-extra | overture-places | failed | Binder Error: Referenced table "categories" not found!
Candidate tables: "read_parquet"
LINE 1: ...LECT id AS key, names.primary AS name, categories.primary AS cls, bbox.ymin AS...
                                                  ^ |
| us-vermont-extra | padus | skipped | needs a hand-supplied file in inputs/padus/VT |
| us-vermont-extra | tiger-addrfeat | ok | 89718 |
| us-vermont-extra | wikidata | ok | 1164 |
