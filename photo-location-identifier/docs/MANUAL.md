# Photo Location Identifier manual {#top}

Photo Location Identifier sorts the pictures in a folder into new folders named by where they were taken, and
when. Point it at your photo album, and if your family goes to the Outer Banks every summer, it makes folders such
as "Outer Banks 2005" and "Outer Banks 2006".

It uses the location your camera or phone saved in each picture (its GPS position). Nothing is moved until you have
checked the new folders, and "Undo the last sort" puts everything back.

Version 1.1.0. Free software under the MIT licence, made by Company Maker, LLC.

## Installing {#installing}

1. Download "PhotoLocationIdentifier-1.1.0-setup.exe" from the program's release page on GitHub
   (github.com/mark-getbraille/place-packs, Releases, "photo-location-identifier-v1.1.0").
2. Open it. Windows may show "Windows protected your PC" (SmartScreen), because the program is new and not
   signed with a paid certificate. Choose "More info", then "Run anyway".
3. Follow the installer. Its progress is read by NVDA and JAWS.

The installer adds "Sort pictures by location" to File Explorer's menu for folders, a Start menu entry and a desktop
shortcut.

On Windows 11 the folder menu entry is under "Show more options" (or press Shift+F10 instead of the Applications
key).

## Starting {#starting}

- In File Explorer, select a folder of pictures (or open it), press the Applications key (or Shift+F10), and choose
  "Sort pictures by location". The program opens on that folder with the focus on "Look at the pictures".
- Or start "Photo Location Identifier" from the Start menu or the desktop and choose the folder with Browse.

## The main window {#main}

Every choice has a label, and the underlined letter is its Alt key.

- **Folder of pictures (Alt+F):** the folder to sort. **Browse (Alt+B)** chooses it.
- **Include subfolders (Alt+S):** also sort the pictures in the folders inside it.
- **Place detail (Alt+D):** how specific the place names are.
  - *Trip area (smart)*, the default: each trip is named by the area around it. A week spent in Duck, Kitty Hawk
    and Nags Head is "Outer Banks", not three towns. See "How trip areas are named" below.
  - *Place*: the park, attraction or building, such as "Jockey's Ridge State Park" (or the town when there is no
    named place).
  - *Town or city*, *County or region*, *State or province*, *Country*.
- **Time (Alt+T):**
  - *None*: one folder for each place, all years together.
  - *Year*, the default: "Outer Banks 2005", "Outer Banks 2006".
  - *Year and month*.
  - *Trip*: each trip separately, with its dates.
- **Folder names (Alt+N):** a pattern for the names. Choose one or type your own:
  - `{place} {year}` (the default): "Outer Banks 2005";
  - `{year}\{place}`: a folder for each year with the places inside it;
  - `{place}\{year}`: a folder for each place with the years inside it;
  - `{year}-{month} {place}`: "2005-07 Outer Banks".

  You can use {place}, {year}, {month} (07), {monthname} (July), {day}, {dates} (the first and last date),
  {start}, {end}, {town}, {county}, {state} and {country}. A backslash (\\) makes a folder inside a folder.
  **Examples of folder names** shows what your pattern makes. If two folders would get the same name (for example
  the pattern has no year but Time is Year), the year or the dates are added so they stay apart.
- **Put the exact place in each picture's name (Alt+P):** off by default, because renaming your files is a bigger
  change than moving them. When it is on, the folder keeps the wider place ("Outer Banks 2005") and each picture's
  name gets the most specific place known for it: a shop, landmark, park, school or building where it was taken,
  with the name it had on the day the picture was taken; otherwise the street address or street (with the town
  when the folder does not already name it, such as "120 Main Street, Nags Head"); otherwise the neighbourhood or
  the village or town ("Nags Head" alone is fine in "Outer Banks 2005"); on the water or in the air, a description
  such as "Off Martha's Vineyard". The folder's own place is never repeated in the name. Pictures without a
  location, pictures whose place was only guessed, and pictures where nothing more exact than the folder is known
  keep their names. You see every new name in the review before anything happens, and Undo puts the old names
  back.
- **Picture names (Alt+R):** the order of the new names. The old name always stays at the end in brackets, so you
  can still recognise each picture:
  - *Date, exact place, then the old name* (the default): "2005-07-14 Jockey's Ridge State Park (IMG_1234).jpg";
  - *Exact place, date, then the old name*: "Jockey's Ridge State Park 2005-07-14 (IMG_1234).jpg";
  - *Exact place and the old name*: "Jockey's Ridge State Park (IMG_1234).jpg".

  New names are always safe for Windows: characters Windows does not allow are left out, a long place is shortened
  so the whole name stays under 120 characters and the whole path under 240 (if even that does not fit, the
  picture keeps its name), and a name that is already taken gets " (2)". Files that belong to a picture (an .AAE
  or .xmp file, a Live Photo's video) get the same new name, and a RAW and JPEG pair stays a pair.
- **Start a new trip after this many days without photos (Alt+W):** 2 by default. If more than this many days pass
  between two photos, a new trip starts.
- **Also start a new trip when the place changes (Alt+H):** for road trips: a new trip begins when you move on.
- **Move or copy (Alt+M):** *Move* (the default, can be undone) or *Copy* (the originals stay where they are).
- **Photos without a location (Alt+O):** *Leave them where they are*; *Put them in a folder called "Unknown
  place"*; or *Guess from photos taken around the same time*. A guess uses a photo with a location taken on the
  same day within 3 hours, and is marked "probably" in the review and the report. Photos whose only date is the
  file's own date are never guessed, because copying a file can change that date.
- **New folders go in (Alt+I):** leave it empty to make the new folders inside the folder of pictures, or choose
  another folder with **Choose where they go (Alt+G)**. Useful with Copy.
- **Place packs downloads (Alt+K):** see "Place packs" below.
- **Look at the pictures (Alt+L):** reads every picture and shows the new folders in the review window. Nothing
  moves yet.
- **My places (Alt+Y)**, **Undo the last sort (Alt+U)**, **About (Alt+A)**, **Help (Alt+E or F1)**, **Close
  (Alt+C or Escape)**.

Your choices are remembered for next time. Enter only presses a button that has the focus; it never starts anything
from a field or a list.

## Progress {#progress}

Looking at the pictures, sorting and undoing run in the background in a progress window. Its title shows the
percent ("40% - Sorting"), and each new step and every 10 percent are announced by your screen reader. **Stop
(Alt+S or Escape)** stops after the file it is working on. A stopped sort can be undone completely.

## Reviewing the new folders {#review}

The review window lists every new folder, for example: "Outer Banks 2005: 42 photos, 2 to 9 July 2005, place from
the place packs (OpenStreetMap), 3 probably (place guessed from photos taken around the same time)".

- **New folders (Alt+N):** use the arrow keys. **Details of the chosen folder (Alt+D)** lists its photos with their
  dates.
- When "Put the exact place in each picture's name" is on, the text at the top says how many pictures get a new
  name, each folder in the list says how many of its pictures do ("12 with a new name", or "names kept"), and
  Details lists each picture as "old name → new name" (your screen reader may say "right arrow" between them).
  Renaming or merging a folder works the names out again, so they never repeat the folder's new name.
- **Rename folder (Alt+R):** type a better name ("Beach week 2005"). Characters Windows does not allow in names are
  left out.
- **Merge into another folder (Alt+M):** puts the chosen folder's photos into another folder from the list.
- **Sort now (Alt+S):** moves (or copies) the photos.
- **Cancel (Alt+C or Escape):** closes without moving anything.

After sorting, the program says how many photos went into how many folders and offers to open the report.

Files are never overwritten: if a name is already taken in a new folder, " (2)" is added. Files that belong to a
photo (an iPhone's .AAE edit file, an .xmp file, a Live Photo's short video) move with it and get the same name.

## The report and Undo {#undo}

Each sort writes a report ("Photo Location Identifier report" with the date and time) into the sorted folder. It
lists every new folder and its photos, the photos left where they were and why, any problems, and the sources of the
place names with their attributions.

When pictures got new names, the report says how many and lists each one as "old name → new name".

**Undo the last sort (Alt+U)** puts every file back where it was, with its old name, and removes the new folders once they are empty.
After a copy, Undo deletes the copies (a copy that was changed since is kept). A file you moved yourself after the
sort is left where it is and listed. The report stays, so you still have a record.

## How trip areas are named {#trip-areas}

1. If most of a trip's photos are in one of **My places**, that name is used.
2. If the trip is spread out (more than one town, or more than about 5 km), it is named by the smallest named area
   around most of its photos: an island chain such as the Outer Banks, an island, a region, a national park or
   seashore.
3. Otherwise it is named by its town. Outside any town, it is named by the named area around it.
4. Then on water or in the air ("Off Martha's Vineyard", "Over the Pacific Ocean"), then the county, state or
   country.

Then the whole album is checked so each area gets one name. If one summer you stayed only in Duck and another summer
you visited several Outer Banks towns, both trips become "Outer Banks". Trips that already share a name, such as
"Nags Head 2005" and "Nags Head 2006", keep it. You can always rename or merge folders in the review.

## My places {#my-places}

Your own names for places come first. A photo taken within the distance you choose of one of My places goes into a
folder with your name, such as "Grandma's house 2007". This works at the Trip area, Place and Town details.

- **My places (Alt+P):** the list.
- **Name (Alt+N)**, **Latitude (Alt+L)** and **Longitude (Alt+T):** in degrees, such as 36.0123 and -75.6789. You
  can paste both into Latitude ("36.0123, -75.6789") and they are split.
- **Within this many metres (Alt+M):** 200 by default.
- **Add or change (Alt+A):** adds the place, or changes the one with the same name. **Remove (Alt+R).**
- **Position from a picture (Alt+I):** fills in the position from a picture taken there.
- **Import (Alt+O)** and **Export (Alt+E):** a .json file, or a .csv file for spreadsheets with the columns name,
  latitude, longitude, metres.
- **Close (Alt+C or Escape)** saves.

## Place packs {#packs}

Place names come from free place packs (made from OpenStreetMap and other open data by this program's sister
project, place-packs). A pack covers one state, province or country region. They are downloaded only when needed,
from the project's public releases on GitHub.

**Place packs downloads (Alt+K):**

- *Ask me first, with the size* (the default): before downloading, the program says which region is needed, for how
  many photos, and its size.
- *Download automatically when needed.*
- *Never download*: use only the packs already on this computer. Photos in other regions are left where they are,
  or go to "Unknown place".

Packs you have downloaded work offline. Water and air descriptions ("Off Martha's Vineyard", "Over the Pacific
Ocean") need no pack.

## Privacy {#privacy}

Everything runs on your computer. The only internet use is downloading place packs, and only when you allow it. No
photo, position, file name or other detail of yours is ever sent. The program never changes a photo: it only moves
or copies files.

## What pictures can be read {#formats}

JPEG, PNG, TIFF, WebP, HEIC and HEIF (iPhone), AVIF, and most RAW files (DNG, CR2, CR3, NEF, ARW, ORF, RW2, PEF,
RAF and others). Only the details saved with the picture are read, so HEIC works without any extra Windows add-on.

Videos (MP4, MOV) are sorted only if the free program ffprobe (part of FFmpeg) is installed and on the PATH;
otherwise they stay where they are. A Live Photo's video always goes with its picture.

The date used is, best first: the date taken, the GPS date, a date in the file name (IMG_20050704_101500.jpg), and
last the file's own date.

## Command line {#command-line}

For power users and scripts (the program is installed in "%LOCALAPPDATA%\Programs\Photo Location Identifier", or "C:\Program Files\Photo Location Identifier" when installed for all users):

    PhotoLocationIdentifier.exe --folder "D:\Photos" --detail trip-area --time year --template "{place} {year}" --dry-run

- `--detail trip-area|place|town|county|state|country`, `--time none|year|month|trip`, `--template "..."`
- `--gap-days 2`, `--split-on-place`, `--copy` or `--move`, `--to FOLDER`
- `--rename` (put the exact place in each picture's name) or `--keep-names`; `--name-pattern
  date-place-name|place-date-name|place-name` chooses the order of the new names and turns renaming on
- `--unknown leave|unknown|guess`, `--guess-hours 3`, `--no-subfolders`, `--no-videos`
- `--packs ask|auto|never`, `--packs-folder FOLDER`, `--yes` (say yes to downloads), `--my-places FILE`
- `--dry-run` (show what would happen), `--report FILE`, `--undo-last`, `--version`

Options you leave out use the choices last saved in the main window.

## About and licences {#about}

**About (Alt+A)** shows the version, the licence, the privacy note and the sources of the place names. **Licences
(Alt+L)** opens the licences of the program and its parts.

Place names: (c) OpenStreetMap contributors, available under the Open Database License (ODbL). The place packs also
hold other open data; each source and its licence is listed in the report and in the place-packs project.

## Problems {#problems}

- **No new folders:** the pictures have no GPS location (many cameras without GPS, scans, pictures sent through some
  messaging apps), or the place pack for that region is not downloaded. Try "Guess from photos taken around the
  same time", or check "Place packs downloads".
- **The wrong area name:** rename the folder in the review, or add one of My places.
- **Windows says the publisher is unknown:** see "Installing" (SmartScreen).
