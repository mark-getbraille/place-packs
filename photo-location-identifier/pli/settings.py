"""The saved choices, and where the program keeps its own files.

The program's folder (home()): %APPDATA%\\Photo Location Identifier on Windows, ~/.config/photo-location-identifier
elsewhere, or PLI_HOME (the tests). In it:
  settings.json       the choices of the main window
  my places.json      My places
  undo\\               one undo file per sort (the newest one is "Undo the last sort")
  reports\\            a copy of each sort's report
"""

import json
import os

from pli import APP_NAME
from pli.grouping import DEFAULT_OPTIONS, NAME_PATTERNS

PACK_MODES = ("ask", "auto", "never")
# full_detail: also download the businesses and address points of each place pack ("Download full detail"); they are
# downloaded anyway when the exact place is put in the pictures' names.
DEFAULTS = {**DEFAULT_OPTIONS, "packs": "ask", "full_detail": False, "last_folder": "", "dest": ""}


def home():
    """The program's own folder (made if missing)."""
    path = os.environ.get("PLI_HOME")
    if not path:
        if os.name == "nt":
            path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
        else:
            path = os.path.join(os.path.expanduser("~"), ".config", "photo-location-identifier")
    os.makedirs(path, exist_ok=True)
    return path


def path_of(name):
    """A file or folder in the program's folder."""
    return os.path.join(home(), name)


def my_places_path():
    """Where My places are kept."""
    return path_of("my places.json")


def load():
    """The saved choices (DEFAULTS for any not saved, or when the file is missing or damaged)."""
    out = dict(DEFAULTS)
    try:
        with open(path_of("settings.json"), encoding="utf-8") as f:
            saved = json.load(f)
        out.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    if out.get("packs") not in PACK_MODES:
        out["packs"] = "ask"
    out["full_detail"] = bool(out.get("full_detail"))
    if out.get("name_pattern") not in NAME_PATTERNS:
        out["name_pattern"] = NAME_PATTERNS[0]
    return out


def save(values):
    """Save the choices (only the known ones)."""
    data = {k: values[k] for k in DEFAULTS if k in values}
    path = path_of("settings.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(path + ".tmp", path)
