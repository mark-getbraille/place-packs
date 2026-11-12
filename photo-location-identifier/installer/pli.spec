# PyInstaller build of Photo Location Identifier (a folder, not one file: it starts faster and its parts stay
# replaceable). Run from the photo-location-identifier folder:   pyinstaller installer/pli.spec
# The result is dist/PhotoLocationIdentifier/ with PhotoLocationIdentifier.exe, which the Inno Setup script packs.
# Bundled: the program (pli), placepacks' reading, lookup and download parts (not its pack builder and its readers),
# placepacks' regions list, type phrases (types.json) and water layer, the manual, the licences, and the licence
# files of wxPython, Pillow and openpyxl (with et_xmlfile).

import glob
import os
from importlib import metadata

HERE = os.path.abspath(os.path.join(SPECPATH, ".."))           # noqa: F821 - SPECPATH is given by PyInstaller
REPO = os.path.dirname(HERE)

datas = [
    (os.path.join(HERE, "docs", "manual.html"), "docs"),
    (os.path.join(HERE, "docs", "manual.txt"), "docs"),
    (os.path.join(HERE, "LICENSES.txt"), "."),
    (os.path.join(REPO, "placepacks", "regions.json"), "placepacks"),
    # The fine place types: lookup.py asks types.most_specific, which reads it, for every place with a type.
    (os.path.join(REPO, "placepacks", "types.json"), "placepacks"),
]
datas += [(f, "placepacks/data") for f in glob.glob(os.path.join(REPO, "placepacks", "data", "*"))]

# The licence files of the bundled libraries, from their installed package details.
for dist in ("wxPython", "pillow", "openpyxl", "et_xmlfile", "pyinstaller"):
    try:
        for f in metadata.distribution(dist).files or []:
            name = os.path.basename(str(f)).upper()
            if name.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                datas.append((str(f.locate()), os.path.join("third-party-licences", dist)))
    except metadata.PackageNotFoundError:
        pass
try:                                    # wxPython also keeps its licence inside the wx package
    import wx as _wx
    for f in glob.glob(os.path.join(os.path.dirname(_wx.__file__), "*icen[cs]e*")):
        datas.append((f, os.path.join("third-party-licences", "wxPython")))
except ImportError:
    pass

hiddenimports = ["placepacks.lookup", "placepacks.regions", "placepacks.when", "placepacks.water",
                 "placepacks.download", "placepacks.manifest", "placepacks.fmt", "placepacks.types"]

a = Analysis(                                                     # noqa: F821
    [os.path.join(HERE, "run_pli.py")],
    pathex=[HERE, REPO],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["placepacks.build", "placepacks.fetch", "placepacks.readers", "placepacks.writer", "duckdb", "osmium",
              "numpy", "matplotlib", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)                                                 # noqa: F821
exe = EXE(                                                        # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PhotoLocationIdentifier",
    console=False,
    version=os.path.join(HERE, "installer", "version_info.txt"),
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PhotoLocationIdentifier")   # noqa: F821
