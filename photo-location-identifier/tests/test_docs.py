"""The manual: its HTML and text are made from MANUAL.md and up to date, and every part F1 opens exists."""

import os
import re

import make_manual

PROGRAM = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_manual_is_up_to_date():
    """docs/manual.html and docs/manual.txt match docs/MANUAL.md (run python tools/make_manual.py)."""
    assert make_manual.main(["--check"]) == 0


def test_every_f1_section_is_in_the_manual():
    """Each window's F1 section (install_keys and open_manual calls) is an anchor of the manual."""
    html = open(os.path.join(PROGRAM, "docs", "manual.html"), encoding="utf-8").read()
    anchors = set(re.findall(r'id="([\w-]+)"', html))
    used = set()
    for here, _, files in os.walk(os.path.join(PROGRAM, "pli", "gui")):
        for f in files:
            if f.endswith(".py"):
                text = open(os.path.join(here, f), encoding="utf-8").read()
                used |= set(re.findall(r'install_keys\(self, "([\w-]+)"', text))
                used |= set(re.findall(r'open_manual\("([\w-]+)"\)', text))
    assert used and used <= anchors, used - anchors


def test_licences_and_readme_name_the_parts():
    """LICENSES.txt covers the program and every bundled part; the README has the SmartScreen note."""
    lic = open(os.path.join(PROGRAM, "LICENSES.txt"), encoding="utf-8").read()
    for name in ("MIT License", "wxPython", "wxWindows Library Licence", "Pillow", "PyInstaller", "Inno Setup",
                 "Python Software Foundation", "pillow-heif", "OpenStreetMap", "Natural Earth"):
        assert name in lic, name
    readme = open(os.path.join(PROGRAM, "README.md"), encoding="utf-8").read()
    assert "SmartScreen" in readme and "Sort pictures by location" in readme
