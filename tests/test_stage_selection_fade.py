"""Unit test verifying stage selection fade wait, single-look search, and live delay reload."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.controller import MacroController
from sloppykeys.core.image_search import ImageMatch


# 1. Verify select_stage waits panel_fade_wait and searches with timeout=0.0
nav = LobbyNavigator.__new__(LobbyNavigator)
nav._rect = lambda: (0, 0, 1152, 756)
nav.park_client = (8, 8)
nav.panel_fade_wait = 0.5
nav.scroll_settle = 0.05
nav._park = MagicMock()
nav._click = MagicMock(return_value=(True, "ok"))
nav._scroll = MagicMock(return_value=(True, "scrolled"))
nav._miss = MagicMock(return_value="miss")

slept = []
import time
orig_sleep = time.sleep
time.sleep = slept.append

try:
    # Scenario A: matched on attempt 0
    match0 = ImageMatch("stage", 0.95, 200, 300, 150, 250, 100, 100)
    nav._find = MagicMock(return_value=match0)

    ok, msg = nav.select_stage("Story", "King's Tomb", max_scrolls=3)
    assert ok is True
    assert nav._park.called
    assert nav._find.call_count == 1
    assert nav._find.call_args[1].get("timeout") == 0.0 or nav._find.call_args[0][1] == 0.0
    assert 0.5 in slept, f"Expected 0.5 in {slept}"
    assert nav._scroll.call_count == 0

    # Scenario B: not matched on attempt 0, matched on attempt 1
    slept.clear()
    nav._park.reset_mock()
    nav._scroll.reset_mock()
    calls = []

    def mock_find(path, timeout=0.0, **kwargs):
        calls.append(timeout)
        if len(calls) == 1:
            return None
        return match0

    nav._find = mock_find
    ok, msg = nav.select_stage("Story", "King's Tomb", max_scrolls=3)
    assert ok is True
    assert calls == [0.0, 0.0], f"Expected all looks with timeout 0.0, got {calls}"
    assert nav._scroll.call_count == 1
    assert 0.5 in slept
    assert 0.05 in slept
finally:
    time.sleep = orig_sleep


# 2. Verify controller.reload_delays updates navigator and placer
ctrl = MacroController.__new__(MacroController)
ctrl._app_root = ROOT
ctrl._nav = LobbyNavigator.__new__(LobbyNavigator)
ctrl._nav.click_settle = ctrl._nav.scroll_settle = ctrl._nav.panel_fade_wait = ctrl._nav.search_timeout = -1.0
from sloppykeys.macro.placement import UnitPlacer
ctrl._placer = UnitPlacer.__new__(UnitPlacer)
ctrl._placer.search_timeout = ctrl._placer.settle = -1.0

ctrl.reload_delays()
assert ctrl._nav.panel_fade_wait > 0, "panel_fade_wait should be reloaded from settings"
assert ctrl._nav.search_timeout > 0, "search_timeout should be reloaded from settings"
assert ctrl._placer.settle > 0, "placement settle should be reloaded from settings"

print("stage selection fade and reload delays test: OK")
