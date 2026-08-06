"""Runnable checks for start-position plans: the target key, the Raid preset, the
override/preset fallback, and that only WASD survives a read.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_start_position.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.start_position import StartPositionStore  # noqa: E402
from sloppykeys.content.start_position import (  # noqa: E402
    MAX_HOLD_MS,
    PositionMove,
    preset_moves,
    target_key,
    total_hold_ms,
)

# # Target keys
assert target_key("Raid", "Spirit City", "Act 2") == "Raid/Spirit City/Act 2"
# A gamemode with no act dimension still has a usable two-part key.
assert target_key("Expedition", "Rose Kingdom", "") == "Expedition/Rose Kingdom"
# Anything less than gamemode + map isn't a target at all.
assert target_key("Raid", "", "Act 2") == ""
assert target_key("", "", "") == ""

# # The Raid Act 2 preset: s, d, s — 1s each
preset = preset_moves("Raid", "Spirit City", "Act 2")
assert [(move.key, move.hold_ms) for move in preset] == [("s", 1000), ("d", 1000), ("s", 1000)]
assert total_hold_ms(preset) == 3000
# Presets are copies: editing one must not poison the table for the next read.
preset[0].hold_ms = 99
assert preset_moves("Raid", "Spirit City", "Act 2")[0].hold_ms == 1000
act3 = preset_moves("Raid", "Spirit City", "Act 3")
assert [(move.key, move.hold_ms) for move in act3] == [("d", 2500)], act3

# Every other target starts empty.
assert preset_moves("Raid", "Spirit City", "Act 1") == []
assert preset_moves("Story", "Flower Forest", "Act 1") == []

# # Payload validation — this value ends up in a generated AHK Send()
assert PositionMove.from_payload({"key": "w", "hold_ms": 500}) == PositionMove("w", 500)
assert PositionMove.from_payload({"key": "S", "hold_ms": "1500"}) == PositionMove("s", 1500)
for bad in (
    {"key": "q", "hold_ms": 100},          # not a movement key
    {"key": "w down", "hold_ms": 100},     # not a single key
    {"key": "", "hold_ms": 100},
    {"hold_ms": 100},
    "w",
    None,
):
    assert PositionMove.from_payload(bad) is None, bad
# Out-of-range holds are clamped, not rejected.
assert PositionMove.from_payload({"key": "d", "hold_ms": 10**9}).hold_ms == MAX_HOLD_MS
assert PositionMove.from_payload({"key": "d", "hold_ms": -50}).hold_ms == 0
assert not PositionMove("d", 0).is_actionable()  # a 0ms hold does nothing

# # Store: preset until edited, then the edit, and an empty plan sticks
with tempfile.TemporaryDirectory() as root:
    store = StartPositionStore(root)
    assert not store.has_override("Raid", "Spirit City", "Act 2")
    assert len(store.moves("Raid", "Spirit City", "Act 2")) == 3
    assert store.moves("Story", "Flower Forest", "Act 1") == []

    assert store.set_moves("Raid", "Spirit City", "Act 2", [PositionMove("w", 750)])
    assert store.has_override("Raid", "Spirit City", "Act 2")
    reread = StartPositionStore(root).moves("Raid", "Spirit City", "Act 2")
    assert [(m.key, m.hold_ms) for m in reread] == [("w", 750)], reread

    # Clearing every move is a real answer: it must not fall back to the preset.
    assert store.set_moves("Raid", "Spirit City", "Act 2", [])
    assert StartPositionStore(root).moves("Raid", "Spirit City", "Act 2") == []

    # Reset drops the override so the preset comes back.
    assert store.clear("Raid", "Spirit City", "Act 2")
    assert len(store.moves("Raid", "Spirit City", "Act 2")) == 3
    assert store.clear("Raid", "Spirit City", "Act 2") is False  # nothing left to clear

    # An incomplete target can't be saved.
    assert store.set_moves("Raid", "", "Act 2", [PositionMove("w", 100)]) is False

    # Hand-edited rubbish in settings.json is dropped, not executed.
    path = os.path.join(root, "settings.json")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["start_position"] = {
        "Raid/Spirit City/Act 1": [
            {"key": "s", "hold_ms": 1000},
            {"key": "Escape", "hold_ms": 1000},
            "not a move",
        ]
    }
    payload["private_server_link"] = "keep me"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    survivors = StartPositionStore(root).moves("Raid", "Spirit City", "Act 1")
    assert [(m.key, m.hold_ms) for m in survivors] == [("s", 1000)], survivors

    # Writing a plan leaves the rest of settings.json alone.
    StartPositionStore(root).set_moves("Story", "Flower Forest", "Act 1", [PositionMove("a", 200)])
    with open(path, encoding="utf-8") as handle:
        after = json.load(handle)
    assert after["private_server_link"] == "keep me"
    assert set(after["start_position"]) == {"Raid/Spirit City/Act 1", "Story/Flower Forest/Act 1"}

print("start position: OK")
