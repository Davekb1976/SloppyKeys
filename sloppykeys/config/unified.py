"""Unified settings accessor for the webview bridge.

One class that reads and writes all keys in settings.json. Auto-saves on every
set — no save button. Each set() call is atomic (update_json under the lock).

This is the new single point of entry for the bridge's get_settings/set_setting
API. The existing per-concern stores (DelaysStore, StatsTracker,
KeybindStore, etc.) continue working independently — they all write to the same
file through the same update_json lock. This class does NOT replace them: it
provides a flat key→value interface for the UI, while the stores own their
domain logic (validation, defaults, migrations).
"""

from __future__ import annotations

import os
from typing import Any

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"

# All known top-level keys and their defaults. A missing key returns its default
# on read. Keys not in this table are still preserved — user data from other
# stores (tasks, delays, stats, keybinds, etc.) lives alongside these.
DEFAULTS: dict[str, Any] = {
    # General
    "private_server_link": "empty",
    "discord_webhook": "",
    # Optional. Pinged on a loss, and only if the webhook itself is set.
    "discord_user_id": "",
    "hard_mode": False,
    "camera_once_per_session": False,
    "auto_update": True,
    # New settings
    "start_minimized": False,
    "auto_reopen_roblox": True,
    # There is no `action_delay_ms`. It was a General-tab number box promising an extra pause
    # after every click, and nothing in this tree ever read it. A stored value is ignored
    # harmlessly — `UnifiedSettings.get` only answers for keys this table declares. Real
    # per-step waits live in `config/delays.py::DELAY_SPEC`, which the Delays tab builds itself.
    "debug_screenshots": False,
    # Image thresholds (per-name overrides, dict)
    "image_thresholds": {},
}


class UnifiedSettings:
    """Flat get/set over settings.json. Auto-saves on every set."""

    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)

    def get_all(self) -> dict[str, Any]:
        """All settings with defaults merged in. Unknown keys from disk are preserved."""
        stored = read_json(self._path)
        merged = dict(DEFAULTS)
        merged.update(stored)
        return merged

    def get(self, key: str, default: Any = None) -> Any:
        """One key, with a fallback to DEFAULTS or the caller's default."""
        stored = read_json(self._path)
        if key in stored:
            return stored[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def set(self, key: str, value: Any) -> bool:
        """Write one key atomically. Returns True on success."""
        def mutate(payload: dict) -> None:
            payload[key] = value

        return update_json(self._path, mutate)

    def set_many(self, changes: dict[str, Any]) -> bool:
        """Write multiple keys in one atomic operation."""
        def mutate(payload: dict) -> None:
            payload.update(changes)

        return update_json(self._path, mutate)

    def delete(self, key: str) -> bool:
        """Remove a key (revert to default on next read)."""
        def mutate(payload: dict) -> None:
            payload.pop(key, None)

        return update_json(self._path, mutate)

    # -- Hotkeys (nested under "hotkeys" key) --

    def get_hotkeys(self) -> dict[str, str]:
        from .keybinds import DEFAULTS as KB_DEFAULTS, KeybindStore

        # Read through the existing store so defaults and validation stay in one place.
        store = KeybindStore(os.path.dirname(self._path))
        binds = store.all()
        return {action: bind.display() for action, bind in binds.items()}

    def reset_hotkeys(self) -> dict[str, str]:
        from .keybinds import DEFAULTS as KB_DEFAULTS

        def mutate(payload: dict) -> None:
            payload["keybinds"] = {
                action: bind.to_dict() for action, bind in KB_DEFAULTS.items()
            }

        update_json(self._path, mutate)
        return {action: bind.display() for action, bind in KB_DEFAULTS.items()}

    # -- Delays (nested under "delays" key) --

    def get_delays(self) -> dict[str, float]:
        from .delays import DEFAULTS as DELAY_DEFAULTS, DELAYS_KEY

        stored = read_json(self._path).get(DELAYS_KEY, {})
        result = dict(DELAY_DEFAULTS)
        if isinstance(stored, dict):
            for key in DELAY_DEFAULTS:
                try:
                    result[key] = float(stored[key])
                except (KeyError, TypeError, ValueError):
                    pass
        return result

    def set_delay(self, key: str, value: float) -> bool:
        from .delays import DEFAULTS as DELAY_DEFAULTS, DELAYS_KEY

        if key not in DELAY_DEFAULTS:
            return False

        def mutate(payload: dict) -> None:
            delays = payload.get(DELAYS_KEY)
            if not isinstance(delays, dict):
                delays = {}
            delays[key] = float(value)
            payload[DELAYS_KEY] = delays

        return update_json(self._path, mutate)

    # -- Tasks (nested under "tasks" key) --

    def get_tasks(self) -> list[dict]:
        raw = read_json(self._path).get("tasks", [])
        return raw if isinstance(raw, list) else []

    def set_tasks(self, tasks: list[dict]) -> bool:
        def mutate(payload: dict) -> None:
            payload["tasks"] = tasks

        return update_json(self._path, mutate)

    # -- Stats (nested under "stats" key) --

    def get_stats(self) -> dict[str, int]:
        raw = read_json(self._path).get("stats", {})
        if not isinstance(raw, dict):
            return {"wins": 0, "losses": 0}
        return {
            "wins": max(0, int(raw.get("wins", 0))),
            "losses": max(0, int(raw.get("losses", 0))),
        }
