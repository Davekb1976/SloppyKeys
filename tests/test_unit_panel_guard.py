"""Runnable checks for the unit-panel guard on the unit-action blocks.

Upgrade, sell and target priority press `t`, `x` and `r` at a placed unit. Those keys are
only unit actions while that unit's panel is open — with no panel they go into the game
world. So each of those blocks has to prove the panel is up before it presses anything, and
press *nothing at all* when it cannot. A fixed settle used to stand in for the proof, which
cannot tell a swallowed click from a selection.

Asserted with a fake placer and a fake AHK bridge, so nothing captures a screen or fires
input. Any script reaching the fake bridge is a keypress: with the click delegated to the
placer, these handlers build no other kind of script.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_unit_panel_guard.py`
"""

from __future__ import annotations

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.units import PRIORITY_OPTIONS  # noqa: E402
from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.placement import UnitPlacer  # noqa: E402

# An app root with no settings.json, so `_game_keybind` answers from its own defaults
# (t/x/r/v). Deliberately not the repo root: the real file holds the private-server link
# and the webhook, and a test has no business opening it.
EMPTY_ROOT = tempfile.mkdtemp(prefix="sk-guard-")

# Window at a known origin, viewport at the pinned reference size, so `_client_to_screen`
# is a pure offset and the point handed to the guard is checkable.
RECT = (100, 200, 1152, 756)
UNIT_CLIENT = (500, 400)
UNIT_SCREEN = (600, 600)


class FakePlacer:
    """Confirms the panel for the first `opens` selections, then never again."""

    def __init__(self, opens: int = 99) -> None:
        self.opens = opens
        self.selections: list[tuple[int, int]] = []
        self.parks = 0

    def open_unit_panel_at(self, sx: int, sy: int, label: str = "") -> tuple[bool, str]:
        self.selections.append((sx, sy))
        if len(self.selections) <= self.opens:
            return (True, f"panel open at {sx},{sy}")
        return (False, "unit panel never appeared")

    def park(self) -> None:
        self.parks += 1


class FakeAhk:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def run(self, script: str, wait: bool = False, timeout: float = 0.0):
        self.scripts.append(script)
        return (True, "")


def controller(placer: FakePlacer, ahk: FakeAhk) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    ctrl._placer = placer
    ctrl._ahk = ahk
    ctrl._app_root = EMPTY_ROOT
    ctrl._rect = lambda: RECT
    ctrl._log = lambda _m: None
    ctrl._upgrade_state = {}
    return ctrl


def presses(ahk: FakeAhk) -> list[tuple[str, int]]:
    """(key, count) for every key script the handler sent. Empty means nothing was pressed."""
    out: list[tuple[str, int]] = []
    for script in ahk.scripts:
        key = re.search(r'Send\("\{(\w+)\}"\)', script)
        count = re.search(r"Loop (\d+) \{", script)
        assert key is not None and count is not None, script
        out.append((key.group(1), int(count.group(1))))
    return out


def block(btype: str, **params) -> dict:
    """A unit-action block carrying its own coordinates (the legacy shape `index` falls back
    to), so nothing here needs a whole phase table to resolve."""
    extra = {k: params.pop(k) for k in ("autograde",) if k in params}
    return {
        "type": btype,
        "params": {"x": UNIT_CLIENT[0], "y": UNIT_CLIENT[1], **params},
        **extra,
    }


def drain(ctrl: MacroController, blk: dict, max_ticks: int = 20) -> int:
    """Run the block the way the match loop does. Returns the tick it finished on."""
    for tick in range(1, max_ticks + 1):
        if ctrl._tick_upgrade_unit(blk):
            return tick
    raise AssertionError(f"never finished in {max_ticks} ticks")


# # The point the guard is given is the *converted* one
placer, ahk = FakePlacer(), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_sell_unit(block("sell_unit")) is True
assert placer.selections == [UNIT_SCREEN], placer.selections
assert presses(ahk) == [("x", 1)], presses(ahk)
assert placer.parks == 0, placer.parks

# # Panel never appears: the key is not pressed, and the cursor leaves the unit
placer, ahk = FakePlacer(opens=0), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_sell_unit(block("sell_unit")) is True  # skipped, not retried forever
assert len(placer.selections) == 1, placer.selections
assert presses(ahk) == [], presses(ahk)
assert placer.parks == 1, placer.parks

# # Upgrade: one press per repeat, and every repeat re-verifies
placer, ahk = FakePlacer(), FakeAhk()
ctrl = controller(placer, ahk)
assert drain(ctrl, block("upgrade_unit", times=3)) == 3
assert len(placer.selections) == 3, placer.selections
assert presses(ahk) == [("t", 1)] * 3, presses(ahk)
assert ctrl._upgrade_state == {}, ctrl._upgrade_state

# # Upgrade whose panel stops appearing part way: the remaining presses are abandoned
placer, ahk = FakePlacer(opens=1), FakeAhk()
ctrl = controller(placer, ahk)
assert drain(ctrl, block("upgrade_unit", times=3)) == 2
assert len(placer.selections) == 2, placer.selections
assert presses(ahk) == [("t", 1)], presses(ahk)
assert ctrl._upgrade_state == {}, ctrl._upgrade_state  # state cleared, so a loop re-asserts
assert placer.parks == 1, placer.parks

# # Auto upgrade: `times` is the level, one verified selection, one run of presses
placer, ahk = FakePlacer(), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_upgrade_unit(block("upgrade_unit", times=4, autograde=True)) is True
assert len(placer.selections) == 1, placer.selections
assert presses(ahk) == [("v", 4)], presses(ahk)

placer, ahk = FakePlacer(opens=0), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_upgrade_unit(block("upgrade_unit", times=4, autograde=True)) is True
assert presses(ahk) == [], presses(ahk)
assert ctrl._upgrade_state == {}, ctrl._upgrade_state

# # Target priority: the press count is the option's index
placer, ahk = FakePlacer(), FakeAhk()
ctrl = controller(placer, ahk)
assert PRIORITY_OPTIONS.index("Closest") == 2, PRIORITY_OPTIONS
assert ctrl._tick_target_priority(block("target_priority", priority="Closest")) is True
assert len(placer.selections) == 1, placer.selections
assert presses(ahk) == [("r", 2)], presses(ahk)

placer, ahk = FakePlacer(opens=0), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_target_priority(block("target_priority", priority="Closest")) is True
assert presses(ahk) == [], presses(ahk)

# # The first option is where a fresh unit already sits: no press, so no click either
placer, ahk = FakePlacer(), FakeAhk()
ctrl = controller(placer, ahk)
assert ctrl._tick_target_priority(block("target_priority", priority=PRIORITY_OPTIONS[0])) is True
assert placer.selections == [], placer.selections
assert presses(ahk) == [], presses(ahk)

# # An unusable keybind costs no click: nothing to press means nothing to select, and a
# # panel opened by a block that then presses nothing is a panel left over the board.
for btype, params in (
    ("upgrade_unit", {"times": 2}),
    ("upgrade_unit", {"times": 2, "autograde": True}),
    ("sell_unit", {}),
    ("target_priority", {"priority": "Closest"}),
):
    placer, ahk = FakePlacer(), FakeAhk()
    ctrl = controller(placer, ahk)
    ctrl._safe_game_key = lambda _action: ""
    handler = {
        "upgrade_unit": ctrl._tick_upgrade_unit,
        "sell_unit": ctrl._tick_sell_unit,
        "target_priority": ctrl._tick_target_priority,
    }[btype]
    assert handler(block(btype, **params)) is True, (btype, params)
    assert placer.selections == [], (btype, params, placer.selections)
    assert presses(ahk) == [], (btype, params, presses(ahk))

# # No coordinate resolves: still nothing pressed
for btype, params in (
    ("upgrade_unit", {"times": 2}),
    ("sell_unit", {}),
    ("target_priority", {"priority": "Closest"}),
):
    placer, ahk = FakePlacer(), FakeAhk()
    ctrl = controller(placer, ahk)
    blk = {"type": btype, "params": dict(params)}  # no x/y, no index
    handler = {
        "upgrade_unit": ctrl._tick_upgrade_unit,
        "sell_unit": ctrl._tick_sell_unit,
        "target_priority": ctrl._tick_target_priority,
    }[btype]
    assert handler(blk) is True, btype
    assert placer.selections == [], (btype, placer.selections)
    assert presses(ahk) == [], (btype, presses(ahk))

# # Both entry points to the guard still resolve on the placer, and the client-space one
# # offsets exactly once. Double-offsetting is the mistake `_click_screen` exists for.
assert callable(getattr(UnitPlacer, "open_unit_panel_at"))
assert callable(getattr(UnitPlacer, "open_unit_panel"))
assert callable(getattr(MacroController, "_select_unit"))

real = UnitPlacer.__new__(UnitPlacer)
real._rect = lambda: RECT
seen: list[tuple] = []
real.open_unit_panel_at = lambda sx, sy, label="": (seen.append((sx, sy, label)), (True, ""))[1]
assert real.open_unit_panel(*UNIT_CLIENT) == (True, "")
assert seen == [(UNIT_SCREEN[0], UNIT_SCREEN[1], "500,400")], seen

# # No window, no click: the guard reports the fault instead of clicking the desktop
no_window = UnitPlacer.__new__(UnitPlacer)
no_window._rect = lambda: None
ok, message = no_window.open_unit_panel(*UNIT_CLIENT)
assert ok is False and "Roblox not found" in message, message

os.rmdir(EMPTY_ROOT)
print("unit panel guard: OK")
