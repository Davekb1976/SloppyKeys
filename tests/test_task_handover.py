"""Runnable check for the queue's handover between tasks.

A task switch builds a **whole new chain**, and that chain's first step lands on
whatever screen the macro is standing on. At the end of a match cycle that is the
result screen, so the switch has to click Match Play first — a chain that opens with
the lobby's `Play` against a victory screen fails on its first step and stops the run
(`Play not found (best 0.54 < 0.70)`).

No framework, no capture, and **no input**: `leave_match` is stubbed, so nothing here
clicks. Offscreen Qt, so it needs no display:

`.venv\\Scripts\\python.exe tests\\test_task_handover.py`
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

from sloppykeys.config.tasks import TaskSlot  # noqa: E402
from sloppykeys.macro.runner import MacroTarget, StepResult  # noqa: E402
from sloppykeys.macro.tasks import TaskDirector  # noqa: E402
from sloppykeys.ui.window import (  # noqa: E402
    ENTRY_LOBBY,
    ENTRY_MODE_PANEL,
    MainWindow,
)

app = QApplication([])

# A temp app root, never the real one: the live `settings.json` holds the private-server
# link and the webhook URL, and a test has no business reading or rewriting either.
with tempfile.TemporaryDirectory() as root:
    # `auto_update` defaults to on, and a test has no business asking GitHub anything.
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump({"auto_update": False}, handle)

    window = MainWindow(root)

    def target(gamemode: str, map_name: str, act: str) -> TaskSlot:
        return TaskSlot(
            kind="target", gamemode=gamemode, map_name=map_name, act=act, limit=1
        )

    events = target("Events", "Villian Invasion", "Act 1")
    story = target("Story", "School Grounds", "Act 1")

    # A unit config with steps, without depending on what is in `configs/` — the switch is
    # skipped when the next task has no enabled steps, and that is not what's under test.
    class _Plan:
        def enabled_steps(self):
            return [object()]

    window._config_store.load = lambda *_args: _Plan()

    clicks: list[str] = []
    window._nav.leave_match = lambda: (
        clicks.append("Match Play"),
        (True, "Match Play (stub)"),
    )[1]

    window._director = TaskDirector(slots=[events, story], challenges=False)
    window._last_decision = window._director.decide()
    window._last_won = True
    window._challenge_slot = None
    # What `_start_queued_run_inner` leaves behind once it has consumed the entry steps.
    window._entry_screen = ENTRY_LOBBY
    window._runner.start(
        MacroTarget(gamemode="Events", map_name="Villian Invasion", target="Act 1"),
        [],
        loop_from=0,
    )

    assert window._next_task_step().action() is StepResult.DONE
    assert clicks == ["Match Play"], "a target switch must leave the match"
    assert window._entry_screen == ENTRY_MODE_PANEL, window._entry_screen
    assert window._pending_target is not None
    assert window._pending_target.gamemode == "Story", window._pending_target
    assert window._pending_target.map_name == "School Grounds", window._pending_target
    assert window._runner.stop_requested, "the switch restarts the run, so it must stop"
    window._runner.stop()

    # The chain the next run builds must not open with the lobby's Play — that is the whole
    # point of leaving the match. Story, Raid and Expedition all share this builder, so all
    # three failed the same way; Events is the exception that finds the lobby itself.
    window._nav.in_match = lambda: False  # a *finished* match; never look at the screen
    for gamemode, map_name, act in (
        ("Story", "School Grounds", "Act 1"),
        ("Raid", "", ""),
        ("Expedition", "", ""),
    ):
        window._entry_screen = ENTRY_MODE_PANEL
        steps, error = window._build_run_steps(
            MacroTarget(gamemode=gamemode, map_name=map_name, target=act)
        )
        assert steps, f"{gamemode}: {error}"
        assert steps[0].name != "Play", f"{gamemode} still opens with the lobby's Play"
        assert steps[0].name == "Change gamemode", (gamemode, steps[0].name)

    # Let any startup worker finish before the window goes: a `QRunnable` still holding a
    # signal back into a deleted window raises "Signal source has been deleted" on exit.
    window._pool.waitForDone(5000)
    window.close()

print("task handover: OK")
