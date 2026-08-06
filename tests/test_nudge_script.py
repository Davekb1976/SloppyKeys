"""Runnable checks for the nudge's geometry: the wiggle must stay off the target,
the last movement before the click must be the target itself, and a world-space
(tight) nudge must wiggle sideways rather than up — vertical screen motion is depth
in the game's camera, so an upward wiggle drags the placement ghost across the map.

No framework, no input fired (the script text is only rendered, never run):
`.venv\\Scripts\\python.exe tests\\test_nudge_script.py`
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro import input_scripts  # noqa: E402
from sloppykeys.macro.input_scripts import (  # noqa: E402
    SPREAD_TIGHT,
    SPREAD_WIDE,
    nudge_click_script,
)

MOVE = re.compile(r"MouseMove\((-?\d+), (-?\d+)")


def moves(script: str) -> list[tuple[int, int]]:
    return [(int(mx), int(my)) for mx, my in MOVE.findall(script)]


TARGET = (400, 300)

# # World clicks: sideways only, and they land on the target last
tight = moves(nudge_click_script(*TARGET, spread=SPREAD_TIGHT))
assert tight[-1] == TARGET, tight
assert all(point[1] == TARGET[1] for point in tight), f"tight nudge moved vertically: {tight}"
assert max(abs(point[0] - TARGET[0]) for point in tight) <= SPREAD_TIGHT, tight
# The wiggle has to actually leave the target, or there is no hover event.
assert any(point != TARGET for point in tight), tight

# # Lobby clicks keep the vertical swing they were tuned with
wide = moves(nudge_click_script(*TARGET, spread=SPREAD_WIDE))
assert wide[-1] == TARGET, wide
assert any(point[1] != TARGET[1] for point in wide), wide
assert max(abs(point[1] - TARGET[1]) for point in wide) <= SPREAD_WIDE, wide

# # The click comes after the final move plus the settle hold
script = nudge_click_script(*TARGET, spread=SPREAD_TIGHT)
last_move = script.rindex(f"MouseMove({TARGET[0]}, {TARGET[1]}")
assert script.index('Click("Left")') > last_move, "click precedes the landing move"
assert script.index(f"Sleep({input_scripts.nudge_settle_ms()})") > last_move, "settle is not on target"

# # The settle is a frame count, not a duration: Roblox drains queued mouse-moves per
# rendered frame, so the same milliseconds cover fewer frames on a slower monitor and the
# click lands on a stale cursor position. Every rate must buy the same frames, and the
# 165Hz panel it was tuned on must be untouched.
assert input_scripts.nudge_settle_ms(165) == 200, input_scripts.nudge_settle_ms(165)
assert input_scripts.nudge_settle_ms(60) == 550, input_scripts.nudge_settle_ms(60)
for hz in (165, 120, 100, 75, 60):
    frames = input_scripts.nudge_settle_ms(hz) * hz / 1000
    assert abs(frames - input_scripts.NUDGE_SETTLE_FRAMES) < 0.5, (hz, frames)
# Clamped: never shorter than the tuned value, never absurd on a bogus reading.
assert input_scripts.nudge_settle_ms(240) == input_scripts.NUDGE_SETTLE_MIN_MS
assert input_scripts.nudge_settle_ms(1) == input_scripts.NUDGE_SETTLE_MAX_MS
# Changing the rate changes *only* the settle, not the movement or the clicks.
input_scripts.set_refresh_hz(165)
tuned = nudge_click_script(*TARGET, spread=SPREAD_TIGHT)
input_scripts.set_refresh_hz(60)
slow = nudge_click_script(*TARGET, spread=SPREAD_TIGHT)
assert tuned.replace("Sleep(200)", "Sleep(550)") == slow, "only the settle may differ"
input_scripts.set_refresh_hz(input_scripts.TUNED_REFRESH_HZ)

# # Cost shape: no activate wait when Roblox is already focused, no trailing gap
assert "if !WinActive(" in script, "the activate must be skipped when already active"
assert script.index("WinActivate(") > script.index("if !WinActive("), script
# One click means no CLICK_GAP_MS at all; the gap only separates repeats.
single = nudge_click_script(*TARGET)
repeat = nudge_click_script(*TARGET, count=3)
assert "A_Index > 1" in single, single
assert single.count("Click(") == repeat.count("Click(") == 1  # one Click inside a Loop
assert "Loop 1 {" in single and "Loop 3 {" in repeat

# # The no-nudge path still lands on the target (kept for re-testing USE_NUDGE)
input_scripts.USE_NUDGE = False
try:
    plain = moves(nudge_click_script(*TARGET, spread=SPREAD_TIGHT))
    assert plain == [TARGET], plain
finally:
    input_scripts.USE_NUDGE = True

print("nudge script: OK")
