"""Getting around with the navigation part (us-vermont-navigation.osmpack, placepacks/navigation.py): the lookups
a program asks when its user is walking. Only the Python standard library is used.

    from placepacks.download import ensure_pack
    from placepacks.navigate import Navigator

    ensure_pack("us-vermont", part="navigation")
    nav = Navigator()
    nav.nearest_intersection(44.4759, -73.2121)  # {"streets": ["Church Street", "Main Street"], "distance_m": 18,
                                                  #  "bearing": "north", "signals": True, "phrase": "..."}
    nav.crossing_here(44.4759, -73.2121)         # how to cross: the crossing's type, signals, tactile paving, kerbs
    nav.next_buses(44.4759, -73.2121, when=datetime.datetime(2026, 11, 23, 8, 0))
    nav.features_near(44.4759, -73.2121, 50, kinds={"entrance"})
    nav.street_here(44.4759, -73.2121)           # the segment one is on: its name, sidewalks, surface, lighting

Every answer is a dict with "phrase", a plain sentence for a screen reader, beside the facts it was made from; None
when there is nothing within reach (or no navigation pack covers the position). Distances are in metres;
phrase(units="miles") says feet instead. GTFS times are the feed's local time (nav_feeds.timezone): pass `when` in
that local time.
"""

import datetime
import json

from placepacks import fmt
from placepacks.lookup import default_folder, open_packs
from placepacks.water import bearing_word

ATTRIBUTION_OSM = "© OpenStreetMap contributors"
CROSSING_WORDS = {"traffic_signals": "a crossing with traffic signals", "zebra": "a marked zebra crossing",
                  "marked": "a marked crossing", "uncontrolled": "a marked crossing without signals",
                  "unmarked": "an unmarked crossing", "no": "no crossing", "informal": "an informal crossing",
                  "island": "a crossing with a traffic island"}
WHEELCHAIR_WORDS = {"yes": "step-free", "limited": "partly step-free", "no": "not step-free",
                    "designated": "made for wheelchairs"}
ROUTE_KINDS = {0: "tram", 1: "subway", 2: "train", 3: "bus", 4: "ferry", 5: "cable car", 6: "gondola",
               7: "funicular", 11: "trolleybus", 12: "monorail"}


def _around(lat, lon, rings=1):
    """The fine cells around a position (rings=1: 3 by 3 cells, about 3 km across)."""
    step = 1.0 / fmt.FINE
    return sorted({fmt.fine_cell(lat + dy * step, lon + dx * step) for dy in range(-rings, rings + 1)
                   for dx in range(-rings, rings + 1)})


def distance_words(metres, units="metres"):
    """"18 metres" or "60 feet" (rounded: to 5 below 100, to 10 above)."""
    if units == "miles":
        feet = metres * 3.28084
        if feet >= 1000:
            return f"{metres / 1609.344:.1f} miles"
        return f"{int(round(feet / 10.0) * 10)} feet"
    step = 5 if metres < 100 else 10
    return f"{int(round(metres / step) * step)} metres"


def _tags(text):
    """The tags of a row (JSON text) as a dict."""
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def _streets(text):
    """The street names of a row (JSON list text) as a list."""
    try:
        return list(json.loads(text)) if text else []
    except ValueError:
        return []


def join_names(names):
    """"Main Street", "Main Street and Elm Street", "Main Street, Elm Street and Oak Avenue"."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def crossing_facts(tags):
    """{type, signals, sound, vibration, button, arrow, tactile_paving, kerb, island, markings} of a crossing's tags,
    each None when the map does not say."""
    def yes(key):
        """True, False, or None when the tag is not there."""
        v = tags.get(key)
        return None if v is None else v not in ("no", "none")
    kind = tags.get("crossing") or ("traffic_signals" if tags.get("highway") == "traffic_signals" else None)
    signals = tags.get("crossing:signals")
    return {"type": kind,
            "signals": (signals not in ("no", None)) if signals else (True if kind == "traffic_signals" else
                                                                      False if kind in ("uncontrolled", "unmarked",
                                                                                        "zebra") else None),
            "sound": yes("traffic_signals:sound"), "vibration": yes("traffic_signals:vibration"),
            "button": yes("button_operated"), "arrow": yes("traffic_signals:arrow"),
            "tactile_paving": yes("tactile_paving"), "kerb": tags.get("kerb"),
            "island": yes("crossing:island"), "markings": tags.get("crossing:markings")}


def crossing_phrase(facts, street, distance_m, bearing, units="metres", kerbs=()):
    """A sentence about a crossing: "A crossing with traffic signals over Main Street, 20 metres northeast. It has a
    push button and the signal sounds (an accessible pedestrian signal). Tactile paving: yes. Kerb: lowered."."""
    kind = CROSSING_WORDS.get(facts["type"] or "", "a crossing")
    where = f" over {street}" if street else ""
    out = [f"{kind[0].upper() + kind[1:]}{where}, {distance_words(distance_m, units)} {bearing}."]
    aps = [w for w, k in (("the signal sounds", "sound"), ("it vibrates", "vibration"),
                          ("it has a raised arrow", "arrow")) if facts[k]]
    if facts["button"]:
        out.append("It has a push button" + (", and " + " and ".join(aps) if aps else "") + ".")
    elif aps:
        out.append(join_names(aps).capitalize() + ".")
    if aps:
        out.append("It has an accessible pedestrian signal.")
    elif facts["signals"] and facts["sound"] is False:
        out.append("The signal does not sound.")
    if facts["island"]:
        out.append("There is a traffic island in the middle.")
    if facts["tactile_paving"] is not None:
        out.append("Tactile paving: " + ("yes." if facts["tactile_paving"] else "no."))
    kerb = facts["kerb"] or (kerbs[0] if kerbs else None)
    if kerb:
        out.append(f"Kerb: {kerb}.")
    return " ".join(out)


LISTED_SIGNAL_M = 35       # a city's listed accessible pedestrian signal this near a crossing belongs to it
LISTED_RAMP_M = 20         # a city's listed curb ramp this near a crossing is one of its ramps


def listed_phrase(listed, ramps, lead=True):
    """Sentences about a city's own lists at a crossing: "The city lists an accessible pedestrian signal here
    (installed 2023-12-16; locator tone; vibrating arrow button)." and "Curb ramp in the city's list: ADA compliant:
    yes; detectable warning surface: yes; condition: good." ("" when there is nothing.) lead=False leaves out the
    first sentence's opening (the caller has said it)."""
    out = []
    if listed:
        t = listed["tags"]
        bits = [f"installed {t['installed']}"] if t.get("installed") else []
        bits += [w for k, w in (("locator_tone", "locator tone"), ("vibration", "vibrating arrow button"),
                                ("speech", "speech message")) if t.get(k) == "yes"]
        if lead:
            out.append("The city lists an accessible pedestrian signal here" + (f" ({'; '.join(bits)})." if bits
                                                                                  else "."))
        elif bits:
            out.append(f"It is listed with: {'; '.join(bits)}.")
    if ramps:
        t = ramps[0]["tags"]
        bits = [f"{w}: {t[k]}" for k, w in (("compliant", "ADA compliant"),
                                            ("detectable_warning", "detectable warning surface"),
                                            ("condition", "condition")) if t.get(k)]
        n = len(ramps)
        out.append(("A curb ramp" if n == 1 else f"{n} curb ramps") + " in the city's list"
                   + (f" (the nearest: {'; '.join(bits)})." if bits else "."))
    return " ".join(out)


def service_runs(service, day, exceptions):
    """True when a timetable (days bitmask, start, end) runs on a date (datetime.date); exceptions: {YYYYMMDD: 1
    added or 0 removed} of that timetable."""
    key = day.year * 10000 + day.month * 100 + day.day
    if key in exceptions:
        return exceptions[key] == 1
    days, start, end = service
    return bool(days & (1 << day.weekday())) and (not start or start <= key) and (not end or key <= end)


class NavPack:
    """One navigation pack (a PackReader whose part is "navigation")."""

    def __init__(self, reader):
        """reader: a placepacks.lookup.PackReader of a navigation part."""
        self.reader = reader
        self.rows = reader._rows

    def near(self, table, lat, lon, within, where="", args=()):
        """Rows of a point table (nav_intersections, nav_features, nav_stops) within metres, nearest first, with
        "d" (metres), "lat" and "lon" in degrees."""
        rings = 1 if within <= 1000 else 2
        cells = ",".join(map(str, _around(lat, lon, rings)))
        out = []
        for r in self.rows(f"SELECT * FROM {table} WHERE cell IN ({cells}){' AND ' + where if where else ''}", args):
            r["lat"], r["lon"] = r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE
            r["d"] = fmt.metres(lat, lon, r["lat"], r["lon"])
            if r["d"] <= within:
                out.append(r)
        return sorted(out, key=lambda r: r["d"])

    def ways_near(self, lat, lon, within):
        """Segments within metres, nearest first, with "d" (metres)."""
        fine = ",".join(map(str, _around(lat, lon)))
        ids = [r["way"] for r in self.rows(f"SELECT DISTINCT way FROM nav_grid WHERE (level = 1 AND cell IN ({fine})) "
                                           f"OR (level = 0 AND cell = ?)", (fmt.coarse_cell(lat, lon),))]
        out = []
        for chunk in range(0, len(ids), 500):
            marks = ",".join(map(str, ids[chunk:chunk + 500]))
            for r in self.rows(f"SELECT * FROM nav_ways WHERE id IN ({marks})"):
                pts = fmt.unpack_points(r["pts"])
                r["d"] = min(fmt.segment_metres(lat, lon, a, b) for a, b in zip(pts, pts[1:])) if len(pts) > 1 \
                    else 1e9
                if r["d"] <= within:
                    r["tags"] = _tags(r["tags"])
                    out.append(r)
        return sorted(out, key=lambda r: r["d"])


class Navigator:
    """The navigation lookups over every navigation pack in a folder (see the module docstring)."""

    def __init__(self, folder=None, packs=None):
        """folder: where the packs are (placepacks.lookup.default_folder()); packs: PackReaders (for tests)."""
        readers = packs if packs is not None else open_packs(folder or default_folder())
        self.packs = [NavPack(p) for p in readers if p.part == "navigation"]

    def _packs_at(self, lat, lon):
        """The navigation packs whose bounds hold the position."""
        return [p for p in self.packs if p.reader.covers(lat, lon)]

    def _near(self, table, lat, lon, within, where="", args=()):
        """Rows of a table from every pack covering the position, nearest first (each with "pack")."""
        out = []
        for p in self._packs_at(lat, lon):
            for r in p.near(table, lat, lon, within, where, args):
                r["pack"] = p
                out.append(r)
        return sorted(out, key=lambda r: r["d"])

    # -- the street network

    def nearest_intersection(self, lat, lon, within=400, units="metres"):
        """The nearest intersection of named streets: {"streets", "distance_m", "bearing", "signals", "lat", "lon",
        "phrase"}, or None."""
        rows = self._near("nav_intersections", lat, lon, within)
        if not rows:
            return None
        r = rows[0]
        streets = _streets(r["streets"])
        bearing = bearing_word(lat, lon, r["lat"], r["lon"])
        phrase = f"{join_names(streets)}, {distance_words(r['d'], units)} {bearing}" + \
            (", with traffic signals." if r["signals"] else ".")
        if r["d"] < 8:
            phrase = f"At {join_names(streets)}" + (", with traffic signals." if r["signals"] else ".")
        return {"streets": streets, "distance_m": round(r["d"]), "bearing": bearing, "signals": bool(r["signals"]),
                "lat": r["lat"], "lon": r["lon"], "key": r["key"], "phrase": phrase,
                "attribution": ATTRIBUTION_OSM}

    def street_here(self, lat, lon, within=30, units="metres"):
        """The segment nearest the position: {"name", "kind", "sidewalk", "surface", "lit", "tags", "distance_m",
        "phrase"}, or None."""
        best = None
        for p in self._packs_at(lat, lon):
            for r in p.ways_near(lat, lon, within):
                if best is None or r["d"] < best["d"]:
                    best = r
        if best is None:
            return None
        t = best["tags"]
        sidewalk = t.get("sidewalk") or ("both" if t.get("sidewalk:both") in ("yes", "separate") else None)
        name = best["name"] or {"footway": "a footpath", "path": "a path", "steps": "steps", "cycleway": "a cycle path",
                                "service": "a service road", "pedestrian": "a pedestrian street",
                                "corridor": "an indoor corridor"}.get(best["kind"], "an unnamed road")
        if t.get("footway") == "sidewalk":
            name = "a sidewalk"
        elif t.get("footway") == "crossing":
            name = "a crossing"
        bits = [f"On {name}." if best["d"] < 12 else f"Near {name}, {distance_words(best['d'], units)} away."]
        if sidewalk:
            bits.append({"both": "Sidewalks on both sides.", "left": "A sidewalk on the left side of the way it was "
                         "drawn.", "right": "A sidewalk on the right side of the way it was drawn.",
                         "no": "No sidewalk.", "none": "No sidewalk.", "separate": "The sidewalks are mapped "
                         "separately."}.get(sidewalk, f"Sidewalk: {sidewalk}."))
        if t.get("surface"):
            bits.append(f"Surface: {t['surface'].replace('_', ' ')}.")
        if t.get("lit"):
            bits.append("Lit at night." if t["lit"] == "yes" else "Not lit." if t["lit"] == "no" else "")
        if best["kind"] == "steps" and t.get("step_count"):
            bits.append(f"{t['step_count']} steps.")
        if t.get("handrail") in ("yes", "no"):
            bits.append("Handrail." if t["handrail"] == "yes" else "No handrail.")
        if t.get("incline"):
            bits.append(f"Incline: {t['incline']}.")
        return {"name": best["name"], "kind": best["kind"], "sidewalk": sidewalk, "surface": t.get("surface"),
                "lit": t.get("lit"), "tags": t, "distance_m": round(best["d"]), "key": best["key"],
                "phrase": " ".join(b for b in bits if b), "attribution": ATTRIBUTION_OSM}

    # -- crossings and accessibility features

    def features_near(self, lat, lon, within=50, kinds=None, units="metres"):
        """Features within metres, nearest first: [{"kind", "name", "tags", "streets", "distance_m", "bearing",
        "lat", "lon"}]. kinds: a set of feature kinds (navigation.feature_kind) to keep, or None for all."""
        out = []
        for r in self._near("nav_features", lat, lon, within):
            if kinds is not None and r["kind"] not in kinds:
                continue
            out.append({"kind": r["kind"], "name": r["name"], "tags": _tags(r["tags"]),
                        "streets": _streets(r["streets"]), "distance_m": round(r["d"]),
                        "bearing": bearing_word(lat, lon, r["lat"], r["lon"]), "lat": r["lat"], "lon": r["lon"],
                        "key": r["key"]})
        return out

    def crossing_here(self, lat, lon, within=60, units="metres"):
        """How to cross here: the nearest crossing (or crossing with traffic signals) within metres, {"type",
        "street", "signals", "sound", "vibration", "button", "arrow", "tactile_paving", "kerb", "island",
        "distance_m", "bearing", "phrase", "listed_signal", "curb_ramps"}, or None. Kerbs mapped as their own points
        within 15 m of the crossing fill in its kerb when the crossing itself does not say. A city's or DOT's own
        list (open data, source street-access-navigation) adds the accessible pedestrian signal it lists within
        LISTED_SIGNAL_M of the crossing (listed_signal: its install date, locator tone, vibrating arrow) and its curb
        ramps within LISTED_RAMP_M (curb_ramps: condition, ADA compliance, detectable warning), said after the map's
        facts; where the map has no crossing but a city lists a signal within metres, that signal is said."""
        found = self.features_near(lat, lon, within, {"crossing", "traffic signals"})
        crossings = [f for f in found if f["kind"] == "crossing"] or found
        if not crossings:
            return self._listed_signal_only(lat, lon, within, units)
        c = crossings[0]
        tags = dict(c["tags"])
        if c["kind"] == "crossing" and not tags.get("crossing"):
            # A crossing node next to signals (traffic signals mapped at the stop line) is a signalled crossing.
            if any(f["kind"] == "traffic signals" and fmt.metres(c["lat"], c["lon"], f["lat"], f["lon"]) < 25
                   for f in found):
                tags.setdefault("crossing", "traffic_signals")
        for f in found:
            if f["kind"] == "traffic signals" and fmt.metres(c["lat"], c["lon"], f["lat"], f["lon"]) < 25:
                for k in ("traffic_signals:sound", "traffic_signals:vibration", "button_operated",
                          "traffic_signals:arrow"):
                    if k in f["tags"]:
                        tags.setdefault(k, f["tags"][k])
        facts = crossing_facts(tags)
        kerbs = [f["tags"].get("kerb") for f in self.features_near(c["lat"], c["lon"], 15, {"kerb"})
                 if f["tags"].get("kerb")]
        streets = [s for s in c["streets"] if s not in ("footway", "path", "crossing")]
        street = join_names(streets)
        listed = self.listed_signal(c["lat"], c["lon"])
        ramps = self.listed_curb_ramps(c["lat"], c["lon"])
        phrase = crossing_phrase(facts, street, c["distance_m"], c["bearing"], units, kerbs)
        extra = listed_phrase(listed, ramps)
        attribution = ATTRIBUTION_OSM + ("; " + ", ".join(dict.fromkeys(
            x["tags"].get("source", "") for x in ([listed] if listed else []) + ramps if x["tags"].get("source")))
            if listed or ramps else "")
        return dict(facts, street=street, kerbs=kerbs, distance_m=c["distance_m"], bearing=c["bearing"],
                    lat=c["lat"], lon=c["lon"], key=c["key"], listed_signal=listed, curb_ramps=ramps,
                    phrase=phrase + (" " + extra if extra else ""), attribution=attribution.rstrip("; "))

    # -- cities' own lists (open data, source street-access-navigation)

    def listed_signal(self, lat, lon, within=LISTED_SIGNAL_M):
        """The nearest accessible pedestrian signal of a city's or a DOT's own list within metres of a crossing:
        {"name", "tags" (installed, locator_tone, vibration, button, source ...), "distance_m", ...}, or None."""
        found = self.features_near(lat, lon, within, {"accessible pedestrian signal"})
        return found[0] if found else None

    def listed_curb_ramps(self, lat, lon, within=LISTED_RAMP_M):
        """The curb ramps of a city's own inventory within metres of a crossing, nearest first."""
        return self.features_near(lat, lon, within, {"curb ramp"})

    def _listed_signal_only(self, lat, lon, within, units):
        """crossing_here where the map has no crossing but a city lists an accessible pedestrian signal nearby: its
        facts and a sentence, or None."""
        listed = self.listed_signal(lat, lon, within)
        if not listed:
            return None
        where = f" at {listed['name']}" if listed["name"] else ""
        phrase = (f"No crossing is mapped here, but the city lists an accessible pedestrian signal{where}, "
                  f"{distance_words(listed['distance_m'], units)} {listed['bearing']}. "
                  + listed_phrase(listed, [], lead=False))
        facts = crossing_facts({})
        return dict(facts, street="", kerbs=[], distance_m=listed["distance_m"], bearing=listed["bearing"],
                    lat=listed["lat"], lon=listed["lon"], key=listed["key"], listed_signal=listed, curb_ramps=[],
                    phrase=phrase.strip(), attribution=listed["tags"].get("source", ""))

    # -- transit

    def nearest_stops(self, lat, lon, within=400, limit=3):
        """The nearest transit stops (not stations): [{"name", "code", "wheelchair", "distance_m", "bearing",
        "feed", "stop", "pack"}]."""
        out = []
        for r in self._near("nav_stops", lat, lon, within, "location_type = 0"):
            out.append({"name": r["name"], "code": r["code"], "wheelchair": r["wheelchair"], "feed": r["feed"],
                        "stop": r["id"], "distance_m": round(r["d"]), "lat": r["lat"], "lon": r["lon"],
                        "bearing": bearing_word(lat, lon, r["lat"], r["lon"]), "pack": r["pack"],
                        "key": r["key"]})
        return out[:limit]

    def stop_amenities(self, lat, lon, within=30):
        """What the map says about the stop at a position (the nearest bus or tram stop of OpenStreetMap within
        metres): {"has": [...], "lacks": [...], "tags", "phrase"} ("It has a shelter, a bench and tactile paving.")."""
        found = self.features_near(lat, lon, within, {"bus stop", "tram stop", "platform"})
        if not found:
            return {"has": [], "lacks": [], "tags": {}, "phrase": ""}
        t = found[0]["tags"]
        words = (("a shelter", "shelter"), ("a bench", "bench"), ("tactile paving", "tactile_paving"),
                 ("a bin", "bin"), ("lighting", "lit"), ("a departures board", "departures_board"))
        has = [w for w, k in words if t.get(k) and t[k] not in ("no", "none")]
        lacks = [w for w, k in words if t.get(k) in ("no", "none")]
        bits = []
        if has:
            bits.append(f"It has {join_names(has)}.")
        if lacks:
            bits.append(f"No {join_names([w.split(' ', 1)[-1] if w.startswith('a ') else w for w in lacks])}.")
        return {"has": has, "lacks": lacks, "tags": t, "phrase": " ".join(bits)}

    def departures(self, pack, stop, when, limit=3, hours=3):
        """The next departures from a stop (its nav_stops id in pack) after when (a local datetime), within hours:
        [{"route", "kind", "headsign", "time", "minutes", "wheelchair"}]. A trip of the day before that runs past
        midnight (GTFS times over 24:00) is counted too."""
        out = []
        for back in (1, 0):
            day = when.date() - datetime.timedelta(days=back)
            now = (when - datetime.datetime.combine(day, datetime.time())).total_seconds()
            rows = pack.rows("SELECT t.time, tr.service, tr.headsign, tr.wheelchair, r.short_name, r.long_name, "
                             "r.type, s.days, s.start, s.end FROM nav_times t JOIN nav_trips tr ON tr.id = t.trip "
                             "JOIN nav_routes r ON r.id = tr.route JOIN nav_services s ON s.id = tr.service "
                             "WHERE t.stop = ? AND t.time >= ? AND t.time <= ? ORDER BY t.time",
                             (stop, int(now), int(now + hours * 3600)))
            exceptions = {}
            for row in rows:
                if row["service"] not in exceptions:
                    exceptions[row["service"]] = {d["date"]: d["added"] for d in pack.rows(
                        "SELECT date, added FROM nav_service_dates WHERE service = ?", (row["service"],))}
                if not service_runs((row["days"], row["start"], row["end"]), day, exceptions[row["service"]]):
                    continue
                at = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(seconds=row["time"])
                out.append({"route": row["short_name"] or row["long_name"], "kind": ROUTE_KINDS.get(row["type"], "bus"),
                            "headsign": row["headsign"], "time": at.strftime("%H:%M"), "at": at,
                            "minutes": int((at - when).total_seconds() // 60), "wheelchair": row["wheelchair"]})
        out.sort(key=lambda d: d["at"])
        return out[:limit]

    def next_buses(self, lat, lon, when=None, within=400, limit=3, units="metres"):
        """The next departures from the nearest stop that has any within three hours: {"stop", "code",
        "wheelchair_boarding", "distance_m", "bearing", "departures", "phrase", "attribution"}, or None when no stop
        is within reach."""
        when = when or datetime.datetime.now()
        stops = self.nearest_stops(lat, lon, within, limit=5)
        if not stops:
            return None
        chosen, deps = stops[0], []
        for s in stops:
            deps = self.departures(s["pack"], s["stop"], when, limit)
            if deps:
                chosen = s
                break
        name = chosen["name"] + (f" (stop {chosen['code']})" if chosen["code"] else "")
        bits = [f"Nearest stop: {name}, {distance_words(chosen['distance_m'], units)} {chosen['bearing']}."]
        if chosen["wheelchair"] in (1, 2):
            bits.append("Wheelchair boarding: " + ("yes." if chosen["wheelchair"] == 1 else "no."))
        amenities = self.stop_amenities(chosen["lat"], chosen["lon"])
        if amenities["phrase"]:
            bits.append(amenities["phrase"])
        if not deps:
            bits.append("No departures in the next three hours.")
        for d in deps:
            what = f"{d['kind'].capitalize()} {d['route']}" + (f" to {d['headsign']}" if d["headsign"] else "")
            access = {1: ", wheelchair accessible", 2: ", not wheelchair accessible"}.get(d["wheelchair"], "")
            bits.append(f"{what} at {d['time']}, in {d['minutes']} minutes{access}.")
        feed = chosen["pack"].rows("SELECT provider, licence_url FROM nav_feeds WHERE feed = ?", (chosen["feed"],))
        credit = (feed[0]["provider"] if feed else "") or chosen["feed"]
        return {"stop": chosen["name"], "code": chosen["code"], "wheelchair_boarding": chosen["wheelchair"],
                "distance_m": chosen["distance_m"], "bearing": chosen["bearing"],
                "departures": [{k: v for k, v in d.items() if k != "at"} for d in deps], "phrase": " ".join(bits),
                "attribution": f"Timetable: {credit}" + (f" ({feed[0]['licence_url']})" if feed and
                                                         feed[0]["licence_url"] else "")}
