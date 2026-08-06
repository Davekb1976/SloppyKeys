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
