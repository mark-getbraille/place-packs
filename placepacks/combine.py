"""One pack of a parent region made from its sub-regions' packs, for the programs that know only the parent.

    python -m placepacks.combine gb-england core --out built/gb-england.osmpack built/gb-england-london.osmpack ...
    python -m placepacks.combine plan built/ packs.json
        prints "<parent> <part> <child key> <file or published name> ..." for each parent with a child built now:
        the children's packs to put together (a child not rebuilt this month is taken from the release).

A region too large for one pack (England, Texas) is built as its children's packs (placepacks.regions). Programs
made before the sub-regions know only "gb-england" and "gb-england-extra" (and leave the other entries of packs.json
out): the workflow publishes, under the parent's keys, the core and extra of all its children put together, so those
programs still find the towns and the streets. A record in two children (a street across their border) is kept once.
Programs that know the sub-regions download the children instead (download.ensure_pack maps a parent to them).
"""

import argparse
import json
import os
import sqlite3
import sys

from placepacks import fmt
from placepacks.writer import SOURCE_COLUMNS, TABLES, PackWriter, previous_addresses

ROW_TABLES = ("points", "areas", "lines", "ranges")
TYPES = {"points": "point_types", "areas": "area_types", "lines": "", "ranges": ""}


def _columns(con, schema, table):
    """The column names of a table in an attached database (schema: "main" or an ATTACH alias)."""
    return [r[1] for r in con.execute(f"PRAGMA {schema}.table_info({table})")]


def combine(region_id, part, paths, out):
    """Write out: the rows of every pack in paths (each record once), as region_id's part. Returns the counts."""
    from placepacks.regions import REGIONS
    if not paths:
        raise ValueError("no pack to combine")
    region = REGIONS.get(region_id, {"name": region_id, "country": ""})
    writer = PackWriter(out)
    db = writer.db
    metas, statuses, months = [], {}, []
    for i, path in enumerate(paths):
        alias = f"c{i}"
        db.execute("ATTACH DATABASE ? AS " + alias, (path,))
        have = {r[0] for r in db.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type = 'table'")}
        meta = dict(db.execute(f"SELECT key, value FROM {alias}.meta"))
        metas.append(meta)
        months.append(int(meta.get("built_month", "0") or 0))
        for table in ROW_TABLES:
            if table not in have:
                continue
            mine = [c.split()[0] for c in TABLES[table].split(", ") if not c.startswith("id ")]
            theirs = set(_columns(db, alias, table))
            picks = []
            for c in mine:
                if c in theirs:
                    picks.append(f"o.{c}")
                elif c == "type" and {"types", TYPES[table]} <= have:
                    picks.append(f"(SELECT t.name FROM {alias}.{TYPES[table]} l JOIN {alias}.types t ON t.id = "
                                 f"l.type WHERE l.id = o.id)")
                elif c == "brand" and {"brands", "point_brands"} <= have:
                    picks.append(f"(SELECT b.name || '|' || b.wikidata FROM {alias}.point_brands l JOIN "
                                 f"{alias}.brands b ON b.id = l.brand WHERE l.id = o.id)")
                elif c == "note" and {"notes", "point_notes"} <= have:
                    picks.append(f"(SELECT n.text FROM {alias}.point_notes l JOIN {alias}.notes n ON n.id = "
                                 f"l.note WHERE l.id = o.id)")
                else:
                    picks.append("NULL")
            db.execute(f"INSERT INTO main.{table} ({', '.join(mine)}) SELECT {', '.join(picks)} FROM "
                       f"{alias}.{table} o ORDER BY o.id")
        if "address_cells" in have:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            db.executemany("INSERT INTO addr (key, source, name, cls, street, city, lat, lon, first, last) VALUES "
                           "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", previous_addresses(con))
            con.close()
        if "sources" in have:
            names = _columns(db, alias, "sources")
            for row in db.execute(f"SELECT * FROM {alias}.sources").fetchall():
                fields = dict(zip(names, row))
                writer.sources.setdefault(fields["id"], {c: str(fields.get(c, "") or "") for c in SOURCE_COLUMNS})
        if "removals" in have:
            db.execute(f"INSERT INTO main.removals SELECT * FROM {alias}.removals")
        for sid, st in json.loads(meta.get("source_status", "{}") or "{}").items():
            old = statuses.get(sid)
            if old is None or (old.get("status") != "ok" and st.get("status") == "ok"):
                statuses[sid] = dict(st)
            elif st.get("status") == "ok" and old.get("status") == "ok":
                old["rows"] = int(old.get("rows", 0) or 0) + int(st.get("rows", 0) or 0)
        try:
            s, w, n, e = (float(v) for v in meta.get("bounds", "").split(","))
            writer._extend(s, w, n, e)
        except ValueError:
            pass
        db.commit()
        db.execute("DETACH DATABASE " + alias)
    # A record in two children (it crosses their border, or lies within their overlap) once.
    for table in tuple(ROW_TABLES) + ("addr",):
        db.execute(f"DELETE FROM {table} WHERE id NOT IN (SELECT MIN(id) FROM {table} GROUP BY key, name, source, "
                   f"first, last)")
    db.execute("DELETE FROM removals WHERE rowid NOT IN (SELECT MIN(rowid) FROM removals GROUP BY key)")
    writer.month = max(months) or fmt.month_of()
    builds = sorted({int(b) for m in metas for b in (m.get("builds") or "").split(",") if b.strip()})
    meta = {"region_id": region_id, "region_name": region["name"], "country": region.get("country", ""),
            "state": region["name"], "part": part, "parent": "", "combined_from": ",".join(
                m.get("region_id", "") for m in metas),
            "licence": metas[0].get("licence", ""), "attribution": metas[0].get("attribution", fmt.ATTRIBUTION),
            "notice": metas[0].get("notice", ""), "tool": metas[0].get("tool", ""),
            "sources_used": metas[0].get("sources_used", ""), "sources_missing": ",".join(
                sorted(sid for sid, st in statuses.items() if st.get("status") != "ok")),
            "source_status": json.dumps(statuses, separators=(",", ":"))}
    counts = writer.finish(meta, dedupe=False)
    # The builds of the children (finish wrote only this month's).
    con = sqlite3.connect(out)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('builds', ?)", (",".join(map(str, builds or [writer.month])),))
    con.commit()
    con.close()
    return counts


def plan(built_dir, manifest_path=""):
    """[(parent, part, [(child key, local file or published name)])] for every parent with a child built now; a
    parent whose children are not all built or published is left out (its older combined pack stays)."""
    from placepacks.manifest import key_of
    from placepacks.regions import REGIONS
    published = {}
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            published = {k: e.get("name", "") for k, e in (json.load(f).get("packs") or {}).items()
                         if isinstance(e, dict)}
    out = []
    for rid, r in REGIONS.items():
        children = r.get("children") or []
        built = {c for c in children if os.path.exists(os.path.join(built_dir, key_of(c, "core") + fmt.PACK_SUFFIX))}
        if not built:
            continue
        for part in ("core", "extra"):
            files = []
            for c in children:
                key = key_of(c, part)
                local = os.path.join(built_dir, key + fmt.PACK_SUFFIX)
                files.append((key, local if os.path.exists(local) else published.get(key, "")))
            if all(f for _, f in files):
                out.append((rid, part, files))
    return out


def main(argv=None):
    """The command line (see the module docstring)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["plan"]:
        for parent, part, files in plan(argv[1], argv[2] if len(argv) > 2 else ""):
            print(parent, part, " ".join(f"{k} {f}" for k, f in files))
        return 0
    p = argparse.ArgumentParser(description="Put a parent region's sub-region packs together.")
    p.add_argument("region")
    p.add_argument("part", choices=("core", "extra"))
    p.add_argument("--out", required=True)
    p.add_argument("packs", nargs="+")
    a = p.parse_args(argv)
    missing = [x for x in a.packs if not os.path.exists(x)]
    if missing:
        raise SystemExit(f"Missing packs: {', '.join(missing)}")
    print(json.dumps(combine(a.region, a.part, a.packs, a.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
