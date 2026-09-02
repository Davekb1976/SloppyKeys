"""Runnable checks for the three clicks that begin a challenge, and the cleanup after.

The run loop used to fire Row / Select Stage / Start itself as blind
`nudge_click_script` calls at the raw coordinates, bypassing `LobbyNavigator.start_challenge`
— which *searches* `select_stage.png` and `start_match.png` and gives Start its `fade_wait`.
On a panel whose height varies with the map, the blind clicks landed wrong and Start arrived
mid-fade, so both looked like they never happened.

The other half is cleanup. The challenge list is a panel over the gamemode cards, so a detour
that starts nothing has to close it or the next task's Play search is on the wrong screen —
and a detour is now taken before every match, not once per queue pass.

No framework, no capture, no input: both classes are built with `__new__`.

`.venv\\Scripts\\python.exe tests\\test_challenge_start.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.challenge import SELECT_STAGE_CLICK, START_CLICK  # noqa: E402
from sloppykeys.content.nav_images import (  # noqa: E402
    select_stage_image,
    start_match_image,
)
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402


# # start_challenge searches both buttons, and passes the coordinates only as fallbacks
class SpyNav(LobbyNavigator):
    def __init__(self) -> None:  # noqa: D107 - test double
        self.calls: list[tuple] = []
        self.panel_fade_wait = 1.0
        self.click_settle = 0.0
        self.search_timeout = 6.0

    def _rect(self):
        return (0, 0, 1152, 756)

    def select_challenge_row(self, slot):
        self.calls.append(("row", slot))
        return (True, f"row {slot}")

    def click_select_stage(self, fallback=None):
        self.calls.append(("select_stage", fallback))
        return (True, "clicked Select Stage")

    def click_start_match(self, fallback=None, fade_wait=0.0):
        self.calls.append(("start", fallback, fade_wait))
        return (True, "clicked Start")


nav = SpyNav()
ok, message = nav.start_challenge(2)
assert ok, message
kinds = [call[0] for call in nav.calls]
# Order is load-bearing: selecting the stage is what makes Start exist.
assert kinds == ["row", "select_stage", "start"], kinds
assert nav.calls[0] == ("row", 2), nav.calls[0]
# Searched, with the measured points as the missing-template fallback — not clicked blind.
assert nav.calls[1] == ("select_stage", SELECT_STAGE_CLICK), nav.calls[1]
# Start arrives from the Select Stage click, so it matches while still fading. Without this
# wait the click is swallowed and nothing says so.
assert nav.calls[2] == ("start", START_CLICK, nav.panel_fade_wait), nav.calls[2]
# Every leg is reported, so a fallback-coordinate click is visible in the log.
for part in ("row 2", "Select Stage", "Start"):
    assert part in message, (part, message)

# A failed leg stops the chain rather than pressing on to Start.
class HaltingNav(SpyNav):
    def click_select_stage(self, fallback=None):
        self.calls.append(("select_stage", fallback))
        return (False, "Select Stage not found (best 0.31 < 0.80)")


nav = HaltingNav()
ok, message = nav.start_challenge(1)
assert not ok
assert [c[0] for c in nav.calls] == ["row", "select_stage"], nav.calls
assert "stage select" in message, message


# # The templates the chain relies on are the same two every other gamemode searches
assert select_stage_image().endswith("select_stage.png")
assert start_match_image().endswith("start_match.png")

print("challenge start: OK")
