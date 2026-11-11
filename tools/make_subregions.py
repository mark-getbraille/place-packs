"""Make the sub-regions of placepacks/regions.json: the regions whose core and extra packs together would be larger
than about 300 MB are cut into children, each with its own packs (README "Sub-regions"). For maintainers only; the
programs and the build read the result in regions.json and need none of these files.

    python tools/make_subregions.py --ne ne_10m_admin_1_states_provinces.shp --counties cb_2023_us_county_500k.shp \
        --population co-est2023-alldata.csv [--sizes sizes.json] [--write]

--ne         Natural Earth Admin 1 (public domain): England's nine regions, Australia's states and territories
--counties   the Census cartographic county boundaries (US Government work): US states cut by groups of counties
--population the Census county population estimates (US Government work): balanced groups of counties
--sizes      {region: {"core": {"rest": bytes}, "extra": {"rest": bytes}, "core_hist": {"lat": {...}, "lon": {...}}}}
             measured from the published packs: which other regions to cut, into how many, and where
--write      write regions.json (else only print what would be made)

How a parent is cut: its box is divided into grid cells (SPECS "step" degrees); each cell goes to the child whose
area holds the cell's centre (a county, an English region, a state; for Ontario and Quebec, a rule on the
position). A cell inside another state, province or country (Natural Earth Admin 1: Vermont in New York's box, New
Jersey beside New York City, Wales beside England) belongs to no child; cells at sea go to the nearest child, up to
FILL_DEGREES out. A child's cells are joined into rectangles ("boxes"), so every position belongs to at most one
child (placepacks.regions.in_region). A US child also lists its counties (and those just across its border), whose
TIGER/Line files it downloads.
"""

import argparse
import collections
import csv
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS_JSON = os.path.join(ROOT, "placepacks", "regions.json")
TARGET_MB = 240             # a child's core and extra together (the limit is about 300 MB: room for growth)
MARGIN = 0.2                # degrees added round the parent's box (islands, the extract's own edges)
FILL_DEGREES = 0.5          # how far out at sea a child reaches (coastal waters, islands Natural Earth leaves out)


def _county(name):
    return lambda c: c["name"] in name


SPECS = {
    "gb-england": {"step": 0.05, "units": "ne", "unit": lambda d: d["adm0_a3"] == "GBR" and d["geonunit"] == "England",
                   "key": lambda d: d["region"], "children": [
                       ("gb-england-london", "England: London", {"Greater London"}),
                       ("gb-england-south-east", "England: South East", {"South East"}),
                       ("gb-england-south-west", "England: South West", {"South West"}),
                       ("gb-england-east", "England: East of England", {"East"}),
                       ("gb-england-east-midlands", "England: East Midlands", {"East Midlands"}),
                       ("gb-england-west-midlands", "England: West Midlands", {"West Midlands"}),
                       ("gb-england-yorkshire-and-the-humber", "England: Yorkshire and the Humber",
                        {"Yorkshire and the Humber"}),
                       ("gb-england-north-west", "England: North West", {"North West"}),
                       ("gb-england-north-east", "England: North East", {"North East"})]},
    "au-australia": {"step": 0.1, "units": "ne", "unit": lambda d: d["adm0_a3"] == "AUS", "key": lambda d: d["name"],
                     "children": [
                         ("au-new-south-wales", "New South Wales", {"New South Wales", "Jervis Bay Territory",
                                                                   "Lord Howe Island"}),
                         ("au-victoria", "Victoria", {"Victoria"}),
                         ("au-queensland", "Queensland", {"Queensland"}),
                         ("au-western-australia", "Western Australia", {"Western Australia"}),
                         ("au-south-australia", "South Australia", {"South Australia"}),
                         ("au-tasmania", "Tasmania", {"Tasmania", "Macquarie Island"}),
                         ("au-northern-territory", "Northern Territory", {"Northern Territory"}),
                         ("au-australian-capital-territory", "Australian Capital Territory",
                          {"Australian Capital Territory"})]},
    "nl-netherlands": {"step": 0.05, "units": "ne", "unit": lambda d: d["adm0_a3"] == "NLD", "key": lambda d: d["name"],
                       "children": [
                           ("nl-netherlands-west", "Netherlands: Holland, Utrecht and Flevoland",
                            {"Noord-Holland", "Zuid-Holland", "Utrecht", "Flevoland"}),
                           ("nl-netherlands-north-east-south", "Netherlands: North, East and South",
                            {"Groningen", "Friesland", "Drenthe", "Overijssel", "Gelderland", "Noord-Brabant",
                             "Limburg", "Zeeland", "Bonaire", "St. Eustatius", "Saba"})]},
    "no-norway": {"step": 0.1, "units": "ne", "unit": lambda d: d["adm0_a3"] == "NOR", "key": lambda d: d["name"],
                  "children": [
                      ("no-norway-east-and-south", "Norway: East and South",
                       {"Oslo", "Akershus", "Østfold", "Buskerud", "Vestfold", "Telemark", "Hedmark", "Oppland",
                        "Aust-Agder", "Vest-Agder"}),
                      ("no-norway-west-and-north", "Norway: West and North",
                       {"Rogaland", "Hordaland", "Sogn og Fjordane", "Møre og Romsdal", "Sør-Trøndelag",
                        "Nord-Trøndelag", "Nordland", "Troms", "Finnmark", "Svalbard", "Bouvet Island"})]},
    "se-sweden": {"step": 0.1, "units": "ne", "unit": lambda d: d["adm0_a3"] == "SWE", "key": lambda d: d["name"],
                  "children": [
                      ("se-sweden-south-and-west", "Sweden: South and West",
                       {"Skåne", "Blekinge", "Kronoberg", "Kalmar", "Halland", "Västra Götaland", "Jönköping",
                        "Östergötland", "Gotland"}),
                      ("se-sweden-stockholm-and-north", "Sweden: Stockholm and the North",
                       {"Stockholm", "Uppsala", "Södermanland", "Västmanland", "Orebro", "Värmland", "Dalarna",
                        "Gävleborg", "Västernorrland", "Jämtland", "Västerbotten", "Norrbotten"})]},
    "fi-finland": {"step": 0.1, "units": "ne", "unit": lambda d: d["adm0_a3"] == "FIN", "key": lambda d: d["name"],
                   "children": [
                       ("fi-finland-south", "Finland: South",
                        {"Uusimaa", "Finland Proper", "Kymenlaakso", "Tavastia Proper", "Päijät-Häme",
                         "South Karelia", "Satakunta", "Pirkanmaa"}),
                       ("fi-finland-centre-and-north", "Finland: Centre and North",
                        {"Lapland", "Northern Ostrobothnia", "Kainuu", "North Karelia", "Ostrobothnia",
                         "Central Ostrobothnia", "Northern Savonia", "Southern Savonia", "Central Finland",
                         "Southern Ostrobothnia"})]},
    "ca-quebec": {"step": 0.1, "units": "rules", "children": [
        ("ca-quebec-montreal", "Quebec: Montreal and the West", lambda lat, lon: lon < -73.0 and lat < 46.3),
        ("ca-quebec-east-and-north", "Quebec: Quebec City, the East and the North", lambda lat, lon: True)]},
    # US states: groups of counties (a county's centre is the middle of its box).
    "us-texas": {"step": 0.1, "units": "counties", "children": [
        ("us-texas-west", "Texas: West and Panhandle", lambda c: c["lon"] < -100.0),
        ("us-texas-north", "Texas: North and East", lambda c: c["lat"] >= 31.3),
        ("us-texas-gulf-coast", "Texas: Gulf Coast", lambda c: c["lon"] >= -97.25),
        ("us-texas-south-central", "Texas: Central and South", lambda c: True)]},
    "us-california": {"step": 0.1, "units": "counties", "children": [
        ("us-california-los-angeles", "California: Los Angeles Area", _county({"Los Angeles", "Orange", "Ventura"})),
        ("us-california-south", "California: San Diego and Inland Empire",
         _county({"San Diego", "Imperial", "Riverside", "San Bernardino"})),
        ("us-california-bay-area", "California: Bay Area",
         _county({"Alameda", "Contra Costa", "Marin", "Napa", "San Francisco", "San Mateo", "Santa Clara",
                  "Santa Cruz", "Solano", "Sonoma"})),
        ("us-california-central", "California: Central",
         _county({"Santa Barbara", "San Luis Obispo", "Kern", "Tulare", "Kings", "Fresno", "Madera", "Merced",
                  "Mariposa", "Inyo", "Mono", "Monterey", "San Benito", "Stanislaus", "Tuolumne", "San Joaquin",
                  "Calaveras"})),
        ("us-california-north", "California: North", lambda c: True)]},
    "us-new-york": {"step": 0.05, "units": "counties", "children": [
        ("us-new-york-city", "New York: New York City", _county({"New York", "Kings", "Queens", "Bronx", "Richmond"})),
        ("us-new-york-downstate", "New York: Long Island and Hudson Valley",
         _county({"Nassau", "Suffolk", "Westchester", "Rockland", "Putnam", "Orange", "Dutchess", "Ulster",
                  "Sullivan"})),
        ("us-new-york-upstate", "New York: Upstate", lambda c: True)]},
    "us-florida": {"step": 0.1, "units": "counties", "children": [
        ("us-florida-south", "Florida: South", lambda c: c["lat"] < 27.0),
        ("us-florida-central", "Florida: Central", lambda c: c["lat"] < 29.0),
        ("us-florida-north", "Florida: North and Panhandle", lambda c: True)]},
    # Ontario: rules on the position (no finer boundaries in Natural Earth); the first that holds wins.
    "ca-ontario": {"step": 0.1, "units": "rules", "children": [
        ("ca-ontario-north", "Ontario: North", lambda lat, lon: lat >= 46.0 or lon < -84.0),
        ("ca-ontario-toronto", "Ontario: Toronto and the Golden Horseshoe",
         lambda lat, lon: -80.25 <= lon <= -78.75 and 43.0 <= lat <= 44.5),
        ("ca-ontario-south-west", "Ontario: Southwest", lambda lat, lon: lon < -80.25),
        ("ca-ontario-east", "Ontario: East and Central", lambda lat, lon: True)]},
}
AXIS_NAMES = {("lon", 2): ["West", "East"], ("lon", 3): ["West", "Central", "East"],
              ("lon", 4): ["West", "West Central", "East Central", "East"],
              ("lat", 2): ["South", "North"], ("lat", 3): ["South", "Central", "North"],
              ("lat", 4): ["South", "South Central", "North Central", "North"]}


# ------------------------------------------------------------------------------------------- the grid

class Grid:
    """The parent's box in cells of step degrees: cell (row, col) has its south-west corner at origin + step*(col,
    row)."""

    def __init__(self, bbox, step):
        w, s, e, n = bbox
        self.step = step
        self.w0 = math.floor((w - MARGIN) / step) * step
        self.s0 = math.floor((s - MARGIN) / step) * step
        self.cols = math.ceil((e + MARGIN - self.w0) / step)
        self.rows = math.ceil((n + MARGIN - self.s0) / step)
        self.owner = {}
        self.foreign = set()        # cells inside another state, province or country

    def centre(self, row, col):
        return self.s0 + (row + 0.5) * self.step, self.w0 + (col + 0.5) * self.step

    def cell_of(self, lat, lon):
        return (min(max(math.floor((lat - self.s0) / self.step), 0), self.rows - 1),
                min(max(math.floor((lon - self.w0) / self.step), 0), self.cols - 1))

    def rasterise(self, rings):
        """The cells whose centre is inside a shape (rings of (lon, lat); holes even-odd)."""
        lats = [p[1] for r in rings for p in r]
        if not lats:
            return []
        r0, r1 = self.cell_of(min(lats), 0)[0], self.cell_of(max(lats), 0)[0]
        out = []
        for row in range(r0, r1 + 1):
            y = self.s0 + (row + 0.5) * self.step
            xs = []
            for ring in rings:
                for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                    if (y1 <= y < y2) or (y2 <= y < y1):
                        xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            xs.sort()
            for a, b in zip(xs[::2], xs[1::2]):
                c0 = math.ceil((a - self.w0) / self.step - 0.5)
                c1 = math.floor((b - self.w0) / self.step - 0.5)
                out += [(row, c) for c in range(max(c0, 0), min(c1, self.cols - 1) + 1)]
        return out

    def fill(self, limit=None):
        """Give the cells without an owner that are not foreign (sea, water outside every unit) the owner of the
        nearest owned cell, at most limit cells away (default FILL_DEGREES)."""
        limit = round(FILL_DEGREES / self.step) if limit is None else limit
        queue = collections.deque((cell, 0) for cell in self.owner)
        while queue:
            (r, c), d = queue.popleft()
            if d >= limit:
                continue
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < self.rows and 0 <= nc < self.cols and (nr, nc) not in self.owner and \
                        (nr, nc) not in self.foreign:
                    self.owner[(nr, nc)] = self.owner[(r, c)]
                    queue.append(((nr, nc), d + 1))

    def boxes(self, child):
        """The child's cells joined into rectangles [west, south, east, north]: runs along each row, then runs of
        the same columns in consecutive rows."""
        runs = {}
        for row in range(self.rows):
            col = 0
            while col < self.cols:
                if self.owner.get((row, col)) == child:
                    start = col
                    while col < self.cols and self.owner.get((row, col)) == child:
                        col += 1
                    runs.setdefault((start, col), []).append(row)
                else:
                    col += 1
        out = []
        for (c0, c1), rows in runs.items():
            start = prev = rows[0]
            for row in rows[1:] + [None]:
                if row is not None and row == prev + 1:
                    prev = row
                    continue
                out.append([round(self.w0 + c0 * self.step, 4), round(self.s0 + start * self.step, 4),
                            round(self.w0 + c1 * self.step, 4), round(self.s0 + (prev + 1) * self.step, 4)])
                if row is not None:
                    start = prev = row
        return sorted(out, key=lambda b: (b[1], b[0]))


def _rings(shape):
    starts = list(shape.parts) + [len(shape.points)]
    return [[tuple(p) for p in shape.points[a:b]] for a, b in zip(starts, starts[1:])]


# ------------------------------------------------------------------------------------------- the children

def counties_of(path, fips, population):
    """[{"fp", "name", "lat", "lon", "pop", "rings"}] of a state's counties."""
    import shapefile
    out = []
    with shapefile.Reader(path) as shp:
        names = [f[0] for f in shp.fields[1:]]
        for sr in shp.iterShapeRecords():
            d = dict(zip(names, sr.record))
            if d["STATEFP"] != fips:
                continue
            w, s, e, n = sr.shape.bbox
            out.append({"fp": d["COUNTYFP"], "name": d["NAME"], "lat": (s + n) / 2, "lon": (w + e) / 2,
                        "pop": population.get(fips + d["COUNTYFP"], 0), "rings": _rings(sr.shape)})
    return out


def balanced(units, k, axis):
    """k groups of units with about the same population, cut along an axis ("lat" or "lon")."""
    units = sorted(units, key=lambda u: u[axis])
    total = sum(u["pop"] for u in units) or 1
    group, done, out = 0, 0, {}
    for u in units:
        if done >= total * (group + 1) / k and group < k - 1:
            group += 1
        out[u["fp"]] = group
        done += u["pop"]
    return out


def is_home(parent, d):
    """True when a Natural Earth Admin 1 unit is part of the parent region (its country; for a US state or Canadian
    province, that state or province; for England, England)."""
    if d["iso_a2"] != parent.get("cc"):
        return False
    if parent.get("cc") in ("US", "CA"):
        return d["name"] == parent["name"]
    if parent.get("cc") == "GB":
        return d["geonunit"] == parent["name"]
    return True


def mark_foreign(grid, parent, ne_path):
    """Mark the cells inside the Natural Earth Admin 1 units that are not the parent's."""
    import shapefile
    top, right = grid.s0 + grid.rows * grid.step, grid.w0 + grid.cols * grid.step
    with shapefile.Reader(ne_path, encoding="utf-8") as shp:
        names = [f[0] for f in shp.fields[1:]]
        for sr in shp.iterShapeRecords():
            w, s, e, n = sr.shape.bbox
            if e < grid.w0 or w > right or n < grid.s0 or s > top:
                continue
            if not is_home(parent, dict(zip(names, sr.record))):
                grid.foreign.update(grid.rasterise(_rings(sr.shape)))


def make_children(parent, spec, args, population):
    """[child region dicts] of a parent by its spec."""
    import shapefile
    grid = Grid(parent["bbox"], spec["step"])
    mark_foreign(grid, parent, args.ne)
    ids = [c[0] for c in spec["children"]]
    counties = []
    if spec["units"] == "ne":
        with shapefile.Reader(args.ne, encoding="utf-8") as shp:
            names = [f[0] for f in shp.fields[1:]]
            for sr in shp.iterShapeRecords():
                d = dict(zip(names, sr.record))
                if not spec["unit"](d):
                    continue
                child = next((cid for cid, _, keys in spec["children"] if spec["key"](d) in keys), None)
                if child is None:
                    raise SystemExit(f"{parent['id']}: no child for {spec['key'](d)!r}")
                for cell in grid.rasterise(_rings(sr.shape)):
                    grid.owner[cell] = child
    elif spec["units"] == "counties":
        counties = counties_of(args.counties, parent["fips"], population)
        for c in counties:
            c["child"] = next(cid for cid, _, rule in spec["children"] if rule(c))
            cells = grid.rasterise(c["rings"]) or [grid.cell_of(c["lat"], c["lon"])]
            c["cells"] = set(cells)
            for cell in cells:
                grid.owner[cell] = c["child"]
    else:
        for row in range(grid.rows):
            for col in range(grid.cols):
                if (row, col) in grid.foreign:
                    continue
                lat, lon = grid.centre(row, col)
                grid.owner[(row, col)] = next(cid for cid, _, rule in spec["children"] if rule(lat, lon))
    grid.fill()
    out = []
    for cid, name, _ in spec["children"]:
        boxes = grid.boxes(cid)
        if not boxes:
            raise SystemExit(f"{cid}: no cell")
        child = {k: v for k, v in parent.items() if k not in ("id", "name", "bbox", "bbox_note", "children",
                                                              "boxes")}
        child.update(id=cid, name=name, parent=parent["id"],
                     bbox=[min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                           max(b[3] for b in boxes)],
                     grid={"step": spec["step"], "origin": [round(grid.w0, 4), round(grid.s0, 4)],
                           "size": [grid.cols, grid.rows]},
                     boxes=boxes)
        if counties:
            # Its counties and the counties next to its cells (their address ranges may cross into it).
            mine = {cell for cell, owner in grid.owner.items() if owner == cid}
            near = {(r + dr, c + dc) for r, c in mine for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
            child["counties"] = sorted(c["fp"] for c in counties if c["child"] == cid or c["cells"] & near)
        out.append(child)
    assert len(ids) == len(out)
    return out


def generic_spec(parent, k, sizes, population, args):
    """A spec cutting a region into k children of about the same size: a US state by groups of counties of the same
    population; another region by the density of its rows (sizes' histograms), along its longer side."""
    w, s, e, n = parent["bbox"]
    axis = "lon" if (e - w) * math.cos(math.radians((s + n) / 2)) >= (n - s) else "lat"
    labels = AXIS_NAMES[(axis, k)]
    base = parent["name"]
    if parent.get("fips"):
        groups = balanced(counties_of(args.counties, parent["fips"], population), k, axis)
        return {"step": 0.1, "units": "counties", "children": [
            (f"{parent['id']}-{label.lower().replace(' ', '-')}", f"{base}: {label}",
             (lambda g: lambda c: groups[c["fp"]] == g)(i)) for i, label in enumerate(labels)]}
    hist = collections.Counter()
    for part in ("core", "extra"):
        h = (sizes.get(f"{part}_hist") or {}).get(axis, {})
        rows = sum(h.values()) or 1
        weight = (sizes.get(part) or {}).get("rest", 0) / rows
        for band, count in h.items():
            hist[int(band)] += count * weight
    total, done, cuts = sum(hist.values()) or 1, 0, []
    for band in sorted(hist):
        done += hist[band]
        if len(cuts) < k - 1 and done >= total * (len(cuts) + 1) / k:
            cuts.append((band + 1) * 0.05)
    cuts += [999.0] * (k - 1 - len(cuts))
    def below(i):
        return lambda lat, lon: (lon if axis == "lon" else lat) < cuts[i]
    rules = [below(i) for i in range(k - 1)] + [lambda lat, lon: True]
    return {"step": 0.1, "units": "rules", "children": [
        (f"{parent['id']}-{label.lower().replace(' ', '-')}", f"{base}: {label}", rules[i])
        for i, label in enumerate(labels)]}


def dump(doc):
    """regions.json's text: one item per line, lists of numbers on one line."""
    text = json.dumps(doc, indent=1, ensure_ascii=False)
    return re.sub(r"\[\s+(-?[\d.eE+-]+(?:,\s+-?[\d.eE+-]+)*)\s+\]",
                  lambda m: "[" + ", ".join(re.split(r",\s+", m.group(1))) + "]", text) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ne", required=True)
    p.add_argument("--counties", required=True)
    p.add_argument("--population", required=True)
    p.add_argument("--sizes", default="")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    population = {}
    with open(args.population, encoding="latin-1") as f:
        for row in csv.DictReader(f):
            if row["SUMLEV"] == "050":
                population[row["STATE"] + row["COUNTY"]] = int(row["POPESTIMATE2023"])
    sizes = {}
    if args.sizes:
        with open(args.sizes, encoding="utf-8") as f:
            sizes = json.load(f)
    with open(REGIONS_JSON, encoding="utf-8") as f:
        doc = json.load(f)
    regions = [r for r in doc["regions"] if not r.get("parent")]
    for r in regions:
        r.pop("children", None)
    specs = dict(SPECS)
    for rid, measured in sizes.items():
        if rid in specs or rid not in {r["id"] for r in regions}:
            continue
        mb = sum((measured.get(part) or {}).get("rest", 0) for part in ("core", "extra")) / 1e6
        if mb > 300:
            k = min(4, math.ceil(mb / TARGET_MB))
            specs[rid] = generic_spec(next(r for r in regions if r["id"] == rid), k, measured, population, args)
    out = []
    for r in regions:
        out.append(r)
        if r["id"] in specs:
            children = make_children(r, specs[r["id"]], args, population)
            r["children"] = [c["id"] for c in children]
            out += children
            for c in children:
                share = ""
                if c.get("counties"):
                    share = f", {len(c['counties'])} counties"
                print(f"{c['id']}: {c['name']}, {len(c['boxes'])} boxes{share}")
    doc["regions"] = out
    leaves = sum(1 for r in out if not r.get("children"))
    doc["note"] = re.sub(r"^The \d+ regions", f"The {leaves} regions", doc["note"])
    if "children" not in doc["note"]:
        doc["note"] += (" A region with children (England, Texas, ...) is made as its children's packs: see "
                        "placepacks/regions.py and tools/make_subregions.py.")
    if args.write:
        with open(REGIONS_JSON, "w", encoding="utf-8") as f:
            f.write(dump(doc))
        print(f"regions.json: {leaves} regions with packs, {len(out)} in all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
