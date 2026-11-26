"""Store-locator collectors for big US chains that All The Places misses (the source "chain-locators").

Why: All The Places (the source "alltheplaces") reads about 5,800 chains' store locators, but in its November 2026
run several big US chains gave nothing or almost nothing (notes: US-CHAIN-GAPS.md). The owner decided on
26 November 2026 to collect big chains' store locators himself and publish them in the packs (locations, hours and
phone numbers), even where a chain's terms or robots.txt say no. The rules that still hold, in polite.py: an
identified User-Agent naming the project, a pause of at least a second per host, a request budget per chain,
retries with back-off, and a clean stop on any refusal (403, 429, a challenge page), recorded as "blocked". No
CAPTCHA is solved, no anti-bot challenge or login is got round, no e-mail is kept, and no individual's own office
(insurance agents and the like) is collected.

The modules:
  polite.py      the web client (User-Agent, pauses, budget, retries, Blocked)
  base.py        the row (the All The Places CSV's shape), the US test, the search grid, sitemaps
  hours.py       opening hours in OpenStreetMap's syntax
  jsonld.py      schema.org JSON-LD on store pages
  pages.py       the "sitemap of store pages" collector
  burger_king.py, jack_in_the_box.py, avis.py, budget.py, wyndham.py, gm_dealers.py, ford_dealers.py
                 one small collector per chain (or group of brands)
  run.py         runs one chain: its CSV and its summary (ok, blocked, incomplete, failed)
  release.py     the monthly set in the release "chain-locators" (the workflow's last job), and the pack build's
                 reading of it (fetch method "release_csv")
The endpoints follow All The Places' open-source spiders (github.com/alltheplaces/alltheplaces, MIT licence;
credited in each module and in LICENSES.md and NOTICE). Only the Python standard library is used.

CHAINS lists every collector with what was found when it was checked (26 November 2026, a few requests each):
the endpoint kind, about how many US stores to expect, and the robots.txt notes (kept for the record).
BLOCKED lists the chains that refused even those few requests, so they have no collector.
"""

from placepacks.chains import (
    avis,
    budget,
    burger_king,
    ford_dealers,
    gm_dealers,
    jack_in_the_box,
    wyndham,
)


def _chain(collect, title, endpoint, expected, budget_requests, pause, timeout_min, robots):
    """One entry of CHAINS (see the module docstring)."""
    return {"collect": collect, "title": title, "endpoint": endpoint, "expected": expected,
            "budget": budget_requests, "pause": pause, "timeout_min": timeout_min, "robots": robots}


CHAINS = {
    "burger-king": _chain(burger_king.collect, "Burger King", "JSON (GraphQL) store API, US grid of radius searches",
                          6700, 700, 2.0, 60, "API host has no robots.txt"),
    "jack-in-the-box": _chain(jack_in_the_box.collect, "Jack in the Box", "sitemap + schema.org JSON-LD store pages",
                              2100, 2400, 1.5, 150, "robots.txt allows everything"),
    "avis": _chain(avis.collect, "Avis", "sitemap + schema.org JSON-LD location pages", 1900, 2300, 2.0, 180,
                   "location pages not disallowed"),
    "budget": _chain(budget.collect, "Budget", "sitemap + schema.org JSON-LD location pages", 1650, 2000, 2.0, 150,
                     "location pages not disallowed"),
    "wyndham-days-inn-super-8": _chain(wyndham.collector("wyndham-days-inn-super-8"), "Days Inn and Super 8",
                                       "sitemaps + hotel pages (JSON-LD and map settings)", 2450, 2800, 1.5, 200,
                                       "hotel pages not disallowed"),
    "wyndham-la-quinta-baymont": _chain(wyndham.collector("wyndham-la-quinta-baymont"),
                                        "La Quinta, Baymont, Microtel, Travelodge, Howard Johnson",
                                        "sitemaps + hotel pages (JSON-LD and map settings)", 2200, 2700, 1.5, 200,
                                        "hotel pages not disallowed"),
    "wyndham-other": _chain(wyndham.collector("wyndham-other"), "Ramada, Wingate, AmericInn and Wyndham's other brands",
                            "sitemaps + hotel pages (JSON-LD and map settings)", 1500, 2500, 1.5, 200,
                            "hotel pages not disallowed"),
    "buick-dealers": _chain(gm_dealers.collector("buick-dealers"), "Buick dealers",
                            "JSON dealer-locator API, US grid of radius searches", 1900, 1300, 1.5, 75,
                            "/bypass/ not disallowed"),
    "gmc-dealers": _chain(gm_dealers.collector("gmc-dealers"), "GMC dealers",
                          "JSON dealer-locator API, US grid of radius searches", 1900, 1300, 1.5, 75,
                          "/bypass/ not disallowed"),
    "ford-dealers": _chain(ford_dealers.collect, "Ford and Lincoln dealers", "JSON dealer API, one request per state",
                           3500, 150, 10.0, 60, "Crawl-delay 10 (kept); the API path is not disallowed"),
}

# Checked 26 November 2026 and refused at once (no collector; a later check may find them open):
BLOCKED = {
    "McDonald's": "JSON store API (googleappsv2/geolocation): HTTP 403 from Akamai",
    "Jersey Mike's": "JSON store API (bapi.prd.jerseymikes.com): HTTP 403, DataDome captcha",
    "YMCA": "sitemap: HTTP 403, Cloudflare challenge",
    "Planet Fitness": "sitemap: HTTP 403, Cloudflare challenge",
    "Health Mart": "sitemap answered once, then Imperva (Incapsula) challenge",
    "Citgo": "station API needs a reCAPTCHA token",
    "Choice Hotels": "sitemap: HTTP 403 from Akamai",
    "H&R Block": "sitemap: HTTP 403 from Akamai",
    "Best Western": "sitemap answered (2,477 US hotels), hotel pages: HTTP 403, DataDome captcha",
    "Stellantis (Jeep, Chrysler, Dodge, Ram)": "dealer API (bdlws): HTTP 403 from Akamai",
    "Fastenal": "HTTP 403 from Akamai (even robots.txt)",
    "Tractor Supply": "store sitemap: connection dropped (HTTP/2 stream reset)",
    "Goodwill": "locator: HTTP 403",
    "Bitcoin Depot": "TLS handshake refused (not reachable from the test machine)",
    "Allstate": "not collected: individual agents' offices",
}
