"""place-packs: offline place-name packs with history (MIT; the data is under each source's licence).

Reading and lookup use the Python standard library only:
  placepacks.lookup    Finder (lookup, areas_at), PackReader, Result, search_names
  placepacks.when      When (the picture's date, a span, or none)
  placepacks.regions   REGIONS, regions_for, region_label, tree
  placepacks.water     WaterLayer (lakes, seas, the open ocean, the air; no pack needed)
  placepacks.download  Catalogue, ensure_pack, ensure_packs, updates_available (anonymous, from the public releases:
                       "packs" for core and extra, "packs-detail-YYYYMMDD" for names, businesses and addresses)
  placepacks.manifest  packs.json (parse, publish, plan, release_for)
Building (needs requirements.txt): placepacks.fetch, placepacks.build, placepacks.split, placepacks.readers,
placepacks.combine (a parent's pack from its sub-regions'), placepacks.seed (the TIGER history seed),
placepacks.status (sources-status.md). Developer tools: tools/.
"""

__version__ = "2.0"
