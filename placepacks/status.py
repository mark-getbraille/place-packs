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
             "LICENSES.md for the licences and attributions.", "",
             "| Pack | Built | Size (MB) | History from | Sources |", "|---|---|---|---|---|"]
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
