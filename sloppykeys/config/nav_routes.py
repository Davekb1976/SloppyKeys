"""Saved Events routes: the custom maps/acts and their navigation steps.

Own file (`routes.json`) rather than a key inside `settings.json`: a route is
content, like a unit config, and a handful of routes with per-step regions is far
more data than the small scalars settings.json holds.

On-disk shape:

    {
      "Schema": 1,
      "Maps": {
        "Villain Invasion": {
          "Acts": ["Act 1", "Act 2"],
          "Routes": {"Act 1": [<NavStep payload>, ...]}
        }
      }
    }

`Shipped` is the other top-level key: the `"<Map>/<Act>"` names this install has already
been offered by a build (see `merge_shipped`).

A map always carries at least one act (`DEFAULT_ACT`) so the rest of the app sees
the same Gamemode / Map / Act shape it already handles — an event with no act
divisions is just one act called Main. That is what lets a task name an event and an
act the same way it names a Story map and act, with no special case anywhere else.

Names are validated through `safe_component` on the way in because they become
path segments: `assets/events/<Event>/` for the step templates and
`assets/reference/Events/<Event>/` for the placement backdrop.
"""

from __future__ import annotations

import os

from sloppykeys.content.nav_images import events_templates_dir
from sloppykeys.content.nav_route import NavStep

from .store import read_json, update_json
from .unit_configs import safe_component

ROUTES_FILE = "routes.json"
# Where a route's own captured templates live, as a relative path with forward slashes —
# `assets/events/`. Taken from `nav_images` so this file cannot drift from it again.
EVENTS_PREFIX = events_templates_dir().replace("\\", "/") + "/"
# The build's own copy of ROUTES_FILE, written beside it by `build_exe.py`. The installer
# replaces this one on every upgrade and leaves `routes.json` alone, which is what makes
# `merge_shipped` possible: `routes.json` *is* the user's file the moment they have one, so
# a shipped route has nowhere else to arrive from.
SHIPPED_FILE = "routes.default.json"
SCHEMA_VERSION = 1
DEFAULT_ACT = "Main"
NAME_MAX = 40


def clean_name(value: str) -> str:
    """A map or act name that is safe to use as a path segment. "" if unusable."""
    return safe_component(str(value).strip())[:NAME_MAX].strip()


def step_image(map_name: str, act: str, index: int) -> str:
    """Where a route step's captured template lives. One shape, used by the capture, the
    rename and the deletion sweep — three spellings of this was how a renamed event kept
    pointing at files under the old folder.

    The folder comes from `nav_images` rather than being spelled again: this said `images/`
    long after every template moved to `assets/`, which would have sent a capture to a tree
    nothing else reads.
    """
    return f"{EVENTS_PREFIX}{clean_name(map_name)}/{clean_name(act)}_{int(index)}.png"


def _reimage(step: dict, old_map: str, new_map: str, old_act: str, new_act: str) -> dict:
    """A step payload with its `Image` path moved to the new event/act folder.

    Only rewrites a path that actually sits under the old event's own folder. A step
    pointing at a shared or hand-placed template elsewhere in `assets/` is left alone —
    renaming an event is not a licence to rewrite a path it does not own.
    """
    if not isinstance(step, dict):
        return step
    image = str(step.get("Image") or "")
    if not image:
        return step
    prefix = f"{EVENTS_PREFIX}{clean_name(old_map)}/"
    spelled = image.replace("\\", "/")
    if not spelled.startswith(prefix):
        return step
    tail = spelled[len(prefix) :]
    stem = f"{clean_name(old_act)}_"
    if not tail.startswith(stem):
        # Same event folder, another act's file: the folder moves, the name does not.
        moved = f"{EVENTS_PREFIX}{clean_name(new_map)}/{tail}"
    else:
        moved = f"{EVENTS_PREFIX}{clean_name(new_map)}/{clean_name(new_act)}_{tail[len(stem):]}"
    step = dict(step)
    step["Image"] = moved
    return step


class RouteStore:
    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, ROUTES_FILE)

    # # Reads
    def _payload(self) -> dict:
        payload = read_json(self._path)
        return payload if isinstance(payload, dict) else {}

    def _maps(self) -> dict:
        raw = self._payload().get("Maps")
        return raw if isinstance(raw, dict) else {}

    def maps(self) -> list[str]:
        """Custom map names, in insertion order — this fills the Map dropdown."""
        return list(self._maps().keys())

    def acts(self, map_name: str) -> list[str]:
        entry = self._maps().get(map_name)
        if not isinstance(entry, dict):
            return []
        raw = entry.get("Acts")
        acts = [str(name) for name in raw if str(name).strip()] if isinstance(raw, list) else []
        # Never hand back an empty act list for a map that exists: the Run strip
        # would show a map that can't complete a selection.
        return acts or [DEFAULT_ACT]

    def steps(self, map_name: str, act: str) -> list[NavStep]:
        entry = self._maps().get(map_name)
        if not isinstance(entry, dict):
            return []
        routes = entry.get("Routes")
        if not isinstance(routes, dict):
            return []
        raw = routes.get(act or DEFAULT_ACT)
        if not isinstance(raw, list):
            return []
        return [NavStep.from_payload(item) for item in raw if isinstance(item, dict)]

    def has_map(self, map_name: str) -> bool:
        return map_name in self._maps()

    def all_images(self) -> set[str]:
        """Every template path referenced by any saved route.

        Used to decide whether a captured PNG is still wanted after a route, act or
        event is deleted: a file two routes share must survive the first deletion.
        """
        images: set[str] = set()
        for map_name, entry in self._maps().items():
            if not isinstance(entry, dict):
                continue
            for act in self.acts(map_name):
                images.update(step.image for step in self.steps(map_name, act) if step.image)
        return images

    def images_for(self, map_name: str, act: str = "") -> set[str]:
        """Template paths referenced by one route, or by every act of a map."""
        acts = [act] if act else self.acts(map_name)
        images: set[str] = set()
        for name in acts:
            images.update(step.image for step in self.steps(map_name, name) if step.image)
        return images

    # # Writes
    def _write(self, maps: dict) -> bool:
        """Replace `Maps`, keeping every other top-level key — `Shipped` is one."""

        def mutate(payload: dict) -> None:
            payload["Schema"] = SCHEMA_VERSION
            payload["Maps"] = maps

        return update_json(self._path, mutate)

    def merge_shipped(self) -> list[str]:
        """Add routes a new build ships that this install has never been offered.

        Returns the `"<Map> / <Act>"` names added, for the log.

        An upgrade can't overwrite `routes.json` — it holds the user's own events — so a
        route shipped with a new version would otherwise never reach anyone but a fresh
        install, while its unit config and images (new paths) arrive normally and sit there
        orphaned.

        **The `Shipped` ledger is what makes this safe to run every launch.** A name is
        recorded the first time it is seen whether or not anything was added, so an act the
        user deletes stays deleted instead of coming back on the next start. An act they
        already have is never touched: their steps are theirs, even under a shipped name.
        """
        shipped = read_json(os.path.join(os.path.dirname(self._path), SHIPPED_FILE))
        shipped_maps = shipped.get("Maps")
        if not isinstance(shipped_maps, dict):
            return []
        # Nothing new means no write at all. `update_json` writes whatever the callback
        # leaves behind, so without this every launch would rewrite `routes.json`.
        if not self._unseen(shipped_maps):
            return []

        added: list[str] = []

        def mutate(payload: dict) -> None:
            maps = payload.get("Maps")
            maps = maps if isinstance(maps, dict) else {}
            raw_seen = payload.get("Shipped")
            seen = [str(key) for key in raw_seen] if isinstance(raw_seen, list) else []
            known = set(seen)

            for raw_map, entry in shipped_maps.items():
                # Names off disk become path segments downstream, so they are cleaned here
                # rather than trusted, same as any name the user types.
                map_name = clean_name(raw_map)
                if not map_name or not isinstance(entry, dict):
                    continue
                routes = entry.get("Routes")
                routes = routes if isinstance(routes, dict) else {}
                raw_acts = entry.get("Acts")
                acts = raw_acts if isinstance(raw_acts, list) else []
                for raw_act in acts:
                    act = clean_name(raw_act)
                    if not act:
                        continue
                    key = f"{map_name}/{act}"
                    if key in known:
                        continue
                    known.add(key)
                    seen.append(key)
                    target = maps.get(map_name)
                    if not isinstance(target, dict):
                        target = {"Acts": [], "Routes": {}}
                    mine = target.get("Acts")
                    mine = [str(name) for name in mine] if isinstance(mine, list) else []
                    if act in mine:
                        continue
                    mine.append(act)
                    target["Acts"] = mine
                    steps = routes.get(raw_act)
                    if isinstance(steps, list):
                        own = target.get("Routes")
                        own = own if isinstance(own, dict) else {}
                        own[act] = [item for item in steps if isinstance(item, dict)]
                        target["Routes"] = own
                    maps[map_name] = target
                    added.append(f"{map_name} / {act}")

            payload["Schema"] = SCHEMA_VERSION
            payload["Maps"] = maps
            payload["Shipped"] = seen

        update_json(self._path, mutate)
        return added

    def _unseen(self, shipped_maps: dict) -> bool:
        """Does the shipped file name a `"<Map>/<Act>"` this install hasn't been offered?"""
        raw_seen = self._payload().get("Shipped")
        known = {str(key) for key in raw_seen} if isinstance(raw_seen, list) else set()
        for raw_map, entry in shipped_maps.items():
            map_name = clean_name(raw_map)
            if not map_name or not isinstance(entry, dict):
                continue
            raw_acts = entry.get("Acts")
            for raw_act in raw_acts if isinstance(raw_acts, list) else []:
                act = clean_name(raw_act)
                if act and f"{map_name}/{act}" not in known:
                    return True
        return False

    def add_map(self, map_name: str) -> str:
        """Create a map with one default act. Returns the stored name, or ""."""
        name = clean_name(map_name)
        if not name:
            return ""
        maps = self._maps()
        if name in maps:
            return name
        maps[name] = {"Acts": [DEFAULT_ACT], "Routes": {}}
        return name if self._write(maps) else ""

    def remove_map(self, map_name: str) -> bool:
        maps = self._maps()
        if map_name not in maps:
            return False
        del maps[map_name]
        return self._write(maps)

    def add_act(self, map_name: str, act: str) -> str:
        name = clean_name(act)
        maps = self._maps()
        entry = maps.get(map_name)
        if not name or not isinstance(entry, dict):
            return ""
        acts = self.acts(map_name)
        if name not in acts:
            acts.append(name)
        entry["Acts"] = acts
        maps[map_name] = entry
        return name if self._write(maps) else ""

    def remove_act(self, map_name: str, act: str) -> bool:
        maps = self._maps()
        entry = maps.get(map_name)
        if not isinstance(entry, dict):
            return False
        acts = [name for name in self.acts(map_name) if name != act]
        if not acts:
            return False  # a map keeps at least one act
        entry["Acts"] = acts
        routes = entry.get("Routes")
        if isinstance(routes, dict):
            routes.pop(act, None)
        maps[map_name] = entry
        return self._write(maps)

    def rename_map(self, old: str, new: str) -> str:
        """Rename an event, keeping its acts, routes and act order. Returns the stored name.

        `""` when the name is unusable or already taken — **rejected, not merged**. Merging
        two events' acts would silently discard one side's routes, and a name collision is
        a mistake worth reporting rather than resolving.

        Rewrites each step's `Image` path, because a step's template lives under
        `assets/events/<Event>/`. **This is only the record.** The file mover that went with
        it (`config/route_paths.rename_event`) was deleted with the PySide6 UI and nothing
        replaced it, so a rename here leaves the PNGs under the old folder name and the
        route's steps pointing at files that are not there. There is no rename in the web UI
        yet, which is the only reason that is not biting.
        """
        name = clean_name(new)
        maps = self._maps()
        if not name or old not in maps:
            return ""
        if name != old and name in maps:
            return ""
        # Rebuilt rather than mutated in place: a dict keeps insertion order, and renaming a
        # key by pop/insert would move the event to the end of the Map dropdown.
        renamed: dict = {}
        for key, entry in maps.items():
            if key != old:
                renamed[key] = entry
                continue
            if isinstance(entry, dict):
                entry = dict(entry)
                entry["Routes"] = {
                    act: [_reimage(step, old, name, act, act) for step in steps]
                    for act, steps in (entry.get("Routes") or {}).items()
                    if isinstance(steps, list)
                }
            renamed[name] = entry
        return name if self._write(renamed) else ""

    def rename_act(self, map_name: str, old: str, new: str) -> str:
        """Rename one act of an event, keeping its position in the act order.

        `""` when unusable, unknown, or already an act of this event — same reason as
        `rename_map`: two acts merged is one route silently lost.
        """
        name = clean_name(new)
        maps = self._maps()
        entry = maps.get(map_name)
        if not name or not isinstance(entry, dict):
            return ""
        acts = self.acts(map_name)
        if old not in acts or (name != old and name in acts):
            return ""
        entry = dict(entry)
        entry["Acts"] = [name if act == old else act for act in acts]
        routes = entry.get("Routes")
        if isinstance(routes, dict):
            entry["Routes"] = {
                (name if act == old else act): [
                    _reimage(step, map_name, map_name, old, name) if act == old else step
                    for step in steps
                ]
                for act, steps in routes.items()
                if isinstance(steps, list)
            }
        maps[map_name] = entry
        return name if self._write(maps) else ""

    def set_steps(self, map_name: str, act: str, steps: list[NavStep]) -> bool:
        maps = self._maps()
        entry = maps.get(map_name)
        if not isinstance(entry, dict):
            return False
        routes = entry.get("Routes")
        if not isinstance(routes, dict):
            routes = {}
        routes[act or DEFAULT_ACT] = [step.as_payload() for step in steps]
        entry["Routes"] = routes
        maps[map_name] = entry
        return self._write(maps)
