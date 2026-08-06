"""Saving and loading unit plans per farm target.

Layout:  configs/<Gamemode>/<Map>/<Target>.json
e.g.     configs/Story/Fairy King Forest/Act 3.json
         configs/Expedition/School Grounds/Difficulty 2.json
"""

from __future__ import annotations

import os

from sloppykeys.content.gamemodes import has_targets
from sloppykeys.content.units import TOTAL_STEPS, UnitPlan, UnitStep

from .store import read_json, write_json

CONFIGS_DIR_NAME = "configs"

# Bump when a change to the on-disk shape can't be read by simply defaulting
# missing keys. Adding a field does not need a bump; the readers default.
SCHEMA_VERSION = 1


def safe_component(value: str) -> str:
    """One path segment from a display name. Shared with the placement picker's
    reference images, so any name that becomes a path goes through here."""
    cleaned = str(value).strip()
    for illegal in '<>:"/\\|?*':
        cleaned = cleaned.replace(illegal, "-")
    # No traversal: none of the real gamemode/map/act names contain "..", so this
    # only ever fires on something that shouldn't be building a path.
    return cleaned.replace("..", "-")


class UnitConfigStore:
    def __init__(self, app_root: str) -> None:
        self._root = os.path.join(app_root, CONFIGS_DIR_NAME)

    @property
    def root(self) -> str:
        return self._root

    def path_for(self, gamemode: str, map_name: str, target: str) -> str | None:
        """configs/<Gamemode>/<Map>/<Target>.json, or configs/<Gamemode>/<Map>.json
        for a gamemode with no target dimension (Expedition — its difficulty is a
        setting, not a separate farm target)."""
        if not gamemode or not map_name:
            return None
        if not has_targets(gamemode):
            return os.path.join(
                self._root,
                safe_component(gamemode),
                f"{safe_component(map_name)}.json",
            )
        if not target:
            return None
        return os.path.join(
            self._root,
            safe_component(gamemode),
            safe_component(map_name),
            f"{safe_component(target)}.json",
        )

    def exists(self, gamemode: str, map_name: str, target: str) -> bool:
        path = self.path_for(gamemode, map_name, target)
        return bool(path) and os.path.isfile(path)

    def load(self, gamemode: str, map_name: str, target: str) -> UnitPlan:
        path = self.path_for(gamemode, map_name, target)
        if path is None or not os.path.isfile(path):
            return UnitPlan.empty()

        payload = read_json(path)
        raw_steps = payload.get("Units", [])
        if not isinstance(raw_steps, list):
            return UnitPlan.empty()

        plan = UnitPlan.empty()
        for position, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict) or position > TOTAL_STEPS:
                continue
            step = UnitStep.from_payload(raw_step, fallback_step=position)
            if 1 <= step.step <= TOTAL_STEPS:
                plan.steps[step.step - 1] = step

        return plan

    def save(self, gamemode: str, map_name: str, target: str, plan: UnitPlan) -> str | None:
        path = self.path_for(gamemode, map_name, target)
        if path is None:
            return None

        payload = {
            "Schema": SCHEMA_VERSION,
            "Gamemode": gamemode,
            "Map": map_name,
            "Target": target,
            # Only steps carrying data are written. The loader starts from an
            # empty 72-step plan and slots each entry in by its "Step" number, so
            # a sparse list restores identically and keeps the file readable.
            "Units": [step.as_payload() for step in plan.steps if _has_data(step)],
        }
        return path if write_json(path, payload) else None


def _has_data(step: UnitStep) -> bool:
    """True when a step holds anything worth saving, so blank steps are skipped."""
    blank = UnitStep(step=step.step)
    return step.as_payload() != blank.as_payload()
