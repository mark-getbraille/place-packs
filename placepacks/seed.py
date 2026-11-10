"""The TIGER history seed (the workflow's "seed_history"): one pack per US region built from the older TIGER/Line
releases (settings tiger_seed_years x tiger_seed_sources), oldest first, each the previous pack of the next.

    python -m placepacks.seed fingerprint      the seed's fingerprint (12 hex characters)

A finished seed is kept as a release asset (seed-<region>-<fingerprint>.osmpack in the "seeds" release) and reused
by later builds; it is made again only when the fingerprint changes: the seed years, the seed sources, their
catalogue entries or the pack format.
"""

import hashlib
import json
import sys

from placepacks import catalogue, fmt


def fingerprint(cat=None):
    """The seed's fingerprint: a hash of the seed years, the seed sources' catalogue entries and the pack format."""
    cat = cat or catalogue.load()
    settings = cat["settings"]
    sources = settings.get("tiger_seed_sources", [])
    entries = {e["id"]: e for e in cat["accepted"] if e["id"] in sources}
    data = {"years": settings.get("tiger_seed_years", []), "sources": sources,
            "entries": [entries.get(s) for s in sources], "format": [fmt.PACK_FORMAT, fmt.PACK_VERSION]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def main(argv=None):
    """The command line (see the module docstring)."""
    argv = argv if argv is not None else sys.argv[1:]
    if argv[:1] == ["fingerprint"]:
        print(fingerprint())
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
