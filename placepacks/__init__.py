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
placepacks.status (sources-status.md), placepacks.gov_details (government places with phone, hours and
accessibility: ssa_offices, nps_api, ridb, usfs_details; opening hours in OpenStreetMap's syntax: placepacks.hours),
placepacks.chains (big chains' store locators), placepacks.directories (tourism boards' Simpleview listings,
chambers' ChamberMaster directories, businesses' homepages, Yellow Pages lookups) and placepacks.details (the
details-only sources' files and their "details" reader).
Developer tools: tools/ (tools/yp_lookup.py: the Yellow Pages lookup job).
"""

__version__ = "2.0"
