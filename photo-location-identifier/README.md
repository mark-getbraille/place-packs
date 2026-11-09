# Photo Location Identifier

A free Windows program that sorts a folder of pictures into new folders named by **where** and **when** they were
taken. Point it at your photo album, and if your family goes to the Outer Banks every summer, you get "Outer Banks
2005", "Outer Banks 2006" and so on.

- **Right-click a folder** in File Explorer and choose **Sort pictures by location**. (On Windows 11 it is under
  "Show more options", or press Shift+F10.)
- **Choose how detailed:** trip area (smart), place, town, county, state or country; by year, year and month, or
  trip; and a pattern for the folder names, such as `{place} {year}` or `{year}\{place}`.
- **Check before anything moves:** a list of the new folders, with photo counts, dates and where each name came from.
  Rename or merge folders, then **Sort now**. **Undo the last sort** puts everything back.
- **My places:** your own names, such as "Grandma's house", come first.
- **Photos without a location** can stay where they are, go to "Unknown place", or be guessed from photos taken
  around the same time (marked "probably").
- **Made for screen readers:** every window works with NVDA and JAWS: labels on every field, Alt keys on every
  button, Escape to close, F1 for the manual, and progress announced as it goes.
- **Private:** everything runs on your computer. The only internet use is downloading the free place packs
  (OpenStreetMap and other open data, from this repository's releases), and only when you allow it. No photo data
  is ever sent.

Reads JPEG, PNG, TIFF, WebP, HEIC/HEIF, AVIF and most RAW files; videos too when ffprobe is installed.

## Download and install

Download `PhotoLocationIdentifier-1.0.0-setup.exe` from the release **photo-location-identifier-v1.0.0** on this
repository's Releases page and open it.

The installer is not signed with a paid certificate, so Windows **SmartScreen** may say "Windows protected your PC".
Choose **More info**, then **Run anyway**.

The full manual is in [docs/MANUAL.md](docs/MANUAL.md) (press F1 in the program).

## Command line

```
PhotoLocationIdentifier.exe --folder "D:\Photos" --detail trip-area --time year --template "{place} {year}" --dry-run
PhotoLocationIdentifier.exe --undo-last
```

See the manual's "Command line" part for every option.

## For developers

Python 3.12 and wxPython; the place lookups use the `placepacks` package one folder up in this repository.

```
pip install -r requirements-build.txt
python -m pli                                  # the program
python -m pytest tests                         # the tests (on Linux: xvfb-run -a python -m pytest tests)
python tools/make_manual.py                    # docs/manual.html and docs/manual.txt from docs/MANUAL.md
pyinstaller installer/pli.spec                 # then Inno Setup: ISCC installer\pli.iss
```

Layout:

- `pli/photos.py`: reads GPS, height and date (EXIF, HEIC boxes, RAW, videos via ffprobe)
- `pli/places.py`: the adapter to placepacks (names at every level, water and air, pack downloads)
- `pli/grouping.py`: trips, smart trip-area names, guessing by time, folder-name templates
- `pli/sorter.py`: move or copy, never overwrite, the report, the undo file
- `pli/gui/`: the windows; `pli/cli.py`: the command line
- `tools/make_test_pack.py`: a tiny made-up place pack for the tests and the installer's smoke test
- `installer/`: PyInstaller and Inno Setup; `.github/workflows/photo-location-identifier.yml` builds, tests,
  smoke-tests and publishes

Code under the MIT licence; see [LICENSES.txt](LICENSES.txt) for the parts it uses. Place names: (c) OpenStreetMap
contributors (ODbL) and the other open sources listed in the place packs.
