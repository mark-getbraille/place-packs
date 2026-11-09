"""The start of the program, and its command line.

  photo-location-identifier                       open the main window
  photo-location-identifier --open FOLDER         open the main window on a folder (File Explorer's "Sort pictures
                                                  by location"; a folder given on its own does the same)
  photo-location-identifier --folder FOLDER ...   sort without any window (power users, scripts and the tests):
      --detail trip-area|place|town|county|state|country   (default trip-area)
      --time none|year|month|trip                          (default year)
      --template "{place} {year}"                          folder names; \\ or / for folders inside folders
      --gap-days 2  --split-on-place                       how trips are split
      --copy (or --move, the default)
      --unknown leave|unknown|guess  --guess-hours 3       photos without a location
      --to FOLDER                                          make the new folders there (default: the folder itself)
      --rename (or --keep-names)                           put the exact place in each picture's name (off by
                                                           default): the folder keeps the broad place
      --name-pattern date-place-name|place-date-name|place-name   the new names' order (implies --rename):
                                                           "2005-07-14 Jockey's Ridge State Park (IMG_1234).jpg"
      --no-subfolders  --no-videos
      --packs ask|auto|never  --packs-folder FOLDER  --yes  place packs (ask: asks on the console; --yes says yes)
      --my-places FILE                                     My places from this file instead of the saved ones
      --dry-run                                            show what would happen; nothing is moved
      --report FILE                                        also write the report there
  photo-location-identifier --undo-last           undo the last sort
Options left out use the choices last saved in the main window.
Exit codes: 0 done, 1 something went wrong, 2 the command line was not right.
"""

import argparse
import os
import sys

from pli import APP_NAME, __version__, grouping, job, myplaces, settings, sorter
from pli.places import Places


def _attach_console():
    """The installed program is a window program, so it has no console. When it is run from a Command Prompt, write
    to that one (Windows only; nothing happens elsewhere)."""
    if os.name != "nt" or (sys.stdout is not None and getattr(sys.stdout, "isatty", lambda: False)()):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = sys.stdout
    except Exception:  # noqa: BLE001 - no console: the report file says it all
        pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
        sys.stderr = sys.stdout


def parser():
    """The command-line parser."""
    p = argparse.ArgumentParser(prog="photo-location-identifier",
                                description=f"{APP_NAME}: sort pictures into folders by where (and when) they were "
                                            f"taken. Without --folder the window opens.")
    p.add_argument("open_folder", nargs="?", default="", help="open the window on this folder")
    p.add_argument("--open", default="", help="open the window on this folder")
    p.add_argument("--folder", default="", help="sort this folder without opening a window")
    p.add_argument("--detail", choices=grouping.DETAILS, default=None)
    p.add_argument("--time", choices=grouping.TIMES, default=None)
    p.add_argument("--template", default=None)
    p.add_argument("--gap-days", type=float, default=None)
    p.add_argument("--split-on-place", action="store_true", default=None)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--copy", dest="mode", action="store_const", const="copy")
    mode.add_argument("--move", dest="mode", action="store_const", const="move")
    p.add_argument("--unknown", choices=grouping.UNKNOWN_CHOICES, default=None)
    p.add_argument("--guess-hours", type=float, default=None)
    p.add_argument("--to", default="", help="make the new folders in this folder")
    names = p.add_mutually_exclusive_group()
    names.add_argument("--rename", dest="rename", action="store_const", const=True, default=None,
                       help="put the exact place in each picture's name")
    names.add_argument("--keep-names", dest="rename", action="store_const", const=False,
                       help="keep the pictures' names (the default)")
    p.add_argument("--name-pattern", choices=grouping.NAME_PATTERNS, default=None,
                   help="the order of the new names: date-place-name (2005-07-14 Jockey's Ridge State Park "
                        "(IMG_1234).jpg), place-date-name, or place-name; implies --rename")
    p.add_argument("--no-subfolders", action="store_true")
    p.add_argument("--no-videos", action="store_true")
    p.add_argument("--packs", choices=settings.PACK_MODES, default=None)
    p.add_argument("--packs-folder", default="")
    p.add_argument("--yes", action="store_true", help="answer yes to every download question")
    p.add_argument("--my-places", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", default="")
    p.add_argument("--undo-last", action="store_true")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p


def options_from(args, saved=None):
    """grouping.options() from the command line, the saved settings filling what is not given."""
    saved = saved or {}
    get = lambda name: getattr(args, name) if getattr(args, name) is not None else saved.get(name)  # noqa: E731
    rename = get("rename")
    if args.name_pattern is not None and args.rename is None:
        rename = True                      # --name-pattern on its own means: rename, with this pattern
    return grouping.options(detail=get("detail"), time=get("time"), template=get("template"),
                            gap_days=get("gap_days"), split_on_place=get("split_on_place"), mode=get("mode"),
                            unknown=get("unknown"), guess_hours=get("guess_hours"),
                            subfolders=not args.no_subfolders, videos=not args.no_videos,
                            rename=rename, name_pattern=get("name_pattern"))


def console_ask(yes):
    """The pack question on the console: always yes with --yes, else asked when there is someone to answer."""
    def ask(label, size, count):
        if yes:
            return True
        if not sys.stdin or not sys.stdin.isatty():
            print(f"The place pack for {label} is needed for {count} photos; not downloaded (add --yes, or "
                  f"--packs auto).")
            return False
        answer = input(f"Download the place pack for {label} ({size / 1e6:.0f} MB) for {count} photos? [y/N] ")
        return answer.strip().lower().startswith("y")
    return ask


def run_sort(args):
    """Sort --folder from the command line. Returns the exit code."""
    ok, why = job.is_sortable_folder(args.folder)
    if not ok:
        print(why, file=sys.stderr)
        return 2
    saved = settings.load()
    try:
        opts = options_from(args, saved)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    mine = myplaces.MyPlaces.load(args.my_places or settings.my_places_path())
    places = Places(my_places=mine, packs_folder=args.packs_folder or None)
    last = [""]

    def progress(text, done, total):
        if text != last[0]:
            print(text + "...", flush=True)
            last[0] = text
    plan, _ = job.build_plan(os.path.abspath(args.folder), opts, places, args.packs or saved.get("packs", "ask"),
                             ask=console_ask(args.yes), progress=progress)
    dest = os.path.abspath(args.to) if args.to else plan.root
    if args.dry_run:
        text = sorter.report_text(plan, dest=dest, dry_run=True)
        print(text)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(text)
        return 0
    os.makedirs(dest, exist_ok=True)
    out = sorter.apply(plan, dest, progress=lambda d, t, f: None)
    print(out.summary())
    for g in plan.groups:
        print(f"  {g.folder}: {len(g.photos)} photos")
    print(f"Report: {out.report_path}")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(sorter.report_text(plan, out, dest))
    return 1 if out.problems else 0


def run_undo():
    """Undo the last sort from the command line. Returns the exit code."""
    path = sorter.last_undo()
    if not path:
        print("There is no sort to undo.")
        return 1
    print(f"Undoing {sorter.describe_undo(path)}...")
    restored, problems = sorter.undo(path)
    print(f"Put back {restored} files.")
    for p, reason in problems:
        print(f"  {p}: {reason}")
    return 1 if problems else 0


def main(argv=None):
    """Start the program (see the module docstring). Returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    args = parser().parse_args(argv)
    if args.folder or args.undo_last:
        _attach_console()
        try:
            sys.stdout.reconfigure(errors="replace")   # a console that cannot show "→" shows "?" instead
        except (AttributeError, ValueError):
            pass
        return run_undo() if args.undo_last else run_sort(args)
    from pli.gui.main_window import run
    return run(args.open or args.open_folder)


if __name__ == "__main__":
    sys.exit(main())
