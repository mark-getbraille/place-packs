"""The program's smaller windows:

  ReviewWindow     the new folders before anything moves: each with its photo count, dates and where its place
                   name came from (and, when pictures get the exact place in their names, how many, with each
                   picture's "old name → new name" in the details); Rename folder, Merge into another folder,
                   Sort now
  RenameWindow     type a folder's new name
  MergeWindow      choose the folder to merge the chosen one into
  MyPlacesWindow   your own names for places ("Grandma's house" within 200 metres), with import and export
  AboutWindow      the version, the licence, the privacy note and the place-name attributions

Every window follows access.py: labels ending in ":" before fields and lists, Alt keys on every button (named in the
tooltips), Escape closes, F1 opens the manual, Enter presses only the focused button.
"""

import os

import wx

from pli import APP_NAME, PUBLISHER, __version__, sorter
from pli import myplaces as mp
from pli.gui import access


def _row(sizer):
    """A row of buttons added to sizer."""
    row = wx.BoxSizer(wx.HORIZONTAL)
    sizer.Add(row, 0, wx.LEFT | wx.RIGHT, 4)
    return row


class ReviewWindow(wx.Dialog):
    """The review (see the module docstring). plan: grouping.Plan. Ends with wx.ID_OK when Sort now is pressed,
    wx.ID_CANCEL otherwise. dest: where the new folders go (for the intro text)."""

    def __init__(self, parent, plan, dest=None):
        """Make the window for plan."""
        super().__init__(parent, title=f"New folders - {APP_NAME}", size=(760, 600),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.plan, self.dest = plan, dest or plan.root
        self.names = {}                    # {id(photo): new file name or None}, from sorter.preview
        self.update_names()
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        self.intro = wx.StaticText(panel, label=self.intro_text())
        self.intro.Wrap(720)
        s.Add(self.intro, 0, wx.ALL, 8)
        self.folders = access.labelled(panel, s, "&New folders:", lambda: wx.ListBox(panel, style=wx.LB_SINGLE),
                                       proportion=1)
        self.details = access.labelled(panel, s, "&Details of the chosen folder:",
                                       lambda: wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY,
                                                           size=(-1, 150)))
        row = _row(s)
        self.rename_btn = access.button(panel, row, "&Rename folder...", "Type a new name for the chosen folder",
                                        self.on_rename)
        self.merge_btn = access.button(panel, row, "&Merge into another folder...",
                                       "Put the chosen folder's photos into another new folder", self.on_merge)
        row = _row(s)
        self.sort_btn = access.button(panel, row, "&Sort now", "Move or copy the photos into these folders",
                                      self.on_sort)
        self.cancel_btn = access.button(panel, row, "&Cancel", "Close without moving anything (Escape)",
                                        self.on_cancel)
        panel.SetSizer(s)
        self.folders.Bind(wx.EVT_LISTBOX, lambda e: self.show_details())
        access.install_keys(self, "review", on_escape=self.on_cancel)
        self.refresh(0)
        self.folders.SetFocus()

    def intro_text(self):
        """The sentence at the top: how many photos go into how many folders, and what stays."""
        p = self.plan
        verb = "copied" if p.options.get("mode") == "copy" else "moved"
        text = (f"{p.photo_count} photos will be {verb} into {len(p.groups)} new folders in {self.dest}. Nothing has "
                f"moved yet. Check the names, rename or merge folders if you like, then choose Sort now.")
        if p.options.get("rename"):
            n = self.renamed_count()
            text += (f" {n} picture{'s' if n != 1 else ''} will get a new name with the exact place; Details lists "
                     f"each old name and its new name." if n else
                     " No picture gets a new name: no place more exact than its folder's was found.")
        if p.left:
            text += f" {len(p.left)} photos stay where they are (the report lists them)."
        if p.problems:
            text += " " + " ".join(p.problems)
        return text

    def update_names(self):
        """Work out the new names again (after a rename or merge, the names change with the folder)."""
        self.names = sorter.preview(self.plan, self.dest) if self.plan.options.get("rename") else {}

    def new_name(self, photo):
        """The photo's new file name, or "" when it keeps its name."""
        new = self.names.get(id(photo))
        return new if new and new != os.path.basename(photo.path) else ""

    def renamed_count(self, group=None):
        """How many photos (of group, or of every folder) get a new name."""
        groups = [group] if group is not None else self.plan.groups
        return sum(1 for g in groups for p in g.photos if self.new_name(p))

    def row_text(self, g):
        """A folder's line in the list: its description and, when renaming, how many get a new name."""
        text = g.describe()
        if self.plan.options.get("rename"):
            n = self.renamed_count(g)
            text += f", {n} with a new name" if n else ", names kept"
        return text

    def chosen(self):
        """The Group chosen in the list, or None."""
        i = self.folders.GetSelection()
        return self.plan.groups[i] if 0 <= i < len(self.plan.groups) else None

    def refresh(self, select=None):
        """Fill the list again (after a rename or merge), choosing row select."""
        self.update_names()
        self.intro.SetLabel(self.intro_text())
        self.intro.Wrap(720)
        self.folders.Set([self.row_text(g) for g in self.plan.groups])
        if self.plan.groups:
            self.folders.SetSelection(max(0, min(select or 0, len(self.plan.groups) - 1)))
        self.show_details()
        has = bool(self.plan.groups)
        self.rename_btn.Enable(has)
        self.merge_btn.Enable(len(self.plan.groups) > 1)
        self.sort_btn.Enable(has)

    def show_details(self):
        """The chosen folder's photos, each with its date and how its place was found."""
        g = self.chosen()
        if g is None:
            self.details.SetValue("There are no new folders: no photo has a place that could be found.")
            return
        lines = [self.row_text(g), ""]
        for p in g.photos:
            bits = [f"{p.taken:%Y-%m-%d %H:%M}" if p.taken else "no date"]
            if p.probably:
                bits.append("probably here (guessed from a photo taken around the same time)")
            info = getattr(p, "info", None)
            if info is not None and info.known and not g.unknown:
                bits.append(info.name_at("place"))
            new = self.new_name(p)
            old = os.path.relpath(p.path, self.plan.root)
            lines.append((f"{old} → {new}" if new else old) + ": " + ", ".join(b for b in bits if b))
        self.details.SetValue("\n".join(lines))

    def on_rename(self):
        """Rename the chosen folder (RenameWindow)."""
        g = self.chosen()
        if g is None:
            return
        with RenameWindow(self, g.folder) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            name = dlg.value()
        try:
            new = self.plan.rename(g, name)
        except ValueError as e:
            access.message(self, str(e), "Rename folder", wx.OK | wx.ICON_WARNING)
            return
        self.refresh(self.plan.groups.index(g))
        access.announce(self, f"Renamed to {new}")

    def on_merge(self):
        """Merge the chosen folder into another one (MergeWindow)."""
        g = self.chosen()
        if g is None or len(self.plan.groups) < 2:
            return
        others = [x for x in self.plan.groups if x is not g]
        with MergeWindow(self, g.folder, [x.folder for x in others]) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            target = others[dlg.choice()]
        self.plan.merge(target, g)
        self.refresh(self.plan.groups.index(target))
        access.announce(self, f"Merged into {target.folder}, now {len(target.photos)} photos")

    def on_cancel(self):
        """Cancel (or Escape): close without sorting."""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.SetReturnCode(wx.ID_CANCEL)
            self.Destroy()

    def on_sort(self):
        """Sort now: end the review with OK."""
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.SetReturnCode(wx.ID_OK)
            self.Destroy()


class RenameWindow(wx.Dialog):
    """Type a new name for a folder. Ends with wx.ID_OK (Save) or wx.ID_CANCEL."""

    def __init__(self, parent, name):
        """name: the folder's name now."""
        super().__init__(parent, title=f"Rename folder - {APP_NAME}", size=(480, 200))
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        self.name = access.labelled(panel, s, "New folder &name (\\ for a folder inside a folder):",
                                    lambda: wx.TextCtrl(panel, value=name))
        row = _row(s)
        access.button(panel, row, "&Save", "Use this name", lambda: self.EndModal(wx.ID_OK))
        access.button(panel, row, "&Cancel", "Keep the old name (Escape)", lambda: self.EndModal(wx.ID_CANCEL))
        panel.SetSizer(s)
        access.install_keys(self, "review", on_escape=lambda: self.EndModal(wx.ID_CANCEL))
        self.name.SetFocus()
        self.name.SelectAll()

    def value(self):
        """The name typed."""
        return self.name.GetValue()


class MergeWindow(wx.Dialog):
    """Choose the folder to merge a folder into. Ends with wx.ID_OK (Merge) or wx.ID_CANCEL."""

    def __init__(self, parent, name, others):
        """name: the folder being merged; others: the names of the folders it can go into."""
        super().__init__(parent, title=f"Merge {name} - {APP_NAME}", size=(520, 360),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        self.list = access.labelled(panel, s, f"Put the photos of {name.replace('&', '&&')} &into:",
                                    lambda: wx.ListBox(panel, choices=others, style=wx.LB_SINGLE), proportion=1)
        if others:
            self.list.SetSelection(0)
        row = _row(s)
        access.button(panel, row, "&Merge", "Merge into the folder chosen", lambda: self.EndModal(wx.ID_OK))
        access.button(panel, row, "&Cancel", "Do not merge (Escape)", lambda: self.EndModal(wx.ID_CANCEL))
        panel.SetSizer(s)
        access.install_keys(self, "review", on_escape=lambda: self.EndModal(wx.ID_CANCEL))
        self.list.SetFocus()

    def choice(self):
        """The index of the folder chosen."""
        return max(0, self.list.GetSelection())


class MyPlacesWindow(wx.Dialog):
    """My places (see the module docstring). places: myplaces.MyPlaces (saved when the window closes).
    photo_reader(path) -> (lat, lon) or None: reads a picture's position (photos.read_photo by default)."""

    def __init__(self, parent, places, photo_reader=None):
        """Make the window for places."""
        super().__init__(parent, title=f"My places - {APP_NAME}", size=(620, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.places = places
        self.photo_reader = photo_reader or _photo_position
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(panel, label="Your own names for places come first: a photo taken within the distance "
                                           "you choose is put in a folder with your name, such as Grandma's house.")
        intro.Wrap(580)
        s.Add(intro, 0, wx.ALL, 8)
        self.list = access.labelled(panel, s, "My &places:", lambda: wx.ListBox(panel, style=wx.LB_SINGLE),
                                    proportion=1)
        self.name = access.labelled(panel, s, "&Name:", lambda: wx.TextCtrl(panel))
        self.lat = access.labelled(panel, s, "&Latitude (or paste both, such as 36.0123, -75.6789):",
                                   lambda: wx.TextCtrl(panel))
        self.lon = access.labelled(panel, s, "Longi&tude:", lambda: wx.TextCtrl(panel))
        self.radius = access.labelled(panel, s, "Within this many &metres:",
                                      lambda: wx.SpinCtrl(panel, min=10, max=50000, initial=mp.DEFAULT_RADIUS_M))
        row = _row(s)
        access.button(panel, row, "&Add or change", "Add this place, or change the one with the same name",
                      self.on_add)
        self.remove_btn = access.button(panel, row, "&Remove", "Remove the place chosen in the list", self.on_remove)
        access.button(panel, row, "Position from a p&icture...", "Fill in the position from a picture's GPS details",
                      self.on_from_photo)
        row = _row(s)
        access.button(panel, row, "Imp&ort...", "Add the places in a .json or .csv file", self.on_import)
        access.button(panel, row, "&Export...", "Save My places to a .json or .csv file", self.on_export)
        access.button(panel, row, "&Close", "Save My places and close (Escape)", self.on_close)
        panel.SetSizer(s)
        self.list.Bind(wx.EVT_LISTBOX, lambda e: self.on_select())
        self.lat.Bind(wx.EVT_TEXT, lambda e: self.on_lat_typed())
        self.Bind(wx.EVT_CLOSE, lambda e: self.on_close())
        access.install_keys(self, "my-places", on_escape=self.on_close)
        self.refresh()
        self.list.SetFocus()

    def refresh(self, select=None):
        """Fill the list again."""
        self.list.Set([p.describe() for p in self.places.places])
        if self.places.places:
            self.list.SetSelection(select if select is not None and 0 <= select < len(self.places.places) else 0)
            self.on_select()
        self.remove_btn.Enable(bool(self.places.places))

    def on_select(self):
        """Show the chosen place in the fields, to change it."""
        i = self.list.GetSelection()
        if 0 <= i < len(self.places.places):
            p = self.places.places[i]
            self.name.ChangeValue(p.name)
            self.lat.ChangeValue(f"{p.lat:.6f}")
            self.lon.ChangeValue(f"{p.lon:.6f}")
            self.radius.SetValue(int(p.radius_m))

    def on_lat_typed(self):
        """"36.0123, -75.6789" pasted into Latitude is split into the two fields."""
        text = self.lat.GetValue()
        if "," in text:
            a, b = text.split(",", 1)
            try:
                float(a), float(b)
            except ValueError:
                return
            self.lat.ChangeValue(a.strip())
            self.lon.ChangeValue(b.strip())

    def on_add(self):
        """Add (or change) the place in the fields."""
        try:
            place = mp.MyPlace(self.name.GetValue(), self.lat.GetValue(), self.lon.GetValue(),
                               self.radius.GetValue())
        except (ValueError, TypeError) as e:
            access.message(self, f"The place could not be added: {e}. Type a name, and the latitude and longitude "
                                 f"in degrees, such as 36.0123 and -75.6789.", "My places", wx.OK | wx.ICON_WARNING)
            return
        self.places.add(place)
        self.places.save()
        self.refresh(self.places.places.index(place))
        access.announce(self, f"Added {place.name}")

    def on_remove(self):
        """Remove the chosen place."""
        i = self.list.GetSelection()
        if 0 <= i < len(self.places.places):
            name = self.places.places[i].name
            self.places.remove(i)
            self.places.save()
            self.refresh(min(i, len(self.places.places) - 1))
            access.announce(self, f"Removed {name}")

    def on_from_photo(self):
        """Fill in the position from a picture."""
        with wx.FileDialog(self, "Choose a picture taken at the place", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
                           wildcard="Pictures|*.jpg;*.jpeg;*.heic;*.heif;*.png;*.tif;*.tiff;*.dng;*.webp|"
                                    "All files|*.*") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        pos = self.photo_reader(path)
        if not pos:
            access.message(self, "That picture has no GPS position.", "My places", wx.OK | wx.ICON_WARNING)
            return
        self.lat.ChangeValue(f"{pos[0]:.6f}")
        self.lon.ChangeValue(f"{pos[1]:.6f}")
        if not self.name.GetValue().strip():
            self.name.SetFocus()
        access.announce(self, f"Position {pos[0]:.5f}, {pos[1]:.5f} filled in; type a name and choose Add")

    def on_import(self):
        """Add the places in a file."""
        with wx.FileDialog(self, "Import My places", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
                           wildcard="My places (*.json;*.csv)|*.json;*.csv|All files|*.*") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        added, problems = self.places.import_file(path)
        self.places.save()
        self.refresh()
        text = f"Added {added} places."
        if problems:
            text += " Not added: " + "; ".join(problems[:10])
        access.message(self, text, "Import My places")

    def on_export(self):
        """Save the places to a file."""
        with wx.FileDialog(self, "Export My places", defaultFile="My places.json",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
                           wildcard="JSON (*.json)|*.json|CSV for spreadsheets (*.csv)|*.csv") as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self.places.export(path)
        access.announce(self, f"Saved {len(self.places.places)} places to {os.path.basename(path)}")

    def on_close(self):
        """Save and close."""
        self.places.save()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


def _photo_position(path):
    """(lat, lon) of a picture's GPS position, or None."""
    from pli import photos
    p = photos.read_photo(path)
    return (p.lat, p.lon) if p.location_source == "gps" else None


def about_text(attributions=()):
    """The text of the About window."""
    lines = [f"{APP_NAME} {__version__}", f"Made by {PUBLISHER}. Free software under the MIT licence.",
             "Source code: https://github.com/mark-getbraille/place-packs", "",
             "Privacy: everything runs on this computer. The only internet use is downloading place packs (free "
             "place-name files) from the place-packs project's public releases, and only when you allow it. No "
             "photo, position or other detail of yours is ever sent.", "",
             "Place names:",
             "© OpenStreetMap contributors. OpenStreetMap data is available under the Open Database License "
             "(ODbL) 1.0: https://www.openstreetmap.org/copyright",
             "The place packs also hold other open data (such as US Census TIGER/Line, Natural Earth and "
             "OurAirports); each source and its licence and attribution is listed in the place-packs project's "
             "SOURCES.md, and in the report of each sort."]
    lines += [f"  {a}" for a in attributions]
    lines += ["", "Made with Python, wxPython (wxWindows Library Licence), Pillow (HPND licence), PyInstaller and "
                  "Inno Setup. See Licences for the full texts."]
    return "\n".join(lines)


class AboutWindow(wx.Dialog):
    """About the program (see about_text)."""

    def __init__(self, parent, attributions=()):
        """Make the window."""
        super().__init__(parent, title=f"About - {APP_NAME}", size=(620, 480),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        self.text = access.labelled(panel, s, "&About:", lambda: wx.TextCtrl(
            panel, value=about_text(attributions), style=wx.TE_MULTILINE | wx.TE_READONLY), proportion=1)
        row = _row(s)
        access.button(panel, row, "&Licences", "Open the licences of the program and its parts", self.on_licences)
        access.button(panel, row, "&Close", "Close this window (Escape)", self.on_close)
        panel.SetSizer(s)
        access.install_keys(self, "about", on_escape=self.on_close)
        self.text.SetFocus()

    def on_licences(self):
        """Open LICENSES.txt."""
        path = access.resource("LICENSES.txt")
        access.MANUAL_OPENED.append("licences")
        if not os.environ.get("PLI_NO_BROWSER"):
            import webbrowser
            webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/").lstrip("/"))

    def on_close(self):
        """Close."""
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


# For the tests: every window of this module, made with test data.
def all_windows(parent, plan):
    """[window] of every window here (not shown)."""
    return [ReviewWindow(parent, plan), RenameWindow(parent, "Outer Banks 2005"),
            MergeWindow(parent, "Outer Banks 2005", ["Outer Banks 2006"]),
            MyPlacesWindow(parent, mp.MyPlaces([mp.MyPlace("Grandma's house", 36.0, -75.7)])), AboutWindow(parent)]

