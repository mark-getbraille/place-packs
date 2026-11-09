# Licences

## The code

The code of this repository (the `placepacks` package, the tools and the workflows) is under the MIT licence
(`LICENSE`).

## The data: each pack is a collective database

A pack mixes OpenStreetMap with other open data. OpenStreetMap is under the Open Database License (ODbL) 1.0, which
is share-alike: a database *derived* from OpenStreetMap must be offered under the ODbL. The other sources have
their own licences (public domain, CC0, PDDL, CC BY 4.0, the Open Government Licences of Canada and the UK, Licence
Ouverte 2.0, CDLA Permissive 2.0, Apache 2.0, the open-use terms of New York City's and New York State's open-data
portals, and the Newberry Library's open terms).

We chose to make each pack a **collective database** (ODbL 1.0, section 1, "Collective Database"; section 4.5),
not one database under a single licence:

- **The OpenStreetMap layer** (rows with `source = 'osm'`) is a database derived from OpenStreetMap: its named
  places, areas and streets, simplified. It is offered under the **ODbL 1.0** (`LICENSES/ODbL-1.0.txt`),
  © OpenStreetMap contributors. Anyone may obtain it with the pack and rebuild it with this repository's code.
- **Every other layer** is an independent database kept in its own rows (its `source` column says which), under its
  **own licence** (`SOURCES.md` and the pack's `sources` table, with its attribution text).
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
(`sources.attribution`). The release also carries `NOTICE` (Foursquare's and Overture's notices) and the licence
texts in `LICENSES/`.

## Conditions passed on

- **National Address Database (US):** state laws forbid using it as a mailing list. The packs are for naming places.
- **Foursquare Open Source Places:** keep `NOTICE` with any copy of the data in files (Apache 2.0, section 4).
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
- **IRS exempt organizations:** only names and located points are kept, never the "in care of" (people's) names; an
  organization at a home address is placed on its street.
- **OpenHistoricalMap:** CC0, except features with their own `license` tag, which the packs leave out.
- **Personal data:** the business sources keep only a business's trade name, class, position and dates. Records
  that may be someone's home (home-based businesses, contractors, mobile caterers, childminders, short-term rentals,
  individual licences) and licensee names that look like a person's are left out; see `SOURCES.md`. A takedown
  request goes in `removals.json`.

## Removals

`removals.json` lists records removed for a licence problem or a takedown request. Nothing else is ever deleted from
the history.
