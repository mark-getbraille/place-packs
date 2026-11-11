"""Build one part of one region's pack from the fetched inputs, merged with the previous pack's history.

    python -m placepacks.build us-vermont --part core --inputs work/us-vermont/fetched.json \
        --previous previous/us-vermont.osmpack --out out/us-vermont.osmpack [--month 202611] [--only osm,nad]

fetched.json (written by placepacks.fetch) says, for each source, the local file or folder and its version. A source
that could not be fetched is left out of this month's data, but its history stays (the previous pack's rows are
kept, closed at their last month). --month builds as of another month (seeding the history from a past release:
the seed runs go oldest first, each one the --previous of the next). --only builds only some sources (seed runs).
--part all builds every part's sources into one pack (a seed: the history of the address ranges and the extra).

    python -m placepacks.build us-texas-gulf-coast --part addresses --inputs ... --previous-dir previous --out ...
        takes the history from the packs in previous/ (previous_files): the part's own older pack, else the packs
        the region (or its parent) had before the part existed (the addresses were in core and extra; a sub-region's
        history was in its parent's packs), else previous/seed.osmpack. Only the rows of the part's own sources and,
        for a sub-region, of its own area are taken (writer.Keep).
    python -m placepacks.build us-texas-gulf-coast --list-previous
        prints the pack keys whose files --previous-dir may use (the workflow downloads those that are published).
"""

import argparse
import json
import os
import sys

from placepacks import catalogue, fmt
from placepacks.readers import load_all
from placepacks.writer import Keep, PackWriter

SEED = "seed.osmpack"           # the TIGER history seed in the previous folder (placepacks.seed)


def previous_keys(region_id):
    """The pack keys whose older files may hold a region's history: its own parts, and its parent's core and extra
    (a sub-region's first build)."""
    from placepacks.manifest import key_of
    from placepacks.regions import parent_of
    keys = [key_of(region_id, p) for p in fmt.PARTS]
    parent = parent_of(region_id)
    if parent:
        keys += [key_of(parent, p) for p in ("core", "extra")]
    return keys


def previous_files(region_id, part, folder):
    """The older packs a part takes its history from (paths in folder, named <key>.osmpack): its own, else the
    region's (or its parent's) core and extra of before (where the moved sources were), else the seed. [] for the
    names part (no history)."""
    from placepacks.manifest import key_of
    from placepacks.regions import parent_of
    if part == "names":
        return []
    path = lambda key: os.path.join(folder, key + fmt.PACK_SUFFIX)  # noqa: E731
    own = path(key_of(region_id, part))
    if os.path.exists(own):
        return [own]
    for rid in (region_id, parent_of(region_id)):
        older = [path(key_of(rid, p)) for p in ("core", "extra") if rid and os.path.exists(path(key_of(rid, p)))]
        if older:
            return older
    seed = os.path.join(folder, SEED)
    return [seed] if os.path.exists(seed) else []


def keep_for(region, part, cat):
    """The writer.Keep of a part: not the rows of another part's sources; a sub-region's own area only."""
    drop = set() if part == "all" else {e["id"] for e in cat["accepted"] if e["part"] != part}
    return Keep(drop, region if region.get("parent") else None)


def pack_name(region_id, part):
    """The local file name of a part: "us-vermont.osmpack" (core), "us-vermont-extra.osmpack", "us-vermont-names.osmpack"."""
    return region_id + ("" if part == "core" else f"-{part}") + fmt.PACK_SUFFIX


def removals(path=None):
    """The removal list (removals.json: [{"key", "reason", "date"}]); [] when there is none."""
    path = path or os.path.join(catalogue.ROOT, "removals.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("removals", [])


def empty_reason(entry, path):
    """Why a source read nothing for a region: "" when the region simply has none of its rows (an empty slice of a
    national file, or a file whose columns are all there), else what did not match ("missing columns: X")."""
    from placepacks.split import EMPTY, needed_columns
    if os.path.isdir(path) and os.path.exists(os.path.join(path, EMPTY)):
        return ""                       # the national file has rows, none in this region
    try:
        if entry["reader"] == "tabular":
            import csv
            from placepacks.readers.tabular import open_texts
            for text in open_texts(path, entry.get("member", "*"), entry.get("encoding", "utf-8-sig")):
                header = next(csv.reader(text, delimiter=entry.get("delimiter", ",")), None) \
                    if not entry.get("fieldnames") else entry["fieldnames"]
                if not header:
                    return ""           # an empty file: nothing in this region
                wanted = (needed_columns(entry) or set()) - {"statcan_lambert"}
                missing = sorted(c for c in wanted if c not in header and not c.startswith("_"))
                return f"missing columns: {', '.join(missing)}" if missing else ""
        if entry["reader"] == "shapes":
            import shapefile
            from placepacks.readers.shapes import files_of
            for file in files_of(path, entry.get("shp_member")):
                with shapefile.Reader(file) as shp:
                    names = {f[0] for f in shp.fields[1:]}
                want = entry.get("fields", {}).get("name")
                options = want if isinstance(want, list) else [want] if want else []
                if options and not any(o in names for o in options):
                    return f"no name field ({', '.join(options)})"
                return ""
    except Exception as e:  # noqa: BLE001 - the check itself failing says nothing about the region
        return f"the file could not be checked ({str(e)[:80]})"
    return ""


def build(region_id, part, fetched, out, previous=None, month=None, only=None, cat=None, regions=None,
          removal_list=None):
    """Build the pack out. fetched: {source id: {"path", "version", "ok"}}. Returns the meta written."""
    cat = cat or catalogue.load()
    problems = catalogue.check(cat)
    if problems:
        raise SystemExit("The catalogue is not right: " + "; ".join(problems))
    region = dict((regions or catalogue.regions())[region_id])
    if region.get("children"):
        raise SystemExit(f"{region_id} is made as its sub-regions' packs: {', '.join(region['children'])}")
    if fetched.get("_bbox") and not region.get("boxes"):
        region["bbox"] = fetched["_bbox"]           # the extract's own box (fetch.extract_bbox)
    readers = load_all()
    # The local inputs of every source, for readers that use another source (the geocoder reads the NAD slice).
    region["_inputs"] = {sid: got.get("path") for sid, got in fetched.items() if isinstance(got, dict) and got.get("ok")}
    # A sub-region keeps only what is in it (its sources are often read from its parent's files).
    writer = PackWriter(out, month, clip=region if region.get("parent") else None)
    used, missing, status = [], [], {}
    for entry in catalogue.sources_for(region, part, cat, only):
        got = fetched.get(entry["id"]) or {}
        lic = cat["licences"][entry["licence"]]
        writer.add_source(id=entry["id"], name=entry["name"], short=entry["short"], kind=entry.get("kind", ""),
                          part=part, licence=entry["licence"], licence_url=lic["url"],
                          attribution=entry["attribution"], url=entry["url"], version=got.get("version", ""),
                          date=got.get("date", ""), history_note=entry["history"])
        if not got.get("ok") or not got.get("path") or not os.path.exists(got["path"]):
            missing.append(entry["id"])
            status[entry["id"]] = {"status": got.get("status", "skipped" if not got else "failed"),
                                   "reason": got.get("reason") or got.get("error") or "not fetched",
                                   "version": got.get("version", "")}
        else:
            try:
                count = readers[entry["reader"]](got["path"], entry, region, writer)
            except Exception as e:  # noqa: BLE001 - one source failing does not stop the pack
                count, error = None, f"could not be read: {str(e)[:200]}"
            else:
                error = ""
            used.append(f"{entry['id']}={count if isinstance(count, int) else 'ok'}")
            if error:
                status[entry["id"]] = {"status": "failed", "reason": error, "version": got.get("version", "")}
            elif count == 0:
                # Read, but nothing kept. A region that simply has none (the source's rows are all elsewhere) is
                # ok; a file whose columns do not match the catalogue is a real failure.
                mismatch = empty_reason(entry, got["path"])
                if mismatch:
                    status[entry["id"]] = {"status": "failed", "reason": f"read, but no rows matched: {mismatch}",
                                           "version": got.get("version", "")}
                else:
                    status[entry["id"]] = {"status": "ok", "rows": 0, "note": "0 in this region",
                                           "version": got.get("version", "")}
            else:
                status[entry["id"]] = {"status": "ok", "rows": count, "version": got.get("version", "")}
        from placepacks.fetch import status_line
        print(status_line(entry["id"], status[entry["id"]], status[entry["id"]].get("rows")), flush=True)
    # Sources that would repeat another source's places (the national transit stops and the agencies' own GTFS
    # feeds): their duplicates are removed once every source has been read.
    for entry in catalogue.sources_for(region, part, cat, only):
        if entry.get("dedupe_against") and status.get(entry["id"], {}).get("status") == "ok":
            gone = writer.drop_duplicates(entry["id"], entry["dedupe_against"], entry.get("dedupe_m", 100))
            if gone:
                print(f"  {entry['id']}: {gone:,} duplicates of {', '.join(entry['dedupe_against'])} removed", flush=True)
    meta = {"region_id": region_id, "region_name": region["name"], "country": region["country"],
            "parent": region.get("parent", ""),
            "state": catalogue.parent_values(region).get("name") or region["name"], "part": part, "sources_used": ",".join(used), "sources_missing": ",".join(missing),
            "licence": "collective (see sources)", "attribution": fmt.ATTRIBUTION,
            "notice": "This pack is a collective database. Its OpenStreetMap layer (source osm) is a database "
                      "derived from OpenStreetMap, (c) OpenStreetMap contributors, made available under the Open "
                      "Database License (ODbL) 1.0. Every other layer is an independent database under its own "
                      "licence, listed in the sources table with its attribution.",
            "tool": "place-packs (github.com/mark-getbraille/place-packs)",
            "source_status": json.dumps(status, separators=(",", ":"))}
    counts = writer.finish(meta, previous=previous, removals=removal_list if removal_list is not None else removals(),
                           keep=keep_for(region, part, cat))
    return {**meta, **{k: str(v) for k, v in counts.items()}}


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser(description="Build one part of a place pack.")
    p.add_argument("region")
    p.add_argument("--part", choices=fmt.PARTS + ("all",), default="core")
    p.add_argument("--inputs", help="fetched.json from placepacks.fetch")
    p.add_argument("--previous", action="append", default=[], help="an older pack (may be given more than once)")
    p.add_argument("--previous-dir", default="", help="the folder of older packs (previous_files chooses)")
    p.add_argument("--list-previous", action="store_true", help="print the keys --previous-dir may use")
    p.add_argument("--out")
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--only", default="")
    a = p.parse_args(argv)
    if a.list_previous:
        print("\n".join(previous_keys(a.region)))
        return 0
    if not a.inputs or not a.out:
        p.error("--inputs and --out are needed")
    with open(a.inputs, encoding="utf-8") as f:
        fetched = json.load(f)
    previous = [x for x in a.previous if x and os.path.exists(x)]
    if a.previous_dir:
        previous += [x for x in previous_files(a.region, a.part, a.previous_dir) if x not in previous]
    if previous:
        print(f"History from: {', '.join(os.path.basename(x) for x in previous)}", flush=True)
    meta = build(a.region, a.part, fetched, a.out, previous or None, a.month,
                 set(a.only.split(",")) if a.only else None)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
