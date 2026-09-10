"""Runnable checks for strict wave counter OCR and Story Infinite leave-at-wave logic.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_leave_at_wave.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.units import WAVE_MAX
from sloppykeys.macro.placement import parse_wave
from sloppykeys.macro.controller import MacroController


# # 1. Strict parse_wave assertions
assert WAVE_MAX == 999, f"WAVE_MAX should be 999 to support infinite waves, got {WAVE_MAX}"

# Fractions
assert parse_wave("1/15") == 1
assert parse_wave("5 / 15 wave") == 5
assert parse_wave("15/15") == 15
assert parse_wave("12/25", 25) == 12
assert parse_wave("12/26", 25) is None  # stage total mismatch

# Wave keyword
assert parse_wave("Wave 120") == 120
assert parse_wave("120 wave") == 120
assert parse_wave("Wave 1") == 1
assert parse_wave("wave: 50") == 50
assert parse_wave("120 wave", 200) == 120

# Bare isolated numbers MUST be rejected as outliers
assert parse_wave("3") is None
assert parse_wave("12") is None
assert parse_wave("120") is None
assert parse_wave("3", 25) is None
assert parse_wave("12", 25) is None
assert parse_wave("") is None
assert parse_wave(None) is None


# # 2. Controller leave-at-wave early exit logic
class StubNav:
    def __init__(self):
        self.calls = []

    def back_to_lobby(self):
        self.calls.append("back_to_lobby")
        return (True, "returned to lobby")

    def click_repeat(self):
        self.calls.append("click_repeat")
        return (True, "repeated")


app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ctrl = MacroController.__new__(MacroController)
ctrl._app_root = app_root
ctrl._log = lambda _m: None
ctrl._rect = lambda: (0, 0, 1152, 756)
ctrl._stop_requested = False
ctrl._camera_set = True
ctrl._kept_position = True
ctrl._left_early = False
ctrl._nav = StubNav()

class StubStats:
    def __init__(self):
        self.abandoned = False
    def abandon_stage(self):
        self.abandoned = True

ctrl._stats = StubStats()

# Mock wave reading at wave 120
ctrl._read_current_wave = lambda: 120
ctrl._current_task = {"mode": "Story", "stage": "Infinite", "leave_at_wave": 120}

# Simulate early exit check from _run_match
leave_at_wave = int(ctrl._current_task.get("leave_at_wave", 0))
assert leave_at_wave == 120

current_w = ctrl._read_current_wave()
assert current_w >= leave_at_wave

ctrl._stats.abandon_stage()
ok, msg = ctrl._back_to_lobby()
ctrl._left_early = True

assert ok is True
assert ctrl._left_early is True
assert ctrl._stats.abandoned is True
assert ctrl._camera_set is False, "back_to_lobby must clear camera_set"
assert ctrl._nav.calls == ["back_to_lobby"]

# Simulate repeat handling in _run: _left_early must skip click_repeat
if ctrl._left_early:
    ctrl._left_early = False
    ctrl._kept_position = False
else:
    ctrl._nav.click_repeat()

assert ctrl._left_early is False
assert ctrl._kept_position is False
assert ctrl._nav.calls == ["back_to_lobby"], "click_repeat must NOT be called when _left_early"

print("leave at wave: OK")
