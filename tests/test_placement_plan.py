"""Runnable checks for how a plan turns into a run: step ordering, priority
presses, the auto-upgrade press count, and the sell delay surviving a payload
round trip.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_placement_plan.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.units import (  # noqa: E402
    AUTOUPGRADE_CYCLE,
    PRIORITY_OPTIONS,
    UnitPlan,
    UnitStep,
    autoupgrade_is_on,
    autoupgrade_presses,
)
from sloppykeys.macro.placement import priority_presses, split_steps  # noqa: E402


def unit(number: int, preplacement: bool = False) -> UnitStep:
    return UnitStep(
        step=number,
        x="100",
        y="200",
        slot="1",
        preplacement=preplacement,
    )


# # Pre-placement ordering
pre_only = [unit(1, preplacement=True), unit(2, preplacement=True)]
pre, during = split_steps(pre_only)
assert [s.step for s in pre] == [1, 2] and during == []

mixed = [unit(1), unit(2, preplacement=True), unit(3), unit(4, preplacement=True)]
pre, during = split_steps(mixed)
# Pre-placement steps run before Start Game; both lists keep step order.
assert [s.step for s in pre] == [2, 4], [s.step for s in pre]
assert [s.step for s in during] == [1, 3], [s.step for s in during]

pre, during = split_steps([])
assert pre == [] and during == []

# # Priority presses
assert priority_presses(PRIORITY_OPTIONS[0]) == 0
for index, name in enumerate(PRIORITY_OPTIONS):
    assert priority_presses(name) == index, name
assert priority_presses("") == 0
assert priority_presses("Nonsense") == 0

# # A step survives a payload round trip, and old configs still read
# This was a save/load through `UnitConfigStore`, which is gone with the `configs/` tree —
# plans are blocks in `operations/<name>.json` now, keyed by operation name rather than by
# gamemode/map/act. The payload shape is the half that still has to hold.
step = UnitPlan.empty().steps[0]
step.x, step.y, step.slot = "300", "400", "2"
step.sell = True
step.sell_wait = "5000"
step.autoupgrade = 3
step.preplacement = True
restored = UnitStep.from_payload(step.as_payload(), 1)
assert restored.sell_wait == "5000", restored.sell_wait
assert restored.sell and restored.preplacement
assert restored.autoupgrade == 3, restored.autoupgrade

# A config written before the field existed means "sell immediately".
legacy = UnitStep.from_payload(
    {"Step": 1, "Kind": "unit", "X": "1", "Y": "2", "Slot": "1", "Sell": 1}, 1
)
assert legacy.sell_wait == "", legacy.sell_wait

# # Auto upgrade is a press count, and the old 0/1 flag still means what it meant
assert autoupgrade_presses(0) == 0
assert autoupgrade_presses(1) == 1, "legacy AutoUpgrade: 1 was one press = level 1"
assert autoupgrade_presses(True) == 1 and autoupgrade_presses(False) == 0
assert autoupgrade_presses("yes") == 1 and autoupgrade_presses("off") == 0
assert autoupgrade_presses("4") == 4
assert autoupgrade_presses(99) == AUTOUPGRADE_CYCLE, "clamped to the full cycle"
assert autoupgrade_presses(-2) == 0 and autoupgrade_presses("junk") == 0
# 1..6 leave auto running, so the manual Upgrade Level is skipped; 7 ends on off.
assert [autoupgrade_is_on(value) for value in range(0, 8)] == [
    False, True, True, True, True, True, True, False
]
# A saved 7 comes back as 7 rather than collapsing to a flag.
cycled = UnitStep.from_payload(
    {"Step": 2, "Kind": "unit", "X": "1", "Y": "2", "Slot": "1", "AutoUpgrade": 7}, 2
)
assert cycled.autoupgrade == 7 and cycled.as_payload()["AutoUpgrade"] == 7

# # UnitPlacer's public surface
# A module-level def once landed inside the class body, which silently turned every
# method below it into a nested function: it compiled, imported, and only failed at
# runtime when F1 built the step list. This catches that shape of mistake.
from sloppykeys.macro.placement import UnitPlacer  # noqa: E402

for name in (
    "run_step",
    "place_unit",
    "open_unit_panel",
    "close_unit_panel",
    "run_sequence",
    "run_action",
    "apply_delays",
):
    assert callable(getattr(UnitPlacer, name, None)), f"UnitPlacer.{name} is missing"

print("placement plan: OK")
