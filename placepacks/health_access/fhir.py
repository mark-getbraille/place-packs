"""Health insurers' public FHIR provider directories: the accessibility facts, hours and phone of clinics and
hospitals (the owner's request of 27 November 2026, notes/helper-rules.txt; part of source "health-access").

Under the CMS Interoperability and Patient Access rule, Medicare Advantage, Medicaid and CHIP managed care and
marketplace plans must publish their provider directories as open FHIR APIs, with no login (most follow the Da
Vinci PDex Plan-Net profile). A directory's Location records carry the place's name, address, position, phone,
hours (hoursOfOperation) and accessibility extensions (Plan-Net "accessibility": handicap accessible, ADA
compliant, public transit; the older VhDir codes: building, exam room, equipment, parking, restroom, ASL, TTY).

The directories read (PAYERS) answered without a login on 27 November 2026; others tried are in sources.json
"rejected" (Optum/UnitedHealthcare's public directory did not answer, Centene's did not answer, Elevance's answered
an error). Only Location records are read: never Practitioner, PractitionerRole or any person's name. A Location
named like a person or a practitioner's own office ("Alice Example MD", "... DDS") is left out, as is one without a
position, one whose name is only its street address, and one that says nothing about accessibility or hours.

Each kept Location becomes a "site" row (features.FEATURE_FIELDS: key "<unit>:<Location id>", name, NPI when the
record has one, position, phone, opening_hours in OpenStreetMap syntax, address, and the note "Accessibility
(<payer> provider directory): handicap accessible; ASL; TTY ..."). The pack build ties it to the clinic or
hospital already in the pack (the NPI's organisation, else the same name within 400 m) and gives that place the
details it lacks; a row that matches no place adds nothing (entry "keep_unmatched_sites": false).
Politeness: robots.txt first (obeyed), an identified User-Agent, a pause between pages, a request budget; a refusal
stops the directory ("blocked").

Resuming: the big directories (Humana about 1.25 million Locations, Molina about 560,000 on 27 November 2026) cannot
be read in one job. collect() writes the address of the next page it has not read into stats["resume"] before every
request, so when the budget or the job's time runs out the run (placepacks/directories/run.py, units "resumable")
publishes the rows read so far and the release's list keeps that address; next month's run starts there
(stats["resume_from"]) and its rows are merged with the earlier ones, so the whole directory is covered over a few
months. The payers' next links are stateless cursors (Humana's _continuationToken, Molina's cursorMark), so they
still work a month later; should one have expired (the server answers an error or "not found"), the run starts again
from the first page.
"""

import re
import urllib.parse

from placepacks import features
from placepacks.chains.polite import NotFound, RequestFailed
from placepacks.directories.common import person_name

USER_AGENT = "place-packs-health-access/1 (+https://github.com/mark-getbraille/place-packs)"
PAGE_SIZE = 500
PAYERS = {
    "fhir-cigna": {"payer": "Cigna", "base": "https://fhir.cigna.com/ProviderDirectory/v1",
                   "hosts": ["fhir.cigna.com"]},
    "fhir-humana": {"payer": "Humana", "base": "https://fhir.humana.com/api", "hosts": ["fhir.humana.com"]},
    "fhir-molina": {"payer": "Molina Healthcare", "base": "https://api.interop.molinahealthcare.com/providerdirectory",
                    "hosts": ["api.interop.molinahealthcare.com", "molina.sapphirethreesixtyfive.com"]},
}
# Plan-Net and VhDir accessibility codes without a display text.
CODES = {"handiaccess": "handicap accessible", "adacomp": "ADA compliant", "pubtrans": "public transit nearby",
         "ha": "handicap accessible", "asl": "American Sign Language", "tty": "TTY", "bld": "accessible building",
         "eqp": "accessible equipment", "exr": "accessible exam room", "prk": "accessible parking",
         "rst": "accessible restroom", "cultcomp": "cultural competence"}
CREDENTIALS = re.compile(r"(,|\s)\s*(m\.?d|d\.?o|dds|dmd|dpm|np|pa-?c|lcsw|ph\.?d|rn|o\.?d|d\.?c|pt|dpt|lpc|lmft|"
                         r"psyd|aud|faap|facp)\.?\s*$", re.I)
ADDRESS_NAME = re.compile(r"^\d+\s+\S+.*(-|,)\s*[A-Z .]+-\s*[A-Z]{2}\b|^\d+\s+[\w .]+$", re.I)
DAYS = {"mon": "Mo", "tue": "Tu", "wed": "We", "thu": "Th", "fri": "Fr", "sat": "Sa", "sun": "Su"}
ORDER = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def accessibility(res):
    """The accessibility phrases of a Location's extensions (Plan-Net and VhDir), each once, in order."""
    out = []

    def add(text):
        """Keep a phrase once."""
        t = " ".join(str(text or "").split())
        if t and t.lower() not in (o.lower() for o in out):
            out.append(t)

    def walk(exts):
        """Look through extensions (and nested ones) for accessibility values."""
        for e in exts or []:
            if not isinstance(e, dict):
                continue
            if str(e.get("url", "")).lower().endswith("accessibility"):
                cc = e.get("valueCodeableConcept") or {}
                names = [c.get("display") or CODES.get(str(c.get("code", "")).lower(), "") for c in
                         cc.get("coding") or []]
                names = [" ".join(str(n).split()) for n in names if n]
                text = " ".join(str(cc.get("text") or "").split())
                if text and names and [n.lower() for n in names] != [text.lower()]:
                    # VhDir groups its codes under a heading: "Handicap Accessible: Building, Parking, Restroom".
                    add(f"{text}: {', '.join(names)}")
                elif names:
                    for n in names:
                        add(n)
                elif text:
                    add(text)
            walk(e.get("extension"))
    walk(res.get("extension"))
    return out


def hours_of(res):
    """A Location's hoursOfOperation in OpenStreetMap syntax ("Mo-Fr 08:00-17:00; Sa 09:00-12:00"; a day with two
    spans "Mo-Fr 09:00-17:00,17:00-21:00"), or ""."""
    per_day = {}
    for h in res.get("hoursOfOperation") or []:
        days = [DAYS.get(str(d).lower()[:3]) for d in h.get("daysOfWeek") or []]
        days = [d for d in days if d]
        if h.get("allDay"):
            span = "00:00-24:00"
        elif h.get("openingTime") and h.get("closingTime"):
            span = f"{str(h['openingTime'])[:5]}-{str(h['closingTime'])[:5]}"
        else:
            continue
        for d in days:
            if span not in per_day.setdefault(d, []):
                per_day[d].append(span)
    spans = {}
    for d, times in per_day.items():
        spans.setdefault(",".join(sorted(times)), set()).add(d)
    parts = []
    for span, days in sorted(spans.items(), key=lambda kv: min(ORDER.index(d) for d in kv[1])):
        idx = sorted(ORDER.index(d) for d in days)
        runs, run = [], [idx[0]]
        for i in idx[1:]:
            if i == run[-1] + 1:
                run.append(i)
            else:
                runs.append(run)
                run = [i]
        runs.append(run)
        text = ",".join(ORDER[r[0]] if len(r) == 1 else f"{ORDER[r[0]]}-{ORDER[r[-1]]}" for r in runs)
        parts.append(f"{text} {span}")
    return "; ".join(parts)


def phone_of(res):
    """The first work (or any) phone number of a Location's telecom, or ""."""
    phones = [t for t in res.get("telecom") or [] if isinstance(t, dict) and t.get("system") == "phone"]
    phones.sort(key=lambda t: t.get("use") != "work")
    return str(phones[0].get("value", "")) if phones else ""


def has_tty(res):
    """True when a Location's telecom lists a TTY line."""
    return any("tty" in str(t.get("value", "")).lower() or "tty" in str(t.get("system", "")).lower()
               for t in res.get("telecom") or [] if isinstance(t, dict))


def name_of(res):
    """A Location's name to say (its own, else its managing organisation's), or "" when it is only an address or a
    person's or practitioner's own name."""
    for text in (res.get("name"), (res.get("managingOrganization") or {}).get("display")):
        name = " ".join(str(text or "").split())
        if not name or ADDRESS_NAME.match(name):
            continue
        if person_name(name) or CREDENTIALS.search(name):
            return ""
        return name
    return ""


def address_of(res):
    """"1125 N Madeup Blvd, Sparks, NV 89431" from a Location's address, or ""."""
    a = res.get("address") or {}
    line = ", ".join(" ".join(str(x).split()) for x in a.get("line") or [] if x)
    tail = " ".join(x for x in (a.get("state", ""), a.get("postalCode", "")) if x)
    return ", ".join(x for x in (line, a.get("city", ""), tail) if x)


def npi_of(res):
    """The NPI among a Location's identifiers, or ""."""
    for i in res.get("identifier") or []:
        if "npi" in str(i.get("system", "")).lower() and re.fullmatch(r"\d{10}", str(i.get("value", ""))):
            return str(i["value"])
    return ""


def row_of(res, unit, payer):
    """The "site" row of one Location resource, or None (see the module docstring)."""
    if res.get("resourceType", "Location") != "Location" or res.get("status", "active") != "active":
        return None
    name = name_of(res)
    pos = res.get("position") or {}
    try:
        lat, lon = float(pos["latitude"]), float(pos["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    access = accessibility(res)
    if has_tty(res) and not any("tty" in a.lower() or "telephony" in a.lower() for a in access):
        access.append("TTY")
    hours = hours_of(res)
    if not name or not (access or hours):
        return None
    note = f"Accessibility ({payer} provider directory): {'; '.join(access)}" if access else ""
    return {"key": f"{unit}:{res.get('id')}", "kind": "site", "site": f"{unit}:{res.get('id')}", "name": name,
            "site_name": name, "npi": npi_of(res), "lat": round(lat, 6), "lon": round(lon, 6),
            "phone": phone_of(res), "opening_hours": hours, "address": address_of(res),
            "notes": features.clean_note(note, 400), "org": payer, "vendor": "fhir"}


def own_page(url, spec):
    """True when url is a page of the payer's own directory hosts (spec["hosts"])."""
    try:
        return (urllib.parse.urlsplit(str(url or "")).hostname or "") in spec["hosts"]
    except ValueError:
        return False


def collect(client, unit, stats):
    """Every Location page of one payer's directory (PAYERS[unit]), following the bundles' "next" links on the
    payer's own hosts, from the first page or from stats["resume_from"] (where last month's run stopped), until the
    end or until the budget or the time runs out; stats["resume"] always holds the next page not yet read ("" at
    the end), see the module docstring. Yields the kept rows, each place once (the same name at the same
    position)."""
    from placepacks.directories.common import Robots
    spec = PAYERS[unit]
    parts = urllib.parse.urlsplit(spec["base"])
    robots = Robots(client, f"{parts.scheme}://{parts.netloc}", agent="place-packs-health-access")
    first = f"{spec['base']}/Location?_count={PAGE_SIZE}"
    if not robots.allowed(first):
        stats["robots"] = "disallowed"
        stats["may_be_empty"] = True
        return
    url = first
    start = stats.get("resume_from", "")
    if start and own_page(start, spec) and robots.allowed(start):
        url = start
    elif start:
        stats.pop("resume_from", None)          # not the payer's own page: read from the beginning
        stats["resume_ignored"] = str(start)[:300]
    seen = set()
    stats.update(pages=0, locations=0, kept=0)
    while url:
        stats["resume"] = url                   # where the next run starts if this one stops before this page
        try:
            bundle = client.json(url, headers={"Accept": "application/fhir+json"})
        except (NotFound, RequestFailed) as e:
            if url != first and stats["pages"] == 0 and stats.get("resume_from"):
                # Last month's cursor no longer answers: start again from the first page.
                stats.pop("resume_from", None)
                stats["resume_expired"] = f"{str(url)[:200]}: {type(e).__name__}"
                url = first
                continue
            raise
        stats["pages"] += 1
        for e in bundle.get("entry") or []:
            res = e.get("resource") or {}
            stats["locations"] += 1
            row = row_of(res, unit, spec["payer"])
            if not row:
                continue
            ident = (row["name"].lower(), round(row["lat"], 4), round(row["lon"], 4))
            if ident in seen:
                continue
            seen.add(ident)
            stats["kept"] += 1
            yield row
        nxt = next((link.get("url") for link in bundle.get("link") or [] if link.get("relation") == "next"), "")
        url = nxt if nxt and own_page(nxt, spec) else ""
    stats["resume"] = ""                        # the end of the directory: next time from the first page
