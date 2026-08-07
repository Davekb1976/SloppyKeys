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

A map always carries at least one act (`DEFAULT_ACT`) so the rest of the app sees
the same Gamemode / Map / Act shape it already handles — an event with no act
divisions is just one act called Main. That keeps `configs/Events/<Map>/<Act>.json`
identical in shape to Story and Raid, with no special case in `UnitConfigStore`.

Names are validated through `safe_component` on the way in because they become
path segments for the unit config and the reference image.
"""

from __future__ import annotations

import os

from sloppykeys.content.nav_route import NavStep

from .store import read_json, write_json
from .unit_configs import safe_component

ROUTES_FILE = "routes.json"
SCHEMA_VERSION = 1
DEFAULT_ACT = "Main"
NAME_MAX = 40


def clean_name(value: str) -> str:
    """A map or act name that is safe to use as a path segment. "" if unusable."""
    return safe_component(str(value).strip())[:NAME_MAX].strip()


def step_image(map_name: str, act: str, index: int) -> str:
    """Where a route step's captured template lives. One shape, used by the capture, the
    rename and the deletion sweep — three spellings of this was how a renamed event kept
    pointing at files under the old folder."""
    return f"images/events/{clean_name(map_name)}/{clean_name(act)}_{int(index)}.png"


def _reimage(step: dict, old_map: str, new_map: str, old_act: str, new_act: str) -> dict:
    """A step payload with its `Image` path moved to the new event/act folder.

    Only rewrites a path that actually sits under the old event's own folder. A step
    pointing at a shared or hand-placed template elsewhere in `images/` is left alone —
    renaming an event is not a licence to rewrite a path it does not own.
    """
    if not isinstance(step, dict):
        return step
    image = str(step.get("Image") or "")
    if not image:
        return step
    prefix = f"images/events/{clean_name(old_map)}/"
    spelled = image.replace("\\", "/")
    if not spelled.startswith(prefix):
        return step
    tail = spelled[len(prefix) :]
    stem = f"{clean_name(old_act)}_"
    if not tail.startswith(stem):
        # Same event folder, another act's file: the folder moves, the name does not.
        moved = f"images/events/{clean_name(new_map)}/{tail}"
    else:
        moved = f"images/events/{clean_name(new_map)}/{clean_name(new_act)}_{tail[len(stem):]}"
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
        return write_json(self._path, {"Schema": SCHEMA_VERSION, "Maps": maps})

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
        `images/events/<Event>/`. The files are moved by `route_paths.rename_event`; this is
        only the record of where they now are, so the two have to be run together.
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
