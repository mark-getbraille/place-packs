"""place-packs: offline place-name packs with history (MIT; the data is under each source's licence).

Reading and lookup use the Python standard library only:
  placepacks.lookup    Finder (lookup, areas_at), PackReader, Result, search_names
  placepacks.when      When (the picture's date, a span, or none)
  placepacks.regions   REGIONS, regions_for, region_label, tree
  placepacks.water     WaterLayer (lakes, seas, the open ocean, the air; no pack needed)
  placepacks.download  Catalogue, ensure_pack, updates_available (anonymous, from the public releases)
  placepacks.manifest  packs.json (parse, publish)
Building (needs requirements.txt): placepacks.fetch, placepacks.build, placepacks.split, placepacks.readers.
"""

__version__ = "2.0"
