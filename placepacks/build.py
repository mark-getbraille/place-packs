"""Build one part of one region's pack from the fetched inputs, merged with the previous pack's history.

    python -m placepacks.build us-vermont --part core --inputs work/us-vermont/fetched.json \
        --previous previous/us-vermont.osmpack --out out/us-vermont.osmpack [--month 202611] [--only osm,nad]

fetched.json (written by placepacks.fetch) says, for each source, the local file or folder and its version. A source
that could not be fetched is left out of this month's data, but its history stays (the previous pack's rows are
kept, closed at their last month). --month builds as of another month (seeding the history from a past release:
the seed runs go oldest first, each one the --previous of the next). --only builds only some sources (seed runs).
"""

import argparse
import json
import os
import sys

from placepacks import catalogue, fmt
from placepacks.readers import load_all
from placepacks.writer import PackWriter


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


def build(region_id, part, fetched, out, previous=None, month=None, only=None, cat=None, regions=None,
          removal_list=None):
    """Build the pack out. fetched: {source id: {"path", "version", "ok"}}. Returns the meta written."""
    cat = cat or catalogue.load()
    problems = catalogue.check(cat)
    if problems:
        raise SystemExit("The catalogue is not right: " + "; ".join(problems))
    region = dict((regions or catalogue.regions())[region_id])
    if fetched.get("_bbox"):
        region["bbox"] = fetched["_bbox"]           # the extract's own box (fetch.extract_bbox)
    readers = load_all()
    # The local inputs of every source, for readers that use another source (the geocoder reads the NAD slice).
    region["_inputs"] = {sid: got.get("path") for sid, got in fetched.items() if isinstance(got, dict) and got.get("ok")}
    writer = PackWriter(out, month)
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
                # Read, but nothing kept: the file's columns, its filter or the region's box did not match.
                status[entry["id"]] = {"status": "failed", "reason": "read, but no rows matched (columns, filter "
                                       "or box)", "version": got.get("version", "")}
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
            "state": region["name"], "part": part, "sources_used": ",".join(used), "sources_missing": ",".join(missing),
            "licence": "collective (see sources)", "attribution": fmt.ATTRIBUTION,
            "notice": "This pack is a collective database. Its OpenStreetMap layer (source osm) is a database "
                      "derived from OpenStreetMap, (c) OpenStreetMap contributors, made available under the Open "
                      "Database License (ODbL) 1.0. Every other layer is an independent database under its own "
                      "licence, listed in the sources table with its attribution.",
            "tool": "place-packs (github.com/mark-getbraille/place-packs)",
            "source_status": json.dumps(status, separators=(",", ":"))}
    counts = writer.finish(meta, previous=previous, removals=removal_list if removal_list is not None else removals())
    return {**meta, **{k: str(v) for k, v in counts.items()}}


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser(description="Build one part of a place pack.")
    p.add_argument("region")
    p.add_argument("--part", choices=fmt.PARTS, default="core")
    p.add_argument("--inputs", required=True, help="fetched.json from placepacks.fetch")
    p.add_argument("--previous", default="")
    p.add_argument("--out", required=True)
    p.add_argument("--month", type=int, default=None)
    p.add_argument("--only", default="")
    a = p.parse_args(argv)
    with open(a.inputs, encoding="utf-8") as f:
        fetched = json.load(f)
    meta = build(a.region, a.part, fetched, a.out, a.previous if a.previous and os.path.exists(a.previous) else None,
                 a.month, set(a.only.split(",")) if a.only else None)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
