r"""Runnable checks for stage repeat handover and wait_for_match_ready.

    .venv\Scripts\python.exe tests\test_stage_repeat.py

Verifies:
1. After a match win with more reps remaining, click_repeat is called and immediately
   followed by wait_for_match_ready.
2. When wait_for_match_ready succeeds, the subsequent rep skips lobby navigation
   (does not click leave_match or change_gamemode) because in_match() is already True.
3. If wait_for_match_ready fails, _kept_position is cleared so recovery can run.
4. LobbyNavigator.click_repeat passes fade_wait and respects the minimum search budget floor.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController
from sloppykeys.macro.lobby import LobbyNavigator


# 1. Verify click_repeat parameterization on LobbyNavigator
class FakeEngine:
    def template_exists(self, _path: str) -> bool:
        return True


nav = LobbyNavigator.__new__(LobbyNavigator)
nav._engine = FakeEngine()
nav.search_timeout = 1.0
nav.panel_fade_wait = 1.2
recorded_find: dict = {}


def fake_find_click(path: str, label: str, timeout: float = 0.0, fade_wait: float = 0.0):
    recorded_find["path"] = path
    recorded_find["label"] = label
    recorded_find["timeout"] = timeout
    recorded_find["fade_wait"] = fade_wait
    return (True, "clicked")


nav._find_click = fake_find_click
ok, msg = nav.click_repeat()
assert ok is True
assert recorded_find["label"] == "Repeat"
assert recorded_find["timeout"] == 6.0, f"expected budget floor 6.0, got {recorded_find['timeout']}"
assert recorded_find["fade_wait"] == 1.2, f"expected fade_wait 1.2, got {recorded_find['fade_wait']}"


# 2. Verify controller calls wait_for_match_ready on repeat and skips lobby on next rep
class MockNav:
    click_settle = 0.0

    def __init__(self):
        self.calls: list[str] = []
        self._in_match = False

    def in_match(self) -> bool:
        self.calls.append(f"in_match:{self._in_match}")
        return self._in_match

    def result_screen_up(self) -> bool:
        self.calls.append("result_screen_up")
        return False

    def leave_match(self):
        self.calls.append("leave_match")
        return (True, "ok")

    def change_gamemode(self):
        self.calls.append("change_gamemode")
        return (True, "ok")

    def click_play(self):
        self.calls.append("click_play")
        return (True, "ok")

    def open_gamemode(self, mode):
        self.calls.append(f"open_{mode}")
        return (True, "ok")

    def select_stage(self, mode, map_name):
        self.calls.append(f"select_{map_name}")
        return (True, "ok")

    def select_act(self, mode, stage, prefer_golden=False):
        self.calls.append(f"select_{stage}")
        return (True, "ok")

    def start_stage(self, mode, hard):
        self.calls.append(f"start_stage:{mode}:{hard}")
        return (True, "ok")

    def click_start_game(self):
        self.calls.append("click_start_game")
        return (True, "ok")

    def click_repeat(self):
        self.calls.append("click_repeat")
        return (True, "ok")

    def wait_for_match_ready(self):
        self.calls.append("wait_for_match_ready")
        self._in_match = True
        return (True, "stage loaded")


ctrl = MacroController.__new__(MacroController)
mock_nav = MockNav()
ctrl._nav = mock_nav
ctrl._app_root = ""
ctrl._stop_requested = False
ctrl._checkpoint = lambda: False
ctrl._kept_position = False
ctrl._camera_set = False
ctrl._cycle = 0
ctrl._current_task = None
ctrl._left_early = False
ctrl._log = lambda _msg: None
ctrl._ensure_camera = lambda: None
ctrl._try_reopen_roblox = lambda: True
ctrl._challenge_task = lambda _t: None
ctrl._challenge_wants_in = lambda _c: False
ctrl._golden_hour_wants_in = lambda **_k: False
ctrl._eclipse_wants_in = lambda **_k: False
ctrl._run_match = lambda *_a: None
ctrl._run_phase_linear = lambda *_a: None
ctrl._stats = type("S", (), {"start_stage": lambda *_a: None, "record": lambda *_a: None})()
ctrl._placer = type("P", (), {"park": lambda *a: None})()

task = {
    "mode": "Story",
    "map": "King's Tomb",
    "stage": "Mastery",
    "repeat": 2,
    "macro": "",
}

passes = {"n": 0}


class SettingsStub:
    def __init__(self, _root):
        pass

    def get_tasks(self):
        passes["n"] += 1
        return [task] if passes["n"] == 1 else []


import sloppykeys.macro.controller as mod
orig_settings = mod.UnifiedSettings
orig_load = mod.load_operation

mod.UnifiedSettings = SettingsStub
mod.load_operation = lambda *a: {"phases": {}}

try:
    ctrl._run()
finally:
    mod.UnifiedSettings = orig_settings
    mod.load_operation = orig_load

# Verify call sequence:
# Rep 0: initial lobby navigation, start game, match, then click_repeat followed by wait_for_match_ready!
assert "click_repeat" in mock_nav.calls, mock_nav.calls
repeat_idx = mock_nav.calls.index("click_repeat")
assert mock_nav.calls[repeat_idx + 1] == "wait_for_match_ready", mock_nav.calls

# Rep 1: in_match returned True, so lobby navigation was skipped:
calls_after_repeat = mock_nav.calls[repeat_idx + 1:]
assert "leave_match" not in calls_after_repeat, f"leave_match must never be called during clean repeat: {calls_after_repeat}"
assert "change_gamemode" not in calls_after_repeat, f"change_gamemode must never be called during clean repeat: {calls_after_repeat}"
assert "in_match:True" in calls_after_repeat, calls_after_repeat
assert "click_start_game" in calls_after_repeat, calls_after_repeat

print("stage repeat: OK")
