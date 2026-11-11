"""Downloading packs as they are needed, anonymously, from the public releases of github.com/mark-getbraille/place-packs.

  Catalogue(base_url=PUBLIC_RELEASE, cache_path=None, opener=None, max_age=7 days)
      .packs() -> {key: manifest.PackInfo}    packs.json, read at most once per max_age (kept in the pack folder)
  ensure_pack(region_id, part="core", folder=None, ask=None, progress=None, catalogue=None) -> path
      ask(question) -> True to download (None: yes); progress(done, total). The file must have exactly the size and
      SHA-256 of packs.json, otherwise it is deleted. When a pack of the region is already there (an older one), the
      new file is merged with it first (merge_local): every row the older one had is kept. A parent region
      (gb-england, us-texas: regions.json "children") is its sub-regions: each child's part is downloaded (one
      question for all) and the first child's path is returned; the parent's own older file of that part, if any,
      is removed once every child's is there (the children hold the same and more).
  ensure_packs(region_id, parts=None, detail=None, full=False, ...) -> [paths]   the parts a lookup needs:
      parts_for(detail, full) unless parts are given; a detail part that is not published (a region without address
      points) is left out quietly, and a failed detail part never stops the others (the lookup works without it).
  parts_for(detail=None, full=False) -> ("core", "extra"[, "businesses", "addresses"])   the businesses and the
      addresses only for the detail "address" or "exact" (the exact place in a picture's name), or full detail.
  updates_available(folder=None, catalogue=None) -> [PackInfo]    newer versions of the packs that are installed
      (an installed parent pack is updated as its children's packs)
  installed(folder=None) -> {key: {"sha256", "name", "built_month"}}   (installed.json in the pack folder)
Standard library only (urllib). Only the pack's file is requested; nothing about the user is sent.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import time
import urllib.request

from placepacks import fmt, manifest
from placepacks.lookup import close_readers, default_folder

PUBLIC_RELEASE = "https://github.com/mark-getbraille/place-packs/releases/download/packs/"
MANIFEST = "packs.json"
USER_AGENT = "place-packs-client/2 (+https://github.com/mark-getbraille/place-packs)"
WEEK = 7 * 24 * 3600


class PackError(Exception):
    """A pack that cannot be listed or downloaded now, with a plain message."""


def _open(url, timeout=60):
    """Open a URL with the User-Agent (GitHub's redirect to its download host is followed by urllib)."""
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


class Catalogue:
    """The published packs (see the module docstring). opener(url) -> a response, for the tests."""

    def __init__(self, base_url=PUBLIC_RELEASE, cache_path=None, opener=None, max_age=WEEK, now=time.time):
        self.base_url, self.max_age, self.now = base_url, max_age, now
        self.cache_path = cache_path or os.path.join(default_folder(), MANIFEST)
        self.open = opener or _open
        self._packs = None

    def cached(self):
        """The packs from the cache file, whatever its age ({} when there is none)."""
        try:
            with open(self.cache_path, "rb") as f:
                return manifest.parse(f.read())
        except (OSError, ValueError):
            return {}

    def fresh(self):
        """True when the cache file is younger than max_age."""
        try:
            return self.now() - os.path.getmtime(self.cache_path) < self.max_age
        except OSError:
            return False

    def packs(self, refresh=False):
        """{key: PackInfo}: the cache when it is fresh, else packs.json from the release (kept in the cache).
        Raises PackError when it cannot be read and there is no cache."""
        if self._packs is not None and not refresh:
            return self._packs
        if not refresh and self.fresh():
            self._packs = self.cached()
            if self._packs:
                return self._packs
        try:
            with self.open(self.base_url + MANIFEST) as r:
                data = r.read(manifest.LIMIT + 1)
            packs = manifest.parse(data)
        except (OSError, ValueError) as e:
            old = self.cached()
            if old:
                self._packs = old
                return old
            raise PackError(f"The list of place packs could not be read ({e}).") from None
        os.makedirs(os.path.dirname(os.path.abspath(self.cache_path)), exist_ok=True)
        with open(self.cache_path + ".partial", "wb") as f:
            f.write(data)
        os.replace(self.cache_path + ".partial", self.cache_path)
        self._packs = packs
        return packs


def local_name(key):
    """The pack's file name in the pack folder (the same for every version): "us-vermont.osmpack"."""
    return key + fmt.PACK_SUFFIX


def installed(folder=None):
    """{key: {"sha256", "name", "built_month"}} of the downloaded packs (installed.json)."""
    try:
        with open(os.path.join(folder or default_folder(), "installed.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_installed(folder, data):
    """Write installed.json."""
    path = os.path.join(folder, "installed.json")
    with open(path + ".partial", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(path + ".partial", path)


def merge_local(new_path, old_path):
    """Keep every row of the older pack in the newer one (the published packs already keep their history; this
    also keeps rows of a pack built elsewhere). Rows whose key is in the new pack's removals are not brought back."""
    con = sqlite3.connect(new_path)
    try:
        con.execute("ATTACH DATABASE ? AS old", (old_path,))
        removed = "(SELECT key FROM main.removals)"
        have = {s: {r[0] for r in con.execute(f"SELECT name FROM {s}.sqlite_master WHERE type = 'table'")}
                for s in ("main", "old")}
        typed = {"types", "point_types", "area_types"}
        for table in ("points", "areas", "lines", "ranges"):
            # The columns both packs have (an older pack may lack one a newer pack has).
            old_cols = {r[1] for r in con.execute(f"PRAGMA old.table_info({table})")}
            cols = [r[1] for r in con.execute(f"PRAGMA main.table_info({table})") if r[1] != "id" and r[1] in old_cols]
            c = ", ".join(cols)
            start = con.execute(f"SELECT COALESCE(MAX(id), 0) FROM main.{table}").fetchone()[0]
            con.execute(f"INSERT INTO main.{table} ({c}) SELECT {c} FROM old.{table} o WHERE o.key NOT IN {removed} "
                        f"AND NOT EXISTS (SELECT 1 FROM main.{table} m WHERE m.key = o.key AND m.first = o.first "
                        f"AND m.name IS o.name) ORDER BY o.id")
            links = {"points": "point_types", "areas": "area_types"}.get(table)
            if links and typed <= have["main"] and typed <= have["old"]:
                # The kept rows' type phrases: the same rows in the same order, so the i-th old row is start + i.
                kept = [r[0] for r in con.execute(
                    f"SELECT o.id FROM old.{table} o WHERE o.key NOT IN {removed} AND EXISTS (SELECT 1 FROM main."
                    f"{table} m WHERE m.id > ? AND m.key = o.key AND m.first = o.first AND m.name IS o.name) "
                    f"ORDER BY o.id", (start,))]
                for i, old_id in enumerate(kept, start=1):
                    row = con.execute(f"SELECT t.name FROM old.{links} l JOIN old.types t ON t.id = l.type WHERE "
                                      f"l.id = ?", (old_id,)).fetchone()
                    if row:
                        con.execute("INSERT OR IGNORE INTO main.types (name) VALUES (?)", (row[0],))
                        tid = con.execute("SELECT id FROM main.types WHERE name = ?", (row[0],)).fetchone()[0]
                        con.execute(f"INSERT OR REPLACE INTO main.{links} VALUES (?, ?)", (start + i, tid))
                    brand = (con.execute("SELECT b.name, b.wikidata FROM old.point_brands l JOIN old.brands b ON "
                                         "b.id = l.brand WHERE l.id = ?", (old_id,)).fetchone()
                             if table == "points" and {"brands", "point_brands"} <= have["old"] and
                             {"brands", "point_brands"} <= have["main"] else None)
                    if brand:
                        con.execute("INSERT OR IGNORE INTO main.brands (name, wikidata) VALUES (?, ?)", brand)
                        bid = con.execute("SELECT id FROM main.brands WHERE name = ? AND wikidata = ?",
                                          brand).fetchone()[0]
                        con.execute("INSERT OR REPLACE INTO main.point_brands VALUES (?, ?)", (start + i, bid))
                    note = (con.execute("SELECT n.text FROM old.point_notes l JOIN old.notes n ON n.id = l.note "
                                        "WHERE l.id = ?", (old_id,)).fetchone()
                            if table == "points" and {"notes", "point_notes"} <= have["old"] and
                            {"notes", "point_notes"} <= have["main"] else None)
                    if note:
                        con.execute("INSERT OR IGNORE INTO main.notes (text) VALUES (?)", note)
                        nid = con.execute("SELECT id FROM main.notes WHERE text = ?", note).fetchone()[0]
                        con.execute("INSERT OR REPLACE INTO main.point_notes VALUES (?, ?)", (start + i, nid))
        con.commit()
        con.execute("DETACH DATABASE old")
    finally:
        con.close()


DETAILS_NEEDING_PARTS = ("address", "exact")


def parts_for(detail=None, full=False):
    """The parts a lookup needs: core and extra; the businesses and the addresses too for the detail "address" or
    "exact" (the exact place in a picture's name, Describe this picture), or when the user asked for full detail."""
    if full or detail in DETAILS_NEEDING_PARTS:
        return fmt.DEFAULT_PARTS + fmt.DETAIL_PARTS
    return fmt.DEFAULT_PARTS


def _children(region_id):
    """The sub-regions of a parent region ([] for any other region)."""
    from placepacks.regions import REGIONS
    r = REGIONS.get(region_id) or {}
    return list(r.get("children") or [])


def _ensure_children(region_id, children, part, folder, ask, progress, catalogue, update):
    """ensure_pack for a parent: every child's part, after one question for all of them."""
    from placepacks.regions import region_label
    cat = catalogue or Catalogue(cache_path=os.path.join(folder, MANIFEST))
    published = cat.packs()
    keys = [(c, manifest.key_of(c, part)) for c in children]
    infos = [(c, published[k]) for c, k in keys if k in published]
    if not infos:
        raise PackError(f"No place pack is published for {region_label(region_id)} ({part}) yet.")
    have = installed(folder)
    todo = [(c, i) for c, i in infos if not os.path.exists(os.path.join(folder, local_name(i.key))) or
            (update and have.get(i.key, {}).get("sha256") != i.sha256)]
    if todo and ask is not None and not ask(
            f"The place packs for {region_label(region_id)} are available ({len(todo)} areas, "
            f"{sum(i.size for _, i in todo) / 1e6:.0f} MB). Download now?"):
        raise PackError("Not downloaded.")
    paths = []
    for child, info in infos:
        paths.append(ensure_pack(child, part, folder, None, progress, cat, update))
    if len(infos) == len(keys):
        _drop_parent(region_id, part, folder)
    return paths


def _drop_parent(region_id, part, folder):
    """Remove a parent's own older pack of a part once every child's is here: it holds nothing they lack (the
    combined pack is published for programs that know only the parent)."""
    key = manifest.key_of(region_id, part)
    if part in fmt.DEFAULT_PARTS and os.path.exists(os.path.join(folder, local_name(key))):
        remove_pack(key, folder)


def ensure_packs(region_id, parts=None, detail=None, full=False, folder=None, ask=None, progress=None,
                 catalogue=None, update=False):
    """[paths] of the parts of a region (or of a parent's sub-regions) a lookup needs (see the module docstring).
    Raises PackError only when core cannot be had."""
    folder = folder or default_folder()
    paths = []
    for part in parts or parts_for(detail, full):
        try:
            got = ensure_pack(region_id, part, folder, ask, progress, catalogue, update, all_paths=True)
        except PackError:
            if part == "core":
                raise
            continue                        # a lookup works without the other parts
        except OSError:
            if part == "core":
                raise
            continue
        paths += got
    return paths


def ensure_pack(region_id, part="core", folder=None, ask=None, progress=None, catalogue=None, update=False,
                all_paths=False):
    """The path of a region's pack, downloading it when it is not there (or, with update, when a newer one is
    published). See the module docstring. all_paths: return [paths] (a parent's children). Raises PackError when it
    is not published or not wanted.

    While packs.json does not list a parent's sub-regions yet (a program newer than the published packs), the
    parent's own pack is used for the parent and for each of its children; with no list at all (offline), the packs
    already here."""
    from placepacks.regions import parent_of
    folder = folder or default_folder()
    children = _children(region_id)
    here = lambda rid: os.path.join(folder, local_name(manifest.key_of(rid, part)))  # noqa: E731
    if children:
        local = [here(c) for c in children if os.path.exists(here(c))]
        if local and len(local) == len(children) and not update:
            _drop_parent(region_id, part, folder)
            return local if all_paths else local[0]
        cat = catalogue or Catalogue(cache_path=os.path.join(folder, MANIFEST))
        try:
            published = cat.packs()
        except PackError:
            found = local or ([here(region_id)] if os.path.exists(here(region_id)) else [])
            if found:
                return found if all_paths else found[0]
            raise
        if any(manifest.key_of(c, part) in published for c in children):
            paths = _ensure_children(region_id, children, part, folder, ask, progress, cat, update)
            return paths if all_paths else paths[0]
        catalogue = cat                         # not listed yet: the parent's own pack
    elif parent_of(region_id) and not os.path.exists(here(region_id)):
        cat = catalogue or Catalogue(cache_path=os.path.join(folder, MANIFEST))
        try:
            published = cat.packs()
        except PackError:
            published = {}
            if os.path.exists(here(parent_of(region_id))):
                return [here(parent_of(region_id))] if all_paths else here(parent_of(region_id))
        if manifest.key_of(region_id, part) not in published and \
                manifest.key_of(parent_of(region_id), part) in published:
            region_id = parent_of(region_id)    # not listed yet: the parent's own pack holds it
        catalogue = cat
    key = manifest.key_of(region_id, part)
    target = os.path.join(folder, local_name(key))
    if os.path.exists(target) and not update:
        return [target] if all_paths else target
    cat = catalogue or Catalogue(cache_path=os.path.join(folder, MANIFEST))
    info = cat.packs().get(key)
    if info is None:
        raise PackError(f"No place pack is published for {region_id} ({part}) yet.")
    have = installed(folder).get(key, {})
    if os.path.exists(target) and have.get("sha256") == info.sha256:
        return [target] if all_paths else target
    if ask is not None and not ask(f"{'A newer place pack' if os.path.exists(target) else 'The place pack'} for "
                                   f"{region_id} is available ({info.size / 1e6:.0f} MB). Download now?"):
        raise PackError("Not downloaded.")
    os.makedirs(folder, exist_ok=True)
    part_file = target + ".download"
    digest, done = hashlib.sha256(), 0
    with cat.open(cat.base_url + info.name) as r, open(part_file, "wb") as f:
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            done += len(block)
            if done > info.size:
                break
            f.write(block)
            digest.update(block)
            if progress:
                progress(done, info.size)
    if done != info.size or digest.hexdigest() != info.sha256:
        os.remove(part_file)
        raise PackError("The downloaded place pack is not exactly the published file, so it was deleted.")
    if os.path.exists(target):
        close_readers(target)
        merge_local(part_file, target)
    close_readers(target)
    os.replace(part_file, target)
    data = installed(folder)
    data[key] = {"sha256": info.sha256, "name": info.name, "built_month": info.built_month}
    _save_installed(folder, data)
    return [target] if all_paths else target


def updates_available(folder=None, catalogue=None):
    """[PackInfo] of installed packs with a newer published version. An installed pack of a parent region (made
    before it had sub-regions) is updated as its children's packs: their PackInfos are given instead."""
    folder = folder or default_folder()
    cat = catalogue or Catalogue(cache_path=os.path.join(folder, MANIFEST))
    have = installed(folder)
    packs = cat.packs()
    out = []
    for k, v in have.items():
        info = packs.get(k)
        if not os.path.exists(os.path.join(folder, local_name(k))):
            continue
        region, part = manifest.split_key(k) or ("", "")
        children = _children(region)
        if children:
            for child in children:
                ck = manifest.key_of(child, part)
                if ck in packs and ck not in have and packs[ck] not in out:
                    out.append(packs[ck])
        elif info is not None and info.sha256 != v.get("sha256"):
            out.append(info)
    return out


def remove_pack(key, folder=None):
    """Delete an installed pack (closing it first). Returns True if it was there."""
    folder = folder or default_folder()
    target = os.path.join(folder, local_name(key))
    close_readers(target)
    data = installed(folder)
    data.pop(key, None)
    if os.path.isdir(folder):
        _save_installed(folder, data)
    if os.path.exists(target):
        os.remove(target)
        return True
    return False


def add_pack_file(path, folder=None):
    """Copy a pack file into the pack folder under its key's name. Returns the new path."""
    from placepacks.lookup import PackReader
    reader = PackReader(path)
    key = manifest.key_of(reader.region_id or os.path.basename(path)[:-len(fmt.PACK_SUFFIX)], reader.part)
    reader.close()
    folder = folder or default_folder()
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, local_name(key))
    close_readers(target)
    shutil.copyfile(path, target + ".partial")
    os.replace(target + ".partial", target)
    return target
