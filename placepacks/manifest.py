"""packs.json: the list of published packs, read by the programs (parse) and written by the workflow (publish).

    {"format": "place-packs", "version": 2, "made": "2026-11-09", "release": "packs",
     "sources": {"osm": {"name", "licence", "licence_url", "attribution", "url"}, ...},
     "packs": {"us-vermont": {"region": "us-vermont", "part": "core", "name": "us-vermont-20261102.osmpack",
                              "size": 12345678, "sha256": "<64 hex>", "built_month": 202611,
                              "bounds": [west, south, east, north],
                              "history_start": 201101, "sources": {"osm": {"version": "...", "date": "..."}}},
               "us-vermont-extra": {...}}}

Asset names carry the build date, so a new pack never replaces a file a program may be downloading: the workflow
uploads the new files, then packs-previous.json (the manifest before), then packs.json, and only then deletes the
files neither manifest names. parse() treats the file as untrusted data: JSON only, at most LIMIT bytes, the format
and version checked, and each entry's region, part, file name, size and SHA-256 checked; a bad entry is left out.

python -m placepacks.manifest publish --old packs.json --built out/ --fetched-dir work/ --output packs.json
    writes the new manifest (the old entries kept for regions not rebuilt) and prints the asset list.
python -m placepacks.manifest plan --manifest packs.json --fingerprints prints.json --regions "..." [--force]
    prints regions=<JSON> of the regions whose sources changed (ETag, Last-Modified or release names differ).
"""

import argparse
import datetime
import json
import os
import re
import sys

FORMAT = "place-packs"
VERSIONS = (1, 2)
LIMIT = 4_000_000
MAX_PACK_BYTES = 2_000_000_000          # GitHub's per-file limit for release assets
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PackInfo:
    """One published pack: key ("us-vermont", "us-vermont-extra"), region, part, name (the release file), size,
    sha256, built_month, history_start, sources ({id: {"version", "date"}})."""

    def __init__(self, key, region, part, name, size, sha256, built_month=0, history_start=0, sources=None,
                 bounds=None):
        self.key, self.region, self.part, self.name = key, region, part, name
        self.bounds = bounds            # [west, south, east, north] of the pack's data, or None
        self.size, self.sha256 = size, sha256
        self.built_month, self.history_start = built_month, history_start
        self.sources = sources or {}

    def __repr__(self):
        return f"PackInfo({self.key!r}, {self.size}, {self.sha256[:8]}...)"


def key_of(region, part):
    """"us-vermont" for core, "us-vermont-extra" for extra."""
    return region if part == "core" else f"{region}-{part}"


def parse(data, regions=None):
    """{key: PackInfo} from the bytes of packs.json (see the module docstring). Raises ValueError for a file that is
    not a manifest. regions: the known region ids (default placepacks.regions.REGIONS)."""
    if regions is None:
        from placepacks.regions import REGIONS as regions
    if not isinstance(data, (bytes, bytearray)) or len(data) > LIMIT:
        raise ValueError("the packs list is too large or not a file")
    try:
        doc = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("the packs list is not readable") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ValueError("this is not a packs list of place-packs")
    if not isinstance(doc.get("version"), int) or isinstance(doc.get("version"), bool) or \
            doc["version"] not in VERSIONS:
        raise ValueError("the packs list was made for another version")
    packs = doc.get("packs")
    if not isinstance(packs, dict):
        raise ValueError("the packs list has no packs")
    found = {}
    for key, e in packs.items():
        if not isinstance(e, dict) or not isinstance(key, str):
            continue
        region, part = e.get("region"), e.get("part")
        if region not in regions or part not in ("core", "extra") or key != key_of(region, part):
            continue
        name, size, digest = e.get("name"), e.get("size"), e.get("sha256")
        if not isinstance(name, str) or not re.fullmatch(re.escape(key) + r"(-\d{8})?\.osmpack", name):
            continue
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_PACK_BYTES:
            continue
        if not isinstance(digest, str) or not _HEX64.match(digest):
            continue
        month = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and 100001 <= v <= 999912 else 0  # noqa
        sources = e.get("sources") if isinstance(e.get("sources"), dict) else {}
        b = e.get("bounds")
        bounds = [float(v) for v in b] if isinstance(b, list) and len(b) == 4 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and -180 <= v <= 180 for v in b) else None
        found[key] = PackInfo(key, region, part, name, size, digest, month(e.get("built_month")),
                              month(e.get("history_start")),
                              {str(k)[:40]: {kk: str(vv)[:100] for kk, vv in v.items()} for k, v in sources.items()
                               if isinstance(v, dict)}, bounds)
    return found


def fingerprint(fetched):
    """{source id: version text} of a fetched.json (what decides whether a region must be rebuilt)."""
    return {sid: str(v.get("version", "")) for sid, v in fetched.items() if isinstance(v, dict) and v.get("ok")}


def changed(old_entry_sources, new_prints):
    """True when any source's version differs from the one the published pack was built from."""
    old = {k: v.get("version", "") for k, v in (old_entry_sources or {}).items()}
    return any(old.get(k) != v for k, v in new_prints.items()) or not old


def publish(old_path, built_dir, fetched_dir, today=None, cat=None):
    """The new manifest dict: the old one with the packs in built_dir (<key>.osmpack plus <key>.json, the build's
    meta) added under dated names. Returns (manifest, [(local path, asset name)])."""
    from placepacks import catalogue, fmt
    from placepacks.lookup import PackReader
    today = today or datetime.date.today()
    cat = cat or catalogue.load()
    old = {}
    if old_path and os.path.exists(old_path):
        with open(old_path, encoding="utf-8") as f:
            old = json.load(f)
    packs = dict(old.get("packs", {})) if isinstance(old.get("packs"), dict) else {}
    uploads = []
    for name in sorted(os.listdir(built_dir)):
        if not name.endswith(fmt.PACK_SUFFIX):
            continue
        key = name[:-len(fmt.PACK_SUFFIX)]
        path = os.path.join(built_dir, name)
        reader = PackReader(path)
        meta, region, part = reader.meta, reader.region_id, reader.part
        reader.close()
        asset = f"{key}-{today:%Y%m%d}{fmt.PACK_SUFFIX}"
        fetched = {}
        fetched_path = os.path.join(fetched_dir, region, "fetched.json")
        if os.path.exists(fetched_path):
            with open(fetched_path, encoding="utf-8") as f:
                fetched = json.load(f)
        try:
            s_, w_, n_, e_ = (round(float(v), 4) for v in meta.get("bounds", "").split(","))
            bounds = [w_, s_, e_, n_]
        except ValueError:
            bounds = None
        try:
            source_status = json.loads(meta.get("source_status", "{}"))
        except ValueError:
            source_status = {}
        packs[key] = {"region": region, "part": part, "name": asset, "size": os.path.getsize(path), "bounds": bounds,
                      "status": source_status,
                      "sha256": fmt_sha(path), "built_month": int(meta.get("built_month", "0")),
                      "history_start": int(meta.get("history_start", "0") or 0),
                      "sources": {s: {"version": str(v.get("version", "")), "date": str(v.get("date", ""))}
                                  for s, v in fetched.items() if isinstance(v, dict) and v.get("ok")}}
        uploads.append((path, asset))
    manifest = {"format": FORMAT, "version": 2, "made": today.isoformat(), "release": "packs",
                "sources": {e["id"]: {"name": e["name"], "licence": e["licence"],
                                      "licence_url": cat["licences"][e["licence"]]["url"],
                                      "attribution": e["attribution"], "url": e["url"], "history": e["history"]}
                            for e in cat["accepted"]},
                "notice": "Each pack is a collective database: an OpenStreetMap layer under the ODbL 1.0 "
                          "((c) OpenStreetMap contributors) and independent layers under their own licences; see "
                          "the sources and LICENSES.md.",
                "packs": dict(sorted(packs.items()))}
    if len(parse(json.dumps(manifest).encode())) != len(packs):
        raise SystemExit("The new manifest would not be accepted by the programs")
    return manifest, uploads


def fmt_sha(path):
    """The SHA-256 of a file."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def referenced(*manifests):
    """The asset names the manifests name (files not in it may be deleted)."""
    return {e["name"] for m in manifests if m for e in m.get("packs", {}).values() if isinstance(e, dict)}


def main(argv=None):
    """The command line (see the module docstring)."""
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("publish")
    a.add_argument("--old", default="")
    a.add_argument("--built", required=True)
    a.add_argument("--fetched-dir", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--uploads", required=True, help="a text file: one 'local path<TAB>asset name' per line")
    b = sub.add_parser("plan")
    b.add_argument("--manifest", default="")
    b.add_argument("--fingerprints", default="", help="{region: {source: version}} from fetch --fingerprint")
    b.add_argument("--regions", default="")
    b.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "publish":
        manifest, uploads = publish(args.old, args.built, args.fetched_dir)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1, ensure_ascii=False)
        with open(args.uploads, "w", encoding="utf-8") as f:
            f.writelines(f"{path}\t{asset}\n" for path, asset in uploads)
        print(f"{len(uploads)} packs to upload; {len(manifest['packs'])} in the list.")
        return 0
    from placepacks.regions import REGIONS
    wanted = [r for r in args.regions.replace(",", " ").split() if r] or list(REGIONS)
    unknown = [r for r in wanted if r not in REGIONS]
    if unknown:
        raise SystemExit(f"Unknown region ids: {', '.join(unknown)}")
    old = {}
    if args.manifest and os.path.exists(args.manifest):
        with open(args.manifest, encoding="utf-8") as f:
            old = json.load(f).get("packs", {})
    prints = {}
    if args.fingerprints and os.path.exists(args.fingerprints):
        with open(args.fingerprints, encoding="utf-8") as f:
            prints = json.load(f)
    todo = [r for r in wanted if args.force or r not in prints or
            changed(old.get(r, {}).get("sources"), prints.get(r, {}))]
    print("regions=" + json.dumps([{"id": r, "geofabrik": REGIONS[r]["geofabrik"]} for r in todo],
                                  separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
