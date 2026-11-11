"""The steps from a folder to a Plan, shared by the command line and the windows:

  1. find the photos (and their companion files)
  2. read where and when each was taken
  3. get the place packs the positions need (ask first, automatically, or never: the setting): core and extra, and
     the businesses and address points too with "Put the exact place in each picture's name" or full detail
  4. look up the places and work out the folders (grouping.make_plan)
  5. with "Put the exact place in each picture's name", look up the exact place of each photo (look_up_spots)

progress(step_text, done, total) is called throughout; stop() True ends early (the plan then holds what was read).
"""

import os

from pli import grouping, photos as ph
from pli.places import Places


def build_plan(folder, opts, places=None, packs="ask", ask=None, progress=None, stop=None):
    """The Plan for folder with opts (grouping.options()). places: a places.Places (None: placepacks' packs and My
    places from the settings). packs: "ask" (ask(label, size_bytes, photo_count) -> True to download), "auto" or
    "never". Returns (plan, notes): notes are things to tell the user (packs downloaded or not)."""
    if places is None:
        from pli import myplaces, settings
        places = Places(my_places=myplaces.MyPlaces.load(settings.my_places_path()),
                        full_detail=settings.load().get("full_detail", False))

    def say(text, done=0, total=0):
        if progress:
            progress(text, done, total)
    say("Finding the photos")
    found = ph.find_photos(folder, opts.get("subfolders", True), opts.get("videos", True))
    total = len(found)
    ph.read_all(found, progress=lambda d, t, p: say("Reading where and when each photo was taken", d, t),
                stop=stop)
    notes = []
    positions = [(p.lat, p.lon) for p in found if p.has_location]
    if positions and not (stop and stop()):
        say("Checking the place packs")
        got, problems = places.get_packs(positions, packs, ask=ask,
                                         progress=lambda label, d=0, t=0: say(f"Downloading the place pack for "
                                                                              f"{label}", d, t),
                                         exact=bool(opts.get("rename")))
        notes += [f"Downloaded the place pack for {g}." for g in got] + problems
    plan = grouping.make_plan(folder, found, places, opts,
                              progress=lambda d, t, p: say("Looking up the places", d, t), stop=stop)
    if opts.get("rename") and not (stop and stop()):
        look_up_spots(plan, places, progress=lambda d, t: say("Looking up the exact place of each photo", d, t),
                      stop=stop)
    plan.problems = notes + plan.problems
    say(f"Found {total} photos", total, total)
    return plan, notes


def look_up_spots(plan, places, progress=None, stop=None):
    """Give each photo in the plan's new folders (not "Unknown place", not a guessed position) its exact place,
    photo.spot (places.Places.exact), for its new name. progress(done, total) as it goes."""
    todo = [p for g in plan.groups if not g.unknown for p in g.photos if p.has_location and not p.probably]
    for i, p in enumerate(todo):
        if stop and stop():
            break
        p.spot = places.exact(p.lat, p.lon, p.taken, p.altitude)
        if progress:
            progress(i + 1, len(todo))


def is_sortable_folder(folder):
    """(True, "") if folder exists and is a folder, else (False, why)."""
    if not folder:
        return False, "Choose a folder first."
    if not os.path.isdir(folder):
        return False, f"{folder} is not a folder that exists."
    return True, ""
