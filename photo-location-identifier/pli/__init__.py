"""Photo Location Identifier: sort a folder of pictures into folders named by where (and when) they were taken.

Everything runs on this computer. The only internet use is downloading free place packs (place names from
OpenStreetMap and other open data) from the place-packs project's public releases, and no photo data is sent.

Modules:
  photos     read the location, date and height from pictures (and from videos when ffprobe is installed)
  places     the adapter to the placepacks package (place names at each level, water and air, pack downloads)
  myplaces   the user's own names for places ("Grandma's house" within 200 metres), and places from lists
  placelist  Import places from a list: pasted lists, CSV, Excel, SQLite and .sql files, offline address finding
  grouping   trips, guessing places by time, naming each trip by its area, folder-name templates: the plan
  naming     new picture names with the exact place ("Put the exact place in each picture's name")
  sorter     moving or copying (and renaming) the files, the report, and undoing the last sort
  settings   the saved choices
  cli        the command line (and the start of the program)
  gui        the windows
"""

__version__ = "1.3.1"
APP_NAME = "Photo Location Identifier"
PUBLISHER = "Company Maker, LLC"
