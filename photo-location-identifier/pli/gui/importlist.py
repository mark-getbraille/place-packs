"""The "Import places from a list" window (opened from My places): paste a list copied from a chat, a web page or a
spreadsheet, or open a file (CSV, tab-separated text, Excel .xlsx, a SQLite database or a .sql file); the program
finds each place's position on this computer (pli/placelist.py: the position in the list, else the address in the
place packs, else the name in its town), then shows what it found before anything is added:

  "1,234 places found; 1,100 located; 134 could not be located; 20 duplicates of My places"

with a review list ("name — address — located" or "not located: why") and a short report of the places that could
not be located. Import adds the located places to My places as one list, under the name typed in "Name for this
list" (a pasted list is "Pasted list" and the date unless you type another), so "Remove places from a list" in My
places can take them all away again. These places stay on this computer only.

Controls, in Tab order: Paste a list (Alt+P), Find the places (Alt+F), Open a file instead (Alt+O), Name for this
list (Alt+N), Summary, Review the places found (Alt+R), Import (Alt+I), Cancel (Alt+C or Escape). F1 opens the
manual's "Import places from a list" part. Reading and locating run in the background in the progress window
(percent in its title, spoken every 10 percent; Stop ends it early).
"""

import os

import wx

from pli import APP_NAME, placelist
from pli import settings as pli_settings
from pli.gui import access
from pli.gui.progress import ProgressWindow

REVIEW_LIMIT = 5000             # lines in the review list (the counts in the summary cover every row)
FILE_WILDCARD = ("Lists of places (*.csv;*.tsv;*.txt;*.xlsx;*.db;*.sqlite;*.sqlite3;*.sql)|"
                 "*.csv;*.tsv;*.txt;*.xlsx;*.db;*.sqlite;*.sqlite3;*.sql|CSV or text (*.csv;*.tsv;*.txt)|"
                 "*.csv;*.tsv;*.txt|Excel workbook (*.xlsx)|*.xlsx|SQLite database (*.db;*.sqlite;*.sqlite3)|"
                 "*.db;*.sqlite;*.sqlite3|SQL statements (*.sql)|*.sql|All files|*.*")
PRIVACY = "These places stay on this computer only."


def choose_one(parent, prompt, title, choices):
    """Ask the user to choose one of choices (a standard list window); returns its index, or None for Cancel."""
    with wx.SingleChoiceDialog(parent, prompt, f"{title} - {APP_NAME}", choices) as dlg:
        if dlg.ShowModal() != wx.ID_OK:
            return None
        return dlg.GetSelection()


class ImportListWindow(wx.Dialog):
    """See the module docstring. places: myplaces.MyPlaces (saved on Import); finder: a places.Places (for the
    packs folder and pack downloads; None: one made for places); pack_mode: "ask", "auto" or "never" (None: the
    saved setting). Ends with wx.ID_OK after Import, wx.ID_CANCEL otherwise."""

    def __init__(self, parent, places, finder=None, pack_mode=None):
        """Make the window."""
        super().__init__(parent, title=f"Import places from a list - {APP_NAME}", size=(760, 680),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        from pli.places import Places
        self.places = places
        self.finder = finder or Places(my_places=places)
        self.pack_mode = pack_mode or pli_settings.load().get("packs", "ask")
        self.rows = []
        self.file, self.table = None, None
        self.busy = None
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(panel, label="Add businesses, schools or other places from a list. Paste the list "
                                           "(a table or a list from a chat answer works), or open a file. Pictures "
                                           "taken within 60 metres of one of these places get its name. " + PRIVACY)
        intro.Wrap(720)
        s.Add(intro, 0, wx.ALL, 8)
        self.text = access.labelled(panel, s, "&Paste a list (copied from a chat, a web page or a spreadsheet):",
                                    lambda: wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.HSCROLL, size=(-1, 150)),
                                    proportion=1)
        row = wx.BoxSizer(wx.HORIZONTAL)
        s.Add(row, 0, wx.LEFT | wx.RIGHT, 4)
        self.find_btn = access.button(panel, row, "&Find the places", "Read the pasted list and find where each "
                                      "place is, before anything is added", self.on_find)
        access.button(panel, row, "&Open a file instead...", "Read a CSV, Excel, SQLite database or .sql file",
                      self.on_open)
        self.name = access.labelled(panel, s, "&Name for this list (to remove it later):",
                                    lambda: wx.TextCtrl(panel, value=placelist.default_list_name()))
        self.summary = access.labelled(panel, s, "Summary:", lambda: wx.TextCtrl(
            panel, value="Paste a list and choose Find the places (Alt+F), or Open a file instead (Alt+O).",
            style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 90)))
        self.review = access.labelled(panel, s, "&Review the places found:",
                                      lambda: wx.ListBox(panel, style=wx.LB_SINGLE, size=(-1, 160)), proportion=1)
        row = wx.BoxSizer(wx.HORIZONTAL)
        s.Add(row, 0, wx.LEFT | wx.RIGHT, 4)
        self.import_btn = access.button(panel, row, "&Import", "Add the located places to My places as one list",
                                        self.on_import)
        access.button(panel, row, "&Cancel", "Close without adding anything (Escape)", self.on_cancel)
        panel.SetSizer(s)
        self.import_btn.Disable()
        access.install_keys(self, "import-list", on_escape=self.on_cancel)
        self.text.SetFocus()

    # ------------------------------------------------------------ reading and locating

    def on_find(self):
        """Find the places of the pasted text."""
        text = self.text.GetValue()
        if not text.strip():
            access.message(self, "Paste a list into the box first (Alt+P), or choose Open a file instead (Alt+O).",
                           "Import places from a list", wx.OK | wx.ICON_WARNING)
            self.text.SetFocus()
            return
        self.file, self.table = None, None
        self.start(lambda progress, stop: placelist.parse_pasted(text))

    def on_open(self):
        """Open a file of places (choosing the table of a database that has several)."""
        with wx.FileDialog(self, "Open a list of places", wildcard=FILE_WILDCARD,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            path = dlg.GetPath()
        self.open_path(path)

    def open_path(self, path):
        """Read the file at path (see on_open). Returns False if it cannot be read."""
        table = None
        low = path.lower()
        if low.endswith(placelist.SQLITE_ENDINGS + (".sql",)) or placelist.is_sqlite_file(path):
            try:
                tables = placelist.sqlite_tables(path)
            except (ValueError, OSError) as e:
                access.message(self, str(e), "Import places from a list", wx.OK | wx.ICON_WARNING)
                return False
            if not tables:
                access.message(self, "No table of this database has a name column and an address or position "
                                     "column (such as name, street, city, state, zip, latitude, longitude).",
                               "Import places from a list", wx.OK | wx.ICON_WARNING)
                return False
            table = tables[0]
            if len(tables) > 1:
                i = choose_one(self, "This database has several tables of places. Choose the table to import:",
                               "Choose a table", [t.label() for t in tables])
                if i is None:
                    return False
                table = tables[i]
        self.file, self.table = path, (table.name if table else None)
        name = os.path.basename(path) + (f", {self.table}" if table and len(self.table) < 40 and
                                         not low.endswith(".sql") and self.table != placelist.EXPORT_TABLE else "")
        self.name.SetValue(name)

        def read(progress, stop):
            out = []
            for k, row in enumerate(placelist.read_file(path, self.table, progress=lambda d, t: progress(
                    "Reading the list", d, t))):
                out.append(row)
                if k % 1000 == 0 and stop():
                    break
            return out
        self.start(read)
        return True

    def start(self, read):
        """Read the rows (read(progress, stop) -> [Row]) and locate them in the background, with the progress window."""
        places, finder, mode = self.places, self.finder, self.pack_mode

        def work(progress, stop, ask):
            progress("Reading the list")
            rows = read(progress, stop)
            folder = finder.packs_folder or finder.default_packs_folder()
            locator = placelist.Locator(folder)
            needed = locator.regions_needed(rows)
            missing = {rid: n for rid, n in needed.items() if rid not in locator.packs}
            if missing and not stop():
                progress("Getting the place packs needed")
                finder.get_region_packs(missing, mode, ask=lambda label, size, count: ask(
                    lambda: self.ask_pack(label, size, count)))
                locator = placelist.Locator(folder)
            if not stop():
                locator.locate(rows, progress=progress, stop=stop)
            placelist.find_duplicates(rows, places.existing())
            return rows
        self.find_btn.Disable()
        self.import_btn.Disable()
        self.busy = ProgressWindow(self, "Finding the places", work, self.on_found)
        self.busy.Show()

    def ask_pack(self, label, size, count):
        """The pack question (in the window thread): True to download."""
        mb = f"{size / 1e6:.0f} MB" if size else "a few megabytes"
        return access.message(self, f"{count} places of the list are in {label}. To find their addresses, the free "
                                    f"place pack for {label} ({mb}) is needed. Download it now? Only the pack is "
                                    f"downloaded; nothing of your list is sent.", "Download a place pack",
                              wx.YES_NO | wx.ICON_QUESTION) == wx.YES

    def on_found(self, rows, error):
        """The list was read and located: show the summary and the review list."""
        self.busy = None
        if not self:
            return
        self.find_btn.Enable()
        if error is not None:
            self.rows = []
            self.summary.SetValue(f"The list could not be read: {error}")
            access.announce(self, f"The list could not be read: {error}")
            return
        self.show_rows(rows or [])

    def show_rows(self, rows):
        """Fill the summary and the review list (the places that could not be located first)."""
        self.rows = rows
        if not rows:
            text = ("No places were found in the list. A place needs a name and an address (such as 123 Main St, "
                    "Springfield, IL 62701), or a latitude and longitude.")
            self.summary.SetValue(text)
            self.review.Set([])
            self.import_btn.Disable()
            access.announce(self, text)
            return
        head = placelist.summary_text(rows) + "."
        counts = placelist.summary(rows)
        lines = [head, "Check the list below, then choose Import (Alt+I) to add the located places, or Cancel. "
                 + PRIVACY]
        report = placelist.report_lines(rows, limit=100)
        if report:
            lines += ["", "Could not be located:"] + report
        self.summary.SetValue("\n".join(lines))
        order = {"not located": 0, "duplicate": 1}
        shown = sorted(rows, key=lambda r: order.get(r.status, 2))[:REVIEW_LIMIT]
        items = [r.line() for r in shown]
        if len(rows) > REVIEW_LIMIT:
            items.append(f"... and {len(rows) - REVIEW_LIMIT:,} more (counted in the summary)")
        self.review.Set(items)
        if items:
            self.review.SetSelection(0)
        self.import_btn.Enable(counts["located"] > 0)
        access.announce(self, head)
        self.review.SetFocus()

    # ------------------------------------------------------------ import and cancel

    def on_import(self):
        """Add the located places to My places under the list's name, save, and close."""
        source = " ".join(self.name.GetValue().split()) or placelist.default_list_name()
        if any(source == s for s, _n in self.places.list_names()) and access.message(
                self, f"There is already a list called {source}. Add these places to it?", "Import places",
                wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            self.name.SetFocus()
            return
        added = self.places.add_list(source, self.rows)
        self.places.save()
        self.added, self.source = added, source
        access.announce(self, f"Imported {added:,} places as the list {source}")
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.SetReturnCode(wx.ID_OK)
            self.Destroy()

    def on_cancel(self):
        """Cancel (or Escape): stop a search that is running, or close without adding anything."""
        if self.busy is not None:
            self.busy.on_stop()
            return
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.SetReturnCode(wx.ID_CANCEL)
            self.Destroy()
