# Licences

## The code

The code of this repository (the `placepacks` package, the tools and the workflows) is under the MIT licence
(`LICENSE`).

## The data: each pack is a collective database

A pack mixes OpenStreetMap with other open data. OpenStreetMap is under the Open Database License (ODbL) 1.0, which
is share-alike: a database *derived* from OpenStreetMap must be offered under the ODbL. The other sources have
their own licences (public domain, CC0, PDDL, CC BY 4.0, the Open Government Licences of Canada and the UK, Licence
Ouverte 2.0, CDLA Permissive 2.0, Apache 2.0, CC BY 3.0, the open-use terms of New York City's and New York State's
open-data portals, the Newberry Library's open terms, and Florida's public records).

We chose to make each pack a **collective database** (ODbL 1.0, section 1, "Collective Database"; section 4.5),
not one database under a single licence:

- **The OpenStreetMap layer** (rows with `source = 'osm'`) is a database derived from OpenStreetMap: its named
  places, areas and streets, simplified. It is offered under the **ODbL 1.0** (`LICENSES/ODbL-1.0.txt`),
  © OpenStreetMap contributors. Anyone may obtain it with the pack and rebuild it with this repository's code.
- **Every other layer** is an independent database kept in its own rows (its `source` column says which), under its
  **own licence** (`SOURCES.md` and the pack's `sources` table, with its attribution text).
- **The navigation part's OpenStreetMap layer** (`source` `osm-navigation`: the nav_ways, nav_grid,
  nav_intersections and nav_features tables) is also a database derived from OpenStreetMap, made from the same
  extract: under the **ODbL 1.0**, © OpenStreetMap contributors, offered whole in the pack and rebuilt with this
  repository's code. Its transit tables (nav_feeds to nav_times, source `gtfs-navigation`) are not made from
  OpenStreetMap: each feed keeps its own open licence (nav_feeds.licence_url). The lookups only read the two side by
  side (a stop's shelter is read from the nearest OpenStreetMap bus stop when the answer is given); the build does
  not merge them.
- **The services part's OpenStreetMap layer** (`source` `osm-services`: the svc_places table) is likewise derived
  from OpenStreetMap and under the **ODbL 1.0**. Its weather tables (svc_zones, svc_radio) come from the National
  Weather Service (public domain) and are not made from OpenStreetMap.
- **Polling places** (svc_polling, source `cpi-polling-places`): the Center for Public Integrity's U.S. Polling Places
  dataset, **CC BY 4.0**, credited in the sources table; located with the region's address points (not with
  OpenStreetMap). The directions (placepacks/route.py) are this repository's own code (MIT); no routing library is
  used.
- **No other layer is made from OpenStreetMap data.** The build never uses OpenStreetMap to filter, correct, match or
  merge another source, so the other layers are not derived from it, and the share-alike terms do not extend to
  them. Layers are combined only when a program looks a position up (the result is a "Produced Work" under the
  ODbL, and the programs say "© OpenStreetMap contributors" whenever an OpenStreetMap name is used).
- The non-OpenStreetMap layers are matched only with themselves across months (their history) and with other
  non-OpenStreetMap layers.

Why not put everything under the ODbL? Several sources would allow it (public domain, CC0), but others ask for their
own licence text or notices to travel with the data (CDLA Permissive 2.0, Apache 2.0, the Open Government
Licences), and relicensing everyone's permissive data as share-alike would restrict what users can do with it. A
collective database keeps each source's terms exactly.

## Attribution

Wherever the data is shown, credit the sources used, for example "© OpenStreetMap contributors; National Address
Database (USDOT); Overture Maps Foundation". The exact text of each source is in `SOURCES.md` and in every pack
(`sources.attribution`). The release `packs` also carries `NOTICE` (Foursquare's and Overture's notices) and the
licence texts in `LICENSES/`; they cover the packs of the `packs-detail-YYYYMMDD` releases too, which packs.json in
`packs` lists.

## Conditions passed on

- **National Address Database (US):** state laws forbid using it as a mailing list. The packs are for naming places.
- **Foursquare Open Source Places:** keep `NOTICE` with any copy of the data in files (Apache 2.0, section 4). The
  build reads Foursquare's own files from the release `uploaded-sources`, where the owner's Program Downloader
  uploads them unchanged from the Hugging Face dataset `foursquare/fsq-os-places`, each month with Foursquare's
  `NOTICE.txt` (`fsq-<date>-NOTICE.txt`) and its text in the manifest (`fsq-<date>.json`); the prepare job warns
  when that text is not all in this repository's `NOTICE`.
- **CDLA Permissive 2.0 (Overture):** share the licence text with the data.
- **New York City Open Data:** NYC Administrative Code 23-502(d) makes the data available without licence
  requirements or restrictions on use, but lets the City ask that the source and version be named: the pack's
  sources table names the dataset (43nn-pn8j, w7w3-xahh) and its version (rowsUpdatedAt).
- **New York State (OPEN-NY):** no attribution is required; the State may ask anyone breaking its terms (unlawful
  use) to stop. The datasets are named in the attribution all the same.
- **Portal "Public Domain" marks (Austin, Delaware, Montgomery County MD, Colorado, Cincinnati, Baton Rouge):** the
  publishing government marks the dataset public domain on its portal; the packs name it anyway.
- **The Newberry Library (Atlas of Historical County Boundaries):** "available ... for any lawful purpose,
  commercial or non-commercial, without licensing or permission fees"; credit the Atlas and the Newberry Library.
  The Creative Commons note inside the older download is superseded by those terms.
- **CC BY 4.0 city data (Washington DC):** credit the District of Columbia as in `SOURCES.md`.
- **Open Government Licence - Toronto (DineSafe):** "Contains information licensed under the Open Government
  Licence - Toronto".
- **Open Government Licences of British Columbia and Ontario (provincial parks):** "Contains information licensed
  under the Open Government Licence - British Columbia" / "- Ontario".
- **Marine Regions (VLIZ), CC BY 4.0:** the global water layer (`placepacks/data/water.json.gz`) adds Marine
  Regions' bays and gulfs; credit "Marine Regions (VLIZ), CC BY 4.0" wherever the water layer's names are shown.
- **Canadian provincial and city licences (Calgary, Edmonton, Nova Scotia, Vancouver, New Brunswick, Saskatchewan,
  Manitoba, Newfoundland and Labrador):** each grants a worldwide, royalty-free licence to copy, modify and
  redistribute, commercial use included; the packs carry each one's "Contains information licensed under ..." line.
- **Québec (Données Québec), Atlanta Regional Commission, GeoNames, Marine Regions:** CC BY 4.0, credited as in
  `SOURCES.md`.
- **US Post Offices 1639-2000 (Blevins and Helbock), Columbus Public Health, New Orleans, Connecticut DEEP:** CC0.
- **Florida DBPR licence files (food service, alcohol, tobacco):** no licence is stated. They are public records
  under Chapter 119, Florida Statutes, and Florida agencies generally cannot claim copyright in public records without
  a statute that allows it (Microdecisions, Inc. v. Skinner, Fla. 2d DCA 2004). The owner decided (26 November 2026)
  to treat them as public domain (licence `FL-public-records` in sources.json); the packs name the Department all
  the same.
- **Baltimore City liquor licences:** Creative Commons Attribution 3.0 Unported (`LICENSES/CC-BY-3.0.txt`); credit
  the Board of Liquor License Commissioners for Baltimore City as in `SOURCES.md`.
- **Sacramento County business licences, Wake County, Sioux Falls, Arlington TX, Washington DC (ABCA):** CC BY 4.0
  (Sacramento's layer also says public domain dedication; it is credited under CC BY 4.0 all the same).
- **Pennsylvania (data.pa.gov):** the portal marks its datasets "Public Domain U.S. Government" although they are
  state works; read as the portal's public domain mark.
- **NOAA National Marine Sanctuaries:** U.S. government material, identified as such (17 U.S.C. 403).
- **IRS exempt organizations:** only names and located points are kept, never the "in care of" (people's) names; an
  organization at a home address is placed on its street.
- **OpenHistoricalMap:** CC0, except features with their own `license` tag, which the packs leave out.
- **Personal data:** the business sources keep only a business's trade name, class, position and dates. Records
  that may be someone's home (home-based businesses, contractors, mobile caterers, childminders, short-term rentals,
  individual licences) and licensee names that look like a person's are left out; a sole proprietor whose trade name
  is their own name is left out (compared with the licensee's name, which is never kept), and an id that may hold a
  personal number (Texas taxpayer numbers) is kept only as a fingerprint; see `SOURCES.md`. A takedown
  request goes in `removals.json`.

## Removals

`removals.json` lists records removed for a licence problem or a takedown request. Nothing else is ever deleted from
the history.
