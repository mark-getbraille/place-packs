"""The progress window: a long task (looking at the photos, sorting, undoing) runs in the background while this
window shows what it is doing ("Progress:"), a bar, and the percent in its title ("40% - Sorting - Photo Location
Identifier"). Each new step and every 10 percent are said through the screen reader (access.announce). "Stop"
(Alt+S, or Escape) asks the task to stop after the file it is on.

  ProgressWindow(parent, title, work, on_done)
      work(progress, stop, ask) runs in a background thread: progress(text, done, total) reports, stop() is True
      once Stop was pressed, ask(fn) runs fn() in the window thread and returns its result (for a question to the
      user, such as downloading a place pack). on_done(result, error) runs in the window thread at the end.
"""

import threading

import wx

from pli import APP_NAME
from pli.gui import access

ANNOUNCE_EVERY = 10         # percent


class ProgressWindow(wx.Dialog):
    """See the module docstring."""

    def __init__(self, parent, title, work, on_done):
        """Make the window and start work in the background (show it with Show())."""
        super().__init__(parent, title=f"{title} - {APP_NAME}", size=(520, 230),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.task_title, self.work, self.on_done = title, work, on_done
        self.stopping = False
        self.finished = False
        self.last_text = ""
        self.last_tenth = -1
        panel = wx.Panel(self)
        s = wx.BoxSizer(wx.VERTICAL)
        self.status = access.labelled(panel, s, "Progress:",
                                      lambda: wx.TextCtrl(panel, value="Starting", style=wx.TE_READONLY))
        self.gauge = wx.Gauge(panel, range=100)
        self.gauge.SetName("Percent done")
        s.Add(self.gauge, 0, wx.EXPAND | wx.ALL, 8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.stop_btn = access.button(panel, row, "&Stop", "Stop after the file it is working on", self.on_stop)
        s.Add(row, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
        panel.SetSizer(s)
        access.install_keys(self, "progress", on_escape=self.on_stop)
        self.Bind(wx.EVT_CLOSE, lambda e: self.on_stop() if not self.finished else e.Skip())
        self.status.SetFocus()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # -------------------------------------------------- called from the background thread

    def progress(self, text, done=0, total=0):
        """Report from the task (any thread)."""
        wx.CallAfter(self._show, text, done, total)

    def stop(self):
        """True once Stop was pressed."""
        return self.stopping

    def ask(self, fn):
        """Run fn() in the window thread (a question to the user) and return its result, waiting for it."""
        if wx.IsMainThread():
            return fn()
        box, done = [], threading.Event()

        def run():
            try:
                box.append(fn())
            finally:
                done.set()
        wx.CallAfter(run)
        done.wait()
        return box[0] if box else None

    def _run(self):
        """The background thread: the task, then on_done in the window thread."""
        result, error = None, None
        try:
            result = self.work(self.progress, self.stop, self.ask)
        except Exception as e:  # noqa: BLE001 - shown to the user by on_done
            error = e
        wx.CallAfter(self._finish, result, error)

    # -------------------------------------------------- the window thread

    def _show(self, text, done, total):
        """Show the step and the percent, and say what changed."""
        if not self:
            return
        percent = int(done * 100 / total) if total else 0
        line = f"{text}: {done} of {total}" if total else text
        self.status.SetValue(line)
        self.gauge.SetValue(max(0, min(100, percent)))
        self.SetTitle(f"{percent}% - {self.task_title} - {APP_NAME}" if total else
                      f"{self.task_title} - {APP_NAME}")
        tenth = percent // ANNOUNCE_EVERY
        if text != self.last_text:
            self.last_text, self.last_tenth = text, tenth
            access.announce(self, text)
        elif total and tenth != self.last_tenth:
            self.last_tenth = tenth
            access.announce(self, f"{percent} percent")

    def _finish(self, result, error):
        """The task ended: close the window and hand over the result."""
        self.finished = True
        if self:
            self.Destroy()
        self.on_done(result, error)

    def on_stop(self):
        """Stop pressed (or Escape): the task stops after the file it is on."""
        if self.finished:
            return
        self.stopping = True
        self.stop_btn.Disable()
        self.status.SetValue("Stopping after this file")
        access.announce(self, "Stopping after this file")


def wait_for(window, timeout=60):
    """For the tests: let the window's task finish (processing window events) or raise TimeoutError."""
    import time
    end = time.time() + timeout
    while not window.finished:
        if time.time() > end:
            raise TimeoutError("the task did not finish")
        wx.Yield()
        time.sleep(0.01)
    for _ in range(3):
        wx.Yield()
