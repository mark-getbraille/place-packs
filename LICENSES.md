# Licences

## The code

The code of this repository (the `placepacks` package, the tools and the workflows) is under the MIT licence
(`LICENSE`).

`placepacks/data/first_names.txt` (used only to tell a person's name from a business's, never written into a pack)
comes from the US Census Bureau's 1990 first-name lists (dist.female.first, dist.male.first): a US government work in
the public domain.

## The data: each pack is a collective database

A pack mixes OpenStreetMap with other open data. OpenStreetMap is under the Open Database License (ODbL) 1.0, which
is share-alike: a database *derived* from OpenStreetMap must be offered under the ODbL. The other sources have
their own licences (public domain, CC0, PDDL, CC BY 4.0, the Open Government Licences of Canada and the UK, Licence
Ouverte 2.0, CDLA Permissive 2.0, Apache 2.0, CC BY 3.0, the open-use terms of New York City's and New York State's
open-data portals, the Newberry Library's open terms, Florida's public records, and the open-use terms of the
National Laboratory of the Rockies for the Alternative Fuels Data Center's stations).

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
- **Alternative Fuels Data Center stations (U.S. Department of Energy, served by the National Laboratory of the
  Rockies, formerly NREL):** the terms (developer.nlr.gov/terms) say the data "may be used for any purpose
  whatsoever". Two conditions travel with it: the names DOE, NLR and the Alliance for Energy Innovation may not be
  used to endorse or promote anything made with the data (the attribution says they do not endorse the packs), and
  the user indemnifies them against claims arising from the use and distribution of the data (licence
  `NLR-Data-Terms` in sources.json). The data comes as is, with no warranty.
- **NCUA credit union offices, CMS NPPES health care organisations:** US government works (public domain). From
  NPPES only organisations are read, never individual providers, and no official's name or telephone number is
  kept; organisations' names and located points only.
- **Federal and state lists of 26 November 2026:** the federal lists (Library of Congress NLS, CMS, BLM, Reclamation,
  TVA, EPA, HUD, USFA, BOP, BTS, USACE, FAA) are US government works. The TVA's layer says only that it is "made
  publicly available"; the TVA is a corporate agency of the United States, so its work is treated as a government
  work. The electric territories are a copy (on an NTIA organisation's ArcGIS account, after HIFLD Open closed) of
  ORNL's and DOE CESER's layer, credited to them. Kentucky's KDFWR and KyGovMaps layers, Iowa's health facilities
  and Connecticut DEEP's access points are CC0 (credit KDFWR as asked); Utah's boat ramps are CC BY 4.0 (credit
  UGRC). Colorado's and Michigan's child care layers and Hawaii's health facilities state "no restrictions" or
  "public domain" in their own words and are read as public domain marks. The Florida Lottery retailer list has no
  licence and is used, like the DBPR files, as a Florida public record (Chapter 119). New York's lottery, career
  center, Commission for the Blind and health facility lists are under the OPEN-NY terms. Child care lists keep
  centres only (never family or group homes) and no director's or contact person's name, telephone or e-mail.
- **Government facts (licence `government-facts`, since November 2026):** the Social Security field offices
  (`ssa-field-offices`, an ArcGIS copy of the Social Security Administration's office list published by Esri staff
  without a licence; ssa.gov itself refuses programs), Recreation.gov's RIDB export (`ridb-recreation`, whose API
  agreement keeps the vendor's rights and which states no licence) and California's health and human services files
  (`ca-health-facilities`, `ca-child-care-centers`; the portal names only its "Terms of Use"). The owner decided (26
  November 2026) to use government data regardless of a copy's missing licence or a site's own terms or robots.txt.
  Federal works are public domain (17 U.S.C. 105), facts are not protected by copyright in the United States (Feist
  v. Rural Telephone, 1991), and state facility lists are public records. Only facts are kept, collected politely
  (identified, slow, never past a refusal or a challenge); staff names, personal telephone numbers, e-mail addresses
  and internal figures are never kept. The National Park Service's Data API (`nps-places`) and the Forest Service's
  Recreation Opportunities details are US government works (public domain); from the NPS only facts are read, never
  its photos (often credited to others) or long descriptions.
- **Chain store locators (source `chain-locators`, since November 2026):** store positions, addresses, phone
  numbers, store web pages and opening hours read by this project from big US chains' own public store locators
  (`placepacks/chains`). The chains grant no licence; these are facts, which are not protected by copyright in the
  United States (Feist v. Rural Telephone, 1991). The owner decided (26 November 2026) to collect and publish them,
  also where a chain's terms or robots.txt say otherwise (licence `store-locator-facts` in sources.json). They are
  collected politely: an identified User-Agent, at least a second between requests, a request budget per chain, and
  a clean stop at any refusal or anti-bot challenge (never solved or got round); no e-mail address and no
  individual's own office (insurance agents and the like) is collected. The collectors' endpoints and logic are
  adapted from All The Places' spiders (github.com/alltheplaces/alltheplaces), whose code is under the MIT licence,
  Copyright (c) 2016 Ian Dees; its notice is in `NOTICE`.
- **Local directories and lookups (licence `directory-facts`, since November 2026):** tourism boards' Simpleview
  listings (`simpleview-listings`), chambers of commerce's ChamberMaster member directories
  (`chambermaster-listings`), the schema.org data on businesses' own homepages (`business-websites`) and Yellow Pages
  lookups of businesses already in the packs (`yp-lookups`). The sites grant no licence; only facts are kept (names,
  street addresses, positions, telephone numbers, websites, opening hours, categories, accessibility notes), which
  are not protected by copyright in the United States (Feist v. Rural Telephone, 1991); never reviews, ratings,
  descriptions, photos, e-mail addresses or people's names, and one-person and home businesses are left out. The
  owner decided (26 November 2026) to collect and publish them: the homepages, tourism sites and chambers obeying
  their robots.txt; the Yellow Pages lookups (only for businesses already listed by other sources, never copying its
  directory) although yellowpages.com's robots.txt disallows its search pages. All are collected politely (an
  identified User-Agent, paced, never past a refusal, a challenge or a login).
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
