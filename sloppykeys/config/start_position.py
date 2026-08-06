"""Per-target start-position plans, stored in settings.json.

Layout, alongside the other settings without disturbing them (same approach as
DelaysStore):

    "start_position": {
        "Raid/Spirit City/Act 2": [{"key": "s", "hold_ms": 2000}, ...]
    }

A target with no entry falls back to its preset in `content/start_position.py`. An
entry that is an empty list is a deliberate "no moves here", which is why presence
of the key matters and not just truthiness — otherwise clearing a preset would
silently restore it on the next read.
"""

from __future__ import annotations

import os

from sloppykeys.content.start_position import PositionMove, preset_moves, target_key

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
START_POSITION_KEY = "start_position"


class StartPositionStore:
    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)

    # # Reads
    def _all(self) -> dict[str, object]:
        raw = read_json(self._path).get(START_POSITION_KEY, {})
        return raw if isinstance(raw, dict) else {}

    def has_override(self, gamemode: str, map_name: str, act: str) -> bool:
        key = target_key(gamemode, map_name, act)
        return bool(key) and isinstance(self._all().get(key), list)

    def moves(self, gamemode: str, map_name: str, act: str) -> list[PositionMove]:
        """The plan for this target: the user's own list if they have edited it,
        otherwise the preset. Unusable entries are dropped, not repaired."""
        key = target_key(gamemode, map_name, act)
        if not key:
            return []
        stored = self._all().get(key)
        if not isinstance(stored, list):
            return preset_moves(gamemode, map_name, act)
        moves = [PositionMove.from_payload(raw) for raw in stored]
        return [move for move in moves if move is not None]

    # # Writes
    def set_moves(
        self, gamemode: str, map_name: str, act: str, moves: list[PositionMove]
    ) -> bool:
        key = target_key(gamemode, map_name, act)
        if not key:
            return False
        entries = [move.as_payload() for move in moves]

        def mutate(payload: dict) -> None:
            plans = payload.get(START_POSITION_KEY)
            if not isinstance(plans, dict):
                plans = {}
            plans[key] = entries
            payload[START_POSITION_KEY] = plans

        update_json(self._path, mutate)
        return True

    def clear(self, gamemode: str, map_name: str, act: str) -> bool:
        """Drop the override so the target goes back to its preset."""
        key = target_key(gamemode, map_name, act)
        if not key:
            return False
        if key not in self._all():
            return False
        removed = False

        def mutate(payload: dict) -> None:
            nonlocal removed
            plans = payload.get(START_POSITION_KEY)
            if not isinstance(plans, dict) or key not in plans:
                return
            del plans[key]
            payload[START_POSITION_KEY] = plans
            removed = True

        update_json(self._path, mutate)
        return removed
