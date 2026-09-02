"""Rebindable hotkeys.

Keys are polled with GetAsyncKeyState (see core/win32/bindings), so a bind is a
Windows virtual-key code plus which modifiers must be held. Stored in
settings.json under "keybinds" without disturbing the other settings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
KEYBINDS_KEY = "keybinds"
GAME_KEYS_KEY = "game_keys"

# Action id -> human label, in display order.
ACTIONS: dict[str, str] = {
    "start": "Start",
    "pause": "Pause",
    "stop": "Stop",
    "reload": "Reload",
    "image_manager": "Image Manager",
    "compact_mode": "Compact Mode",
}

# In-game keys the macro *presses* through AHK, matching the game's own binds.
# Deliberately separate from ACTIONS: nothing polls these, so binding one here
# must never make the app react to that key being pressed.
GAME_ACTIONS: dict[str, str] = {
    "priority": "Priority",
    "upgrade": "Upgrade",
    "sell": "Sell",
    "autoupgrade": "Auto Upgrade",
}
GAME_DEFAULTS: dict[str, str] = {
    "priority": "r",
    "upgrade": "t",
    "sell": "x",
    "autoupgrade": "v",
}


# What may appear in a string the macro *types* into a game search field. Letters, digits,
# space, apostrophe and hyphen — enough for any item name the game shows, and inert inside
# an AutoHotkey double-quoted string.
SEARCH_TEXT_ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 '-"
)
# Longer than any item name, short enough that a pasted paragraph can't become a script.
SEARCH_TEXT_MAX = 40


def sanitize_search_text(raw: object) -> str:
    """Reduce a typed search string to something safe for `SendText`, or "" if it isn't.

    Same trust boundary as `sanitize_game_key`, and the same answer: a generated AutoHotkey
    script *is* code, so this whitelists and **rejects rather than repairs**. One character
    outside the set fails the whole string.

    Rejecting matters more here than tidying would. Backtick is still special inside an
    AHK string even in text mode, and quotes end the literal — but the reason not to just
    drop the offending characters is the game, not the script: a portal is consumed when it
    is activated, so typing a *different* string than the user asked for can filter the list
    to the wrong item and spend it. A step that refuses and says why costs a run; a step
    that silently searches for something else costs the item.
    """
    text = str(raw or "").strip()
    if not text or len(text) > SEARCH_TEXT_MAX:
        return ""
    if any(char not in SEARCH_TEXT_ALLOWED for char in text):
        return ""
    return text


def sanitize_game_key(raw: object) -> str:
    """Reduce input to one safe key character, or "" if it isn't usable.

    These values get interpolated into generated AutoHotkey scripts, so this is a
    trust boundary: anything but a single letter or digit is rejected rather than
    escaped. That keeps `Send("{...}")` from being handed braces, quotes or
    commands regardless of what ends up in settings.json.
    """
    text = str(raw or "").strip().lower()
    if len(text) != 1 or not text.isalnum() or not text.isascii():
        return ""
    return text


@dataclass
class Keybind:
    vk: int
    ctrl: bool = False
    shift: bool = False
    alt: bool = False

    def display(self) -> str:
        parts: list[str] = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.shift:
            parts.append("Shift")
        if self.alt:
            parts.append("Alt")
        parts.append(vk_name(self.vk))
        return " + ".join(parts)

    def to_dict(self) -> dict:
        return {"vk": self.vk, "ctrl": self.ctrl, "shift": self.shift, "alt": self.alt}

    @classmethod
    def from_dict(cls, raw: object) -> "Keybind | None":
        if not isinstance(raw, dict) or "vk" not in raw:
            return None
        try:
            return cls(
                vk=int(raw["vk"]),
                ctrl=bool(raw.get("ctrl", False)),
                shift=bool(raw.get("shift", False)),
                alt=bool(raw.get("alt", False)),
            )
        except (TypeError, ValueError):
            return None


DEFAULTS: dict[str, Keybind] = {
    "start": Keybind(0x70),                 # F1
    "pause": Keybind(0x71),                 # F2
    "stop": Keybind(0x72),                  # F3
    "reload": Keybind(0x73),                # F4
    "image_manager": Keybind(0x75),         # F6
    "compact_mode": Keybind(0x76),          # F7
}


def vk_name(vk: int) -> str:
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    return _SPECIAL.get(vk, f"0x{vk:02X}")


_SPECIAL = {
    0x20: "Space",
    0x0D: "Enter",
    0x09: "Tab",
    0x08: "Backspace",
    0x2D: "Insert",
    0x2E: "Delete",
    0x24: "Home",
    0x23: "End",
    0x21: "PageUp",
    0x22: "PageDown",
    0xBC: ",",
    0xBE: ".",
    0xBF: "/",
    0xDB: "[",
    0xDD: "]",
}


class KeybindStore:
    def __init__(self, app_root: str) -> None:
        import os

        self._path = os.path.join(app_root, SETTINGS_FILE)

    def all(self) -> dict[str, Keybind]:
        raw = read_json(self._path).get(KEYBINDS_KEY, {})
        result: dict[str, Keybind] = {}
        for action in ACTIONS:
            bind = Keybind.from_dict(raw.get(action)) if isinstance(raw, dict) else None
            result[action] = bind or DEFAULTS[action]
        return result

    def get(self, action: str) -> Keybind:
        return self.all().get(action, DEFAULTS[action])

    def set(self, action: str, keybind: Keybind) -> None:
        entry = keybind.to_dict()

        def mutate(payload: dict) -> None:
            binds = payload.get(KEYBINDS_KEY)
            if not isinstance(binds, dict):
                binds = {}
            binds[action] = entry
            payload[KEYBINDS_KEY] = binds

        update_json(self._path, mutate)


class GameKeyStore:
    """In-game keys, stored in settings.json under "game_keys".

    Kept apart from KeybindStore because these are outputs (keys the macro sends)
    rather than inputs (hotkeys the app watches for).
    """

    def __init__(self, app_root: str) -> None:
        import os

        self._path = os.path.join(app_root, SETTINGS_FILE)

    def all(self) -> dict[str, str]:
        raw = read_json(self._path).get(GAME_KEYS_KEY, {})
        result = dict(GAME_DEFAULTS)
        if isinstance(raw, dict):
            for action in GAME_DEFAULTS:
                key = sanitize_game_key(raw.get(action))
                if key:
                    result[action] = key
        return result

    def get(self, action: str) -> str:
        return self.all().get(action, GAME_DEFAULTS.get(action, ""))

    def set(self, action: str, key: str) -> bool:
        """Persist one key. Returns False (and writes nothing) if the action is
        unknown or the key isn't a usable single character."""
        if action not in GAME_DEFAULTS:
            return False
        clean = sanitize_game_key(key)
        if not clean:
            return False
        def mutate(payload: dict) -> None:
            keys = payload.get(GAME_KEYS_KEY)
            if not isinstance(keys, dict):
                keys = {}
            keys[action] = clean
            payload[GAME_KEYS_KEY] = keys

        update_json(self._path, mutate)
        return True
