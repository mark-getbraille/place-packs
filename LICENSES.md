# Licences

## The code

The code of this repository (the `placepacks` package, the tools and the workflows) is under the MIT licence
(`LICENSE`).

## The data: each pack is a collective database

A pack mixes OpenStreetMap with other open data. OpenStreetMap is under the Open Database License (ODbL) 1.0, which
is share-alike: a database *derived* from OpenStreetMap must be offered under the ODbL. The other sources have
their own licences (public domain, CC0, CC BY 4.0, the Open Government Licences of Canada and the UK, Licence
Ouverte 2.0, CDLA Permissive 2.0, Apache 2.0).

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

## Removals

`removals.json` lists records removed for a licence problem or a takedown request. Nothing else is ever deleted from
the history.
