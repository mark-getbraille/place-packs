"""A build-time offline address geocoder: street addresses of address-only sources (the IRS's exempt
organizations, permittee lists) are located against the region's own address points (the National Address
Database slice the build already has), so nothing is sent anywhere.

  locate(requests, nad_path, nad_entry) -> {index: (lat, lon, how)}
      requests: [(street address line, city, ZIP)]; how is "address" (the address point, matched with the ZIP or
      the city), or "street" (the address is a home: the NAD marks it residential, so the organization is put at
      the middle of its street's points in that ZIP, "on Elm Street", never at the house).
  The NAD is read in one pass, keeping only the streets the requests name (a state's NAD is millions of rows).
  Post office boxes, rural routes and addresses without a house number cannot be located and are left out.
  stats(found, total) gives the line the build prints: "located 3,412 of 4,108 addresses (83%): 2,901 at the
  address, 511 on the street (homes)".
Matching normalises the street: upper case, no punctuation, the usual words shortened (STREET -> ST, NORTH -> N),
and unit suffixes (APT, STE, UNIT, #) dropped. Address ranges (TIGER) are not interpolated yet.
"""

import re

WORDS = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "BOULEVARD": "BLVD",
         "COURT": "CT", "PLACE": "PL", "TERRACE": "TER", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "CIRCLE": "CIR",
         "SQUARE": "SQ", "ROUTE": "RTE", "TURNPIKE": "TPKE", "EXPRESSWAY": "EXPY", "TRAIL": "TRL", "WAY": "WAY",
         "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "NORTHEAST": "NE", "NORTHWEST": "NW",
         "SOUTHEAST": "SE", "SOUTHWEST": "SW", "MOUNT": "MT", "FORT": "FT", "SAINT": "ST", "CENTER": "CTR"}
UNIT = re.compile(r"\s+(APT|APARTMENT|STE|SUITE|UNIT|FL|FLOOR|RM|ROOM|BLDG|DEPT|#)\b.*$")
NO_HOUSE = re.compile(r"^(P\s*O\s*BOX|POST OFFICE BOX|BOX|PO DRAWER|RR|RURAL ROUTE|HC|GENERAL DELIVERY)\b")


def norm_street(text):
    """A street name for matching: "North Main Street" -> "N MAIN ST"."""
    text = re.sub(r"[^A-Z0-9 ]", " ", (text or "").upper())
    return " ".join(WORDS.get(w, w) for w in text.split())


def split_address(line):
    """(house number, normalised street) of an address line ("123 Main St Apt 4" -> ("123", "MAIN ST")), or None for
    a post office box, a rural route or a line without a house number."""
    text = re.sub(r"[.,]", " ", (line or "").upper()).strip()
    if not text or NO_HOUSE.match(text):
        return None
    text = UNIT.sub("", text)
    m = re.match(r"^(\d+)[A-Z]?(?:-\d+)?\s+(.+)$", text)
    if not m:
        return None
    street = norm_street(m.group(2))
    return (m.group(1), street) if street else None


def norm_city(text):
    """A city for matching."""
    return " ".join(re.sub(r"[^A-Z ]", " ", (text or "").upper()).split())


def zip5(text):
    """The five-digit ZIP of "05089-0455"."""
    m = re.match(r"\s*(\d{5})", text or "")
    return m.group(1) if m else ""


def locate(requests, nad_path, nad_entry):
    """Locate the requests against the NAD slice at nad_path (read with its catalogue entry's columns). Returns
    {request index: (lat, lon, how)} (see the module docstring)."""
    from placepacks.readers.tabular import _get, dict_rows, open_texts
    wanted = {}
    for i, (line, city, zipc) in enumerate(requests):
        parts = split_address(line)
        if parts:
            wanted.setdefault(parts[1], []).append((i, parts[0], norm_city(city), zip5(zipc)))
    if not wanted or not nad_path:
        return {}
    cols = nad_entry["columns"]
    exact, by_city, streets = {}, {}, {}
    for text in open_texts(nad_path, nad_entry.get("member", "*"), nad_entry.get("encoding", "utf-8-sig")):
        for row in dict_rows(text, nad_entry):
            street = norm_street(_get(row, cols["street"]))
            if street not in wanted:
                continue
            try:
                lat, lon = float(_get(row, cols["lat"])), float(_get(row, cols["lon"]))
            except ValueError:
                continue
            number = re.match(r"\d+", _get(row, cols["number"]) or "")
            z = zip5(_get(row, cols.get("zip", "")))
            home = "RESIDENT" in (_get(row, cols.get("kind", "")) or "").upper()
            s = streets.setdefault((street, z), [0.0, 0.0, 0])
            s[0] += lat
            s[1] += lon
            s[2] += 1
            if number:
                exact.setdefault((number.group(0), street, z), (lat, lon, home))
                by_city.setdefault((number.group(0), street, norm_city(_get(row, cols.get("city", "")))),
                                   (lat, lon, home))
    out = {}
    for street, items in wanted.items():
        for i, number, city, z in items:
            hit = exact.get((number, street, z)) or by_city.get((number, street, city))
            if not hit:
                continue
            lat, lon, home = hit
            if home:
                # A home address: the middle of the street's points in that ZIP, never the house.
                sums = streets.get((street, z)) or streets.get((street, ""))
                if sums and sums[2]:
                    out[i] = (sums[0] / sums[2], sums[1] / sums[2], "street")
                continue
            out[i] = (lat, lon, "address")
    return out


def stats(found, total):
    """The line the build prints about a geocoded source."""
    at = sum(1 for v in found.values() if v[2] == "address")
    street = len(found) - at
    pct = round(100 * len(found) / total) if total else 0
    return (f"located {len(found):,} of {total:,} addresses ({pct}%): {at:,} at the address, {street:,} on the street "
            f"(homes)")
