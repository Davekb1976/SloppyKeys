"""Runnable checks for leaving a finished match, and for park mode.

    .venv\\Scripts\\python.exe tests\\test_task_handover.py

A chain built while the macro stands on a **result screen** lands its first click on that
screen. The lobby's Play is not there, so the chain used to die on step one — the old PySide6
window handled this and nothing in `MacroController` replaced it. The order that works is
Match Play → the post-match panel → Change gamemode → the gamemode chooser, and the chooser
is where the cards are, so Play must be **skipped**, not retried.

Park mode is the other half: once Battle is spent and there are no loops there is nothing
left to click, so the cursor retreats to the empty corner and clicks it on a slow schedule.
That click keeps Roblox from idle-kicking the session through a long wave.

No window, no capture, and **no input**: the navigator and the placer are recording fakes.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController, OUTCOME_WON  # noqa: E402


class FakeNav:
    """Records every navigator call as a label, in order."""

    click_settle = 0.0

    def __init__(self, on_result_screen: bool) -> None:
        self.calls: list[str] = []
        self._on_result_screen = on_result_screen

    def _ok(self, label: str):
        self.calls.append(label)
        return (True, label)

    def in_match(self) -> bool:
        return False

    def result_screen_up(self) -> bool:
        return self._on_result_screen

    def leave_match(self):
        return self._ok("leave_match")

    def change_gamemode(self):
        return self._ok("change_gamemode")

    def click_play(self):
        return self._ok("play")

    def open_gamemode(self, mode):
        return self._ok(f"card:{mode}")

    def select_stage(self, mode, map_name):
        return self._ok(f"stage:{map_name}")

    def select_act(self, mode, act):
        return self._ok(f"act:{act}")

    def set_difficulty(self, mode, diff):
        return self._ok(f"difficulty:{diff}")

    def start_stage(self, mode, hard):
        return self._ok(f"start:{'hard' if hard else 'easy'}")

    def wait_for_match_ready(self):
        return self._ok("loaded")


class FakePlacer:
    won_poll_click = 0.0  # floored to 1s by the runner, so the test waits ~1s once

    def __init__(self) -> None:
        self.parks = 0
        self.clicks = 0

    def park(self) -> None:
        self.parks += 1

    def park_click(self) -> None:
        self.clicks += 1


class FakeSettings:
    def get_hard_mode(self) -> bool:
        return False


def navigator(on_result_screen: bool, task: dict | None = None) -> tuple[FakeNav, list[str]]:
    logs: list[str] = []
    ctrl = MacroController.__new__(MacroController)
    ctrl._nav = FakeNav(on_result_screen)
    ctrl._log = logs.append
    ctrl._checkpoint = lambda: False
    ctrl._settings = FakeSettings()
    ctrl._current_task = task or {}
    ctrl.run_camera = lambda: None
    assert ctrl._navigate_lobby("Story", "Flower Forest", "Act 1") is True
    return ctrl._nav, logs


# # Off a result screen: leave it, reopen the chooser, and never click the lobby's Play
nav, logs = navigator(True)
assert nav.calls[:3] == ["leave_match", "change_gamemode", "card:Story"], nav.calls
assert "play" not in nav.calls, nav.calls
# The rest of the chain is unchanged by the handover.
assert nav.calls[3:] == ["stage:Flower Forest", "act:Act 1", "start:easy", "loaded"], nav.calls
assert any("Leave match" in line for line in logs), logs

# # In the lobby: no handover clicks at all, and Play is back
nav, _logs = navigator(False)
assert nav.calls[0] == "play", nav.calls
assert "leave_match" not in nav.calls and "change_gamemode" not in nav.calls, nav.calls

# # The task's Easy/Hard still reaches start_stage through the handover path
nav, _logs = navigator(True, {"difficulty": "Hard"})
assert "start:hard" in nav.calls, nav.calls


# # Park mode: announced once, then clicking on its own schedule
def park_run() -> tuple[FakePlacer, list[str]]:
    logs: list[str] = []
    ctrl = MacroController.__new__(MacroController)
    ctrl._stop_requested = False
    ctrl._checkpoint = lambda: False
    ctrl._placer = FakePlacer()
    ctrl._log = logs.append
    ctrl._stats = type("S", (), {"record": lambda *_a, **_k: None})()
    ctrl._send_webhook_result = lambda *_a: None
    # Nothing to run and no outcome for the first second and a bit, so the runner has to
    # fill the time with park clicks rather than spinning silently.
    started = time.monotonic()
    ctrl._check_outcome = lambda: (
        (OUTCOME_WON, "test") if time.monotonic() - started > 1.4 else None
    )
    ctrl._run_match([], [], [])
    return ctrl._placer, logs


placer, logs = park_run()
assert placer.parks == 1, f"parked {placer.parks} times, want exactly one retreat"
assert placer.clicks >= 1, "no keep-alive click in 1.4s with a 1s floor"
assert sum("parked" in line for line in logs) == 1, logs
assert any("Win!" in line for line in logs), logs

print("task handover: OK")
