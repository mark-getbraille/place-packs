"""Business details and local businesses from local directories and lookups (the owner's decisions of 26 November
2026, notes/helper-rules.txt), each with its own source:

  yellowpages.py    Yellow Pages LOOKUPS for businesses already in the packs (source "yp-lookups"; the job is
                    tools/yp_lookup.py, run slowly from the owner's cloud session, not from GitHub)
  websites.py       the business's own homepage: its schema.org phone and hours (source "business-websites"; the
                    monthly web-details workflow)
  simpleview.py     tourism boards' visitor listings on the Simpleview platform: 11 state tourism sites and 77 city
                    and county boards (source "simpleview-listings"; the monthly simpleview-listings workflow, run in
                    matrix groups of sites)
  tempest.py        city and county tourism boards' partner listings on the Tempest platform (source
                    "tempest-listings"; the monthly tempest-listings workflow)
  chambermaster.py  chambers of commerce's public member directories on the older ChamberMaster (GrowthZone v1)
                    platform, found through the US Chamber of Commerce's directory (source "chambermaster-listings";
                    the monthly chambermaster-listings workflow)

Shared parts:
  common.py         privacy filters (home and one-person businesses, people's names, e-mails), name and address
                    matching, robots.txt, category words -> OpenStreetMap-style tags
  github.py         a small GitHub REST client (releases, packs.json) for the jobs outside the pack build
  packs_input.py    the businesses already in the published packs (the input of the two details collectors)
  run.py            runs one unit (a site, a state, a shard) of a collector: its CSV and summary, as for the chains
The web client is the chain collectors' polite one (placepacks/chains/polite.py: an identified User-Agent, at
least a second between requests to a host, a request budget, and a clean stop on 403, 429 or an anti-bot page,
recorded as "blocked"). The monthly sets of Simpleview, Tempest and ChamberMaster are kept and read like the chain stores'
(placepacks/chains/release.py); the two details-only sources' files are read by placepacks/details.py.

Never: an anti-bot challenge, a CAPTCHA or a login passed; a headless or Chrome-imitating browser; another IP
address or connection to get round a block. A site that refuses is recorded as "blocked" and left. Never kept: a
review, a rating, a description, a photo, an e-mail address, a person's name (staff, representatives, owners).
Only the Python standard library is used.
"""
