"""New picture names with the exact place ("Put the exact place in each picture's name"): the folder keeps the
broad place ("Outer Banks 2005"), and each picture's name gets the most specific place known for it.

  exact_place(spot, folder)                     the words for the place in the name, or "" (see the order below)
  wanted_stem(photo, folder, pattern, ...)      the new name (without its ending), or None to keep the old name
  is_named(stem, wanted)                        True if a name is already the wanted one (a second sort leaves it)

The place in the name, the first of these that is known and that the folder's name does not already say:
  1. one of My places ("Grandma's house");
  2. a named business, landmark, park, school or building at the point, as it was named on the photo's date (the
     place packs keep the history of names);
  3. the street address ("120 Main Street") or the street, with the town after a comma when the folder does not
     already name the town ("120 Main Street, Nags Head" in "Outer Banks 2005");
  4. the neighbourhood;
  5. the town or village ("Nags Head" alone is fine in "Outer Banks 2005");
  6. on water or in the air, the water description ("Off Martha's Vineyard", "Over the Pacific Ocean").
A picture keeps its name when nothing more specific than its folder is known, when it has no location, or when its
place was only guessed from photos taken around the same time.

The patterns (grouping.NAME_PATTERNS), with the old name kept in brackets so every picture can still be recognised:
  date-place-name   "2005-07-14 Jockey's Ridge State Park (IMG_1234).jpg"   (the default)
  place-date-name   "Jockey's Ridge State Park 2005-07-14 (IMG_1234).jpg"
  place-name        "Jockey's Ridge State Park (IMG_1234).jpg"

Names are safe for Windows: no < > : " / \\ | ? *, no dot or space at the end, not a reserved name (CON, NUL ...),
at most FILE_NAME_LIMIT characters, and the whole path stays under PATH_LIMIT characters (the place is shortened
first; if even that is not enough, the picture keeps its old name). Names already taken get " (2)", " (3)" ...
(sorter.free_name), and a picture's companion files (.AAE, .xmp, a Live Photo's video) get the same new name.
"""

import os
import re

from pli.grouping import BAD_CHARS, RESERVED, clean_part

FILE_NAME_LIMIT = 120         # the longest new file name made, its ending included
PATH_LIMIT = 240              # the whole path (folder and name) stays under this
NUMBER_ROOM = 6               # room kept for " (2)" ... " (99)" when a name is taken
MIN_PLACE = 8                 # a place shortened to fewer characters than this is not worth putting in the name


def _says(folder, text):
    """True if the folder's name already says text (whole words, any case): "Nags Head" in "Nags Head 2005"."""
    t = (text or "").strip().lower()
    return bool(t) and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", (folder or "").lower()) is not None


def exact_place(spot, folder="", narrow=False):
    """The words for the place in a picture's name (see the module docstring), cleaned for Windows; "" when nothing
    more specific than the folder's name is known. spot: places.Spot (None: nothing). narrow: the folder is named
    by a place smaller than a town (a park, one of My places), so the neighbourhood, the town and the water would be
    wider than the folder and are not used."""
    if spot is None:
        return ""
    town = clean_part(spot.town)
    street = clean_part(f"{spot.house_number} {spot.street}".strip() if spot.street else "")
    if street and town and not narrow and not _says(folder, town) and not _says(street, town):
        street = f"{street}, {town}"
    wider = () if narrow else (spot.neighbourhood, town, spot.water)
    for text in (spot.my_place, spot.name, street) + wider:
        text = clean_part(text)
        if text and not _says(folder, text):
            return text
    return ""


def _lead(place, date, pattern):
    """The part before the old name: "2005-07-14 Jockey's Ridge State Park" (the pattern's order)."""
    if pattern == "place-date-name":
        return f"{place} {date}".strip()
    if pattern == "place-name":
        return place
    return f"{date} {place}".strip()


def original_of(stem, lead):
    """The old name inside a name this program made before with the same lead: "2005-07-14 X (IMG_1)" -> "IMG_1"
    (so a second sort does not wrap it twice); stem itself otherwise."""
    m = re.fullmatch(re.escape(lead) + r" \((.+?)\)( \(\d+\))?", stem)
    return m.group(1) if m else stem


def _shorten(text, length):
    """text cut to at most length characters at a word, without a dot, comma or space at the end."""
    if len(text) <= length:
        return text
    cut = text[:length]
    if " " in cut and not text[length:length + 1] == " ":
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip(" .,-")


def _safe(stem):
    """A file name stem safe for Windows: no characters it does not allow, no dot or space at the end, not a
    reserved name."""
    stem = re.sub(r"\s+", " ", BAD_CHARS.sub(" ", stem)).strip(" .")
    if stem.split(".")[0].strip().lower() in RESERVED:
        stem = "_" + stem
    return stem


def folder_is_narrow(group_place, info):
    """True if a folder named group_place is a place smaller than a town for a photo with this PlaceInfo: the
    photo's park or attraction ("Place" detail) or one of My places, and not its town."""
    g = (group_place or "").strip().lower()
    if not g or info is None or g == (info.town or "").strip().lower():
        return False
    return g in ((info.place or "").strip().lower(), (info.my_place or "").strip().lower())


def wanted_stem(photo, folder, pattern, target_dir="", endings=(), group_place=""):
    """The new name for photo (without its ending) in the folder named folder (the group's folder, which says the
    broad place) at target_dir, or None to keep the old name. endings: the companions' endings (".AAE"), so their
    names fit too. group_place: the place the folder was made for (to tell a park's folder from a town's)."""
    if photo.probably or getattr(photo, "info", None) is None or not photo.info.known:
        return None
    place = exact_place(getattr(photo, "spot", None), folder, folder_is_narrow(group_place, photo.info))
    if not place:
        return None
    name = os.path.basename(photo.path)
    stem, ext = os.path.splitext(name)
    date = f"{photo.taken:%Y-%m-%d}" if photo.taken is not None else ""
    longest = max([len(ext)] + [len(e) for e in endings])
    budget = FILE_NAME_LIMIT - longest
    if target_dir:
        budget = min(budget, PATH_LIMIT - len(os.path.abspath(target_dir)) - 1 - longest - NUMBER_ROOM)
    original = original_of(stem, _lead(place, date, pattern))
    new = _safe(f"{_lead(place, date, pattern)} ({original})")
    if len(new) > budget:
        room = budget - (len(new) - len(place))
        if room < MIN_PLACE:
            return None                 # no room even for a short place: keep the old name
        short = _shorten(place, room)
        if len(short) < MIN_PLACE // 2:
            return None
        original = original_of(stem, _lead(short, date, pattern))
        new = _safe(f"{_lead(short, date, pattern)} ({original})")
        if len(new) > budget:
            return None
    return None if new == stem else new


def is_named(stem, wanted):
    """True if stem is already the wanted name, or the wanted name with " (2)" ... (a name taken the first time)."""
    return stem.lower() == wanted.lower() or re.fullmatch(re.escape(wanted) + r" \(\d+\)", stem, re.IGNORECASE) \
        is not None
