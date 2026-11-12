"""Write SOURCES.md from sources.json (run after changing the catalogue; the tests check that it is up to date).

    python tools/write_sources_md.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def text(cat):
    """The Markdown of SOURCES.md."""
    lic = cat["licences"]
    out = ["# Sources of the place packs", "",
           "Generated from sources.json by tools/write_sources_md.py. Licences checked in November 2026; check them "
           "again when a source changes its terms. Part: the pack part the source is in (core, extra, names, "
           "businesses or addresses; FORMAT.md, \"Parts\").", "",
           "Personal data: the business sources (inspections, licences, registrations, directories) keep only a "
           "trade name, a class, a position and dates, never scores, violations or owners. Business types that are "
           "often run from a home (contractors, consultants, home caterers, childminders, short-term rentals, "
           "individual licences) are left out by each source's class map, only trade names are used where the "
           "source separates them from the owner's name, and licensee names that look like a person's are left "
           "out. The notes below say how for each source.", "",
           "US businesses: there is no federal database of businesses with positions (the counterpart of Statistics "
           "Canada's Open Database of Businesses). The US business backbone is Overture Maps places, All The Places "
           "(chains' own store locators), OpenStreetMap and the city and state licence and inspection lists below; "
           "the IRS exempt-organization file adds non-profits. Aggregated statistics (County Business Patterns and "
           "the like) have no place names and are not used.", "",
           "## Used", "", "| Source | Part | Countries | Licence | Attribution | History |", "|---|---|---|---|---|---|"]
    for e in cat["accepted"]:
        out.append(f"| [{e['name']}]({e['url']}) | {e['part']} | {', '.join(e['countries'])} | "
                   f"[{lic[e['licence']]['name']}]({lic[e['licence']]['url']}) | {e['attribution']} | "
                   f"{e['history']} |")
    out += ["", "## Candidates (licence to confirm; not used yet)", "", "| Source | Licence | Note |", "|---|---|---|"]
    for c in cat.get("candidates", []):
        out.append(f"| {c['name']} | {c['licence']} | {c['note']} |")
    out += ["", "## Not used", "", "| Source | Licence | Why |", "|---|---|---|"]
    for r in cat["rejected"]:
        out.append(f"| {r['name']} | {r['licence']} | {r['reason']} |")
    out += ["", "## Notes on individual sources", ""]
    out += [f"- {e['name']}: {e['notes']}" for e in cat["accepted"] if e.get("notes")]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    with open(os.path.join(ROOT, "sources.json"), encoding="utf-8") as f:
        catalogue = json.load(f)
    with open(os.path.join(ROOT, "SOURCES.md"), "w", encoding="utf-8") as f:
        f.write(text(catalogue))
    sys.exit(0)
