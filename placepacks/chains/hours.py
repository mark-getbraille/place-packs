"""Opening hours in OpenStreetMap's syntax ("Mo-Fr 06:00-23:00; Sa,Su 07:00-22:00"), made from the shapes store
locators use, the way All The Places' OpeningHours helper does (github.com/alltheplaces/alltheplaces,
locations/hours.py, MIT; the logic is rewritten here, not copied).

  - week(days): {day: [(open, close), ...]} -> the OSM text. Days left out are closed (OSM's default).
  - from_spec(items): schema.org openingHoursSpecification (dayOfWeek, opens, closes).
  - from_text(text): "Sun - Sat 7:00 AM - 8:00 PM", "Mon-Fri 9am-5pm, Sat 10am-2pm", or text that already is in
    OSM's syntax ("Mo 08:00-17:00; Tu 08:00-17:00" becomes "Mo,Tu 08:00-17:00"; what cannot be read more simply,
    such as two ranges a day, is kept as it is).
  - clock(text): one time ("7:00 A.M.", "06:00:00", "9am", "noon") -> "07:00", or "" when it is not a time.
A store open round the clock is "00:00-24:00" for that day, and "24/7" when every day is. Anything that cannot be
read gives "" (no hours rather than wrong hours).
"""

import re

DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
_DAY_WORDS = {"mo": "Mo", "tu": "Tu", "we": "We", "th": "Th", "fr": "Fr", "sa": "Sa", "su": "Su"}
_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?(?::\d{2})?\s*([ap])?\.?\s*(?:m\.?)?\s*$", re.I)
_OSM = re.compile(r"^(24/7|((Mo|Tu|We|Th|Fr|Sa|Su|PH)([-,](Mo|Tu|We|Th|Fr|Sa|Su|PH))*\s+"
                  r"(off|closed|\d\d:\d\d-\d\d:\d\d(,\d\d:\d\d-\d\d:\d\d)*)(;\s*|$))+)$")


def day_of(text):
    """The OSM day ("Mo") of a day's name in English ("Monday", "mon", "Thur", "http://schema.org/Monday"), or ""."""
    word = re.sub(r"^.*/", "", str(text or "")).strip().lower()
    if word.startswith("thr"):
        word = "th"
    return _DAY_WORDS.get(word[:2], "") if len(word) >= 2 else ""


def clock(text):
    """One time of day as "HH:MM" (24-hour), or "". "noon" is 12:00, "midnight" 00:00."""
    t = str(text or "").strip().lower().replace("a.m.", "am").replace("p.m.", "pm")
    if t in ("noon", "12 noon"):
        return "12:00"
    if t == "midnight":
        return "00:00"
    m = _TIME.match(t)
    if not m:
        return ""
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if half:
        if not 1 <= hour <= 12:
            return ""
        hour = hour % 12 + (12 if half == "p" else 0)
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        return ""
    return f"{hour:02d}:{minute:02d}"


def span(opens, closes):
    """(open, close) as OSM times, or None. The same time twice (a 24-hour store's "04:00 A.M." to "04:00 A.M.") or
    00:00 to 23:59 is the whole day; a close at 00:00 is 24:00."""
    a, b = clock(opens), clock(closes)
    if not a or not b:
        return None
    if a == b or (a == "00:00" and b in ("23:59", "24:00")):
        return "00:00", "24:00"
    if b == "00:00":
        b = "24:00"
    return a, b


def week(days):
    """The OSM text of {day ("Mo"..."Su"): [(open, close), ...]}; days missing or empty are closed. "" when no day
    is open. Neighbouring days with the same hours are joined: "Mo-Fr", or "Sa,Su" for two."""
    times = {d: ",".join(f"{a}-{b}" for a, b in sorted(set(days.get(d) or []))) for d in DAYS}
    if not any(times.values()):
        return ""
    if all(times[d] == "00:00-24:00" for d in DAYS):
        return "24/7"
    parts, i = [], 0
    while i < 7:
        j = i
        while j + 1 < 7 and times[DAYS[j + 1]] == times[DAYS[i]]:
            j += 1
        if times[DAYS[i]]:
            label = DAYS[i] if i == j else (f"{DAYS[i]},{DAYS[j]}" if j == i + 1 else f"{DAYS[i]}-{DAYS[j]}")
            parts.append(f"{label} {times[DAYS[i]]}")
        i = j + 1
    return "; ".join(parts)


def from_spec(items):
    """OSM hours from schema.org openingHoursSpecification (a dict or a list of them), or ""."""
    if isinstance(items, dict):
        items = [items]
    days = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        names = item.get("dayOfWeek")
        names = names if isinstance(names, list) else [names]
        got = span(item.get("opens"), item.get("closes"))
        for name in names:
            d = day_of(name)
            if d and got:
                days.setdefault(d, []).append(got)
    return week(days)


def days_between(first, last):
    """The days from first to last, going round the week ("Sa" to "Mo" is Sa, Su, Mo; "Su" to "Sa" all seven)."""
    i, j = DAYS.index(first), DAYS.index(last)
    return [DAYS[(i + k) % 7] for k in range((j - i) % 7 + 1)]


_PART = re.compile(r"^\s*(?P<days>[A-Za-z][A-Za-z.,&/ \-]*?)\s*:?\s+(?P<times>(?:\d|noon|midnight|closed|open 24).*)$",
                   re.I)


def from_text(text):
    """OSM hours from a locator's text (see the module docstring), or ""."""
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    osm_already = bool(_OSM.match(text))            # kept as it is when it cannot be read more simply below
    if re.fullmatch(r"(?i)(open )?24 ?(hours|hrs)(,? 7 days( a week)?)?|24/7", text):
        return "24/7"
    days = {}
    for part in re.split(r"\s*[;,|\n]\s*(?=[A-Za-z]{2})", text):
        m = _PART.match(part)
        if not m:
            return text if osm_already else ""
        names, times = m.group("days"), m.group("times").strip()
        found = []
        for chunk in re.split(r"\s*(?:,|&|\band\b)\s*", names):
            ends = [day_of(x) for x in re.split(r"\s*(?:-|–|\bto\b|\bthru\b|\bthrough\b)\s*", chunk.strip(" .")) if x]
            if not ends or not all(ends):
                return text if osm_already else ""
            found += days_between(ends[0], ends[-1]) if len(ends) == 2 else ends
        if re.match(r"(?i)closed", times):
            continue
        if re.match(r"(?i)open 24", times):
            got = [("00:00", "24:00")]
        else:
            pieces = re.split(r"\s*(?:-|–|\bto\b)\s*", times)
            one = span(pieces[0], pieces[1]) if len(pieces) == 2 else None
            if not one:
                return text if osm_already else ""
            got = [one]
        for d in found:
            days.setdefault(d, []).extend(got)
    return week(days)
