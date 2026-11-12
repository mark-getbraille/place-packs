"""The main window: choose a folder and how to sort it, look at the pictures, review the new folders, sort.

Choices (each with a label ending in ":"; see grouping.py for what they do):
  Folder of pictures, Include subfolders
  Place detail:   Trip area (smart), Place, Town or city, County or region, State or province, Country
  Time:           None, Year, Year and month, Trip
  Folder names:   a template ("{place} {year}", "{year}\\{place}", "{place}\\{year}", "{year}-{month} {place}", or
                  your own), with examples of the names it makes
  Picture names:  "Put the exact place in each picture's name" (off by default) and the order of the new names
  Trips:          a new trip after this many days without photos; also when the place changes
  Move or copy, Photos without a location, New folders go in, Place packs downloads, and "Also download full
  detail: businesses and exact addresses" (off by default; they are downloaded anyway for the exact place)
Buttons: Look at the pictures (then the review window, then Sort now), My places, Undo the last sort, About, Help,
Close. The choices are saved for next time.
"""

import os

import wx

from pli import APP_NAME, grouping, job, myplaces, settings, sorter
from pli.gui import access
from pli.gui.dialogs import AboutWindow, MyPlacesWindow, ReviewWindow
from pli.gui.progress import ProgressWindow
from pli.places import Places

DETAIL_LABELS = ["Trip area (smart): each trip named by the area around it, such as Outer Banks",
                 "Place, such as a park or attraction",
                 "Town or city",
                 "County or region",
                 "State or province",
                 "Country"]
TIME_LABELS = ["None: one folder for each place",
               "Year",
               "Year and month",
               "Trip: each trip separately, with its dates"]
NAME_PATTERN_LABELS = ["Date, exact place, then the old name: 2005-07-14 Jockey's Ridge State Park (IMG_1234).jpg",
                       "Exact place, date, then the old name: Jockey's Ridge State Park 2005-07-14 (IMG_1234).jpg",
                       "Exact place and the old name: Jockey's Ridge State Park (IMG_1234).jpg"]
RENAME_TIP = ("Give each picture a new name with the most specific place known for it, such as a park, a shop or a "
              "street; the folder keeps the wider place, such as Outer Banks 2005. Off by default. You see every new "
              "name before anything happens, and Undo puts the old names back (Alt+P)")
MODE_LABELS = ["Move the photos (you can undo it)", "Copy the photos (the originals stay where they are)"]
MODES = ("move", "copy")
UNKNOWN_LABELS = ["Leave them where they are",
                  f"Put them in a folder called \"{grouping.UNKNOWN_FOLDER}\"",
                  "Guess from photos taken around the same time (marked \"probably\")"]
PACK_LABELS = ["Ask me first, with the size", "Download automatically when needed",
               "Never download (use only the packs already on this computer)"]
FULL_DETAIL_TIP = ("Also download each place pack's businesses and address points: bigger downloads, and more exact "
                   "places. They are downloaded anyway when the exact place is put in each picture's name. Off by "
                   "default (Alt+X)")
INTRO = ("Sorts the pictures in a folder into new folders named by where they were taken, and when: for example "
         "Outer Banks 2005 and Outer Banks 2006. It uses the location your camera or phone saved in each picture. "
         "Nothing moves until you have checked the new folders. Everything runs on this computer.")


class MainWindow(wx.Frame):
    """The main window (see the module docstring). folder: the folder to start with. places: a places.Places to
    use instead of the place packs (the tests)."""

    def __init__(self, folder="", places=None):
        """Make the window with the saved choices."""
        super().__init__(None, title=APP_NAME, size=(760, 940))
        self.saved = settings.load()
        self.places_override = places
        self.my_places = myplaces.MyPlaces.load(settings.my_places_path())
        self.plan = None
        self.outcome = None
        self.busy = None
        p = self.panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(p, label=INTRO)
        intro.Wrap(720)
        s.Add(intro, 0, wx.ALL, 8)
        self.folder = access.labelled(p, s, "&Folder of pictures:",
                                      lambda: wx.TextCtrl(p, value=folder or self.saved.get("last_folder", "")))
        row = wx.BoxSizer(wx.HORIZONTAL)
        access.button(p, row, "&Browse...", "Choose the folder of pictures", self.on_browse)
        s.Add(row, 0, wx.LEFT, 4)
        self.subfolders = access.check(p, s, "Include &subfolders, and the folders inside them",
                                       self.saved.get("subfolders", True))
        self.detail = access.labelled(p, s, "Place &detail:", lambda: wx.Choice(p, choices=DETAIL_LABELS))
        self.detail.SetSelection(grouping.DETAILS.index(self.saved.get("detail", "trip-area")))
        self.time = access.labelled(p, s, "&Time:", lambda: wx.Choice(p, choices=TIME_LABELS))
        self.time.SetSelection(grouping.TIMES.index(self.saved.get("time", "year")))
        self.template = access.labelled(p, s, "Folder &names (choose one, or type your own with {place}, {year}, "
                                              "{month}, {monthname}, {dates}, {state}, {country}; \\ for a folder "
                                              "inside a folder):",
                                        lambda: wx.ComboBox(p, value=self.saved.get("template", grouping.TEMPLATES[0]),
                                                            choices=list(grouping.TEMPLATES), style=wx.CB_DROPDOWN))
        self.examples = access.labelled(p, s, "Examples of folder names:",
                                        lambda: wx.TextCtrl(p, style=wx.TE_READONLY))
        self.rename = access.check(p, s, "&Put the exact place in each picture's name",
                                   self.saved.get("rename", False), tip=RENAME_TIP)
        self.name_pattern = access.labelled(p, s, "Pictu&re names (when the exact place is put in them):",
                                            lambda: wx.Choice(p, choices=NAME_PATTERN_LABELS))
        self.name_pattern.SetSelection(grouping.NAME_PATTERNS.index(
            self.saved.get("name_pattern", grouping.NAME_PATTERNS[0])))
        self.gap = access.labelled(p, s, "Start a new trip after this many days &without photos:",
                                   lambda: wx.SpinCtrl(p, min=0, max=365,
                                                       initial=int(self.saved.get("gap_days", 2))))
        self.split = access.check(p, s, "Also start a new trip when the place c&hanges",
                                  self.saved.get("split_on_place", False))
        self.mode = access.labelled(p, s, "&Move or copy:", lambda: wx.Choice(p, choices=MODE_LABELS))
        self.mode.SetSelection(MODES.index(self.saved.get("mode", "move")))
        self.unknown = access.labelled(p, s, "Photos with&out a location:",
                                       lambda: wx.Choice(p, choices=UNKNOWN_LABELS))
        self.unknown.SetSelection(grouping.UNKNOWN_CHOICES.index(self.saved.get("unknown", "leave")))
        self.dest = access.labelled(p, s, "New folders go &in (leave empty for the folder of pictures itself):",
                                    lambda: wx.TextCtrl(p, value=self.saved.get("dest", "")))
        row = wx.BoxSizer(wx.HORIZONTAL)
        access.button(p, row, "Choose where they &go...", "Choose another folder for the new folders",
                      self.on_browse_dest)
        s.Add(row, 0, wx.LEFT, 4)
        self.packs = access.labelled(p, s, "Place pac&ks downloads:", lambda: wx.Choice(p, choices=PACK_LABELS))
        self.packs.SetSelection(settings.PACK_MODES.index(self.saved.get("packs", "ask")))
        self.full_detail = access.check(p, s, "Also download full detail: businesses and e&xact addresses",
                                        self.saved.get("full_detail", False), tip=FULL_DETAIL_TIP)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.look_btn = access.button(p, row, "&Look at the pictures", "Read where each picture was taken and show "
                                                                       "the new folders; nothing moves yet",
                                      self.on_look)
        access.button(p, row, "M&y places...", "Your own names for places, such as Grandma's house",
                      self.on_my_places)
        self.undo_btn = access.button(p, row, "&Undo the last sort", "Put every file of the last sort back",
                                      self.on_undo)
        s.Add(row, 0, wx.LEFT | wx.TOP, 4)
        row = wx.BoxSizer(wx.HORIZONTAL)
        access.button(p, row, "&About", "Version, licence, privacy and place-name sources", self.on_about)
        access.button(p, row, "H&elp", "Open the manual (F1)", lambda: access.open_manual("main"))
        access.button(p, row, "&Close", "Close the program (Escape)", self.Close)
        s.Add(row, 0, wx.LEFT, 4)
        self.status = access.labelled(p, s, "Status:", lambda: wx.TextCtrl(p, style=wx.TE_READONLY))
        p.SetSizer(s)
        self.template.Bind(wx.EVT_TEXT, lambda e: self.update_examples())
        self.template.Bind(wx.EVT_COMBOBOX, lambda e: self.update_examples())
        self.time.Bind(wx.EVT_CHOICE, lambda e: self.update_examples())
        self.Bind(wx.EVT_CLOSE, self.on_close)
        access.install_keys(self, "main")
        self.update_examples()
        self.update_buttons()
        (self.look_btn if folder else self.folder).SetFocus()

    # -------------------------------------------------- choices

    def choices(self):
        """The options chosen now (grouping.options), with "packs" and "dest"."""
        opts = grouping.options(detail=grouping.DETAILS[max(0, self.detail.GetSelection())],
                                time=grouping.TIMES[max(0, self.time.GetSelection())],
                                template=self.template.GetValue().strip() or grouping.TEMPLATES[0],
                                gap_days=self.gap.GetValue(), split_on_place=self.split.GetValue(),
                                mode=MODES[max(0, self.mode.GetSelection())],
                                unknown=grouping.UNKNOWN_CHOICES[max(0, self.unknown.GetSelection())],
                                subfolders=self.subfolders.GetValue(), rename=self.rename.GetValue(),
                                name_pattern=grouping.NAME_PATTERNS[max(0, self.name_pattern.GetSelection())])
        return opts

    def save_choices(self):
        """Save the choices for next time."""
        values = {**self.choices(), "packs": settings.PACK_MODES[max(0, self.packs.GetSelection())],
                  "full_detail": self.full_detail.GetValue(),
                  "last_folder": self.folder.GetValue().strip(), "dest": self.dest.GetValue().strip()}
        try:
            settings.save(values)
        except OSError:
            pass

    def update_examples(self):
        """Show examples of the folder names the template makes."""
        time = grouping.TIMES[max(0, self.time.GetSelection())]
        names = grouping.preview_examples(self.template.GetValue().strip() or grouping.TEMPLATES[0], time)
        self.examples.SetValue(", ".join(names))

    def update_buttons(self):
        """Undo only when there is a sort to undo; nothing while a task runs."""
        self.undo_btn.Enable(self.busy is None and sorter.last_undo() is not None)
        self.look_btn.Enable(self.busy is None)

    def say(self, text):
        """Show text in Status and say it through the screen reader."""
        self.status.SetValue(text)
        access.announce(self, text)

    # -------------------------------------------------- buttons

    def on_browse(self):
        """Choose the folder of pictures."""
        with wx.DirDialog(self, "Choose the folder of pictures", self.folder.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.folder.SetValue(dlg.GetPath())
                self.look_btn.SetFocus()

    def on_browse_dest(self):
        """Choose where the new folders go."""
        with wx.DirDialog(self, "Choose where the new folders go", self.dest.GetValue() or
                          self.folder.GetValue()) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.dest.SetValue(dlg.GetPath())

    def make_places(self):
        """The places.Places for a run (My places as saved now)."""
        if self.places_override is not None:
            self.places_override.my_places = self.my_places
            self.places_override.full_detail = self.full_detail.GetValue()
            return self.places_override
        return Places(my_places=self.my_places, full_detail=self.full_detail.GetValue())

    def ask_pack(self, label, size, count):
        """The pack question (in the window thread): True to download."""
        mb = f"{size / 1e6:.0f} MB" if size else "a few megabytes"
        answer = access.message(self, f"{count} photos were taken in {label}. To name their places, the free place "
                                      f"pack for {label} ({mb}) is needed. Download it now? Only the pack is "
                                      f"downloaded; nothing about your photos is sent.",
                                "Download a place pack", wx.YES_NO | wx.ICON_QUESTION)
        return answer == wx.YES

    def on_look(self):
        """Look at the pictures (in the background, with the progress window), then show the review."""
        folder = self.folder.GetValue().strip()
        ok, why = job.is_sortable_folder(folder)
        if not ok:
            access.message(self, why, "Look at the pictures", wx.OK | wx.ICON_WARNING)
            self.folder.SetFocus()
            return
        opts = self.choices()
        self.save_choices()
        packs = settings.PACK_MODES[max(0, self.packs.GetSelection())]
        places = self.make_places()

        def work(progress, stop, ask):
            """In the background: read the pictures and make the plan."""
            return job.build_plan(os.path.abspath(folder), opts, places, packs,
                                  ask=lambda label, size, count: ask(lambda: self.ask_pack(label, size, count)),
                                  progress=progress, stop=stop)[0]
        self.start("Looking at the pictures", work, self.on_looked)

    def start(self, title, work, done):
        """Run work in the background with the progress window; done(result, error) at the end."""
        def finished(result, error):
            """The work ended: forget the progress window, update the buttons, then call done."""
            self.busy = None
            if self:
                self.update_buttons()
            done(result, error)
        self.busy = ProgressWindow(self, title, work, finished)
        self.update_buttons()
        self.busy.Show()

    def on_looked(self, plan, error):
        """The pictures were looked at: show the review (or say what went wrong)."""
        if error is not None:
            self.say("Something went wrong while looking at the pictures.")
            access.message(self, f"The pictures could not be looked at: {error}", "Look at the pictures",
                           wx.OK | wx.ICON_ERROR)
            return
        self.plan = plan
        if not plan.groups:
            text = "No new folders: no picture has a place that could be found."
            if plan.left:
                text += f" {len(plan.left)} pictures have no location or no place name was found for them."
            text += " " + " ".join(plan.problems)
            self.say(text)
            access.message(self, text, "Look at the pictures")
            return
        self.say(f"{plan.photo_count} photos in {len(plan.groups)} new folders. Review them before sorting.")
        dest = self.dest.GetValue().strip() or plan.root
        review = ReviewWindow(self, plan, dest)
        result = review.ShowModal()
        review.Destroy()
        if result == wx.ID_OK:
            self.sort(plan, dest)

    def sort(self, plan, dest):
        """Sort now: move or copy in the background, then say what happened."""
        def work(progress, stop, ask):
            """In the background: move or copy the files."""
            os.makedirs(dest, exist_ok=True)
            return sorter.apply(plan, dest, progress=lambda d, t, f: progress("Sorting", d, t), stop=stop)
        self.start("Sorting", work, self.on_sorted)

    def on_sorted(self, outcome, error):
        """The sort ended: say the summary and offer the report."""
        if error is not None:
            self.say("The sort stopped because of a problem.")
            access.message(self, f"The sort stopped: {error}. Undo the last sort puts back what was done.",
                           "Sort", wx.OK | wx.ICON_ERROR)
            return
        self.outcome = outcome
        self.say(outcome.summary())
        if access.message(self, outcome.summary() + "\n\nOpen the report now?", "Sorted",
                          wx.YES_NO | wx.ICON_INFORMATION) == wx.YES:
            open_file(outcome.report_path)

    def on_my_places(self):
        """Open My places."""
        dlg = MyPlacesWindow(self, self.my_places, finder=self.make_places(),
                             pack_mode=settings.PACK_MODES[max(0, self.packs.GetSelection())])
        dlg.ShowModal()
        if dlg:
            dlg.Destroy()

    def on_undo(self):
        """Undo the last sort, after asking."""
        path = sorter.last_undo()
        if not path:
            self.say("There is no sort to undo.")
            self.update_buttons()
            return
        if access.message(self, f"Put back every file of {sorter.describe_undo(path)}? Folders the sort made are "
                                f"removed when they are empty again.", "Undo the last sort",
                          wx.YES_NO | wx.ICON_QUESTION) != wx.YES:
            return

        def work(progress, stop, ask):
            """In the background: put the files back."""
            return sorter.undo(path, progress=lambda d, t, name: progress("Putting the files back", d, t))
        self.start("Undoing the last sort", work, self.on_undone)

    def on_undone(self, result, error):
        """The undo ended: say what happened."""
        if error is not None:
            access.message(self, f"The undo stopped: {error}", "Undo the last sort", wx.OK | wx.ICON_ERROR)
            return
        restored, problems = result
        text = f"Put back {restored} files."
        if problems:
            text += f" {len(problems)} could not be put back: " + "; ".join(f"{os.path.basename(p)}: {r}"
                                                                         for p, r in problems[:5])
        self.say(text)
        access.message(self, text, "Undo the last sort")

    def on_about(self):
        """Open About."""
        attrs = self.plan.attributions if self.plan is not None else ()
        dlg = AboutWindow(self, attrs)
        dlg.ShowModal()
        if dlg:
            dlg.Destroy()

    def on_close(self, event):
        """Save the choices and close (not while a task runs: Stop it first)."""
        if self.busy is not None:
            self.say("Stop the task first, or wait for it to finish.")
            if event.CanVeto():
                event.Veto()
                return
        self.save_choices()
        event.Skip()


def open_file(path):
    """Open a file with its program (the report in Notepad)."""
    if not path or os.environ.get("PLI_NO_BROWSER"):
        return
    try:
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - the user's own report
        else:
            import webbrowser
            webbrowser.open("file://" + os.path.abspath(path))
    except OSError:
        pass


def run(folder=""):
    """Start the windows (File Explorer's "Sort pictures by location" gives the folder). Returns 0."""
    app = wx.App(False)
    app.SetAppName(APP_NAME)
    w = MainWindow(folder)
    w.Show()
    app.MainLoop()
    return 0
