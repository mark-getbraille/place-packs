"""The business-website collector: the phone number and opening hours a business gives on its OWN homepage, in
schema.org data (the source "business-websites"; the monthly web-details workflow).

The owner's decision (26 November 2026, evening, notes/helper-rules.txt): reading businesses' websites for contact
details (phone, website, hours) is OK, "since this is for accessibility". For what is published, the standing rule
holds: robots.txt and site terms are obeyed (the owner's override of robots.txt is only for big chains' store
locators and government sites, never for a small business's own site), requests are polite, identified and paced,
no CAPTCHA is passed, no login is used, and no e-mail address is ever read.

Who is read: the businesses in the newest published businesses packs (placepacks/directories/packs_input.py) that
have a website but lack a phone or opening hours; not a chain's store (a place with a brand: the chain collectors
read the chains) and not a website several places share (a chain or a directory, not one business's own site).
Each month's run reads at most BUDGET homepages, split into SHARDS jobs by region (the states with the most people
first): homepages never read come first, then those read longest ago; none is read again within RECHECK_DAYS.

One homepage (check()):
  1. its robots.txt (placepacks/directories/common.py Robots): when it does not let our User-Agent read the
     homepage, nothing more is asked ("robots.txt disallows");
  2. the homepage itself (one request; a redirect to the site's own other address is followed by urllib);
  3. its schema.org data: JSON-LD (homepage_details) or microdata (itemscope/itemprop), only objects of the local-
     business types (LocalBusiness and its kinds: Restaurant, Store, Dentist, AutoRepair, Hotel ...; an
     Organization alone is not taken: it may be the web designer's). Exactly one business on the page, or the one
     whose name is like ours; a single business whose name is unlike ours is not taken ("another name": a
     template or a directory). Its "telephone" and its "openingHoursSpecification" or "openingHours" (OpenStreetMap
     syntax, placepacks/chains/hours.py) are kept;
  4. a refusal or an anti-bot page (403, 429, a challenge) is that site's answer: recorded as "blocked", never
     tried another way, and the run goes on with the next site.
The answer is a row of placepacks/details.py's DETAIL_FIELDS (website left empty: the place already has it).

The run (python -m placepacks.directories.websites):
    plan --shards 10                    the matrix: [{"shard": 1, "of": 10}, ...]
    collect --shard 3 --of 10 --out d/  one job: d/web-details-3.csv.gz and d/web-details-3.json (its summary)
    publish --dir results/              merge the jobs' rows into the newest file of the release "web-details" and
                                        upload it as web-details-<YYYYMMDD>.csv.gz (the newest KEEP kept)
The jobs read the packs and the release with the job's own token (GH_TOKEN; placepacks/directories/github.py).
Only the Python standard library is used.
"""

import argparse
import datetime
import html.parser
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse

from placepacks import contact, details
from placepacks.chains import hours as oh
from placepacks.chains import jsonld
from placepacks.chains.polite import Blocked, BudgetSpent, NotFound, Polite, RequestFailed, _urllib_opener
from placepacks.directories.common import Robots, name_similarity

RELEASE = "web-details"
PREFIX = "web-details"
KEEP = 2                        # files kept in the release
BUDGET = 30000                  # homepages a month, all jobs together
SHARDS = 10                     # jobs a month
RECHECK_DAYS = 180              # a homepage read this recently is not read again
SHARED = 3                      # a website listed for more places than this is not one business's own
NAME_MIN = 0.6                  # a single business on the page whose name is less like ours than this is not ours
TIMEOUT = 20                    # seconds a small business's site may take to answer
PAUSE = 1.0                     # seconds between two requests to one host (robots.txt, then the homepage)
USER_AGENT = "place-packs-web-details/1 (+https://github.com/mark-getbraille/place-packs)"
ROBOTS_AGENT = "place-packs"
# schema.org local-business types (LocalBusiness and its kinds) whose phone and hours are taken.
LOCAL_TYPES = {
    "LocalBusiness", "Restaurant", "FoodEstablishment", "CafeOrCoffeeShop", "BarOrPub", "Bakery", "Brewery",
    "Winery", "Distillery", "FastFoodRestaurant", "IceCreamShop", "Store", "AutoRepair", "AutomotiveBusiness",
    "AutoDealer", "AutoBodyShop", "AutoPartsStore", "AutoWash", "GasStation", "HealthAndBeautyBusiness",
    "BeautySalon", "HairSalon", "DaySpa", "NailSalon", "TattooParlor", "MedicalBusiness", "MedicalClinic", "Dentist",
    "Physician", "Pharmacy", "Optician", "Physiotherapy", "VeterinaryCare", "LodgingBusiness", "Hotel", "Motel",
    "BedAndBreakfast", "Campground", "Hostel", "Resort", "EntertainmentBusiness", "SportsActivityLocation",
    "ExerciseGym", "GolfCourse", "BowlingAlley", "HomeAndConstructionBusiness", "HVACBusiness", "Plumber",
    "Electrician", "ChildCare", "DryCleaningOrLaundry", "Florist", "Library", "AnimalShelter", "TouristAttraction",
    "Museum", "MovieTheater", "PerformingArtsTheater", "ShoppingCenter", "RecyclingCenter", "SelfStorage",
    "TravelAgency", "FinancialService", "BankOrCreditUnion", "ProfessionalService", "EmergencyService",
}
_TYPE_ENDS = ("Store", "Restaurant", "Shop", "Business")


def is_local_type(types):
    """True when one of a schema.org object's types is a local-business type (LOCAL_TYPES, or a name ending in
    Store, Restaurant, Shop or Business)."""
    return any(t.rsplit("/", 1)[-1] in LOCAL_TYPES or t.rsplit("/", 1)[-1].endswith(_TYPE_ENDS) for t in types)


# ------------------------------------------------------------------------------------------------ reading a page

class _Microdata(html.parser.HTMLParser):
    """The local-business items of a page's microdata: [{"type", "name", "telephone", "openingHours": [...]}]."""

    PROPS = ("name", "telephone", "openingHours")

    def __init__(self):
        """Start with no items."""
        super().__init__(convert_charrefs=True)
        self.items, self.stack, self.capture = [], [], None

    def _scope(self):
        """The innermost open local-business item, or None."""
        for tag, item in reversed(self.stack):
            if item is not None:
                return item if item.get("_local") else None
        return None

    def handle_starttag(self, tag, attrs):
        """Open an item (itemscope) or start reading a property (itemprop)."""
        a = dict(attrs)
        item = None
        prop = a.get("itemprop")
        scope = self._scope()
        if "itemscope" in a:
            kind = (a.get("itemtype") or "").rsplit("/", 1)[-1]
            item = {"type": kind, "_local": is_local_type([kind]), "openingHours": []}
            if item["_local"] and scope is None:
                self.items.append(item)
        if prop and scope is not None and prop in self.PROPS and item is None:
            value = a.get("content") or a.get("datetime")
            if value is None and tag == "a" and (a.get("href") or "").startswith("tel:"):
                value = a["href"][4:]
            if value is not None:
                self._set(scope, prop, value)
            elif tag not in ("meta", "link", "img", "br", "input"):
                self.capture = [scope, prop, [], 0]
        if tag not in ("meta", "link", "img", "br", "input", "hr"):
            self.stack.append((tag, item))
            if self.capture:
                self.capture[3] += 1

    def handle_endtag(self, tag):
        """Close the innermost open element of this name (and a property being read)."""
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                closed = len(self.stack) - i
                del self.stack[i:]
                if self.capture:
                    self.capture[3] -= closed
                    if self.capture[3] <= 0:
                        scope, prop, parts, _ = self.capture
                        self._set(scope, prop, " ".join("".join(parts).split()))
                        self.capture = None
                break

    def handle_data(self, data):
        """Text of a property being read."""
        if self.capture:
            self.capture[2].append(data)

    @staticmethod
    def _set(item, prop, value):
        """Keep one property's value (opening hours may be given several times)."""
        if prop == "openingHours":
            item["openingHours"].append(value)
        elif value and not item.get(prop):
            item[prop] = value


def microdata(page):
    """The local-business items of a page's microdata (see _Microdata)."""
    parser = _Microdata()
    try:
        parser.feed(page or "")
        parser.close()
    except Exception:  # noqa: BLE001 - broken HTML: what was read so far
        pass
    return parser.items


def _businesses(page):
    """[(how, {"name", "phone", "opening_hours"})] of the page's local businesses: JSON-LD first, else microdata.
    E-mail is never read."""
    found = []
    for value in jsonld.blocks(page):
        for thing in jsonld.things(value):
            if is_local_type(jsonld.types_of(thing)):
                got = jsonld.store(thing, need_position=False) or {}
                found.append(("homepage json-ld", {"name": got.get("name", ""), "phone": got.get("phone", ""),
                                                   "opening_hours": got.get("opening_hours", "")}))
    if found:
        return found
    for item in microdata(page):
        found.append(("homepage microdata", {"name": item.get("name", ""), "phone": item.get("telephone", ""),
                                             "opening_hours": oh.from_text("; ".join(item["openingHours"]))
                                             if item["openingHours"] else ""}))
    return found


def homepage_details(page, name):
    """(how, {"phone", "opening_hours"}) of a homepage for the business called name, or (why not, {}) (see the
    module docstring, step 3)."""
    found = [(how, b) for how, b in _businesses(page) if b["phone"] or b["opening_hours"]]
    if not found:
        return "no business data", {}
    distinct = {(contact.phone_digits(b["phone"]), b["name"].lower()) for _, b in found}
    if len(distinct) > 1:
        mine = [(how, b) for how, b in found if b["name"] and name_similarity(name, b["name"]) >= 0.8]
        if len({contact.phone_digits(b["phone"]) for _, b in mine}) != 1:
            return "several businesses", {}
        found = mine
    how, b = found[0]
    if b["name"] and name_similarity(name, b["name"]) < NAME_MIN:
        return "another name", {}
    return how, {"phone": b["phone"], "opening_hours": b["opening_hours"]}


def check(client, place, today=None):
    """Read one business's homepage (see the module docstring). place: {"key", "name", "type", "brand", "lat",
    "lon", "website"}. Returns a DETAIL_FIELDS row. Raises BudgetSpent (the job's budget or time is used up)."""
    row = {"key": place["key"], "lat": f"{place['lat']:.6f}", "lon": f"{place['lon']:.6f}", "phone": "",
           "website": "", "opening_hours": "", "matched_on": "",
           "checked": (today or datetime.date.today()).isoformat()}
    url = place["website"]
    parts = urllib.parse.urlsplit(url)
    home = f"{parts.scheme}://{parts.netloc}"
    try:
        robots = Robots(client, home, ROBOTS_AGENT)
        if not robots.allowed(url):
            return {**row, "matched_on": "robots.txt disallows"}
        page = client.fetch(url, headers={"Accept": "text/html, application/xhtml+xml;q=0.9, */*;q=0.5"})
    except Blocked:
        return {**row, "matched_on": "blocked"}
    except NotFound:
        return {**row, "matched_on": "not found"}
    except RequestFailed:
        return {**row, "matched_on": "failed"}
    how, got = homepage_details(page, place["name"])
    if not got:
        return {**row, "matched_on": how}
    cleaned = contact.clean("business-websites", place["name"], place.get("type"), got.get("phone"), None,
                            got.get("opening_hours"), brand=place.get("brand"))
    return {**row, **cleaned, "matched_on": how if cleaned else "nothing usable"}


# ------------------------------------------------------------------------------------------------ choosing the sites

def candidates(records, checked, today):
    """The places to read from a businesses pack's places (packs_input.places): a website, a missing phone or
    hours, no brand, a website no more than SHARED places share, not read within RECHECK_DAYS; never read first,
    then the longest ago. checked: {key: the date it was read}."""
    from placepacks.contact import website as clean_website
    limit = (today - datetime.timedelta(days=RECHECK_DAYS)).isoformat()
    records = [r for r in records if r["website"] and not (r["phone"] and r["opening_hours"]) and not r["brand"]]
    shared = {}
    for r in records:
        r["website"] = clean_website(r["website"])
        shared[r["website"].lower().rstrip("/")] = shared.get(r["website"].lower().rstrip("/"), 0) + 1
    out = [r for r in records if r["website"] and shared[r["website"].lower().rstrip("/")] <= SHARED
           and checked.get(r["key"], "") < limit]
    out.sort(key=lambda r: (checked.get(r["key"], ""), r["key"]))
    return out


def shard_regions(shard, of, regions=None):
    """The regions of one job: every of-th region in population order, starting at shard (1-based)."""
    from placepacks.directories.packs_input import region_order
    return [rid for i, (rid, _) in enumerate(region_order(regions)) if i % of == shard - 1]


def previous_rows(gh, folder):
    """(release, its newest web-details asset or None, {key: row} of that file)."""
    rel = gh.ensure_release(RELEASE, "Business websites' details",
                            "Phone numbers and opening hours read from businesses' own homepages "
                            "(placepacks/directories/websites.py), read by the pack build (source business-websites). "
                            "Not for download.")
    pattern = details.file_pattern(PREFIX)
    files = sorted((a for a in gh.assets(rel) if pattern.match(a["name"])), key=lambda a: a["name"], reverse=True)
    if not files:
        return rel, files, {}
    path = gh.download(files[0], os.path.join(folder, files[0]["name"]))
    rows = details.read_rows(path)
    os.remove(path)
    return rel, files, rows


def collect(shard, of, out, budget=None, gh=None, opener=None, sleep=time.sleep, clock=time.monotonic, today=None,
            minutes=300, regions=None):
    """One job (see the module docstring). Returns its summary."""
    from placepacks.directories import packs_input
    from placepacks.directories.github import GitHub
    gh = gh or GitHub()
    today = today or datetime.date.today()
    budget = budget or BUDGET // of
    os.makedirs(out, exist_ok=True)
    started = clock()
    agent_opener = opener or (lambda request, timeout: _urllib_opener(request, TIMEOUT))
    client = Polite(budget * 2 + 50, PAUSE, opener=agent_opener, sleep=sleep, clock=clock, waits=(),
                    deadline=started + 60 * minutes, agent=USER_AGENT)
    work = tempfile.mkdtemp(prefix=f"web-details-{shard}-", dir=os.environ.get("PLACEPACKS_SCRATCH") or None)
    rows, stats, status, reason = {}, {}, "ok", ""
    try:
        _, _, previous = previous_rows(gh, work)
        checked = {k: r.get("checked", "") for k, r in previous.items()}
        manifest = gh.packs_of(work)
        mine = [rid for rid in shard_regions(shard, of, regions) if (rid, "businesses") in manifest]
        left = budget
        for n, rid in enumerate(mine):
            share = max(1, left // (len(mine) - n))          # an equal share of what is left, region by region
            path = gh.download_pack(manifest[(rid, "businesses")], work)
            todo = candidates(list(packs_input.places(path)), checked, today)[:share]
            os.remove(path)
            for place in todo:
                row = check(client, place, today)
                rows[row["key"]] = row
                stats[row["matched_on"]] = stats.get(row["matched_on"], 0) + 1
                left -= 1
            print(f"web-details {shard}/{of}: {rid}: {len(todo):,} homepages read", flush=True)
    except BudgetSpent as e:
        status, reason = "incomplete", str(e)
    except Exception as e:  # noqa: BLE001 - recorded; the rows read so far are kept
        status, reason = "failed", f"{type(e).__name__}: {str(e)[:300]}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    details.write_rows(os.path.join(out, f"{PREFIX}-{shard}.csv.gz"), rows)
    summary = {"shard": shard, "of": of, "status": status, "reason": reason, "homepages": len(rows),
               "found": sum(1 for r in rows.values() if r["phone"] or r["opening_hours"]), "requests": client.used,
               "stats": stats, "date": today.isoformat(), "seconds": round(clock() - started, 1)}
    with open(os.path.join(out, f"{PREFIX}-{shard}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"web-details {shard}/{of}: {status} ({len(rows):,} homepages, {summary['found']:,} with details, "
          f"{client.used:,} requests{', ' + reason if reason else ''})", flush=True)
    return summary


def publish(folder, gh=None, today=None):
    """Merge the jobs' rows (folder/web-details-*.csv.gz) into the newest file of the release and upload it as
    web-details-<YYYYMMDD>.csv.gz; delete files older than the newest KEEP. Returns (file name, rows, a summary
    table in Markdown)."""
    from placepacks.directories.github import GitHub
    gh = gh or GitHub()
    today = today or datetime.date.today()
    scratch = tempfile.mkdtemp(prefix="web-details-publish-", dir=os.environ.get("PLACEPACKS_SCRATCH") or None)
    try:
        rel, files, merged = previous_rows(gh, scratch)
        new, lines = {}, [f"## Business websites, {today.isoformat()}", "",
                          "| Job | Result | Homepages | With details | Requests | Note |", "|---|---|---|---|---|---|"]
        for name in sorted(os.listdir(folder)):
            if re.match(rf"^{PREFIX}-\d+\.csv\.gz$", name):
                new.update(details.read_rows(os.path.join(folder, name)))
            if re.match(rf"^{PREFIX}-\d+\.json$", name):
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    s = json.load(f)
                lines.append(f"| {s.get('shard')} | {s.get('status')} | {s.get('homepages', 0):,} | "
                             f"{s.get('found', 0):,} | {s.get('requests', 0):,} | "
                             f"{(s.get('reason') or '').replace('|', '/')[:120]} |")
        if not new:
            return None, len(merged), "\n".join(lines + ["", "No homepage was read this time; nothing uploaded."])
        merged = details.merge(merged, new)
        name = f"{PREFIX}-{today:%Y%m%d}.csv.gz"
        path = os.path.join(scratch, "new-" + name)
        count = details.write_rows(path, merged)
        gh.upload(rel, path, name)
        for a in [f for f in files if f["name"] != name][KEEP - 1:]:
            gh.delete(a)
        return name, count, "\n".join(lines + ["", f"Uploaded {name}: {count:,} homepages in all."])
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["plan", "collect", "publish"])
    p.add_argument("--shards", type=int, default=SHARDS)
    p.add_argument("--shard", type=int, default=1)
    p.add_argument("--of", type=int, default=SHARDS)
    p.add_argument("--budget", type=int, default=0, help="homepages for this job (default: BUDGET / of)")
    p.add_argument("--minutes", type=int, default=300, help="the job's time for reading (then it writes its file)")
    p.add_argument("--out", default="web-out")
    p.add_argument("--dir", default="results")
    a = p.parse_args(argv)
    if a.action == "plan":
        print(json.dumps([{"shard": i, "of": a.shards} for i in range(1, a.shards + 1)], separators=(",", ":")))
        return 0
    if a.action == "collect":
        collect(a.shard, a.of, a.out, budget=a.budget or None, minutes=a.minutes)
        return 0
    os.makedirs(a.dir, exist_ok=True)
    _, _, text = publish(a.dir)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
