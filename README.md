# place-packs

Free, offline place-name packs for photos: what is at a position, as it was named when the picture was taken.
Each pack covers one region: a US state, a Canadian province, or a Geofabrik region of Western Europe, Australia,
New Zealand or Japan. Programs download a region's pack the first time a picture from there needs it. After that,
nothing is sent anywhere when a place is looked up.

The packs are built from OpenStreetMap and other open data: national address databases, government names and
facilities, Overture Maps and Foursquare Open Source Places, Wikidata, GeoNames and public transit feeds, and dated
business records: restaurant inspections, liquor and business licences, bank branches, the UK's food hygiene
ratings and Victoria's Sands & McDougall directories (1896–1974). Each source is
listed with its licence in [SOURCES.md](SOURCES.md). The packs are made for the
[Digital Accessibility Toolkit](https://getbraille.com)'s picture describer and the Photo Location Identifier
(`photo-location-identifier/`), and anyone may use them under their licences.

## What a lookup says

- "at Riverside Park, West 120th Street, New York"
- "near 120 Main Street, Springfield", from an address point
- "at about 120 Main Street", estimated from the street's address range
- "next to Riverside Library", or "next to a business listed as Tony's Pizza (now Sally's Ice Cream)"
- "on Vineyard Sound, about 3 miles south of Edgartown", "on Lake Champlain"
- "in the air, about 35,000 feet (10,700 m) over the Pacific Ocean, about 400 miles northeast of Hilo"
- "near Boston Logan International Airport", in the air shortly after take-off

Water, coastlines and the air work without any pack, from the small global layer in `placepacks/data/`
(Natural Earth and OurAirports, both public domain).

## History: names as they were

Packs never forget. Every record (a place, a business, a street, an address) has the months it was first and
last seen. Each monthly build is merged with the history published before:

- a record still there continues;
- a record that is renamed, closed or moved keeps its old row (closed at the last month it was seen);
- the new name starts a new row.

So "Tony's Pizza" is still Tony's Pizza for a photo taken before it became "Sally's Ice Cream". A street renamed
in 2015 is "Main St" for older photos. Rows are deleted only for a licence problem or a takedown request
(`removals.json`).

Records are matched across months by the source's own stable id: OpenStreetMap's id, Overture's GERS id,
Foursquare's id, the TIGER edge id, the GNIS id or the Wikidata Q-id. Without an id, they are matched by position
within a few metres and the same name and class.

How far back each layer goes:

| Layer | History |
|---|---|
| OpenStreetMap | From the first build (November 2026). Full OpenStreetMap history would need about 150 GB, or an OpenStreetMap login for per-state history extracts, so it is not used. |
| US street names and address ranges (TIGER/Line) | Seeded from the yearly releases of 2011, 2014, 2017, 2020 and 2023 (ADDRFEAT starts in 2011), then every build. This catches street renames, new streets and changed ranges. |
| US address points (NAD) | From the first build. Earlier NAD releases are added if USDOT keeps them openly downloadable. The NAD is downloaded again only when USDOT publishes a new file (data.transportation.gov). |
| Restaurant inspections (New York City and State, Austin, Delaware, Montgomery County MD, Boulder County, Cincinnati, Baton Rouge, San Francisco 2016–2019) | Each establishment from its first to its last inspection, one record per permit and name, so a renamed restaurant keeps its old name with its own dates. New York State's go back to 2005. |
| Liquor licences (New York State, Colorado), New York City storefront licences, San Francisco and Los Angeles business locations | Each licence's issue and expiry dates, or each business location's start and end dates (San Francisco's go back to the 1960s). Only storefront businesses, under their trade names. |
| FDIC bank branches | Each branch under its bank's name since the bank took it over, or since it opened. |
| UK food hygiene ratings (FSA) | Each business from its latest rating date, then month by month. |
| Victoria, Australia: Sands & McDougall directories | The directory years 1896–1974 each business was listed in. |
| Overture places | From the first build. Past monthly releases (for example one a quarter) can be merged first while Overture still keeps them. |
| Foursquare Open Source Places | Foursquare's own creation and closing dates. |
| Wikidata | Its start and end dates, often decades back (a mill from 1923 to 1998). |
| France (BAN), Netherlands (BAG), New Zealand (LINZ) | From the first build. Their published archives and change sets can seed earlier years. |
| Everything else | From the first build. |

A lookup uses the photo's date: the camera's date, else the file's date (less certain). A date older than the data
uses the oldest record and says "no older record". Without a date it uses the newest records, "as listed now". A
date range (an old scanned photo, 1950–1960) gives the names valid in that range, said "probably".

## Using the packs

The `placepacks` package (MIT) reads packs with the Python standard library only:

```python
from placepacks.download import ensure_pack
from placepacks.lookup import Finder
from placepacks.regions import regions_for

region = regions_for(44.26, -72.58)[0]          # "us-vermont"
ensure_pack(region)                              # downloads it once; ask= and progress= are optional
f = Finder()
r = f.lookup(44.26, -72.58, when=(2005, 2006), detail="street", altitude=None)
print(r.phrase(units="miles"), "|", r.short("street"), "|", r.details())
print(f.areas_at(44.26, -72.58))                 # every named area holding the point, smallest first
```

The API:

- `placepacks.lookup`: `Finder(folder=None, packs=None, water=None, nearest=None)`, with `.lookup(lat, lon,
  when=None, detail="street", altitude=None)` returning a `Result`, and `.areas_at(lat, lon, when=None)`.
  Also `search_names(text, folder=None, regions=None, when=None, limit=20)` and `PackReader(path)`.
- `Result`: `kind`, `name`, `cls`, `house_number`, `street`, `street_now`, `town`, `neighbourhood`, `zip_area`,
  `water_name`, `distance_m`, `bearing`, `over`, `airport`, `first`, `last`, `now_name`, `listed`, `probably`,
  `as_listed_now`, `no_older_record`, `sources`, `source_names`, `attributions`. Its methods are `phrase(detail,
  units)`, `short(detail)`, `details()` and `source_text()`.
- `placepacks.when`: `When.parse(None | YYYYMM | date | "YYYY-MM" | (start, end))`.
- `placepacks.regions`: `REGIONS`, `regions_for(lat, lon, resolver=None)`, `region_label(id)` and `tree()`.
- `placepacks.download`: `PUBLIC_RELEASE`, `Catalogue()`, `ensure_pack(region, part="core", folder=None,
  ask=None, progress=None)`, `updates_available()`, `installed()`, `remove_pack(key)` and `add_pack_file(path)`.
- `placepacks.water`: `WaterLayer().describe(lat, lon, altitude=None, nearest=None)`.

Each region has two parts: **core** (`us-vermont.osmpack`: OpenStreetMap, address points, Census towns and ZIP
areas) and **extra** (`us-vermont-extra.osmpack`: address ranges, businesses, public facilities, landmarks,
transit stops and Wikidata). The file format is described in [FORMAT.md](FORMAT.md).

## Sizes (estimates)

Estimated, not yet measured. Geofabrik could not be reached from the development machine. A test on a real small
extract (Liechtenstein) gave a pack about half its extract's size, but today's extracts are mostly unnamed buildings
and house numbers, which packs leave out. The first build's `sources-status.md` will give the real numbers.

| Area | Core | Extra |
|---|---|---|
| A typical US state | 60–150 MB | 70–200 MB |
| All US states, DC and Puerto Rico | 3–6 GB | 4–7 GB |
| All of Canada | 0.6–1.2 GB | 0.5–1 GB |
| Germany (16 Länder) | 0.6–1.4 GB | 0.3–0.6 GB |
| France (22 regions) | 0.9–1.8 GB | 0.3–0.6 GB |
| United Kingdom | 0.3–0.7 GB | 0.2–0.4 GB |
| Spain, Italy | 0.2–0.7 GB each | 0.1–0.3 GB each |
| Netherlands, Belgium, Switzerland, Austria, Ireland, the Nordic countries, Portugal | 0.05–0.5 GB each | 0.05–0.2 GB each |
| Australia | 0.15–0.35 GB | 0.1–0.3 GB |
| New Zealand | 0.05–0.15 GB | 0.03–0.1 GB |
| Japan (8 regions) | 0.3–0.7 GB | 0.2–0.5 GB |

GitHub allows release files up to 2 GB each with no total limit, so every pack fits. A user downloads only the
regions their photos need.

## How the packs are built

[.github/workflows/build-packs.yml](.github/workflows/build-packs.yml) ("Build place packs"):

- **When it runs:**
  - **Monthly:** on the 2nd of each month at 04:17 UTC. It rebuilds only the regions whose sources changed, judged
    by their ETags, Last-Modified dates and release names recorded in `packs.json`.
  - **By hand:** Actions, "Build place packs", Run workflow. Inputs:
    - `regions`: for example `us-vermont fr-ile-de-france`; empty means all;
    - `force`: rebuild even when nothing changed;
    - `seed_history`: seed the US address-range history from older TIGER years. Use it once, on the first build.
- **What it does:**
  - It downloads the national files once and splits them per region.
  - It builds each region (two at a time, with polite pauses between downloads), merged with its previous pack.
  - It publishes to the release `packs`, in this order:
    1. the new packs, under dated file names;
    2. the previous list, as `packs-previous.json`;
    3. the new list, `packs.json`, last.
  - It then deletes files that neither list names. A program never sees a list naming a file that is not there.
- **Keys:** only the repository's own `GITHUB_TOKEN` is used.
- **Keep-alive:** GitHub turns off scheduled workflows in repositories with no activity for 60 days. Each run
  commits an updated `sources-status.md`, which keeps the schedule alive.

To build one region yourself:

```
pip install -r requirements.txt
python -m placepacks.fetch us-rhode-island --dir work/us-rhode-island
python -m placepacks.build us-rhode-island --part core --inputs work/us-rhode-island/fetched.json --out us-rhode-island.osmpack
python -m placepacks.build us-rhode-island --part extra --inputs work/us-rhode-island/fetched.json --out us-rhode-island-extra.osmpack
```

Some sources need a file put in `inputs/` by hand: their downloads need an account or change address. `SOURCES.md`
says which.

## Licences

The code is under the MIT licence. Each pack is a collective database:

- its **OpenStreetMap layer** is under the **ODbL 1.0**, © OpenStreetMap contributors;
- **every other layer** is under its own open licence.

[LICENSES.md](LICENSES.md) explains the choice, and [SOURCES.md](SOURCES.md) lists every source with its licence
and attribution. When you show data from a pack, credit the sources used, for example "© OpenStreetMap
contributors".
