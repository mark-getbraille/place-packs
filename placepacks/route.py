"""Offline directions over the navigation part's street network (nav_nodes and nav_edges, placepacks/navigation.py):
walking directions that name the cross streets, the crossings and their accessibility features, simple driving
directions, and a direct transit option (one bus or train, no transfer). Our own A* search (no routing library),
in the Python standard library only.

    from placepacks.navigate import Navigator
    from placepacks.route import directions

    nav = Navigator()
    d = directions(nav, (44.4759, -73.2121), (44.4790, -73.2110), mode="walk", to_name="Made-up Hardware")
    d["steps"]    # ["Walk north on Church Street for 2 blocks, about 400 feet, to Main Street.", ...]
    d["phrase"]   # all the steps in one text, with the distance and time

mode: "walk" (footways, sidewalks, crossings and steps; motorways left out; avoid_steps=True for a step-free route
when the map has one), "drive" (roads only, one-way streets respected) or "transit" (walk to a stop, ride, walk).
The map may lack sidewalks or crossings; the directions say only what the map says. Distances are in feet and
miles (units="metres": metres and km). Walking speed 1.2 m/s, driving speeds by road kind.
"""

import datetime
import heapq
import json
import math

from placepacks import fmt
from placepacks.water import bearing_word

WALK_SPEED = 1.2                        # metres a second
DRIVE_SPEED = {"motorway": 29, "trunk": 25, "primary": 18, "secondary": 16, "tertiary": 14, "motorway_link": 18,
               "trunk_link": 15, "primary_link": 13, "secondary_link": 12, "tertiary_link": 11, "unclassified": 12,
               "residential": 10, "living_street": 5, "service": 6, "road": 10, "busway": 0}
NO_WALK = {"motorway", "motorway_link", "trunk_link", "busway"}
NO_DRIVE = {"footway", "path", "cycleway", "steps", "corridor", "elevator", "platform", "pedestrian", "busway"}
UNNAMED = {"footway": "the footpath", "path": "the path", "cycleway": "the cycle path", "steps": "the steps",
           "service": "the service road", "pedestrian": "the pedestrian street", "corridor": "the corridor",
           "elevator": "the elevator", "platform": "the platform", "living_street": "the street",
           "track": "the track"}
MAX_SEARCH_NODES = 400_000
TURN_SECONDS = {"walk": 8.0, "drive": 15.0}     # what a turn costs in the search (fewer turns, easier directions)


def length_words(metres, units="miles", blocks=0):
    """"2 blocks, about 400 feet", "about 0.6 miles", "about 120 metres"."""
    if units == "miles":
        miles = metres / 1609.344
        text = f"about {max(10, int(round(metres * 3.28084 / 10) * 10))} feet" if miles < 0.2 else \
            f"about {miles:.1f} miles"
    else:
        text = f"about {max(5, int(round(metres / 5) * 5))} metres" if metres < 1000 else \
            f"about {metres / 1000:.1f} km"
    if blocks >= 1:
        return f"{blocks} block{'s' if blocks != 1 else ''}, {text},"
    return text


def minutes_words(seconds):
    """"about 6 minutes", "about 1 hour 10 minutes"."""
    m = max(1, int(round(seconds / 60)))
    if m < 60:
        return f"about {m} minute{'s' if m != 1 else ''}"
    return f"about {m // 60} hour{'s' if m >= 120 else ''}" + (f" {m % 60} minutes" if m % 60 else "")


def turn_words(before, after):
    """The turn from a bearing to another: "continue", "turn slightly right", "turn left", "turn sharply right",
    "make a U-turn"."""
    diff = (after - before + 540) % 360 - 180
    side = "right" if diff > 0 else "left"
    a = abs(diff)
    if a < 25:
        return "continue"
    if a < 60:
        return f"turn slightly {side}"
    if a < 135:
        return f"turn {side}"
    if a < 170:
        return f"turn sharply {side}"
    return "make a U-turn"


class Graph:
    """The part of a navigation pack's network around two positions, loaded once for one search."""

    def __init__(self, pack, south, west, north, east):
        """pack: a navigate.NavPack; the box in degrees."""
        self.pack = pack
        self.nodes, self.adj, self.ways = {}, {}, {}
        cells = set()
        for r in range(int(math.floor((south + 90) * fmt.FINE)), int(math.floor((north + 90) * fmt.FINE)) + 1):
            for c in range(int(math.floor((west + 180) * fmt.FINE)), int(math.floor((east + 180) * fmt.FINE)) + 1):
                cells.add(r * 360 * fmt.FINE + c)
        cells = sorted(cells)
        for i in range(0, len(cells), 500):
            marks = ",".join(map(str, cells[i:i + 500]))
            for r in pack.rows(f"SELECT node, lat, lon FROM nav_nodes WHERE cell IN ({marks})"):
                self.nodes[r["node"]] = (r["lat"] / fmt.SCALE, r["lon"] / fmt.SCALE)
        ids = list(self.nodes)
        for i in range(0, len(ids), 500):
            marks = ",".join(map(str, ids[i:i + 500]))
            for e in pack.rows(f"SELECT id, a, b, way, length, b1, b2 FROM nav_edges WHERE a IN ({marks}) OR b IN "
                               f"({marks})"):
                if e["a"] in self.nodes and e["b"] in self.nodes:
                    self.adj.setdefault(e["a"], {})[e["id"]] = e
                    self.adj.setdefault(e["b"], {})[e["id"]] = e
                    self.ways[e["way"]] = None
        wids = list(self.ways)
        for i in range(0, len(wids), 500):
            marks = ",".join(map(str, wids[i:i + 500]))
            for w in pack.rows(f"SELECT id, name, kind, tags FROM nav_ways WHERE id IN ({marks})"):
                w["tags"] = json.loads(w["tags"]) if w["tags"] else {}
                self.ways[w["id"]] = w

    def allowed(self, edge, forward, mode, avoid_steps=False):
        """True when the edge may be used in this direction (forward: from a to b) in the mode."""
        way = self.ways.get(edge["way"]) or {}
        kind, tags = way.get("kind", ""), way.get("tags", {})
        if mode == "walk":
            if kind in NO_WALK and tags.get("foot") not in ("yes", "designated"):
                return False
            if tags.get("foot") == "no" or tags.get("access") == "no" and tags.get("foot") is None:
                return False
            return not (avoid_steps and kind == "steps")
        if kind in NO_DRIVE or DRIVE_SPEED.get(kind, 0) == 0 or tags.get("access") in ("no", "private"):
            return False
        oneway = tags.get("oneway")
        if oneway in ("yes", "true", "1") and not forward:
            return False
        return not (oneway == "-1" and forward)

    def cost(self, edge, mode):
        """The seconds an edge takes."""
        if mode == "walk":
            kind = (self.ways.get(edge["way"]) or {}).get("kind", "")
            return edge["length"] / WALK_SPEED * (1.3 if kind == "steps" else 1.0)
        kind = (self.ways.get(edge["way"]) or {}).get("kind", "")
        return edge["length"] / DRIVE_SPEED.get(kind, 10)

    def nearest_node(self, lat, lon, mode, avoid_steps=False):
        """The loaded node nearest a position that has an edge usable in the mode, with its distance (metres)."""
        best, dist = None, 1e18
        for n, (y, x) in self.nodes.items():
            d = fmt.metres(lat, lon, y, x)
            if d < dist and any(self.allowed(e, e["a"] == n, mode, avoid_steps) for e in self.adj.get(n, {}).values()):
                best, dist = n, d
        return best, dist

    def search(self, start, goal, mode, avoid_steps=False):
        """A* over (node, arriving edge) states, so a turn costs a little (TURN_SECONDS): of two equal ways, the
        one with fewer turns, which is easier to follow. [(edge, forward)] from node start to node goal, or None."""
        gy, gx = self.nodes[goal]
        speed = WALK_SPEED if mode == "walk" else 29
        turn_cost = TURN_SECONDS[mode]
        first = (start, None)
        best, back = {first: 0.0}, {}
        heap = [(0.0, 0.0, start, None, 0)]
        seen = 0
        while heap:
            _, g, n, via, heading = heapq.heappop(heap)
            state = (n, via)
            if n == goal:
                path = []
                while state != first:
                    edge, forward, prev = back[state]
                    path.append((edge, forward))
                    state = prev
                return path[::-1]
            if g > best.get(state, 1e18):
                continue
            seen += 1
            if seen > MAX_SEARCH_NODES:
                return None
            for e in self.adj.get(n, {}).values():
                forward = e["a"] == n
                if e["a"] == e["b"] or e["id"] == via or not self.allowed(e, forward, mode, avoid_steps):
                    continue
                m = e["b"] if forward else e["a"]
                leave = e["b1"] if forward else (e["b2"] + 180) % 360
                arrive = e["b2"] if forward else (e["b1"] + 180) % 360
                turn = 0.0 if via is None else abs((leave - heading + 540) % 360 - 180)
                ng = g + self.cost(e, mode) + (turn_cost if turn >= 45 else 0.0)
                nxt = (m, e["id"])
                if ng < best.get(nxt, 1e18):
                    best[nxt] = ng
                    back[nxt] = (e, forward, state)
                    y, x = self.nodes[m]
                    heapq.heappush(heap, (ng + fmt.metres(y, x, gy, gx) / speed, ng, m, e["id"], arrive))
        return None


def _name(way):
    """The name a person would hear for a segment ("Main Street", "the sidewalk", "the footpath")."""
    if not way:
        return "the path"
    if way.get("name"):
        return way["name"]
    tags = way.get("tags", {})
    if tags.get("footway") == "sidewalk":
        return "the sidewalk"
    if tags.get("footway") == "crossing":
        return "the crossing"
    return UNNAMED.get(way.get("kind"), "the road")


def _crossing_text(nav, lat, lon, street):
    """", at the signal; the crossing has tactile paving, a push button and an accessible signal" for the crossing
    of a street near a position (navigate.crossing_here), or "" when the map has none within 25 m."""
    c = nav.crossing_here(lat, lon, within=25)
    if not c:
        return ""
    bits = []
    if c["signals"]:
        bits.append("at the signal")
    elif c["type"] in ("zebra", "marked", "uncontrolled"):
        bits.append("at the marked crosswalk")
    has = [w for w, k in (("tactile paving", "tactile_paving"), ("a push button", "button"),
                          ("a talking or vibrating signal", "sound")) if c[k]]
    if c.get("vibration") and not c.get("sound"):
        has = [h for h in has if "signal" not in h] + ["a vibrating signal"]
    if c["kerb"] in ("lowered", "flush"):
        has.append("a curb cut" if c["kerb"] == "lowered" else "a flush curb")
    if c["island"]:
        has.append("a traffic island")
    text = (" " + bits[0]) if bits else ""
    if has:
        from placepacks.navigate import join_names
        text += f"; the crossing has {join_names(has)}"
    if c["tactile_paving"] is False:
        text += "; no tactile paving"
    return text


def _cross_streets(nav, pack, node, own):
    """The other streets of the intersection at a node (nav_intersections), without own."""
    rows = pack.rows("SELECT streets FROM nav_intersections WHERE key = ?", (f"n{node}",))
    if not rows:
        return []
    return [s for s in json.loads(rows[0]["streets"]) if s != own]


def describe(nav, graph, path, start_name, mode, units="miles", to_name="", goal=None):
    """The steps of a path [(edge, forward)] in plain speech: legs along one street, the turns between them, the
    cross streets reached, and, walking, each street crossed with its crossing's accessibility features."""
    pack = graph.pack
    legs = []                                    # {name, length, blocks, bearing_in, bearing_out, end, crossings}
    for edge, forward in path:
        way = graph.ways.get(edge["way"]) or {}
        name = _name(way)
        b_in = edge["b1"] if forward else (edge["b2"] + 180) % 360
        b_out = edge["b2"] if forward else (edge["b1"] + 180) % 360
        end = edge["b"] if forward else edge["a"]
        if legs and legs[-1]["name"] == name and turn_words(legs[-1]["bearing_out"], b_in) in (
                "continue", "turn slightly left", "turn slightly right"):
            leg = legs[-1]
            # The node between the two edges: an intersection passed straight through is a block (and, walking, a
            # street to cross).
            cross = _cross_streets(nav, pack, leg["end"], name)
            if cross:
                leg["blocks"] += 1
                if mode == "walk":
                    leg["crossings"].append((leg["length"], leg["end"], cross))
            leg.update(length=leg["length"] + edge["length"], bearing_out=b_out, end=end)
        else:
            legs.append({"name": name, "kind": way.get("kind"), "tags": way.get("tags", {}),
                         "length": edge["length"], "blocks": 0, "bearing_in": b_in, "bearing_out": b_out,
                         "end": end, "crossings": []})
    verb = "Walk" if mode == "walk" else "Drive"
    steps = []
    for i, leg in enumerate(legs):
        crossing_way = leg["tags"].get("footway") == "crossing" or leg["kind"] == "crossing"
        if crossing_way:
            # A crossing drawn as its own way: say which street it crosses and how.
            y, x = graph.nodes[leg["end"]]
            c = nav.crossing_here(y, x, within=30)
            street = (c or {}).get("street") or "the street"
            text = f"Cross {street}{_crossing_text(nav, y, x, street)}."
            steps.append(text[0].upper() + text[1:])
            continue
        # Each street crossed along the way splits the leg into pieces.
        pieces, done = [], 0.0
        for at, node, cross in leg["crossings"]:
            pieces.append((at - done, node, cross))
            done = at
        pieces.append((leg["length"] - done, leg["end"], None))
        direction = bearing_word_of(leg["bearing_in"])
        if i == 0:
            lead = f"{verb} {direction} on {leg['name']}"
        else:
            turn = turn_words(legs[i - 1]["bearing_out"], leg["bearing_in"])
            if turn == "continue":
                lead = f"Continue {direction} on {leg['name']}"
            else:
                lead = f"{turn[0].upper() + turn[1:]} onto {leg['name']} and {verb.lower()} {direction}"
        for j, (length, node, cross) in enumerate(pieces):
            blocks = 1 if cross else 0
            last = j == len(pieces) - 1
            if last:
                to = _cross_streets(nav, pack, node, leg["name"])
                blocks = max(0, leg["blocks"] - len(leg["crossings"])) + (1 if to else 0)
                target = f" to {join(to)}" if to else ""
                if i == len(legs) - 1:
                    target = ""
            else:
                target = f" to {join(cross)}"
            what = lead if j == 0 else f"Continue {direction} on {leg['name']}"
            steps.append(f"{what} for {length_words(length, units, blocks)}{target}.".replace(",.", "."))
            if cross:
                y, x = graph.nodes[node]
                steps.append(f"Cross {join(cross)}{_crossing_text(nav, y, x, join(cross))}.")
    if goal is not None and path:
        edge, forward = path[-1]
        end = edge["b"] if forward else edge["a"]
        y, x = graph.nodes[end]
        last_bearing = legs[-1]["bearing_out"] if legs else 0
        side = _side(last_bearing, (y, x), goal)
        gap = fmt.metres(y, x, goal[0], goal[1])
        what = to_name or "Your destination"
        if gap < 8:
            steps.append(f"{what} is here.")
        else:
            # "on your left" and "on your right", but "straight ahead" and "behind you" (never "on your ahead")
            where = f"on your {side}" if side in ("left", "right") else ("straight ahead" if side == "ahead" else side)
            steps.append(f"{what} is {length_words(gap, units)} away, {where}.")
    return steps


def join(names):
    """"Main Street", "Main Street and Elm Street"."""
    from placepacks.navigate import join_names
    return join_names(names)


def bearing_word_of(degrees):
    """The compass word of a bearing ("north", "northeast" ...)."""
    words = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    return words[int((degrees % 360 + 22.5) // 45) % 8]


def _side(bearing, here, goal):
    """"left", "right" or "ahead": where goal is seen from here facing bearing."""
    to = (math.degrees(math.atan2(math.radians(goal[1] - here[1]) * math.cos(math.radians(here[0])),
                                  math.radians(goal[0] - here[0]))) + 360) % 360
    diff = (to - bearing + 540) % 360 - 180
    if abs(diff) < 30:
        return "ahead"
    if abs(diff) > 150:
        return "behind you"
    return "right" if diff > 0 else "left"


def directions(nav, start, goal, mode="walk", to_name="", units="miles", avoid_steps=False, when=None):
    """Directions from start to goal ((lat, lon) degrees) over the navigation packs of a Navigator: {"mode",
    "distance_m", "seconds", "steps", "phrase"}; None when no pack covers the two or no way connects them. mode
    "transit": transit_option (walk, one ride, walk), falling back to walking."""
    if mode == "transit":
        found = transit_option(nav, start, goal, when=when, units=units, to_name=to_name)
        if found:
            return found
        mode = "walk"
    span = fmt.metres(start[0], start[1], goal[0], goal[1])
    margin = max(0.006, span * 0.4 / 111_000)
    south, north = min(start[0], goal[0]) - margin, max(start[0], goal[0]) + margin
    west = min(start[1], goal[1]) - margin / max(0.2, math.cos(math.radians(start[0])))
    east = max(start[1], goal[1]) + margin / max(0.2, math.cos(math.radians(start[0])))
    for pack in nav._packs_at(*start):
        graph = Graph(pack, south, west, north, east)
        if not graph.nodes:
            continue
        a, da = graph.nearest_node(*start, mode, avoid_steps)
        b, db = graph.nearest_node(*goal, mode, avoid_steps)
        if a is None or b is None:
            continue
        path = [] if a == b else graph.search(a, b, mode, avoid_steps)
        if path is None:
            continue
        steps = describe(nav, graph, path, "", mode, units, to_name, goal)
        if da > 15:
            y, x = graph.nodes[a]
            steps.insert(0, f"Go {length_words(da, units)} {bearing_word(start[0], start[1], y, x)} to the "
                            f"{'street' if mode == 'drive' else 'path'}.")
        metres = sum(e["length"] for e, _ in path) + da + db
        seconds = metres / WALK_SPEED if mode == "walk" else sum(graph.cost(e, mode) for e, _ in path) + \
            (da + db) / WALK_SPEED
        head = ("Walking" if mode == "walk" else "Driving") + f": {length_words(metres, units)}, " \
            f"{minutes_words(seconds)}."
        return {"mode": mode, "distance_m": round(metres), "seconds": round(seconds), "steps": steps,
                "phrase": " ".join([head] + steps),
                "note": "From the OpenStreetMap network in the pack; check crossings and sidewalks as you go."}
    return None


def transit_option(nav, start, goal, when=None, units="miles", to_name="", within=600):
    """The first direct ride (no transfer) from a stop near start to a stop near goal after when (local time):
    {"mode": "transit", "steps", "phrase", "departure", "arrival", ...}, or None."""
    from placepacks.navigate import service_runs
    when = when or datetime.datetime.now()
    starts = nav.nearest_stops(*start, within=within, limit=8)
    ends = nav.nearest_stops(*goal, within=within, limit=8)
    best = None
    for s in starts:
        pack = s["pack"]
        end_ids = {e["stop"]: e for e in ends if e["pack"] is pack}
        if not end_ids:
            continue
        walk_to = s["distance_m"] / WALK_SPEED
        for back in (1, 0):
            day = when.date() - datetime.timedelta(days=back)
            now = (when - datetime.datetime.combine(day, datetime.time())).total_seconds() + walk_to
            marks = ",".join(map(str, end_ids))
            rows = pack.rows(f"SELECT t1.time AS dep, t2.time AS arr, t2.stop AS end_stop, tr.service, tr.headsign, "
                             f"tr.wheelchair, r.short_name, r.long_name, r.type, sv.days, sv.start, sv.end, "
                             f"(SELECT COUNT(*) FROM nav_times x WHERE x.trip = t1.trip AND x.time > t1.time AND "
                             f"x.time <= t2.time) AS stops FROM nav_times t1 JOIN nav_times t2 ON t2.trip = t1.trip "
                             f"AND t2.time > t1.time JOIN nav_trips tr ON tr.id = t1.trip JOIN nav_routes r ON "
                             f"r.id = tr.route JOIN nav_services sv ON sv.id = tr.service WHERE t1.stop = ? AND "
                             f"t2.stop IN ({marks}) AND t1.time >= ? AND t1.time <= ? ORDER BY t1.time",
                             (s["stop"], int(now), int(now + 3 * 3600)))
            for r in rows:
                exceptions = {d["date"]: d["added"] for d in pack.rows(
                    "SELECT date, added FROM nav_service_dates WHERE service = ?", (r["service"],))}
                if not service_runs((r["days"], r["start"], r["end"]), day, exceptions):
                    continue
                e = end_ids[r["end_stop"]]
                arrive = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(
                    seconds=r["arr"] + e["distance_m"] / WALK_SPEED)
                if best is None or arrive < best["arrive"]:
                    best = {"arrive": arrive, "row": r, "start": s, "end": e, "day": day}
                break
    if best is None:
        return None
    from placepacks.navigate import ROUTE_KINDS
    r, s, e, day = best["row"], best["start"], best["end"], best["day"]
    dep = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(seconds=r["dep"])
    arr = datetime.datetime.combine(day, datetime.time()) + datetime.timedelta(seconds=r["arr"])
    kind = ROUTE_KINDS.get(r["type"], "bus")
    route = r["short_name"] or r["long_name"]
    steps = [f"Walk {length_words(s['distance_m'], units)} {s['bearing']} to the {s['name']} stop.",
             f"Take {kind} {route}" + (f" toward {r['headsign']}" if r["headsign"] else "") +
             f" at {dep:%H:%M}" + ({1: " (wheelchair accessible)", 2: " (not wheelchair accessible)"}.get(
                 r["wheelchair"], "")) + ".",
             f"Ride {r['stops']} stop{'s' if r['stops'] != 1 else ''} to {e['name']}, arriving at {arr:%H:%M}.",
             f"Walk {length_words(e['distance_m'], units)} to {to_name or 'your destination'}."]
    total = (best["arrive"] - (when if isinstance(when, datetime.datetime) else datetime.datetime.now()))
    return {"mode": "transit", "departure": f"{dep:%H:%M}", "arrival": f"{best['arrive']:%H:%M}",
            "route": route, "steps": steps, "seconds": round(total.total_seconds()),
            "phrase": f"By {kind}: arrive about {best['arrive']:%H:%M}. " + " ".join(steps)}
