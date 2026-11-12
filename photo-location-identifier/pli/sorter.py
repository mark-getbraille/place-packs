"""Doing the sort the review agreed to: moving (or copying) every photo into its new folder, writing the report and
the undo file, and undoing the last sort.

  apply(plan, dest, progress, stop)   move or copy; returns an Outcome (counts, problems, report and undo file)
  undo(undo_path, progress)           put every file back where it was and remove the folders the sort made (only
                                      when they are empty again)
  last_undo()                         the newest undo file that has not been undone yet
  preview(plan, dest)                 what apply would do with each photo, without doing it: the review window and
                                      the trial run (dry run) show the new names from it

Rules:
  - A file is never overwritten: when the name is taken in the new folder, " (2)", " (3)" ... is added.
  - A photo's companions (IMG_1.AAE, IMG_1.xmp, a Live Photo's IMG_1.MOV) go with it and get the same new name.
  - With "Put the exact place in each picture's name" (plan.options["rename"]), each photo gets a new name made by
    naming.wanted_stem ("2005-07-14 Jockey's Ridge State Park (IMG_1234).jpg"); a photo already in its folder is
    renamed there if its name is not the wanted one yet.
  - The undo file holds the full old and new path of every file, so Undo puts back both the folder and the name.
    Its format did not change when renaming was added (the header only gained "rename" and "name_pattern"), so
    older undo files still work.
  - The undo file is written as the sort goes (one line per file, JSON), so a sort that was stopped, or a computer
    that was switched off part way, can still be undone.
  - A copy is undone by deleting the copy, only if it still has the same size as when it was made.
  - Photos already in the folder they would go to stay where they are.
"""

import datetime as dt
import json
import os
import re
import shutil
import time

from pli import APP_NAME, __version__, naming
from pli import settings as st
from pli.grouping import date_range_words

UNDO_FOLDER = "undo"
REPORT_FOLDER = "reports"


class Outcome:
    """What a sort did: moved, copied (counts), skipped (already in place), problems [(path, reason)], folders made
    [path], report_path, undo_path, stopped (True if Stop was pressed)."""

    def __init__(self):
        """All zero."""
        self.moved = self.copied = self.skipped = self.renamed = 0
        self.names = {}                    # {photo's old path: its new file name} for the photos renamed
        self.problems, self.folders = [], []
        self.report_path = self.undo_path = ""
        self.stopped = False

    def summary(self):
        """In words: "Moved 120 photos into 4 new folders. 2 could not be moved." """
        done = self.moved + self.copied
        verb = "Copied" if self.copied and not self.moved else "Moved"
        text = f"{verb} {done} photo{'s' if done != 1 else ''} into {len(self.folders)} new " \
               f"folder{'s' if len(self.folders) != 1 else ''}."
        if self.renamed:
            text = text[:-1] + f", {self.renamed} of them with a new name that has the exact place."
        if self.skipped:
            text += f" {self.skipped} {'was' if self.skipped == 1 else 'were'} already in the right folder."
        if self.problems:
            text += f" {len(self.problems)} could not be {'copied' if verb == 'Copied' else 'moved'}: see the report."
        if self.stopped:
            text += " The sort was stopped before the end; Undo the last sort puts back what was done."
        return text


def _stamp():
    """"2026-11-09 153012", for file names."""
    return time.strftime("%Y-%m-%d %H%M%S")


def undo_folder():
    """Where undo files are kept (in the program's folder)."""
    path = os.path.join(st.home(), UNDO_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def free_name(folder, name, extra_names=(), taken=()):
    """A name in folder that is not taken: name itself, or "name (2).ext", "name (3).ext" ... The companions'
    names (extra_names: their endings after the photo's name, such as ".AAE") must be free too. taken: names already
    given in this sort (lower case). Returns the stem to use ("IMG_1 (2)")."""
    stem, ext = os.path.splitext(name)
    number = 1
    while True:
        new_stem = stem if number == 1 else f"{stem} ({number})"
        names = [new_stem + ext] + [new_stem + e for e in extra_names]
        if not any(os.path.exists(os.path.join(folder, n)) or n.lower() in taken for n in names):
            return new_stem
        number += 1


def _ending_after(companion, photo_path):
    """A companion's name after the photo's own stem: IMG_1.AAE -> ".AAE", IMG_1.JPG.xmp -> ".JPG.xmp"."""
    stem = os.path.splitext(os.path.basename(photo_path))[0]
    name = os.path.basename(companion)
    return name[len(stem):] if name.lower().startswith(stem.lower()) else os.path.splitext(name)[1]


def _destination(plan, g, photo, target_dir, used):
    """Where photo goes: (stem, endings) for its new name in target_dir and its companions' endings, or None when it
    stays as it is (already in its folder, with the wanted name when renaming). used: the names given in this
    folder so far (lower case); the chosen names are added to it."""
    here = os.path.dirname(os.path.abspath(photo.path))
    endings = [_ending_after(c, photo.path) for c in photo.companions]
    old_stem, ext = os.path.splitext(os.path.basename(photo.path))
    wanted = None
    if plan.options.get("rename") and not g.unknown:
        wanted = naming.wanted_stem(photo, g.folder, plan.options.get("name_pattern", "date-place-name"),
                                    target_dir, endings, g.place)
    if os.path.normcase(here) == os.path.normcase(os.path.abspath(target_dir)):
        if wanted is None or naming.is_named(old_stem, wanted):
            return None
    stem = free_name(target_dir, (wanted or old_stem) + ext, endings, used)
    used.update(n.lower() for n in [stem + ext] + [stem + e for e in endings])
    return stem, endings


def preview(plan, dest=None):
    """What apply would do, without doing it: {id(photo): new file name} for every photo that moves or is copied
    (its name with " (2)" when it is taken), and None for one that stays where it is. The review window and the
    trial run show the new names from it."""
    dest = dest or plan.root
    out, taken = {}, {}
    for g in plan.groups:
        target_dir = os.path.join(dest, *g.folder.split("\\"))
        used = taken.setdefault(os.path.normcase(target_dir), set())
        for photo in g.photos:
            found = _destination(plan, g, photo, target_dir, used)
            out[id(photo)] = None if found is None else found[0] + os.path.splitext(photo.path)[1]
    return out


def renamed_names(plan, names):
    """[(group, photo, new name)] of the photos whose name changes, from preview()'s or an Outcome's names."""
    out = []
    for g in plan.groups:
        for p in g.photos:
            new = names.get(id(p)) if id(p) in names else names.get(p.path)
            if new and new != os.path.basename(p.path):
                out.append((g, p, new))
    return out


def apply(plan, dest=None, progress=None, stop=None, undo_path=None, report=True):
    """Move (or copy, by plan.options["mode"]) each group's photos into dest\\<group folder> (dest: plan.root when
    None). progress(done, total, text) after each photo; stop() True ends after the current photo. Writes the undo
    file (undo_path, or a new one in the program's undo folder) and, with report, the report. Returns an Outcome."""
    mode = plan.options.get("mode", "move")
    dest = dest or plan.root
    out = Outcome()
    if undo_path is None:
        # Two sorts in the same second must not share (and overwrite) one undo file.
        base = os.path.join(undo_folder(), f"{_stamp()} {os.path.basename(os.path.abspath(dest))}")
        undo_path, n = base + ".jsonl", 2
        while os.path.exists(undo_path):
            undo_path, n = f"{base} ({n}).jsonl", n + 1
    out.undo_path = undo_path
    total = sum(len(g.photos) for g in plan.groups)
    done = 0
    taken = {}
    with open(out.undo_path, "w", encoding="utf-8") as log:
        def write(entry):
            """Add one JSON line to the undo log and flush it (an interrupted sort can still be undone)."""
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
        write({"program": APP_NAME, "version": __version__, "root": plan.root, "dest": dest, "mode": mode,
               "time": dt.datetime.now().isoformat(timespec="seconds"),
               "rename": bool(plan.options.get("rename")), "name_pattern": plan.options.get("name_pattern", "")})
        for g in plan.groups:
            target_dir = os.path.join(dest, *g.folder.split("\\"))
            for photo in g.photos:
                if stop and stop():
                    out.stopped = True
                    break
                done += 1
                try:
                    used = taken.setdefault(os.path.normcase(target_dir), set())
                    found = _destination(plan, g, photo, target_dir, used)
                    if found is None:
                        out.skipped += 1
                        continue
                    stem, endings = found
                    _make_dirs(target_dir, dest, out, write)
                    new_name = stem + os.path.splitext(photo.path)[1]
                    pairs = [(photo.path, os.path.join(target_dir, new_name))]
                    pairs += [(c, os.path.join(target_dir, stem + e)) for c, e in zip(photo.companions, endings)]
                    for src, dst in pairs:
                        if mode == "copy":
                            shutil.copy2(src, dst)
                            write({"op": "copy", "from": src, "to": dst, "size": os.path.getsize(dst)})
                        else:
                            shutil.move(src, dst)
                            write({"op": "move", "from": src, "to": dst})
                    if mode == "copy":
                        out.copied += 1
                    else:
                        out.moved += 1
                    if new_name != os.path.basename(photo.path):
                        out.renamed += 1
                        out.names[photo.path] = new_name
                except OSError as e:
                    out.problems.append((photo.path, e.strerror or str(e)))
                finally:
                    if progress:
                        progress(done, total, g.folder)
            if out.stopped:
                break
    if report:
        out.report_path = write_report(plan, out, dest)
    return out


def _make_dirs(target_dir, dest, out, write):
    """Make target_dir (and the folders above it, up to dest), noting each new one in the undo file."""
    missing = []
    d = os.path.abspath(target_dir)
    while not os.path.isdir(d) and os.path.normcase(d) != os.path.normcase(os.path.abspath(dest)):
        missing.append(d)
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for d in reversed(missing):
        os.makedirs(d, exist_ok=True)
        write({"op": "mkdir", "path": d})
        out.folders.append(d)


def read_undo(undo_path):
    """(header dict, [entries]) of an undo file; entries that cannot be read are left out."""
    header, entries = {}, []
    with open(undo_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if i == 0 and "op" not in item:
                header = item
            else:
                entries.append(item)
    return header, entries


def last_undo():
    """The newest undo file not yet undone, or None."""
    try:
        files = [os.path.join(undo_folder(), f) for f in os.listdir(undo_folder()) if f.endswith(".jsonl")]
    except OSError:
        return None
    def order(path):
        """Newest first by time; within one second, "... (3).jsonl" is newer than "... (2).jsonl" and "....jsonl"."""
        m = re.search(r" \((\d+)\)\.jsonl$", path)
        return os.path.getmtime(path), path[:m.start()] if m else path[:-len(".jsonl")], int(m.group(1)) if m else 1
    return max(files, key=order) if files else None


def describe_undo(undo_path):
    """What an undo file would undo, in words: "the sort of C:\\Photos on 9 November 2026 at 15:30 (120 files
    moved)"."""
    header, entries = read_undo(undo_path)
    files = sum(1 for e in entries if e.get("op") in ("move", "copy"))
    when = header.get("time", "")
    try:
        t = dt.datetime.fromisoformat(when)
        when = f"on {date_range_words(t, t)} at {t:%H:%M}"
    except ValueError:
        pass
    verb = "copied" if header.get("mode") == "copy" else "moved"
    renamed = sum(1 for e in entries if e.get("op") in ("move", "copy") and
                  os.path.basename(e.get("from", "")) != os.path.basename(e.get("to", "")))
    extra = f", {renamed} of them renamed" if renamed else ""
    return f"the sort of {header.get('root', '?')} {when} ({files} files {verb}{extra})"


def undo(undo_path, progress=None):
    """Undo a sort (newest change first): moved files go back to their old folder with their old name, copies are deleted (only if unchanged), and the
    folders the sort made are removed when they are empty again. A file that is no longer where the sort put it, or
    whose old place is taken, is left alone and listed. The undo file is renamed "... (undone).txt" when everything
    went back. Returns (restored, problems [(path, reason)])."""
    _, entries = read_undo(undo_path)
    restored, problems = 0, []
    files = [e for e in entries if e.get("op") in ("move", "copy")]
    for i, e in enumerate(reversed(files)):
        src, dst = e["from"], e["to"]
        try:
            if not os.path.exists(dst):
                problems.append((dst, "it is not there any more"))
            elif e["op"] == "copy":
                if os.path.getsize(dst) != e.get("size"):
                    problems.append((dst, "the copy was changed since, so it was kept"))
                else:
                    os.remove(dst)
                    restored += 1
            elif os.path.exists(src):
                problems.append((dst, f"{src} is already there"))
            else:
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dst, src)
                restored += 1
        except OSError as err:
            problems.append((dst, err.strerror or str(err)))
        if progress:
            progress(i + 1, len(files), os.path.basename(src))
    for e in reversed([e for e in entries if e.get("op") == "mkdir"]):
        try:
            if os.path.isdir(e["path"]) and not os.listdir(e["path"]):
                os.rmdir(e["path"])
        except OSError:
            pass
    if not problems:
        os.replace(undo_path, undo_path[:-len(".jsonl")] + " (undone).txt")
    return restored, problems


# ---------------------------------------------------------------- the report

def report_text(plan, out=None, dest=None, dry_run=False):
    """The plain-text report of a sort (or, with dry_run, of what a sort would do)."""
    o = plan.options
    lines = [f"{APP_NAME} {__version__} report", "",
             f"Folder sorted: {plan.root}"]
    if dest and os.path.normcase(dest) != os.path.normcase(plan.root):
        lines.append(f"New folders made in: {dest}")
    lines += [f"Date: {dt.datetime.now():%Y-%m-%d %H:%M}",
              f"Place detail: {o['detail']}; Time: {o['time']}; Folder names: {o['template']}; "
              f"Trips: new trip after {o['gap_days']:g} days without photos"
              f"{' or when the place changes' if o.get('split_on_place') else ''}; "
              f"{'Copy' if o['mode'] == 'copy' else 'Move'}; Photos without a location: {o['unknown']}",
              "Picture names: " + (f"the exact place put in each name ({o.get('name_pattern')})"
                                   if o.get("rename") else "kept as they are"), ""]
    if dry_run:
        lines += ["This is a trial run (dry run): nothing was moved or copied.", ""]
    elif out is not None:
        lines += [out.summary(), ""]
    names = {}
    if o.get("rename"):
        names = out.names if out is not None else {id(p): n for _g, p, n in renamed_names(plan, preview(plan, dest))}
        count = len(names)
        lines += [f"{count} picture{'s' if count != 1 else ''} "
                  f"{'would get' if out is None else 'got'} a new name with the exact place (old name → new "
                  f"name below).", ""]
    lines.append(f"New folders ({len(plan.groups)}):")
    for g in plan.groups:
        lines.append("")
        lines.append(g.describe())
        for p in g.photos:
            note = []
            if p.probably:
                note.append(f"probably: place guessed from {os.path.basename(p.guessed_from)}, taken around the "
                            f"same time")
            info = getattr(p, "info", None)
            if info is not None and info.probably:
                note.append("the place name is not certain")
            if p.date_source in ("file name", "file date"):
                note.append(f"date from the {p.date_source}")
            when = f"{p.taken:%Y-%m-%d %H:%M}" if p.taken else "no date"
            new = names.get(p.path) if out is not None else names.get(id(p))
            arrow = f" → {new}" if new else ""
            lines.append(f"  {os.path.relpath(p.path, plan.root)}{arrow}, {when}" +
                         (f" ({'; '.join(note)})" if note else ""))
    if plan.left:
        lines += ["", f"Left where they are ({len(plan.left)}):"]
        for p, reason in plan.left:
            lines.append(f"  {os.path.relpath(p.path, plan.root)}: {reason}")
    if out is not None and out.problems:
        lines += ["", "Problems:"]
        lines += [f"  {path}: {reason}" for path, reason in out.problems]
    if plan.problems:
        lines += ["", "Notes:"] + [f"  {p}" for p in plan.problems]
    lines += ["", "Place names:"]
    lines += [f"  {a}" for a in (plan.attributions or [])]
    lines += ["  Place names from the place packs: \u00a9 OpenStreetMap contributors, available under the Open "
              "Database License (ODbL), and the other open sources listed in the place packs' SOURCES.md.",
              "  Everything was worked out on this computer; no photo data was sent anywhere."]
    if out is not None and out.undo_path:
        lines += ["", f"To put everything back, use \"Undo the last sort\" (undo file: {out.undo_path})."]
    return "\n".join(lines) + "\n"


def write_report(plan, out, dest=None):
    """Write the report into the sorted folder (and a copy in the program's reports folder). Returns its path."""
    name = f"{APP_NAME} report {_stamp()}.txt"
    text = report_text(plan, out, dest)
    path = os.path.join(dest or plan.root, name)
    try:
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write(text)
    except OSError:
        path = ""
    copy_dir = os.path.join(st.home(), REPORT_FOLDER)
    os.makedirs(copy_dir, exist_ok=True)
    with open(os.path.join(copy_dir, name), "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path or os.path.join(copy_dir, name)
