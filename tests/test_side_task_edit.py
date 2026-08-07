"""Runnable check that leaving side-task editing cannot blank the config.

`Settings > Tasks > Edit units` points the Units page at a config the Run strip may not be
able to select, and leaving that mode **saves on the way out** so an edit can't be lost.
The cost of saving on a navigation event is that `self._plan` and `self._edit_target` have
to keep describing the same file: the titlebar's change-gamemode button blanked the plan
and left the override pointing at the side task, so the next Run strip touch wrote 72
empty steps over it. The file survived, with `"Units": []` and nothing enabled.

No framework, no capture, no input. Offscreen Qt, temp app root:
`.venv\\Scripts\\python.exe tests\\test_side_task_edit.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

from sloppykeys.content.units import UnitPlan, UnitStep  # noqa: E402
from sloppykeys.ui.window import MainWindow  # noqa: E402

app = QApplication([])

GAMEMODE, MAP, ACT = "Events", "Villian Invasion", "Act 3"


def placed_plan() -> UnitPlan:
    """Three steps with coordinates, which is what makes a step enabled."""
    plan = UnitPlan.empty()
    for number, (x, y) in enumerate(((380, 516), (409, 516), (438, 517)), start=1):
        plan.steps[number - 1] = UnitStep(step=number, x=str(x), y=str(y), slot="5")
    return plan


def enabled_on_disk(window: MainWindow) -> int:
    return len(window._config_store.load(GAMEMODE, MAP, ACT).enabled_steps())


def build(root: str) -> MainWindow:
    # Never the real app root: the live settings.json holds the private-server link and
    # the webhook URL. `auto_update` off so nothing asks GitHub.
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"auto_update": False}, handle)
    window = MainWindow(root)
    assert window._config_store.save(GAMEMODE, MAP, ACT, placed_plan())
    assert enabled_on_disk(window) == 3
    return window


# # Change gamemode while a side task is open, then touch the Run strip
with tempfile.TemporaryDirectory() as root:
    window = build(root)
    window._on_edit_config_requested(GAMEMODE, MAP, ACT)
    assert window._edit_target is not None
    assert len(window._plan.enabled_steps()) == 3, "Edit units must load the config"

    # The titlebar 'change' button. It blanks the plan; it must not leave the override
    # behind pointing at a config the blank plan would be written to.
    window._show_selector()
    assert window._edit_target is None, "leaving the mode must drop the override"
    assert enabled_on_disk(window) == 3, "the plan was saved on the way out, not blanked"

    # Whatever fires next, there is no override left to write through.
    window._on_target_changed()
    assert enabled_on_disk(window) == 3, "a later Run strip touch must not reach the config"

# # An edit made in the Units page survives the same trip
with tempfile.TemporaryDirectory() as root:
    window = build(root)
    window._on_edit_config_requested(GAMEMODE, MAP, ACT)
    window._plan.steps[3] = UnitStep(step=4, x="500", y="300", slot="6")
    window._show_selector()
    assert enabled_on_disk(window) == 4, "leaving must save the edit, not discard it"

# # The guard itself: a plan belonging to no file is never written
with tempfile.TemporaryDirectory() as root:
    window = build(root)
    window._on_edit_config_requested(GAMEMODE, MAP, ACT)
    # What every "the plan belongs to nothing now" path leaves behind.
    window._plan = UnitPlan.empty()
    window._active_config_path = None
    window._clear_edit_override()
    assert window._edit_target is None
    assert enabled_on_disk(window) == 3, "an unowned plan must not overwrite the config"

print("side task edit: OK")
