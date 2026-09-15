"""Tests for Eclipse repeat execution and in-match chaining."""

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.macro.controller import MacroController
from sloppykeys.content.challenge import interval_key

# 1. Test repeat chaining when repeat=3
ctrl = MacroController.__new__(MacroController)
ctrl._app_root = ROOT
ctrl._settings = MagicMock()
ctrl._settings.get_eclipse_macro = MagicMock(return_value="auto play")
ctrl._tasks = [{"mode": "Events", "map": "Eclipse", "repeat": 3, "macro": ""}]
ctrl._current_task = ctrl._tasks[0]
ctrl._cycle = 0
ctrl._eclipse_played_interval = None
ctrl._eclipse_attempted_interval = None
ctrl._stop_requested = False
ctrl._left_early = False
ctrl._kept_position = False
ctrl._camera_set = False

mock_nav = MagicMock()
mock_nav.result_screen_up = MagicMock(return_value=False)
mock_nav.click_play = MagicMock(return_value=(True, "ok"))
mock_nav.open_gamemode = MagicMock(return_value=(True, "ok"))
mock_nav.find_and_select_eclipse_stage = MagicMock(return_value=(True, "ok"))
mock_nav.select_act = MagicMock(return_value=(True, "ok"))
mock_nav.start_stage = MagicMock(return_value=(True, "ok"))
mock_nav.wait_for_match_ready = MagicMock(return_value=(True, "ok"))
mock_nav.click_start_game = MagicMock(return_value=(True, "ok"))
mock_nav.click_repeat = MagicMock(return_value=(True, "ok"))
mock_nav.back_to_lobby = MagicMock(return_value=(True, "ok"))
mock_nav.click_settle = 0.0
mock_nav.fade_wait = 0.0

mock_stats = MagicMock()
mock_placer = MagicMock()

ctrl._nav = mock_nav
ctrl._stats = mock_stats
ctrl._placer = mock_placer
ctrl._log = MagicMock()
ctrl._checkpoint = MagicMock(return_value=False)
ctrl._ensure_camera = MagicMock()
ctrl._ensure_autoplay_preset = MagicMock()
ctrl._run_phase_linear = MagicMock()
ctrl._run_match = MagicMock()

ok = ctrl._run_eclipse_detour_inner()

assert ok is True, "Detour inner must report success"
assert ctrl._cycle == 3, f"Expected 3 cycles completed, got {ctrl._cycle}"
assert mock_nav.click_repeat.call_count == 2, f"Expected 2 Repeat clicks for 3 repeats, got {mock_nav.click_repeat.call_count}"
assert mock_nav.back_to_lobby.call_count == 1, "Expected 1 Back to Lobby at the end"
assert ctrl._eclipse_played_interval is not None, "Expected played interval to be recorded"

# 2. Test repeat chaining failure fallback (e.g. defeat or repeat not found on rep 2)
ctrl2 = MacroController.__new__(MacroController)
ctrl2._app_root = ROOT
ctrl2._settings = MagicMock()
ctrl2._settings.get_eclipse_macro = MagicMock(return_value="auto play")
ctrl2._tasks = [{"mode": "Events", "map": "Eclipse", "repeat": 3, "macro": ""}]
ctrl2._current_task = ctrl2._tasks[0]
ctrl2._cycle = 0
ctrl2._eclipse_played_interval = None
ctrl2._eclipse_attempted_interval = None
ctrl2._stop_requested = False
ctrl2._left_early = False
ctrl2._kept_position = False
ctrl2._camera_set = False

mock_nav2 = MagicMock()
mock_nav2.result_screen_up = MagicMock(return_value=False)
mock_nav2.click_play = MagicMock(return_value=(True, "ok"))
mock_nav2.open_gamemode = MagicMock(return_value=(True, "ok"))
mock_nav2.find_and_select_eclipse_stage = MagicMock(return_value=(True, "ok"))
mock_nav2.select_act = MagicMock(return_value=(True, "ok"))
mock_nav2.start_stage = MagicMock(return_value=(True, "ok"))
mock_nav2.wait_for_match_ready = MagicMock(return_value=(True, "ok"))
mock_nav2.click_start_game = MagicMock(return_value=(True, "ok"))
# Repeat fails on rep 1
mock_nav2.click_repeat = MagicMock(return_value=(False, "Repeat button not visible"))
mock_nav2.back_to_lobby = MagicMock(return_value=(True, "ok"))
mock_nav2.click_settle = 0.0

ctrl2._nav = mock_nav2
ctrl2._stats = mock_stats
ctrl2._placer = mock_placer
ctrl2._log = MagicMock()
ctrl2._checkpoint = MagicMock(return_value=False)
ctrl2._ensure_camera = MagicMock()
ctrl2._ensure_autoplay_preset = MagicMock()
ctrl2._run_phase_linear = MagicMock()
ctrl2._run_match = MagicMock()

ok2 = ctrl2._run_eclipse_detour_inner()

assert ok2 is True, "Must report success even if early exit on repeat failure"
assert ctrl2._cycle == 1, f"Expected 1 cycle completed before repeat failure, got {ctrl2._cycle}"
assert mock_nav2.click_repeat.call_count == 1, "Expected 1 Repeat attempt"
assert mock_nav2.back_to_lobby.call_count == 1, "Must return to lobby on repeat failure"
assert ctrl2._eclipse_played_interval is not None, "Interval must still be marked played since 1 match completed"

print("Eclipse repeat test: OK")
