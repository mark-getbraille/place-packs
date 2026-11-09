"""sources-status.md: what the last build published (written by the workflow every month; the commit also keeps
GitHub's schedule of the workflow alive).

    python -m placepacks.status packs.json > sources-status.md
"""

import datetime
import json
import sys


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
        lines.append(f"| {key} | {built // 100}-{built % 100:02d} | {e.get('size', 0) / 1e6:.1f} | "
                     f"{start // 100}-{start % 100:02d} | {', '.join(sorted(e.get('sources', {})))} |")
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
