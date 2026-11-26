"""The "sitemap of store pages" kind of collector: read the chain's sitemap, keep the addresses of its US store
pages, then read each page's schema.org JSON-LD (placepacks/chains/jsonld.py). This is how All The Places'
SitemapSpider + StructuredDataSpider work (github.com/alltheplaces/alltheplaces, MIT).

collect() is given everything that differs between chains: the sitemaps, a pattern for the store pages, the
schema.org types wanted, the store's tags, brand and Wikidata id, how to make the store's number from its address,
and optionally a fix() for pages whose JSON-LD lacks something the page has elsewhere (Wyndham's position).
A page that has gone (404) is skipped; a page without a store in it is counted, not fatal; a page that keeps
failing is skipped, unless more than one page in twenty (and more than twenty) do.
"""

import re

from placepacks.chains import jsonld
from placepacks.chains.base import make_row, sitemap
from placepacks.chains.polite import NotFound, RequestFailed


def store_pages(client, sitemaps, pattern, keep=None):
    """The store page addresses of the sitemaps that match pattern (a regular expression) and keep(url), each once,
    in sitemap order."""
    found, seen = [], set()
    for url in sitemaps:
        for loc in sitemap(client, url):
            if re.search(pattern, loc) and loc not in seen and (keep is None or keep(loc)):
                seen.add(loc)
                found.append(loc)
    return found


def collect(client, chain, sitemaps, pattern, wanted, tags, brand, brand_wikidata, ref, name=None, keep=None,
            fix=None, stats=None, page_of=None):
    """Yield the rows of a chain's store pages (see the module docstring). ref(url, store) -> the store's number;
    name: a fixed name (else the JSON-LD's, else the brand); fix(page, url, store) may change the store dict (or
    return None to skip the page); stats (a dict) gets "pages", "gone" and "no_store" counts; page_of(url): the
    address to read for a sitemap address (Wyndham's ".../overview"), the sitemap's own by default. tags and brand
    may be functions of the sitemap address (one sitemap of several brands)."""
    stats = stats if stats is not None else {}
    pages = store_pages(client, sitemaps, pattern, keep)
    stats.update(pages=len(pages), gone=0, no_store=0)
    for url in pages:
        try:
            page = client.fetch(page_of(url) if page_of else url)
        except NotFound:
            stats["gone"] += 1
            continue
        except RequestFailed:
            # One page that keeps failing is skipped; many mean the site is in trouble, and the run fails (the
            # previous month's stores are then kept).
            stats["failed"] = stats.get("failed", 0) + 1
            if stats["failed"] > max(20, len(pages) // 20):
                raise
            continue
        found = None
        for thing in jsonld.find(page, wanted):
            found = jsonld.store(thing, need_position=fix is None)     # fix() may find the position elsewhere
            if found:
                break
        if found and fix:
            found = fix(page, url, found)
        row = None
        if found:
            its_brand, its_wikidata = brand(url) if callable(brand) else (brand, brand_wikidata)
            its_tags = tags(url) if callable(tags) else tags
            row = make_row(chain, ref(url, found), name or found.get("name") or its_brand, its_tags, found.get("lat"),
                           found.get("lon"), brand=its_brand, brand_wikidata=its_wikidata, phone=found.get("phone"),
                           website=url, opening_hours=found.get("opening_hours"), street=found.get("street"),
                           city=found.get("city"), state=found.get("state"), postcode=found.get("postcode"))
        if row is None:
            stats["no_store"] += 1
            continue
        yield row
