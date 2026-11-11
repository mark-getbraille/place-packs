"""sources-status.md: what the last build published (written by the workflow every month; the commit also keeps
GitHub's schedule of the workflow alive).

    python -m placepacks.status packs.json > sources-status.md
"""

import datetime
import json
import re
import sys

from placepacks.fmt import month_label

REASON_LIMIT = 200          # characters of a reason in the table (DuckDB's errors run to several lines)


def one_line(text, limit=REASON_LIMIT):
    """text on one line (newlines and runs of spaces become one space; "|" would split a Markdown cell), at most
    limit characters, ending in "..." when it was cut."""
    text = re.sub(r"\s+", " ", str(text or "")).strip().replace("|", "/")
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def status(manifest, today=None):
    """The Markdown text for a manifest dict."""
    today = today or datetime.date.today()
    packs = manifest.get("packs", {})
    total = sum(e.get("size", 0) for e in packs.values())
    lines = [f"# Place packs status, {today.isoformat()}", "",
             f"{len(packs)} packs published, {total / 1e9:.2f} GB in all. Each pack is a collective database; see "
             "LICENSES.md for the licences and attributions.", ""]
    lines += by_region(packs)
    lines += ["## Every pack", "", "| Pack | Built | Size (MB) | History from | Sources |", "|---|---|---|---|---|"]
    for key, e in sorted(packs.items()):
        built, start = e.get("built_month", 0), e.get("history_start", 0)
        lines.append(f"| {key} | {month_label(built)} | {e.get('size', 0) / 1e6:.1f} | "
                     f"{month_label(start)} | {', '.join(sorted(e.get('sources', {})))} |")
    lines += ["", "## Sources of each pack", "",
              "Each source of the last build of each pack: ok (with its rows), skipped (why) or failed (why).", "",
              "| Pack | Source | Status | Rows or reason |", "|---|---|---|---|"]
    for key, e in sorted(packs.items()):
        for sid, st in sorted((e.get("status") or {}).items()):
            detail = (st.get("note") or str(st.get("rows", ""))) if st.get("status") == "ok" else \
                str(st.get("reason", ""))
            lines.append(f"| {key} | {sid} | {one_line(st.get('status', '?'), 20)} | {one_line(detail)} |")
    return "\n".join(lines) + "\n"


def by_region(packs):
    """The table of each region's parts and sizes (MB): what a program downloads by default (core and extra) and on
    demand (businesses, addresses, names)."""
    from placepacks.fmt import PARTS
    from placepacks.manifest import split_key
    from placepacks.regions import REGIONS
    table, combined = {}, set()
    for key, e in packs.items():
        found = split_key(key) or (e.get("region", key), e.get("part", "core"))
        table.setdefault(found[0], {})[found[1]] = e.get("size", 0) / 1e6
        if e.get("combined_from"):
            combined.add(found[0])
    lines = ["## Packs by region", "",
             "Sizes in MB. A program downloads core and extra; businesses and addresses only when a lookup needs them "
             "(the exact place, full detail); names on request. A region with sub-regions (England, Texas, ...) is "
             "listed with them; its own core and extra are its sub-regions put together, for programs that know only "
             "the region.", "",
             "| Region | " + " | ".join(p.capitalize() for p in PARTS) + " | Core + extra |",
             "|---|" + "---|" * (len(PARTS) + 1)]
    for rid in sorted(table, key=lambda r: (REGIONS.get(r, {}).get("parent") or r, r)):
        sizes = table[rid]
        name = rid + (" (its sub-regions put together)" if rid in combined else
                      " (before its sub-regions)" if (REGIONS.get(rid) or {}).get("children") else "")
        cells = [f"{sizes[p]:.1f}" if p in sizes else "" for p in PARTS]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {sizes.get('core', 0) + sizes.get('extra', 0):.1f} |")
    return lines + [""]


def main(argv=None):
    """The command line (see the module docstring)."""
    argv = argv if argv is not None else sys.argv[1:]
    try:
        with open(argv[0], encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError, IndexError):
        manifest = {}
    sys.stdout.write(status(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
