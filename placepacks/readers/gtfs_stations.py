"""Station accessibility from the transit agencies' own GTFS feeds (queue item Q4, notes/helper-rules.txt): the
feeds the build already reads for the transit stops (source "gtfs") and the timetables (source "gtfs-navigation")
also say, when the agency fills them in:

  stops.txt     wheelchair_boarding of each stop and station (1 yes, 2 no, 0 not known: then the parent station's
                value counts), and the station ENTRANCES (location_type 2) with their own positions
  levels.txt    the station's levels ("Street", "Mezzanine", "Platform")
  pathways.txt  how one gets around inside a station: walkways, stairs (pathway_mode 2, with stair_count),
                escalators (4), elevators (5), fare gates; each between two points of the station

This module turns them into:
  - site features of the extra part (reader "gtfs_station_features", source "gtfs-station-features"): each
    entrance (kind "accessible entrance" when wheelchair boarding is yes, else "entrance"), elevator, escalator and
    stairs, with its station (site: the station's key in the extra part, "gtfs:<feed file>:<stop id>"), its level
    and a note ("Elevator from Street to Platform; wheelchair: yes"); and a note on every stop and station that
    says whether wheelchair boarding is possible ("Wheelchair boarding: yes (the agency's timetable data)"), so
    "can I board at this stop in a wheelchair" is answered from the default packs;
  - navigation features (placepacks/readers/navigation.py read_feed calls station_features): entrances (with
    wheelchair=yes/no), elevators, escalators and stairs (kind "steps"), for Navigator.features_near.
Each feed keeps its own open licence (the same files as the source "gtfs"). A feed without pathways.txt simply
has no station features.
Only the Python standard library is used.
"""

import csv
import io
import os
import zipfile

from placepacks import features
from placepacks.readers import reader
from placepacks.regions import in_region

MODES = {2: "stairs", 4: "escalator", 5: "elevator"}
WORDS = {"stairs": "Stairs", "escalator": "Escalator", "elevator": "Elevator"}


def _rows(z, name):
    """The rows of one file of a feed, or [] when the feed does not have it."""
    found = [n for n in z.namelist() if os.path.basename(n) == name]
    if not found:
        return []
    return list(csv.DictReader(io.TextIOWrapper(z.open(found[0]), encoding="utf-8-sig", errors="replace")))


def _int(text, default=0):
    """A whole number from a GTFS field ("" -> default)."""
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


def _pos(stop):
    """(lat, lon) of a stops.txt row, or None (generic nodes and boarding areas may have none)."""
    try:
        lat, lon = float(stop.get("stop_lat") or ""), float(stop.get("stop_lon") or "")
    except ValueError:
        return None
    return (lat, lon) if (lat or lon) else None


def station_of(stops, stop_id, depth=0):
    """The stop id of the station (location_type 1) a stop, entrance or node belongs to, or "" (a stop alone)."""
    s = stops.get(stop_id)
    if not s or depth > 4:
        return ""
    if _int(s.get("location_type")) == 1:
        return stop_id
    return station_of(stops, (s.get("parent_station") or "").strip(), depth + 1)


def wheelchair_of(stops, stop_id):
    """The wheelchair boarding of a stop (1 yes, 2 no, 0 not known), its parent station's when it says 0."""
    s = stops.get(stop_id) or {}
    value = _int(s.get("wheelchair_boarding"))
    if value == 0 and s.get("parent_station"):
        value = _int((stops.get(s["parent_station"].strip()) or {}).get("wheelchair_boarding"))
    return value


def station_features(z):
    """The station features of an open feed (zipfile): [{"key" (without the feed), "kind" (entrance, accessible
    entrance, elevator, escalator, stairs), "name", "station" (its station's stop id), "station_name", "lat",
    "lon", "level", "wheelchair" (1, 2 or 0), "notes"}], and the stops {stop_id: row}. A pathway without any
    position (its ends and its station have none) is left out; each elevator, escalator or stairs between the
    same two points is kept once (a feed often lists both directions)."""
    stops = {(r.get("stop_id") or "").strip(): r for r in _rows(z, "stops.txt")}
    levels = {(r.get("level_id") or "").strip(): (r.get("level_name") or "").strip() or
              f"level {(r.get('level_index') or '').strip()}" for r in _rows(z, "levels.txt")}
    out = []
    for sid, s in stops.items():
        if _int(s.get("location_type")) != 2 or not _pos(s):
            continue
        station = station_of(stops, sid)
        chair = wheelchair_of(stops, sid)
        name = " ".join((s.get("stop_name") or "").split())
        lat, lon = _pos(s)
        out.append({"key": sid, "kind": "accessible entrance" if chair == 1 else "entrance", "name": name,
                    "station": station, "station_name": (stops.get(station) or {}).get("stop_name", ""),
                    "lat": lat, "lon": lon, "level": levels.get((s.get("level_id") or "").strip(), ""),
                    "wheelchair": chair,
                    "notes": "Station entrance" + {1: "; wheelchair: yes", 2: "; wheelchair: no"}.get(chair, "")})
    seen = set()
    for p in _rows(z, "pathways.txt"):
        kind = MODES.get(_int(p.get("pathway_mode")))
        a, b = (p.get("from_stop_id") or "").strip(), (p.get("to_stop_id") or "").strip()
        if not kind or a not in stops or b not in stops:
            continue
        station = station_of(stops, a) or station_of(stops, b)
        name = " ".join((p.get("signposted_as") or "").split())
        ident = (station, kind, name, frozenset((a, b)))
        if ident in seen:
            continue
        seen.add(ident)
        at = _pos(stops[a]) or _pos(stops[b]) or _pos(stops.get(station) or {})
        if not at:
            continue
        la, lb = levels.get((stops[a].get("level_id") or "").strip(), ""), \
            levels.get((stops[b].get("level_id") or "").strip(), "")
        bits = [WORDS[kind] + (f" from {la} to {lb}" if la and lb and la != lb else "")]
        if kind == "stairs" and _int(p.get("stair_count")):
            bits.append(f"{abs(_int(p.get('stair_count')))} steps")
        if kind == "elevator":
            bits.append("wheelchair: yes")
        out.append({"key": f"pathway:{(p.get('pathway_id') or '').strip()}", "kind": kind,
                    "name": name or WORDS[kind], "station": station,
                    "station_name": (stops.get(station) or {}).get("stop_name", ""), "lat": at[0], "lon": at[1],
                    "level": la, "wheelchair": 1 if kind == "elevator" else 0, "notes": "; ".join(bits)})
    return out, stops


def feed_name(file):
    """The feed's name as the source "gtfs" keys its stops: the file name without ".zip" ("mdb-mdb-373")."""
    return os.path.basename(file)[:-4]


@reader("gtfs_station_features")
def read(path, entry, region, writer):
    """Add the station features of every feed .zip in path (a folder or one file) to the extra part, and the
    wheelchair boarding notes of its stops (see the module docstring). Returns the features written plus the stops
    that got a note."""
    files = [os.path.join(path, f) for f in sorted(os.listdir(path)) if f.endswith(".zip")] \
        if os.path.isdir(path) else [path]
    source = entry["id"]
    feats = features.store(writer)
    count = 0
    for file in files:
        try:
            with zipfile.ZipFile(file) as z:
                found, stops = station_features(z)
        except (zipfile.BadZipFile, OSError, KeyError):
            continue
        feed = feed_name(file)
        for f in found:
            if not in_region(region, f["lat"], f["lon"]):
                continue
            site = f"gtfs:{feed}:{f['station']}" if f["station"] else ""
            if feats.add(f"gtfs:{feed}:{f['key']}", source, f["kind"], f["name"], f["lat"], f["lon"], site=site,
                         level=f["level"], notes=f["notes"]):
                count += 1
        if not entry.get("stop_notes", True):
            continue
        for sid, s in stops.items():
            kind = _int(s.get("location_type"))
            at = _pos(s)
            if kind not in (0, 1) or not at or not in_region(region, *at):
                continue
            chair = wheelchair_of(stops, sid)
            if chair in (1, 2) and writer.fill_details(
                    source, f"gtfs:{feed}:{sid}", {},
                    "Wheelchair boarding: " + ("yes" if chair == 1 else "no") + " (the agency's timetable data)"):
                count += 1
    return count
