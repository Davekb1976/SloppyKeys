"""Runnable checks for the `autoplay` block's click/verify cycle.

The block's whole value is the verification: it must not report success on a click the
client swallowed, and it must not spin forever when the active template never matches.
Both are asserted here with a fake navigator, so nothing touches a screen or fires input.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_autoplay_block.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import autoplay_active_image, autoplay_image  # noqa: E402
from sloppykeys.macro.controller import AUTOPLAY_CLICKS, MacroController  # noqa: E402

ACTIVE = autoplay_active_image()
OFF = autoplay_image()


class FakeNav:
    """Reports the toggle as on only after `flips_after` clicks. 0 = on from the start."""

    def __init__(self, flips_after: int = 1) -> None:
        self.flips_after = flips_after
        self.clicks = 0

    def sighted(self, path: str) -> bool:
        assert path == ACTIVE, path  # the block must verify the *active* crop, not the button
        return self.clicks >= self.flips_after

    def click_button(self, path: str, label: str):
        assert path == OFF, path
        self.clicks += 1
        return (True, f"clicked {label}")


class FakeEngine:
    def __init__(self, exists: bool = True) -> None:
        self._exists = exists

    def template_exists(self, _path: str) -> bool:
        return self._exists


def controller(nav, engine=None) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    ctrl._nav = nav
    ctrl._engine = engine or FakeEngine()
    ctrl._log = lambda _m: None
    return ctrl


def drain(ctrl, block, max_ticks: int = 40) -> int:
    """Run the block like the match loop does, ignoring its recheck gap. Returns tick count."""
    for tick in range(1, max_ticks + 1):
        # The gap is wall-clock, so a test must not sleep through it: clearing it each tick
        # is what the real loop does over time.
        for state in getattr(ctrl, "_autoplay_state", {}).values():
            state["next_look"] = 0.0
        if ctrl._tick_autoplay(block):
            return tick
    raise AssertionError(f"never finished in {max_ticks} ticks")


# # Already on: one look, no click
nav = FakeNav(flips_after=0)
ctrl = controller(nav)
block = {"type": "autoplay", "params": {}}
assert drain(ctrl, block) == 1
assert nav.clicks == 0, nav.clicks

# # One click takes
nav = FakeNav(flips_after=1)
ctrl = controller(nav)
block = {"type": "autoplay", "params": {}}
ticks = drain(ctrl, block)
assert nav.clicks == 1, nav.clicks
# Tick 1 clicks, tick 2 sees it on — the click is never trusted in the tick that fired it.
assert ticks == 2, ticks

# # The click is swallowed twice, then takes
nav = FakeNav(flips_after=3)
ctrl = controller(nav)
block = {"type": "autoplay", "params": {}}
drain(ctrl, block)
assert nav.clicks == 3, nav.clicks

# # Never takes: bounded, and it reports done so the match plays on
nav = FakeNav(flips_after=99)
ctrl = controller(nav)
block = {"type": "autoplay", "params": {}}
drain(ctrl, block)
assert nav.clicks == AUTOPLAY_CLICKS, nav.clicks

# # State is cleared on every exit, so a block in a loop phase re-asserts next cycle
nav = FakeNav(flips_after=1)
ctrl = controller(nav)
block = {"type": "autoplay", "params": {}}
drain(ctrl, block)
assert ctrl._autoplay_state == {}, ctrl._autoplay_state
# Second cycle with the toggle switched back off: it clicks again rather than being spent.
nav.flips_after = 2
drain(ctrl, block)
assert nav.clicks == 2, nav.clicks

# # No template captured: inert, not a stall, and it never clicks
nav = FakeNav(flips_after=99)
ctrl = controller(nav, engine=FakeEngine(exists=False))
block = {"type": "autoplay", "params": {}}
assert drain(ctrl, block) == 1
assert nav.clicks == 0, nav.clicks

# # The loop bookkeeping treats it like any other block
assert MacroController._runs_once({"type": "autoplay"}) is False
assert MacroController._runs_once({"type": "autoplay", "once": True}) is True

print("autoplay block: OK")
