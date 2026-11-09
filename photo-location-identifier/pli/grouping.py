"""Working out the new folders: which photos go together and what each folder is called. Nothing is moved here.

  guess_by_time(photos, hours)     photos without a location get the position of a photo with GPS taken the same day
                                   within a few hours (marked "probably")
  make_trips(photos, gap_days)     photos in time order, split into trips where more than gap_days pass without a
                                   photo (and, if chosen, where the place changes)
  name_trip(trip)                  pass 1 of "Trip area (smart)": the most specific named area that covers most of
                                   the trip's photos ("Outer Banks" for a week in Duck, Kitty Hawk and Nags Head)
  unify_trip_names(trips)          pass 2: trips whose areas overlap get one name across the whole album, so the
                                   same beach every summer is "Outer Banks 2005", "Outer Banks 2006", ...
  render(template, group)          a folder name from a template: "{place} {year}" -> "Outer Banks 2005"
  make_plan(photos, places, opts)  all of it: the Plan (groups, the "Unknown place" group, photos left alone)

How "Trip area (smart)" chooses a name for a trip (only photos with a known place count; "most" means more than
half):
  1. One of My places, if most of the trip's photos are in it.
  2. If the trip is spread out (photos in more than one town, or more than SPREAD_KM apart): the smallest named
     area (not a government division: a region such as the Outer Banks, an island, a national park or seashore)
     of a sensible size (MIN_AREA_M2 to MAX_AREA_M2) that covers most of the photos.
  3. Otherwise the town most photos are in; outside any town, the smallest named area around most of them.
  4. Then the water or air description, then the county, state or country covering most of them.
Then, across the whole album, for each named area from small to large: if it covers trips that have different
names (one trip was "Duck", another "Outer Banks"), every one of those trips takes the area's name. Trips that
already share a name keep it ("Nags Head 2005" and "Nags Head 2006" stay as they are).
"""

import bisect
import collections
import datetime as dt
import re

from pli.places import metres

DETAILS = ("trip-area", "place", "town", "county", "state", "country")
TIMES = ("none", "year", "month", "trip")
UNKNOWN_CHOICES = ("leave", "unknown", "guess")
TEMPLATES = ("{place} {year}", "{year}\\{place}", "{place}\\{year}", "{year}-{month} {place}")
# "Put the exact place in each picture's name" (rename, off by default: renaming is a bigger change than moving) and
# the pattern of the new names (see naming.py): date, exact place, then the old name (the default); exact place,
# date, then the old name; or the exact place and the old name only.
NAME_PATTERNS = ("date-place-name", "place-date-name", "place-name")
DEFAULT_OPTIONS = {"detail": "trip-area", "time": "year", "template": TEMPLATES[0], "gap_days": 2,
                   "split_on_place": False, "unknown": "leave", "guess_hours": 3, "mode": "move",
                   "subfolders": True, "videos": True, "rename": False, "name_pattern": NAME_PATTERNS[0]}
UNKNOWN_FOLDER = "Unknown place"
SPREAD_KM = 5                 # a trip more spread out than this is named by an area around it, not one town
PLACE_CHANGE_KM = 80          # "start a new trip when the place changes" in Trip area: this far from the trip start
MIN_AREA_M2 = 5e6             # named areas smaller than 5 km2 (a park, a pier) are places, not trip areas
MAX_AREA_M2 = 5e10            # and larger than 50,000 km2 are too wide to name a trip
NAME_LIMIT = 100              # the longest folder name part made
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
TOKENS = ("place", "year", "month", "monthname", "day", "date", "start", "end", "dates", "town", "county", "state",
          "country")


def options(**changes):
    """DEFAULT_OPTIONS with changes (ValueError for a choice that does not exist)."""
    out = {**DEFAULT_OPTIONS, **{k: v for k, v in changes.items() if v is not None}}
    if out["detail"] not in DETAILS:
        raise ValueError(f"Place detail must be one of {', '.join(DETAILS)}")
    if out["time"] not in TIMES:
        raise ValueError(f"Time must be one of {', '.join(TIMES)}")
    if out["unknown"] not in UNKNOWN_CHOICES:
        raise ValueError(f"Photos without a location must be one of {', '.join(UNKNOWN_CHOICES)}")
    if out["mode"] not in ("move", "copy"):
        raise ValueError("Move or copy must be move or copy")
    if out["name_pattern"] not in NAME_PATTERNS:
        raise ValueError(f"Picture names must be one of {', '.join(NAME_PATTERNS)}")
    out["rename"] = bool(out["rename"])
    out["gap_days"] = max(0.0, float(out["gap_days"]))
    return out


# ---------------------------------------------------------------- guessing by time

def guess_by_time(photos, hours=3):
    """Give each photo without a location the position of the photo with its own GPS taken nearest in time, on the
    same day and within hours hours; it is then marked "probably" (location_source "guess"). Photos whose only date
    is the file's own date are not guessed (copying a file can change that date). Returns the number guessed."""
    located = sorted((p for p in photos if p.location_source == "gps" and p.taken is not None),
                     key=lambda p: p.taken)
    times = [p.taken for p in located]
    count = 0
    for p in photos:
        if p.has_location or p.taken is None or p.date_source == "file date" or not located:
            continue
        i = bisect.bisect_left(times, p.taken)
        best = None
        for j in (i - 1, i):
            if 0 <= j < len(located):
                other = located[j]
                gap = abs((other.taken - p.taken).total_seconds())
                if other.taken.date() == p.taken.date() and gap <= hours * 3600 and (best is None or gap < best[0]):
                    best = (gap, other)
        if best:
            other = best[1]
            p.lat, p.lon, p.altitude = other.lat, other.lon, None
            p.location_source, p.guessed_from = "guess", other.path
            count += 1
    return count


# ---------------------------------------------------------------- trips

class Trip:
    """Photos taken together: photos (in time order), and after naming: name, kind ("my place", "named", "town",
    "water", "county", "state", "country", "fallback"), size_m2 of the area named (None if not known)."""

    def __init__(self, photos):
        """A trip of these photos."""
        self.photos = list(photos)
        self.name, self.kind, self.size_m2 = "", "", None

    @property
    def start(self):
        """When the first photo was taken."""
        return self.photos[0].taken

    @property
    def end(self):
        """When the last photo was taken."""
        return self.photos[-1].taken

    def known(self):
        """The photos whose place is known."""
        return [p for p in self.photos if getattr(p, "info", None) is not None and p.info.known]

    def __repr__(self):
        """For test messages."""
        return f"Trip({self.name!r}, {len(self.photos)} photos, {self.start:%Y-%m-%d})"


def make_trips(photos, gap_days=2, split=None):
    """[Trip] of the photos (those with a date), in time order: a new trip starts where more than gap_days days pass
    without a photo, or where split(trip_photos, photo) says so (a change of place)."""
    dated = sorted((p for p in photos if p.taken is not None), key=lambda p: (p.taken, p.path))
    trips, current = [], []
    gap = dt.timedelta(days=gap_days)
    for p in dated:
        if current and (p.taken - current[-1].taken > gap or (split is not None and split(current, p))):
            trips.append(Trip(current))
            current = []
        current.append(p)
    if current:
        trips.append(Trip(current))
    return trips


def place_change_split(level):
    """split for make_trips when "Start a new trip when the place changes" is ticked: at a level, when the photo's
    name there differs from the trip's last photo's; for Trip area, when the photo is more than PLACE_CHANGE_KM from
    the trip's first photo, or the state or water changes."""
    def split(trip_photos, photo):
        last = trip_photos[-1]
        a, b = getattr(last, "info", None), getattr(photo, "info", None)
        if a is None or b is None or not a.known or not b.known:
            return False
        if level == "trip-area":
            first = trip_photos[0]
            if photo.has_location and first.has_location and \
                    metres(first.lat, first.lon, photo.lat, photo.lon) > PLACE_CHANGE_KM * 1000:
                return True
            return (a.state or a.water or a.country) != (b.state or b.water or b.country)
        return a.name_at(level) != b.name_at(level)
    return split


def _majority(n):
    """How many photos out of n are "most": more than half."""
    return n // 2 + 1


def _named_ok(area, any_size=False):
    """True if a named area (not a government division) may name a trip: its size within MIN_AREA_M2 and
    MAX_AREA_M2 (an unknown size is accepted); any_size: only the upper limit."""
    if area.level:
        return False
    if area.size_m2 is None:
        return True
    return area.size_m2 <= MAX_AREA_M2 and (any_size or area.size_m2 >= MIN_AREA_M2)


def _spread(known):
    """True if the photos are in more than one town (or some in a town and some outside), or more than SPREAD_KM
    apart."""
    towns = {p.info.town for p in known}
    if len(towns) > 1:
        return True
    pts = [(p.lat, p.lon) for p in known if p.has_location]
    if len(pts) < 2:
        return False
    lats, lons = [a for a, _ in pts], [b for _, b in pts]
    return metres(min(lats), min(lons), max(lats), max(lons)) > SPREAD_KM * 1000


def name_trip(trip):
    """Pass 1: choose trip.name, trip.kind and trip.size_m2 (see the module docstring). Returns the name."""
    known = trip.known()
    if not known:
        trip.name, trip.kind = "", ""
        return ""
    need = _majority(len(known))
    count = collections.Counter
    mine = count(p.info.my_place for p in known if p.info.my_place)
    water = count(p.info.water for p in known if p.info.water)
    named, admin, sizes = count(), {lv: count() for lv in ("town", "county", "state", "country")}, {}
    for p in known:
        seen = set()
        for a in p.info.areas:
            if a.name in seen:
                continue
            seen.add(a.name)
            if a.level == "skip":
                continue
            if a.level:
                admin[a.level][a.name] += 1
            elif _named_ok(a, any_size=True):
                named[a.name] += 1
            sizes.setdefault(a.name, a)
        for lv in ("town", "county", "state", "country"):
            value = getattr(p.info, lv)
            if value and value not in seen:
                admin[lv][value] += 1
                seen.add(value)

    def smallest(names, ok=lambda a: True):
        """The smallest area among names that covers most photos and passes ok, or None."""
        found = [sizes.get(n) for n, c in names.items() if c >= need and sizes.get(n) is not None and ok(sizes[n])]
        found.sort(key=lambda a: (a.size_m2 is None, a.size_m2 or 0))
        return found[0] if found else None

    def choose(name, kind, size=None):
        trip.name, trip.kind, trip.size_m2 = name, kind, size
        return name

    top = mine.most_common(1)
    if top and top[0][1] >= need:
        return choose(top[0][0], "my place")
    spread = _spread(known)
    if spread:
        a = smallest(named, _named_ok)
        if a:
            return choose(a.name, "named", a.size_m2)
    top = admin["town"].most_common(1)
    if top and top[0][1] >= need:
        size = sizes[top[0][0]].size_m2 if top[0][0] in sizes else None
        return choose(top[0][0], "town", size)
    a = smallest(named, lambda x: _named_ok(x, any_size=True))
    if a:
        return choose(a.name, "named", a.size_m2)
    top = water.most_common(1)
    if top and top[0][1] >= need:
        return choose(top[0][0], "water")
    for lv in ("county", "state", "country"):
        top = admin[lv].most_common(1)
        if top and top[0][1] >= need:
            return choose(top[0][0], lv, sizes[top[0][0]].size_m2 if top[0][0] in sizes else None)
    names = count(p.info.name_at("town") for p in known)
    return choose(names.most_common(1)[0][0], "fallback")


def _covers(area_name, trip):
    """True if the named area covers most of the trip's photos with a known place."""
    known = trip.known()
    inside = sum(1 for p in known if any(a.name == area_name for a in p.info.areas))
    return bool(known) and inside >= _majority(len(known))


def unify_trip_names(trips):
    """Pass 2: one name per area across the album (see the module docstring). Every named area that covers trips
    named differently (towns, or named areas inside it) gives them all its name, smallest area first. Trips named by
    My places, water or a county, state or country are left as they are. Returns the trips."""
    areas = {}
    for t in trips:
        for p in t.known():
            for a in p.info.areas:
                if not a.level and _named_ok(a) and a.name not in areas:
                    areas[a.name] = a
    for area in sorted(areas.values(), key=lambda a: (a.size_m2 is None, a.size_m2 or 0)):
        covered = [t for t in trips if t.kind in ("town", "named", "fallback") and _covers(area.name, t)]
        covered = [t for t in covered if t.kind != "named" or t.size_m2 is None or area.size_m2 is None or
                   t.size_m2 <= area.size_m2]
        if len({t.name for t in covered}) >= 2:
            for t in covered:
                t.name, t.kind, t.size_m2 = area.name, "named", area.size_m2
    return trips


# ---------------------------------------------------------------- groups and folder names

class Group:
    """One new folder: photos, place (the place name), start and end (the dates of its photos), time_key (what
    separates it from other groups of the same place: "", a year, (year, month) or a trip number), folder (its
    name, from the template; may contain "\\" for a folder inside a folder), probably (how many photos have a
    guessed position), sources (Counter of where the place names came from), unknown (True for "Unknown place")."""

    def __init__(self, place, time_key="", unknown=False):
        """An empty group."""
        self.place, self.time_key, self.unknown = place, time_key, unknown
        self.photos = []
        self.folder = ""
        self.renamed = False
        self.trip = None

    @property
    def start(self):
        """The date of the earliest photo (None if no photo has one)."""
        dates = [p.taken for p in self.photos if p.taken is not None]
        return min(dates) if dates else None

    @property
    def end(self):
        """The date of the latest photo."""
        dates = [p.taken for p in self.photos if p.taken is not None]
        return max(dates) if dates else None

    @property
    def probably(self):
        """How many of its photos have a position guessed from photos taken around the same time."""
        return sum(1 for p in self.photos if p.probably)

    def sources(self):
        """Where its names came from, in words, most photos first: "GPS and the place packs (38), My places (2)"."""
        c = collections.Counter()
        for p in self.photos:
            info = getattr(p, "info", None)
            if self.unknown or info is None or not info.known:
                c["no location"] += 1
            elif info.my_place:
                c["My places"] += 1
            else:
                c[f"the place packs ({info.source})" if info.source else "the place packs"] += 1
        return c

    def describe(self):
        """One line for the review list: "Outer Banks 2005: 42 photos, 2 to 9 July 2005, place from the place packs,
        3 probably (guessed by time)"."""
        n = len(self.photos)
        parts = [f"{self.folder}: {n} photo{'s' if n != 1 else ''}"]
        when = date_range_words(self.start, self.end)
        if when:
            parts.append(when)
        src = self.sources()
        parts.append("place from " + ", ".join(f"{k} ({v})" if len(src) > 1 else k for k, v in src.most_common()))
        if self.probably:
            parts.append(f"{self.probably} probably (place guessed from photos taken around the same time)")
        if any(getattr(p, "info", None) is not None and p.info.probably for p in self.photos):
            parts.append("the place name is not certain")
        return ", ".join(parts)

    def __repr__(self):
        """For test messages."""
        return f"Group({self.folder!r}, {len(self.photos)})"


def date_range_words(start, end):
    """Dates in words: "4 July 2005", "2 to 9 July 2005", "28 June to 3 July 2005", "30 December 2005 to 2 January
    2006"; "" without dates."""
    if start is None:
        return ""
    end = end or start
    a, b = start.date(), end.date()
    if a == b:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year}"
    if a.year != b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year} to {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.month != b.month:
        return f"{a.day} {MONTHS[a.month - 1]} to {b.day} {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day} to {b.day} {MONTHS[a.month - 1]} {a.year}"


def clean_part(text):
    """A folder name part made safe for Windows: no \\ / : * ? " < > |, no dot or space at the end, not a reserved
    name (CON, NUL ...), at most NAME_LIMIT characters."""
    text = re.sub(r"\s+", " ", BAD_CHARS.sub(" ", str(text or ""))).strip(" .")
    if len(text) > NAME_LIMIT:
        text = text[:NAME_LIMIT].rsplit(" ", 1)[0].strip(" .")
    if text.split(".")[0].lower() in RESERVED:
        text = "_" + text
    return text


def clean_folder(text):
    """A folder path typed in the review or made from a template, each part cleaned (clean_part); "\\" or "/"
    separate folders inside folders; empty parts are dropped."""
    parts = [clean_part(p) for p in re.split(r"[\\/]+", str(text or ""))]
    return "\\".join(p for p in parts if p)


def template_values(group, time):
    """{token: text} for a group under a time choice. Without that part of the time (time "none" has no year)
    the date tokens are empty, so "{place} {year}" with Time None is just the place."""
    start, end = group.start, group.end
    info = next((p.info for p in group.photos if getattr(p, "info", None) is not None and p.info.known), None)
    v = {k: "" for k in TOKENS}
    v["place"] = group.place
    for lv in ("town", "county", "state", "country"):
        v[lv] = getattr(info, lv, "") if info is not None else ""
    if start is not None and time != "none":
        v["year"] = f"{start.year}"
        v["start"] = f"{start:%Y-%m-%d}"
        v["end"] = f"{end:%Y-%m-%d}"
        v["dates"] = v["start"] if start.date() == end.date() else f"{v['start']} to {v['end']}"
        if time in ("month", "trip"):
            v["month"] = f"{start.month:02d}"
            v["monthname"] = MONTHS[start.month - 1]
        if time == "trip":
            v["day"] = f"{start.day:02d}"
            v["date"] = v["start"]
    return v


def render(template, group, time="year"):
    """The folder name for a group from a template ("{place} {year}" -> "Outer Banks 2005"). Unknown tokens are
    left out; "\\" or "/" make folders inside folders ("{year}\\{place}" -> "2005\\Outer Banks")."""
    values = template_values(group, time)

    def sub(m):
        return values.get(m.group(1).lower(), "")
    text = re.sub(r"\{(\w+)\}", sub, template or "{place}")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*([\\/])\s*", r"\1", text)
    text = re.sub(r"(^|[\\/])[-_ ,.]+|[-_ ,]+($|[\\/])", r"\1\2", text)
    return clean_folder(text)


def time_label(group, time):
    """What tells two groups of one place apart under a time choice, for names that came out the same: " 2005",
    " 2005-07", " (2005-07-02 to 2005-07-09)"."""
    v = template_values(group, time)
    if time == "year":
        return f" {v['year']}"
    if time == "month":
        return f" {v['year']}-{v['month']}"
    if time == "trip":
        return f" ({v['dates']})"
    return ""


def name_folders(groups, template, time):
    """Set each group's folder from the template. Groups of different times that would get the same name (the
    template has no {year} but Time is Year) get the time added, so they stay apart; groups the user renamed keep
    their names."""
    for g in groups:
        if not g.renamed:
            g.folder = render(template, g, time) or clean_part(g.place) or UNKNOWN_FOLDER
    seen = collections.defaultdict(list)
    for g in groups:
        seen[g.folder.lower()].append(g)
    for same in seen.values():
        if len(same) > 1 and len({g.time_key for g in same}) > 1:
            for g in same:
                if not g.renamed:
                    g.folder = clean_folder(g.folder + time_label(g, time))
    return groups


def preview_examples(template, time="year"):
    """Examples of folder names a template makes, for the window's preview: "Outer Banks 2005, Outer Banks 2006,
    Grandma's house 2007"."""
    from pli.photos import Photo
    out = []
    for place, when, end in (("Outer Banks", dt.datetime(2005, 7, 2), dt.datetime(2005, 7, 9)),
                             ("Outer Banks", dt.datetime(2006, 7, 1), dt.datetime(2006, 7, 8)),
                             ("Grandma's house", dt.datetime(2007, 11, 22), dt.datetime(2007, 11, 22))):
        g = Group(place)
        for t in (when, end):
            p = Photo("x.jpg")
            p.taken = t
            g.photos.append(p)
        out.append(render(template, g, time) or place)
    return out


# ---------------------------------------------------------------- the plan

class Plan:
    """What a sort will do: root (the folder sorted), groups ([Group], the new folders, unknown included),
    left ([(Photo, reason)]: photos that stay where they are), options, attributions (of the place names used),
    problems (things the user should know, such as packs that could not be downloaded)."""

    def __init__(self, root, groups, left, opts, attributions=(), problems=()):
        """Store the fields."""
        self.root, self.groups, self.left, self.options = root, groups, left, opts
        self.attributions = sorted(set(attributions))
        self.problems = list(problems)

    @property
    def photo_count(self):
        """How many photos go into new folders."""
        return sum(len(g.photos) for g in self.groups)

    def merge(self, keep, other):
        """Put the photos of group other into group keep (the review's Merge). Returns keep."""
        if keep is other:
            return keep
        keep.photos.extend(other.photos)
        keep.photos.sort(key=lambda p: (p.taken or dt.datetime.min, p.path))
        self.groups.remove(other)
        return keep

    def rename(self, group, name):
        """Give group a folder name typed in the review (cleaned for Windows). ValueError for an empty name."""
        folder = clean_folder(name)
        if not folder:
            raise ValueError("The folder name is empty or has only characters Windows does not allow.")
        group.folder, group.renamed = folder, True
        return folder


def make_plan(root, photos, places, opts, progress=None, stop=None):
    """The Plan for photos (already read) in root, with places (places.Places) and opts (options()).
    progress(done, total, text) is called while places are looked up; stop() True ends early."""
    left = []
    usable = []
    for p in photos:
        if p.kind == "video" and p.error and not p.has_location:
            left.append((p, p.error))
        else:
            usable.append(p)
    if opts["unknown"] == "guess":
        guess_by_time(usable, opts.get("guess_hours", 3))
    located = [p for p in usable if p.has_location]
    for i, p in enumerate(located):
        if stop and stop():
            break
        p.info = places.lookup(p.lat, p.lon, p.taken, p.altitude)
        if progress:
            progress(i + 1, len(located), p)
    known = [p for p in located if getattr(p, "info", None) is not None and p.info.known]
    for p in [p for p in known if p.taken is None]:
        left.append((p, "it has no date"))                 # rare: not even the file's own date could be read
    known = [p for p in known if p.taken is not None]
    placed = {id(p) for p in known} | {id(p) for p, _ in left}
    unknown = [p for p in usable if id(p) not in placed]
    detail, time = opts["detail"], opts["time"]
    split = place_change_split(detail) if opts.get("split_on_place") else None
    groups = {}

    def group_for(place, key):
        g = groups.get((place.lower(), key))
        if g is None:
            g = groups[(place.lower(), key)] = Group(place, key)
        return g
    if detail == "trip-area" or time == "trip":
        trips = make_trips(known, opts["gap_days"], split)
        if detail == "trip-area":
            for t in trips:
                name_trip(t)
            unify_trip_names(trips)
        else:
            for t in trips:
                names = collections.Counter(p.info.name_at(detail) for p in t.photos)
                t.name = names.most_common(1)[0][0]
        for n, t in enumerate(trips):
            key = {"none": "", "year": t.start.year, "month": (t.start.year, t.start.month), "trip": n}[time]
            g = group_for(t.name, key)
            g.photos.extend(t.photos)
            g.trip = t
    else:
        for p in known:
            key = {"none": "", "year": p.taken.year if p.taken else "",
                   "month": (p.taken.year, p.taken.month) if p.taken else ""}[time]
            group_for(p.info.name_at(detail), key).photos.append(p)
    ordered = sorted(groups.values(), key=lambda g: (g.start or dt.datetime.min, g.place.lower()))
    name_folders(ordered, opts["template"], time)
    for p in unknown:
        reason = "no location in it" if not p.has_location else "no place name was found for its position"
        if p.has_location and places.problem:
            reason += " (" + places.problem.rstrip(".") + ")"
        if opts["unknown"] == "unknown":
            continue
        left.append((p, reason))
    if opts["unknown"] == "unknown" and unknown:
        g = Group(UNKNOWN_FOLDER, unknown=True)
        g.photos = sorted(unknown, key=lambda p: (p.taken or dt.datetime.min, p.path))
        g.folder = UNKNOWN_FOLDER
        ordered.append(g)
    problems = [places.problem] if places.problem and located else []
    return Plan(root, ordered, left, opts, places.attributions, problems)
