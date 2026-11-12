"""When a picture was taken, for choosing the names that were valid then (lookup.Finder).

When.parse accepts:
  None                          no date: the newest names, said "as listed now"
  202611 (YYYYMM), a date or datetime, "2026-11", "2026-11-03T10:00"   one month (certain)
  When(start, end, certain=False)                                     a month or span that is less sure (a file's
                                                                      date instead of the camera's)
  (1950, 1960) years, (195001, 196012) months, or (date, date)       a span (an estimated date): names valid
                                                                      at any time in it, said "probably"
Months are YYYYMM numbers.
"""

import datetime

from placepacks import fmt


class When:
    """start, end: YYYYMM (None, None for no date); certain: the camera's own date; kind: "exact",
    "approximate", "range" or "none"."""

    def __init__(self, start=None, end=None, certain=True, kind=None):
        """start and end: YYYYMM months (end defaults to start); certain: False for an approximate date; kind:
        given, or worked out from start and certain."""
        self.start, self.end = start, end if end is not None else start
        self.certain = certain and start is not None
        self.kind = kind or ("none" if start is None else ("exact" if certain else "approximate"))

    @classmethod
    def parse(cls, value):
        """A When from any of the forms in the module docstring."""
        if isinstance(value, When):
            return value
        if value is None:
            return cls()
        if isinstance(value, datetime.datetime):
            value = value.date()
        if isinstance(value, datetime.date):
            m = value.year * 100 + value.month
            return cls(m, m)
        if isinstance(value, int):
            m = value * 100 + 1 if value < 10000 else value
            return cls(m, m if value >= 10000 else value * 100 + 12)
        if isinstance(value, str):
            m = fmt.parse_month(value)
            return cls(m, m) if m else cls()
        if isinstance(value, (tuple, list)) and len(value) == 2:
            def month(v, last):
                """A YYYYMM from a date, a datetime, a year or a YYYYMM (a year: its first or last month)."""
                if isinstance(v, datetime.datetime):
                    v = v.date()
                if isinstance(v, datetime.date):
                    return v.year * 100 + v.month
                v = int(v)
                return v * 100 + (12 if last else 1) if v < 10000 else v
            start, end = month(value[0], False), month(value[1], True)
            return cls(min(start, end), max(start, end), certain=False, kind="range")
        raise ValueError(f"not a date: {value!r}")

    @property
    def is_range(self):
        """True for an estimated span (names are said "probably")."""
        return self.kind == "range"

    @property
    def known(self):
        """True when there is a date at all."""
        return self.start is not None

    def text(self):
        """"November 2026", "1950 to 1960", or "" for no date."""
        if not self.known:
            return ""
        from placepacks.fmt import year_text
        if self.is_range:
            a, b = year_text(self.start // 100), year_text(self.end // 100)
            return f"{a} to {b}" if a != b else a
        import calendar
        return f"{calendar.month_name[self.start % 100]} {year_text(self.start // 100)}"

    def __repr__(self):
        """A short form for test messages."""
        return f"When({self.start}, {self.end}, {self.kind})"
