"""The windows: every window follows the accessibility rules (assert_accessible), the keys (Escape, F1, Enter,
Alt+letter), and the whole flow (look at the pictures, review, sort, undo) in the main window with the progress
window and its screen-reader announcements.

Skipped without wxPython or a display. On Linux run under a virtual display:  xvfb-run -a python -m pytest tests
"""

import os
import sys
import time

import pytest

wx = pytest.importorskip("wx")
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("no display", allow_module_level=True)

from pli import grouping, job, myplaces as mp, sorter  # noqa: E402
from pli.gui import access, dialogs  # noqa: E402
from pli.gui import main_window as mw  # noqa: E402
from pli.gui.progress import ProgressWindow, wait_for  # noqa: E402
from pli.places import Places  # noqa: E402


@pytest.fixture(scope="module")
def app():
    """One wx.App for every window test."""
    yield wx.GetApp() or wx.App(False)


@pytest.fixture(autouse=True)
def close_windows(app):
    """Destroy the windows a test left open, and start each test with no announcements."""
    access.SPOKEN.clear()
    access.MANUAL_OPENED.clear()
    yield
    for w in list(wx.GetTopLevelWindows()):
        if w:
            w.Destroy()
    for _ in range(3):
        wx.Yield()


def walk(window):
    """Every control inside window in creation (tab) order; windows of their own are left out."""
    for child in window.GetChildren():
        if isinstance(child, wx.TopLevelWindow):
            continue
        yield child
        yield from walk(child)


def assert_accessible(window):
    """The rules of every window: each button has an Alt letter named in its tooltip "(Alt+X)"; no letter is used
    twice; every text field, list, choice, combo box and number field has a label ending in ":" directly before it;
    check boxes have labels."""
    controls = list(walk(window))
    keys = {}
    for c in controls:
        if isinstance(c, (wx.Button, wx.CheckBox, wx.StaticText)):
            label = c.GetLabel().replace("&&", "")
            if "&" in label:
                key = label[label.index("&") + 1].lower()
                assert key not in keys, f"Alt+{key} is used by both {keys[key]!r} and {label!r}"
                keys[key] = label
    for i, c in enumerate(controls):
        if isinstance(c, wx.Button):
            label = c.GetLabel()
            assert "&" in label, f"button {label!r} has no Alt key"
            key = label[label.index("&") + 1].upper()
            assert f"(Alt+{key})" in c.GetToolTipText(), f"tooltip of {label!r} does not name Alt+{key}"
        if isinstance(c, (wx.TextCtrl, wx.ListBox, wx.Choice, wx.ComboBox, wx.SpinCtrl)):
            before = controls[i - 1]
            assert isinstance(before, wx.StaticText), f"{type(c).__name__} has no label before it"
            assert before.GetLabel().rstrip().endswith(":"), before.GetLabel()
        if isinstance(c, wx.CheckBox):
            assert c.GetLabel().strip() and "&" in c.GetLabel()
    # Every Alt letter of a label leads to a control that takes the focus.
    targets = access.mnemonic_targets(window)
    assert set(targets) == set(keys), (set(keys) - set(targets))
    return keys


def key(window, code, mods=wx.MOD_NONE):
    """Send a key to window as the keyboard would (through its key handler)."""
    e = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
    e.SetKeyCode(code)
    e.SetEventObject(window)
    if mods & wx.MOD_ALT:
        e.SetAltDown(True)
    window.GetEventHandler().ProcessEvent(e)
    wx.Yield()


def until(condition, timeout=30):
    """Process window events until condition() is true (TimeoutError after timeout seconds)."""
    end = time.time() + timeout
    while not condition():
        if time.time() > end:
            raise TimeoutError("the window did not get there")
        wx.Yield()
        time.sleep(0.01)


@pytest.fixture
def plan(album, finder):
    """A plan of the Outer Banks album."""
    return job.build_plan(album, grouping.options(unknown="unknown"), Places(finder=finder), "never")[0]


def test_every_window_is_accessible(app, plan, finder):
    """The main window, the review, rename, merge, My places, About and the progress window."""
    frame = mw.MainWindow("", places=Places(finder=finder))
    keys = assert_accessible(frame)
    assert {"f", "b", "s", "d", "t", "n", "p", "r", "w", "h", "m", "o", "i", "g", "k", "l", "y", "u", "a", "e",
            "c"} == set(keys)
    for w in dialogs.all_windows(frame, plan):
        assert_accessible(w)
        w.Destroy()
    p = ProgressWindow(frame, "Testing", lambda progress, stop, ask: 1, lambda r, e: None)
    assert_accessible(p)
    wait_for(p)


def test_keys_escape_f1_enter_and_alt(app, finder, tmp_path, monkeypatch):
    """F1 opens the manual at the window's part; Enter in a list or choice does nothing, on a button presses it;
    Alt+letter goes to its control; Escape closes."""
    frame = mw.MainWindow(str(tmp_path), places=Places(finder=finder))
    frame.Show()
    key(frame, wx.WXK_F1)
    assert access.MANUAL_OPENED == ["main"]
    pressed = []
    frame.look_btn.Unbind(wx.EVT_BUTTON)
    frame.look_btn.Bind(wx.EVT_BUTTON, lambda e: pressed.append("look"))
    focus = [frame.detail]
    monkeypatch.setattr(access, "focused", lambda: focus[0])
    for control in (frame.detail, frame.folder, frame.template):
        focus[0] = control
        key(frame, wx.WXK_RETURN)
    assert pressed == []
    focus[0] = frame.look_btn
    key(frame, wx.WXK_RETURN)
    assert pressed == ["look"]
    targets = access.mnemonic_targets(frame)
    assert (targets["t"], targets["n"], targets["l"]) == (frame.time, frame.template, frame.look_btn)
    value = frame.split.GetValue()
    key(frame, ord("H"), wx.MOD_ALT)
    assert frame.split.GetValue() is not value
    key(frame, ord("L"), wx.MOD_ALT)
    assert pressed == ["look", "look"]
    about = dialogs.AboutWindow(frame)
    about.Show()
    key(about, wx.WXK_F1)
    assert access.MANUAL_OPENED[-1] == "about"
    closed = []
    about.Bind(wx.EVT_WINDOW_DESTROY, lambda e: closed.append(1))
    key(about, wx.WXK_ESCAPE)
    until(lambda: closed, 5)


def test_template_preview_and_saved_choices(app, finder, tmp_path):
    """The examples follow the template and the time; the choices are saved for next time."""
    frame = mw.MainWindow(str(tmp_path), places=Places(finder=finder))
    assert frame.examples.GetValue() == "Outer Banks 2005, Outer Banks 2006, Grandma's house 2007"
    frame.template.SetValue("{year}\\{place}")
    frame.update_examples()
    assert frame.examples.GetValue().startswith("2005\\Outer Banks")
    frame.time.SetSelection(grouping.TIMES.index("month"))
    frame.template.SetValue("{year}-{month} {place}")
    frame.update_examples()
    assert frame.examples.GetValue().startswith("2005-07 Outer Banks")
    frame.mode.SetSelection(1)
    frame.save_choices()
    again = mw.MainWindow("", places=Places(finder=finder))
    assert again.choices()["mode"] == "copy" and again.choices()["time"] == "month"
    assert again.folder.GetValue() == str(tmp_path)


def test_look_review_sort_and_undo(app, album, finder, monkeypatch):
    """The whole flow: Look at the pictures (progress announced), the review (rename one folder), Sort now, then
    Undo the last sort; the progress window's title has the percent and every step is announced."""
    frame = mw.MainWindow(album, places=Places(finder=finder))
    frame.Show()
    titles = []
    real_show = ProgressWindow._show

    def show(self, text, done, total):
        real_show(self, text, done, total)
        titles.append(self.GetTitle())
    monkeypatch.setattr(ProgressWindow, "_show", show)
    answers = []
    monkeypatch.setattr(access, "message", lambda parent, text, title, style=0: answers.append(title) or wx.YES
                        if title == "Undo the last sort" and style & wx.YES_NO else wx.NO)

    def review(self):
        assert_accessible(self)
        assert self.folders.GetCount() == 3 and self.folders.GetString(0).startswith("Outer Banks 2005: 3 photos")
        self.plan.rename(self.plan.groups[1], "Beach week 2006")
        return wx.ID_OK
    monkeypatch.setattr(dialogs.ReviewWindow, "ShowModal", review)
    monkeypatch.setattr(mw.ReviewWindow, "ShowModal", review)
    frame.on_look()
    until(lambda: frame.outcome is not None and frame.busy is None)
    assert sorted(d for d in os.listdir(album) if os.path.isdir(os.path.join(album, d))) == \
        ["Beach week 2006", "Outer Banks 2005", "Wrightsville Beach 2007"]
    assert any(t.startswith("100% - Sorting") for t in titles)
    assert "Reading where and when each photo was taken" in access.SPOKEN
    assert any(s.endswith("percent") for s in access.SPOKEN)
    assert frame.status.GetValue().startswith("Moved 7 photos into 3 new folders")
    assert frame.undo_btn.IsEnabled()
    frame.on_undo()
    until(lambda: frame.busy is None and "Put back 7 files." in access.SPOKEN)
    assert not any(os.path.isdir(os.path.join(album, d)) for d in os.listdir(album))
    assert not frame.undo_btn.IsEnabled()


def test_review_rename_merge_buttons(app, plan, monkeypatch):
    """Rename and Merge in the review window change the list (their own windows answered by stand-ins)."""
    review = dialogs.ReviewWindow(None, plan)

    class Answer:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def ShowModal(self):
            return wx.ID_OK

        def value(self):
            return "Summer 2005"

        def choice(self):
            return 0
    monkeypatch.setattr(dialogs, "RenameWindow", Answer)
    monkeypatch.setattr(dialogs, "MergeWindow", Answer)
    review.folders.SetSelection(0)
    review.on_rename()
    assert review.folders.GetString(0).startswith("Summer 2005: 3 photos")
    review.folders.SetSelection(2)
    review.on_merge()
    assert review.folders.GetCount() == 3 and "Merged into Summer 2005, now 5 photos" in access.SPOKEN
    assert "Unknown place" in review.folders.GetString(review.folders.GetCount() - 1)


def test_my_places_window(app, tmp_path):
    """Add (a pasted "lat, lon" is split), change, remove; saved when closed."""
    places = mp.MyPlaces(path=str(tmp_path / "my.json"))
    w = dialogs.MyPlacesWindow(None, places, photo_reader=lambda path: (36.01, -75.67))
    w.name.SetValue("Grandma's house")
    w.lat.SetValue("36.0123, -75.6789")
    assert (w.lat.GetValue(), w.lon.GetValue()) == ("36.0123", "-75.6789")
    w.on_add()
    assert w.list.GetString(0).startswith("Grandma's house, within 200 metres")
    w.radius.SetValue(500)
    w.on_add()
    assert w.list.GetCount() == 1 and places.places[0].radius_m == 500
    w.on_remove()
    assert w.list.GetCount() == 0
    w.on_close()
    assert mp.MyPlaces.load(str(tmp_path / "my.json")).places == []


def test_about_shows_privacy_and_attribution(app):
    """About names the licence, the privacy rule and the OpenStreetMap attribution."""
    w = dialogs.AboutWindow(None, ["Test source attribution"])
    text = w.text.GetValue()
    assert "MIT" in text and "No photo, position or other detail of yours is ever sent" in text
    assert "© OpenStreetMap contributors" in text and "Test source attribution" in text
    w.on_licences()
    assert access.MANUAL_OPENED[-1] == "licences"


def test_pack_question_runs_in_the_window_thread(app, tmp_path, monkeypatch):
    """A question asked from the background task (a pack download) is shown by the window thread and its answer
    goes back to the task."""
    frame = mw.MainWindow(str(tmp_path))
    seen = []
    monkeypatch.setattr(access, "message", lambda parent, text, title, style=0: seen.append(text) or wx.YES)
    results = []
    p = ProgressWindow(frame, "Testing", lambda progress, stop, ask: ask(lambda: frame.ask_pack(
        "North Carolina, United States", 12_000_000, 7)), lambda r, e: results.append((r, e)))
    p.Show()
    wait_for(p)
    assert results == [(True, None)]
    assert "7 photos were taken in North Carolina, United States" in seen[0] and "12 MB" in seen[0]
    assert "nothing about your photos is sent" in seen[0]


def test_stop_ends_the_task(app):
    """Stop (or Escape) asks the task to stop; it is announced."""
    def work(progress, stop, ask):
        while not stop():
            time.sleep(0.01)
        return "stopped"
    results = []
    p = ProgressWindow(None, "Testing", work, lambda r, e: results.append(r))
    p.Show()
    key(p, wx.WXK_ESCAPE)
    wait_for(p)
    assert results == ["stopped"] and "Stopping after this file" in access.SPOKEN


def test_sorter_left_no_undo_between_tests():
    """The test set-up gives every test its own program folder (no undo file is left over)."""
    assert sorter.last_undo() is None


def test_exact_place_in_names_choice(app, finder, tmp_path):
    """"Put the exact place in each picture's name" (Alt+P, named in its tooltip, off by default) and "Picture
    names:" (Alt+R, a label ending in ":" before it) are in the main window, change the options and are saved."""
    frame = mw.MainWindow(str(tmp_path), places=Places(finder=finder))
    assert frame.rename.GetLabel() == "&Put the exact place in each picture's name"
    assert "(Alt+P)" in frame.rename.GetToolTipText() and not frame.rename.GetValue()
    controls = list(walk(frame))
    label = controls[controls.index(frame.name_pattern) - 1]
    assert isinstance(label, wx.StaticText) and label.GetLabel().startswith("Pictu&re names")
    assert label.GetLabel().endswith(":")
    targets = access.mnemonic_targets(frame)
    assert (targets["p"], targets["r"]) == (frame.rename, frame.name_pattern)
    assert frame.name_pattern.GetCount() == len(grouping.NAME_PATTERNS)
    assert frame.name_pattern.GetString(0).startswith("Date, exact place, then the old name")
    assert frame.choices()["rename"] is False and frame.choices()["name_pattern"] == "date-place-name"
    key(frame, ord("P"), wx.MOD_ALT)
    assert frame.rename.GetValue()
    frame.name_pattern.SetSelection(2)
    frame.save_choices()
    again = mw.MainWindow("", places=Places(finder=finder))
    assert again.rename.GetValue() and again.choices()["name_pattern"] == "place-name"


def test_review_shows_old_and_new_names(app, tmp_path):
    """With renaming on, the review says how many pictures get a new name, each folder's row says how many, and the
    details list "old name \u2192 new name"; a merge works the names out again. The window stays accessible."""
    from test_naming import AREAS, PLACES, STREETS, WATER, plan_of, week
    from pli.places import StandInFinder
    finder = StandInFinder(areas=AREAS, places=PLACES, water=WATER, streets=STREETS)
    plan = plan_of(week(tmp_path / "a"), finder, detail="town")
    review = dialogs.ReviewWindow(None, plan)
    assert_accessible(review)
    assert "will get a new name with the exact place" in review.intro.GetLabel()
    row = review.folders.GetString(0)
    assert row.startswith("Pelican Point 2005") and "with a new name" in row
    details = review.details.GetValue()
    assert "IMG_0001.jpg \u2192 2005-07-14 Heron Dunes State Park (IMG_0001).jpg" in details
    assert "IMG_0003.jpg \u2192 2005-07-14 120 Seagrass Lane (IMG_0003).jpg" in details
    sandpiper = next(i for i, g in enumerate(plan.groups) if g.folder == "Sandpiper Bay 2005")
    pelican = plan.groups[0]
    plan.merge(pelican, plan.groups[sandpiper])
    plan.rename(pelican, "Beach week 2005")
    review.refresh(0)
    assert "IMG_0006.jpg \u2192 2005-07-15 Sandpiper Bay (IMG_0006).jpg" in review.details.GetValue()
    review.Destroy()
