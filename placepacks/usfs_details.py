"""Details of the Forest Service's recreation sites (hours, season, fees, reservations, accessibility, open status),
joined to the existing source usfs-recreation-sites when it is fetched, so a site is never listed twice.

The places themselves come from the Enterprise Data Warehouse's InfraRecreationSites layer (sources.json,
usfs-recreation-sites). The Recreation Opportunities layer (EDW_RecreationOpportunities_01, about 14,200 records,
the data behind fs.usda.gov's recreation pages; public domain, no key) describes the same sites for visitors. Its
"infra_cn" is the infrastructure site's "site_cn"; a record without one is matched by the same name (normalised:
placepacks.lookup.normal_name) within MATCH_M metres. A record that matches no site is not added.

The catalogue entry's fetch has "join": {"url": the Recreation Opportunities layer, "fields": its columns,
"on": "site_cn", "join_on": "infra_cn", "name": "site_name", "join_name": "recareaname"}. fetch_arcgis
(placepacks/fetch.py) fetches the region's records of both layers and calls join(); the site's CSV gains:
  _hours    the opening hours in OpenStreetMap's syntax when the layer's words are plain enough
            (placepacks.hours.from_text: "Monday - Friday, 8:00 a.m. - 4:30 p.m." -> "Mo-Fr 08:00-16:30",
            "24/7", "Sunrise to sunset"); else empty
  _website  the site's page on fs.usda.gov ("recareaurl")
  _note     "Season: May to October 31; Hours: <the layer's words, when they are not OpenStreetMap hours>; Fees: ...;
            Reservations: ...; Accessibility: ...; Status at the last build: closed" (data only, never spoken;
            HTML taken out; telephone numbers and e-mail addresses are taken out by the tabular reader)
The site's own telephone number comes from the infrastructure layer ("site_phone_nbr"), not from this join.
"""

import csv
import os

from placepacks import hours

MATCH_M = 300
NEW_COLUMNS = ["_hours", "_website", "_note"]
# The layer's open status words that are worth a note (the status is as of the build, so it is said as such).
CLOSED = {"closed", "temporarily closed"}


def details_of(rec):
    """{"_hours", "_website", "_note"} of one Recreation Opportunities record (see the module docstring)."""
    from placepacks.gov_details import note_of
    text = hours.plain_text(rec.get("operational_hours"))
    osm = hours.from_text(text)
    start, end = hours.plain_text(rec.get("open_season_start")), hours.plain_text(rec.get("open_season_end"))
    season = f"{start} to {end}" if start and end and start != end else start or end
    status = (rec.get("openstatus") or "").strip().lower()
    parts = [("Season", season), ("Hours", "" if osm else text),
             ("Fees", hours.plain_text(rec.get("feedescription"))[:300]),
             ("Reservations", hours.plain_text(rec.get("reservation_info"))[:300]),
             ("Accessibility", hours.plain_text(rec.get("accessibility"))),
             ("Status at the last build", status if status in CLOSED else "")]
    url = (rec.get("recareaurl") or "").strip()
    return {"_hours": osm, "_website": url if url.startswith(("http://", "https://")) else "",
            "_note": note_of(parts)}


def _richness(rec):
    """How much a record says (a site with several records keeps the one that says most)."""
    return sum(1 for k in ("operational_hours", "open_season_start", "feedescription", "reservation_info",
                           "accessibility", "recareaurl") if (rec.get(k) or "").strip())


def match(sites, records, spec):
    """{index of a site: its best record}: by the shared id (spec "on" = spec "join_on"), else by the same normalised
    name within MATCH_M metres. sites and records are dict rows with "_lat" and "_lon"."""
    from placepacks import fmt
    from placepacks.lookup import normal_name
    by_id, by_name = {}, {}
    for rec in records:
        rid = (rec.get(spec["join_on"]) or "").strip()
        if rid:
            if rid not in by_id or _richness(rec) > _richness(by_id[rid]):
                by_id[rid] = rec
        else:
            by_name.setdefault(normal_name(rec.get(spec["join_name"])), []).append(rec)
    out = {}
    for i, site in enumerate(sites):
        rec = by_id.get((site.get(spec["on"]) or "").strip())
        if rec is None:
            try:
                lat, lon = float(site["_lat"]), float(site["_lon"])
            except (TypeError, ValueError, KeyError):
                continue
            near = []
            for r in by_name.get(normal_name(site.get(spec["name"])), []):
                try:
                    d = fmt.metres(lat, lon, float(r["_lat"]), float(r["_lon"]))
                except (TypeError, ValueError, KeyError):
                    continue
                if d <= MATCH_M:
                    near.append((d, -_richness(r), id(r), r))
            rec = min(near)[3] if near else None
        if rec is not None:
            out[i] = rec
    return out


def join_files(site_csv, record_csv, spec):
    """Add NEW_COLUMNS to the sites' CSV from the records' CSV (both written by fetch_arcgis). Returns the number
    of sites that got details."""
    with open(site_csv, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = [c for c in reader.fieldnames or [] if c not in NEW_COLUMNS]
        sites = list(reader)
    with open(record_csv, newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    found = match(sites, records, spec)
    with open(site_csv + ".partial", "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=header + NEW_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for i, site in enumerate(sites):
            w.writerow({**site, **(details_of(found[i]) if i in found else dict.fromkeys(NEW_COLUMNS, ""))})
    os.replace(site_csv + ".partial", site_csv)
    return len(found)


def join(entry, region, folder, site_csv, sleep):
    """fetch_arcgis's step for an entry with "join": fetch the region's Recreation Opportunities records into a
    temporary CSV, add their details to site_csv, and delete the temporary file. A join that fails leaves the
    sites as they are (they are still listed, without the details) and says why."""
    from placepacks import fetch
    spec = entry["fetch"]["join"]
    sub = {"id": entry["id"] + "-details", "fetch": {"url": spec["url"], "where": spec.get("where", "1=1"),
                                                     "fields": spec["fields"], "page": spec.get("page", 500),
                                                     "pause": spec.get("pause", entry["fetch"].get("pause", 1))}}
    try:
        got = fetch.fetch_arcgis(sub, region, folder, False, sleep)
        count = join_files(site_csv, got["path"], spec)
    except Exception as e:  # noqa: BLE001 - the sites are kept without details
        print(f"  {entry['id']}: the recreation details were not joined ({str(e)[:150]})", flush=True)
        return 0
    finally:
        temp = os.path.join(folder, sub["id"] + ".csv")
        if os.path.exists(temp):
            os.remove(temp)
    print(f"  {entry['id']}: details for {count:,} sites (Recreation Opportunities)", flush=True)
    return count
