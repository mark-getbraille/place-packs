"""Whether a place's name is a person's name ("Alice Example", "Jane Q. Doe Jr."), so that a one-person business or
an individual's own office gets no phone, website or hours (and, for All The Places, is left out).

A name counts as a person's only when it has the shape of one (two or three capitalised words, maybe an initial and
Jr/Sr/II/III) AND its first word is a first name from the US Census Bureau's lists (placepacks/data/first_names.txt,
public domain). The shape alone was too broad: "Golden Corral", "Muddy Waters" or "Lost Lake" are businesses and
places, not people. Only the Python standard library is used.
"""

import os
import re

_SHAPE = re.compile(r"^[A-Z][a-z]+(?: [A-Z]\.?)?(?: [A-Z][a-z'-]+){1,2}(?:,? (?:Jr|Sr|II|III)\.?)?$")
_NAMES = None


def first_names():
    """The set of first names (lower case), read once from placepacks/data/first_names.txt."""
    global _NAMES
    if _NAMES is None:
        path = os.path.join(os.path.dirname(__file__), "data", "first_names.txt")
        with open(path, encoding="utf-8") as f:
            _NAMES = {line.strip() for line in f if line.strip() and not line.startswith("#")}
    return _NAMES


class PersonName:
    """Used like a compiled pattern: PERSON.match(name) is true for a person's name (see the module docstring)."""

    def match(self, name):
        text = " ".join(str(name or "").split())
        return bool(_SHAPE.match(text)) and text.split(" ", 1)[0].lower() in first_names()


PERSON = PersonName()
