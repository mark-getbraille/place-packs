"""Opening hours written in OpenStreetMap's syntax ("Mo-Fr 09:00-16:00; Sa,Su off"), made from what government
sources give: a table of weekday opening and closing times (the Social Security offices: "9:00 AM", "4:00 PM"), the
National Park Service's weekly hours ("9:00AM - 5:00PM", "All Day", "Closed", "Sunrise to Sunset") with their dated
exceptions, and short free text ("Monday - Friday, 8:00 a.m. - 4:30 p.m.", "24/7", "Sunrise to sunset").

Every function here returns "" when it cannot be sure: the caller then keeps the source's own words as a plain-text
note instead (FORMAT.md, "Notes on places"), so a wrong guess never becomes a stated opening time. Only the Python
standard library is used.
"""

import datetime
import html
import re

DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")
# Day names in the forms the sources write them, each to OpenStreetMap's two letters.
DAY_WORDS = {"monday": "Mo", "mon": "Mo", "tuesday": "Tu", "tues": "Tu", "tue": "Tu", "wednesday": "We", "wed": "We",
             "thursday": "Th", "thurs": "Th", "thur": "Th", "thu": "Th", "friday": "Fr", "fri": "Fr",
             "saturday": "Sa", "sat": "Sa", "sunday": "Su", "sun": "Su"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# One clock time: "9:00 AM", "9AM", "9 a.m.", "12:30pm", "noon", "midnight".
_TIME = r"(?:(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\b\.?|(noon)|(midnight))"
_TIME_RE = re.compile(_TIME, re.I)
# One time range: "9:00 AM - 4:00 PM", "6 am to 10 pm", "8:00 a.m.- 4:30 p.m.".
_RANGE = re.compile(_TIME + r"\s*(?:-|–|—|to|until|till)\s*" + _TIME, re.I)
_DAY = r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
_DAY_RANGE = re.compile(_DAY + r"\.?\s*(?:-|–|—|to|through|thru)\s*" + _DAY + r"\b\.?", re.I)
# Words that show the times are not opening hours (quiet hours, check-in time, generator rules).
NOT_OPENING = re.compile(r"quiet|check.?in|check.?out|generator|checkout|arriv|depart", re.I)


def plain_text(text):
    """Source text without HTML tags and entities, its spaces tidied ("<p>Accessible&nbsp;toilets</p>" ->
    "Accessible toilets")."""
    text = re.sub(r"<\s*(br|/p|/li|/div|/h[1-6])\s*/?>", "; ", text or "", flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    text = re.sub(r"\s*;\s*(;\s*)*", "; ", " ".join(text.split()))
    return text.strip(" ;")


def _clock(hour, minute, half, noon, midnight, closing=False):
    """"HH:MM" of one matched time (closing: midnight at the end of a range is "24:00"), or "" when it is not one."""
    if noon:
        return "12:00"
    if midnight:
        return "24:00" if closing else "00:00"
    h, m = int(hour), int(minute or 0)
    if not 1 <= h <= 12 or m > 59:
        return ""
    if half.lower() == "a":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    if closing and h == 0 and m == 0:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def clock(text, closing=False):
    """"09:00" from "9:00 AM" ("12:00 PM" is "12:00"; a closing "12:00 AM" is "24:00"); "" when text is not a
    clock time."""
    m = _TIME_RE.fullmatch(" ".join((text or "").split()))
    return _clock(*m.groups(), closing=closing) if m else ""


def time_range(text):
    """"09:00-17:00" from "9:00AM - 5:00PM"; several ranges joined by "," ("9AM-12PM, 1PM-5PM" ->
    "09:00-12:00,13:00-17:00"); "" when text holds anything else."""
    text = " ".join((text or "").split())
    spans, rest = [], text
    for m in _RANGE.finditer(text):
        a, b = _clock(*m.groups()[:5]), _clock(*m.groups()[5:], closing=True)
        if not a or not b:
            return ""
        spans.append(f"{a}-{b}")
        rest = rest.replace(m.group(0), " ", 1)
    if not spans or re.sub(r"[\s,;&]|and", "", rest):
        return ""
    return ",".join(spans)


def day_value(text):
    """One day's hours in OpenStreetMap's syntax from the National Park Service's words: "9:00AM - 5:00PM" ->
    "09:00-17:00", "All Day" -> "00:00-24:00", "Closed" -> "off", "Sunrise to Sunset" -> "sunrise-sunset"; "" when
    the text is something else."""
    t = " ".join((text or "").split()).strip(" .")
    low = t.lower()
    if low in ("closed", "close", "off"):
        return "off"
    if low in ("all day", "open 24 hours", "24 hours", "open all day"):
        return "00:00-24:00"
    if re.fullmatch(r"(sunrise|dawn)\s*(-|–|to|until)\s*(sunset|dusk)", low):
        return "sunrise-sunset"
    return time_range(t)


def _day_list(days):
    """"Mo-We,Fr" from ["Mo", "Tu", "We", "Fr"] (runs of three or more days written as a range)."""
    idx = sorted(DAYS.index(d) for d in days)
    parts, run = [], [idx[0]]
    for i in idx[1:]:
        if i == run[-1] + 1:
            run.append(i)
        else:
            parts.append(run)
            run = [i]
    parts.append(run)
    out = []
    for r in parts:
        if len(r) >= 3:
            out.append(f"{DAYS[r[0]]}-{DAYS[r[-1]]}")
        else:
            out.extend(DAYS[i] for i in r)
    return ",".join(out)


def weekly(days):
    """OpenStreetMap opening hours from {day: hours} (day "Mo".."Su"; hours "09:00-16:00", "off" or "" for a day
    the source does not give): days with the same hours are written together ("Mo-Fr 09:00-16:00; Sa,Su off").
    Every day open all day is "24/7". "" when no day is given."""
    given = [(d, days.get(d)) for d in DAYS if days.get(d)]
    if not given:
        return ""
    if len(given) == 7 and all(v == "00:00-24:00" for _, v in given):
        return "24/7"
    groups = {}
    for d, v in given:
        groups.setdefault(v, []).append(d)
    if len(given) == 7 and len(groups) == 1:
        return f"Mo-Su {given[0][1]}"
    rules = [f"{_day_list(ds)} {v}" for v, ds in groups.items() if v != "off"]
    rules += [f"{_day_list(ds)} off" for v, ds in groups.items() if v == "off"]
    return "; ".join(rules)


def weekday_table(row, columns):
    """OpenStreetMap hours from a table of opening and closing times: columns = {"Mo": (open column, close
    column), ...} (the Social Security offices' MONDAY_OPEN_TIME and MONDAY_CLOSE_TIME). A day written "CLOSED" is
    "off"; "" when any given time cannot be read (the caller then keeps nothing rather than a wrong time)."""
    days = {}
    for day, (open_col, close_col) in columns.items():
        a, b = (row.get(open_col) or "").strip(), (row.get(close_col) or "").strip()
        if not a and not b:
            continue
        if a.upper() == "CLOSED" or b.upper() == "CLOSED":
            days[day] = "off"
            continue
        start, end = clock(a), clock(b, closing=True)
        if not start or not end:
            return ""
        days[day] = f"{start}-{end}"
    return weekly(days)


def _date_text(text):
    """"2026 Nov 01" from "2026-11-01" (OpenStreetMap's date form), or "" when it is not a date."""
    try:
        d = datetime.date.fromisoformat((text or "")[:10])
    except ValueError:
        return ""
    return f"{d.year} {MONTHS[d.month - 1]} {d.day:02d}"


NPS_DAYS = {"monday": "Mo", "tuesday": "Tu", "wednesday": "We", "thursday": "Th", "friday": "Fr", "saturday": "Sa",
            "sunday": "Su"}


def nps_week(standard):
    """OpenStreetMap hours of one National Park Service "standardHours" (or "exceptionHours") object; "" when a day
    cannot be read. An empty object (an exception without hours, such as a winter closure) is "off"."""
    if not standard:
        return "off"
    days = {}
    for word, day in NPS_DAYS.items():
        if word not in standard:
            continue
        v = day_value(standard.get(word))
        if not v:
            return ""
        days[day] = v
    return weekly(days)


def nps_hours(operating, today=None, limit=255):
    """OpenStreetMap hours from the first "operatingHours" entry of a National Park Service record: its standard
    week, then its exceptions that have not ended yet ("2026 Nov 01-2027 Apr 30 off"; a later rule overrides an
    earlier one in OpenStreetMap's syntax, so exceptions come after the standard week). Exceptions are dropped from
    the end when the text would be longer than limit. "" when the standard week cannot be written (the caller keeps
    the source's description as a note)."""
    if not operating:
        return ""
    first = operating[0] or {}
    base = nps_week(first.get("standardHours") or {})
    if not base or base == "off":
        return ""
    today = today or datetime.date.today()
    rules = [base]
    for ex in first.get("exceptions") or []:
        start, end = _date_text(ex.get("startDate")), _date_text(ex.get("endDate"))
        if not start or not end:
            continue
        try:
            if datetime.date.fromisoformat(ex["endDate"][:10]) < today:
                continue                                # already over
        except ValueError:
            continue
        week = nps_week(ex.get("exceptionHours") or {})
        if not week:
            continue
        span = start if start == end else f"{start}-{end}"
        if week == "off":
            rules.append(f"{span} off")
        else:
            # "Mo-Fr 09:00-12:00; Sa,Su off" inside a date range: each rule of the week gets the range.
            rules.extend(f"{span} {r}" for r in week.split("; "))
    while len("; ".join(rules)) > limit and len(rules) > 1:
        rules.pop()
    text = "; ".join(rules)
    return text if len(text) <= limit else ""


def _days_in(text):
    """The days a text names ("Monday - Friday" -> Mo..Fr, "daily" -> every day, "weekends" -> Sa, Su), or None
    when it names none."""
    m = _DAY_RANGE.search(text)
    if m:
        a, b = DAY_WORDS[m.group(1).lower()[:3]], DAY_WORDS[m.group(2).lower()[:3]]
        i, j = DAYS.index(a), DAYS.index(b)
        return [DAYS[k % 7] for k in range(i, j + 1 if j >= i else j + 8)]
    low = text.lower()
    if re.search(r"\b(daily|every day|7 days a week|seven days a week)\b", low):
        return list(DAYS)
    if re.search(r"\bweekdays\b", low):
        return list(DAYS[:5])
    if re.search(r"\bweekends?\b", low):
        return ["Sa", "Su"]
    return None


def from_text(text):
    """OpenStreetMap hours from a short sentence of a recreation site's hours, only in the plain cases: "24/7" or
    "open 24 hours"; "sunrise to sunset"; one time range with or without a day range ("Monday - Friday, 8:00 a.m.-
    4:30 p.m." -> "Mo-Fr 08:00-16:30"; "Day use hours are 6 am to 10 pm" -> "06:00-22:00"). Quiet hours,
    check-in times and anything with more than one range are "" (the text stays a note)."""
    t = plain_text(text)
    if not t or len(t) > 160 or NOT_OPENING.search(t):
        return ""
    low = t.lower()
    if re.fullmatch(r"(open\s+)?(24/7|24 hours( a day)?(,? 7 days a week)?|24 hours, 7 days)\.?", low):
        return "24/7"
    if re.fullmatch(r"(open\s+)?(daily\s+)?(from\s+)?(sunrise|dawn)\s*(-|–|to|until)\s*(sunset|dusk)\.?(\s*daily\.?)?",
                    low):
        return "sunrise-sunset"
    spans = list(_RANGE.finditer(t))
    if len(spans) != 1:
        return ""
    m = spans[0]
    a, b = _clock(*m.groups()[:5]), _clock(*m.groups()[5:], closing=True)
    if not a or not b:
        return ""
    days = _days_in(t)
    # Only a few connecting words may be left besides the days and the times.
    rest = _DAY_RANGE.sub(" ", t.replace(m.group(0), " "))
    rest = re.sub(r"\b(open|opens|hours?|are|is|day[- ]use|daily|every day|weekdays|weekends?|from|of|operation|"
                  r"operating|the|site|area|eastern|central|mountain|pacific|alaska|time|unless otherwise posted|"
                  r"seven days a week|7 days a week)\b|[,.:;()]", " ", rest, flags=re.I)
    if rest.strip():
        return ""
    return f"{_day_list(days)} {a}-{b}" if days and len(days) < 7 else (f"Mo-Su {a}-{b}" if days else f"{a}-{b}")
