"""The businesses already in the published packs, as the input of the details collectors (the Yellow Pages lookups,
tools/yp_lookup.py, and the business-website collector, placepacks/directories/websites.py).

A region's newest "businesses" pack (packs.json in the release "packs" names it and the release that holds it) is
downloaded and read here: its places listed now (the last month of each row is the pack's build month) whose class
is "business", with their key, source, name, fine type, brand, position and the details they already have (the
pack's biz_details table: phone, website, opening hours). The region's "addresses" pack, when there is one, gives
each place the street addresses within ADDRESS_M metres and its town (the nearest address within TOWN_M metres),
which the Yellow Pages search and its address check need.
Only the Python standard library is used (and placepacks.lookup's PackReader).
"""

import sqlite3

# The states (and DC and Puerto Rico) by population, the most people first (2020 census): the order the details
# collectors work in.
POPULATION = ["CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI", "NJ", "VA", "WA", "AZ", "MA", "TN", "IN",
              "MD", "MO", "WI", "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT", "IA", "NV", "AR", "MS",
              "KS", "NM", "NE", "ID", "WV", "HI", "NH", "ME", "RI", "MT", "DE", "SD", "ND", "AK", "DC", "VT", "WY",
              "PR"]
ADDRESS_M = 75                  # an address this close to a place may be its own (the matching rule's distance)
TOWN_M = 500                    # the town of the nearest address this close is the place's town


def region_order(regions=None):
    """[(region id, state code)] in POPULATION order; a state with sub-regions gives its sub-regions."""
    from placepacks import catalogue
    regions = regions or catalogue.regions()
    by_code = {r.get("code"): r for r in regions.values() if r.get("cc") == "US" and not r.get("parent")}
    out = []
    for code in POPULATION:
        r = by_code.get(code)
        if r:
            out += [(c, code) for c in r.get("children") or [r["id"]]]
    return out


def places(path):
    """Yield the businesses listed now in a businesses pack: {"key", "source", "name", "type", "brand", "lat",
    "lon", "phone", "website", "opening_hours"} (the details are "" when the pack has none)."""
    from placepacks import fmt
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        month = int(dict(db.execute("SELECT key, value FROM meta").fetchall()).get("built_month") or 0)
        cols = ["p.key", "p.source", "p.name", "p.lat", "p.lon"]
        joins = ""
        if "point_types" in tables:
            cols.append("t.name")
            joins += " LEFT JOIN point_types pt ON pt.id = p.id LEFT JOIN types t ON t.id = pt.type"
        else:
            cols.append("NULL")
        if "point_brands" in tables:
            cols.append("b.name")
            joins += " LEFT JOIN point_brands pb ON pb.id = p.id LEFT JOIN brands b ON b.id = pb.brand"
        else:
            cols.append("NULL")
        if "biz_details" in tables:
            cols += ["d.phone", "d.website", "d.opening_hours"]
            joins += " LEFT JOIN biz_details d ON d.id = p.id"
        else:
            cols += ["NULL", "NULL", "NULL"]
        sql = (f"SELECT {', '.join(cols)} FROM points p{joins} WHERE p.cls = 'business'"
               + (" AND p.last = ?" if month else "") + " ORDER BY p.id")
        for key, source, name, lat, lon, kind, brand, phone, website, hours in db.execute(sql, (month,) if month
                                                                                            else ()):
            yield {"key": key, "source": source, "name": name or "", "type": kind or "", "brand": brand or "",
                   "lat": lat / fmt.SCALE, "lon": lon / fmt.SCALE, "phone": phone or "", "website": website or "",
                   "opening_hours": hours or ""}
    finally:
        db.close()


class Addresses:
    """The address points of a region's addresses pack (None: no pack, every answer is empty)."""

    def __init__(self, path):
        """Open the pack (placepacks.lookup.PackReader), or nothing."""
        from placepacks.lookup import PackReader
        self.pack = PackReader(path) if path else None

    def near(self, lat, lon):
        """(["184 Main St", ...] within ADDRESS_M metres, nearest first; the town of the nearest address within
        TOWN_M metres, or "")."""
        if self.pack is None:
            return [], ""
        found = self.pack.addresses_near(lat, lon, TOWN_M)
        close = []
        for a in found:
            line = f"{a['number']} {a['street']}"
            if a["d"] <= ADDRESS_M and line not in close:
                close.append(line)
        town = next((a["city"] for a in found if a.get("city")), "")
        return close, town
