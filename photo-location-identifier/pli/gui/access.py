"""Accessibility helpers used by every window, so they all follow the same rules:

  - a label ending in ":" is made directly before every field, list and choice (labelled), so screen readers
    (NVDA, JAWS, Narrator) read it as the control's name, and its &letter is the Alt key that goes to it;
  - every button has an &letter, named in its tooltip "(Alt+X)" (button);
  - Escape closes the window, F1 opens the manual at the window's part, and Enter presses only the button that
    has the focus: it never starts anything from a field or list (install_keys);
  - Alt+letter works the same on every system (mnemonic_targets), and presses a button or ticks a check box;
  - announce(window, text) says a message through the screen reader with a UI Automation notification (Windows
    10 and later; NVDA, JAWS and Narrator read it), and keeps it in SPOKEN (for the tests).
"""

import os
import re
import sys
import webbrowser

import wx

SPOKEN = []                 # every announcement, newest last (the tests read it)
MANUAL_OPENED = []          # the manual parts opened with F1 (the tests read it)


def labelled(parent, sizer, label, factory, proportion=0, flag=wx.EXPAND):
    """Add a label (ending in ":") and, right after it, the control factory() makes; returns the control. The
    control is made after its label, so the label is its name for screen readers and its &letter goes to it."""
    assert label.rstrip().endswith(":"), label
    text = wx.StaticText(parent, label=label)
    sizer.Add(text, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
    control = factory()
    sizer.Add(control, proportion, flag | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
    return control


def button(parent, sizer, label, tip, handler, ident=wx.ID_ANY):
    """A button with an &letter, its tooltip naming it ("... (Alt+X)"), added to sizer; handler() runs when it is
    pressed. Returns the button."""
    m = re.search(r"&([A-Za-z0-9])", label.replace("&&", ""))
    assert m, f"button {label!r} has no Alt key"
    key = m.group(1).upper()
    if f"(Alt+{key})" not in tip:
        tip = f"{tip} (Alt+{key})"
    b = wx.Button(parent, ident, label=label)
    b.SetToolTip(tip)
    b.Bind(wx.EVT_BUTTON, lambda e: handler())
    sizer.Add(b, 0, wx.ALL, 4)
    return b


def check(parent, sizer, label, value=False, tip=""):
    """A check box with an &letter, ticked or not, added to sizer; returns it."""
    c = wx.CheckBox(parent, label=label)
    c.SetValue(bool(value))
    if tip:
        c.SetToolTip(tip)
    sizer.Add(c, 0, wx.ALL, 6)
    return c


def mnemonic_targets(window):
    """{letter: control} of the Alt keys in a window: a button or check box acts itself; a label's letter goes to
    the control made right after it. The first control with a letter wins it."""
    out = {}

    def walk(w):
        for child in w.GetChildren():
            if isinstance(child, wx.TopLevelWindow) or not child.IsShown():
                continue
            if isinstance(child, (wx.Button, wx.CheckBox, wx.StaticText)):
                m = re.search(r"&([A-Za-z0-9])", child.GetLabel().replace("&&", ""))
                if m:
                    letter = m.group(1).lower()
                    if isinstance(child, wx.StaticText):
                        siblings = list(child.GetParent().GetChildren())
                        later = siblings[siblings.index(child) + 1:]
                        target = next((s for s in later if s.AcceptsFocus()), None)
                        if target is not None:
                            out.setdefault(letter, target)
                    else:
                        out.setdefault(letter, child)
            walk(child)
    walk(window)
    return out


def press(control):
    """Act as if the user pressed a button or ticked a check box (posting the event, as a click does)."""
    if isinstance(control, wx.Button):
        if control.IsEnabled():
            control.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.wxEVT_BUTTON, control.GetId()))
    elif isinstance(control, wx.CheckBox):
        if control.IsEnabled():
            control.SetValue(not control.GetValue())
            event = wx.CommandEvent(wx.wxEVT_CHECKBOX, control.GetId())
            event.SetEventObject(control)
            event.SetInt(int(control.GetValue()))
            control.GetEventHandler().ProcessEvent(event)
            control.SetFocus()
    else:
        control.SetFocus()


def resource(*parts):
    """A file shipped with the program (the manual, the licences): next to the program when installed, else in the
    source folder."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
        __file__))))
    return os.path.join(base, *parts)


def open_manual(section=""):
    """Open the manual (docs/manual.html) in the web browser, at a section's anchor ("" for the start)."""
    MANUAL_OPENED.append(section)
    if os.environ.get("PLI_NO_BROWSER"):
        return
    path = resource("docs", "manual.html")
    url = "file:///" + os.path.abspath(path).replace("\\", "/").lstrip("/")
    webbrowser.open(url + (f"#{section}" if section else ""))


def focused():
    """The control that has the keyboard focus (or None)."""
    return wx.Window.FindFocus()


def install_keys(window, section, on_escape=None):
    """Escape closes window (or calls on_escape), F1 opens the manual at section, Enter presses only a focused
    button (in a field or list it does nothing; in a multi-line field it is a new line), and Alt+letter goes to its
    control everywhere."""
    def on_key(event):
        key, mods = event.GetKeyCode(), event.GetModifiers()
        if key == wx.WXK_ESCAPE and mods == wx.MOD_NONE:
            if on_escape is not None:
                on_escape()
            else:
                window.Close()
            return
        if key == wx.WXK_F1 and mods == wx.MOD_NONE:
            open_manual(section)
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and mods == wx.MOD_NONE:
            focus = focused()
            if isinstance(focus, wx.Button):
                press(focus)
                return
            if isinstance(focus, wx.TextCtrl) and focus.IsMultiLine() and focus.IsEditable():
                event.Skip()
            return
        if mods == wx.MOD_ALT and 0 < key < 256 and chr(key).isalnum():
            target = mnemonic_targets(window).get(chr(key).lower())
            if target is not None and target.IsEnabled():
                press(target)
                return
        event.Skip()
    window.Bind(wx.EVT_CHAR_HOOK, on_key)


class _Uia:
    """UI Automation notifications on Windows 10 1709 and later (NVDA, JAWS and Narrator read them)."""

    def __init__(self):
        """Load UIAutomationCore and oleaut32 (None on other systems)."""
        self.core = None
        if os.name != "nt":
            return
        try:
            import ctypes
            self.ctypes = ctypes
            self.core = ctypes.windll.UIAutomationCore
            self.oleaut = ctypes.windll.oleaut32
            self.oleaut.SysAllocString.restype = ctypes.c_void_p
            self.oleaut.SysAllocString.argtypes = [ctypes.c_wchar_p]
            self.oleaut.SysFreeString.argtypes = [ctypes.c_void_p]
        except (AttributeError, OSError):
            self.core = None

    def say(self, hwnd, text):
        """Raise the notification on the window hwnd. Returns True if it was raised."""
        if not self.core or not hwnd:
            return False
        ctypes = self.ctypes
        provider = ctypes.c_void_p()
        if self.core.UiaHostProviderFromHwnd(ctypes.c_void_p(hwnd), ctypes.byref(provider)) != 0:
            return False
        msg = self.oleaut.SysAllocString(text)
        act = self.oleaut.SysAllocString("PhotoLocationIdentifier.status")
        try:
            # NotificationKind_ActionCompleted = 2... Other = 4; NotificationProcessing_ImportantMostRecent = 1
            return self.core.UiaRaiseNotificationEvent(provider, 4, 1, ctypes.c_void_p(msg),
                                                       ctypes.c_void_p(act)) == 0
        except OSError:
            return False
        finally:
            self.oleaut.SysFreeString(msg)
            self.oleaut.SysFreeString(act)
            vtbl = ctypes.cast(provider, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(provider)


_uia = None


def announce(window, text):
    """Say text through the screen reader (a UI Automation notification on window) and keep it in SPOKEN."""
    global _uia
    SPOKEN.append(text)
    if os.name != "nt" or window is None:
        return
    if _uia is None:
        _uia = _Uia()
    try:
        _uia.say(window.GetHandle(), text)
    except Exception:  # noqa: BLE001 - speech is a help, never a reason to fail
        pass


def message(parent, text, title, style=wx.OK | wx.ICON_INFORMATION):
    """A standard message box ("title - Photo Location Identifier"); returns the button pressed (wx.OK, wx.YES ...)."""
    from pli import APP_NAME
    return wx.MessageBox(text, f"{title} - {APP_NAME}", style, parent)
