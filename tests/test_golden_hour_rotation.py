"""Tests for MacroController._golden_hour_wants_in and 30-minute rotation handling."""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.macro.controller import MacroController
from sloppykeys.content.challenge import interval_key

# Verify method resolution
assert callable(getattr(MacroController, "_golden_hour_wants_in", None))
assert callable(getattr(MacroController, "_run_golden_hour_detour", None))
assert callable(getattr(MacroController, "_run_golden_hour_detour_inner", None))

ctrl = MacroController.__new__(MacroController)
ctrl._app_root = ROOT
ctrl._settings = MagicMock()
ctrl._golden_hour_played_interval = None
ctrl._golden_hour_attempted_interval = None

orig_isfile = os.path.isfile

# 1. Disabled in settings
ctrl._settings.get_prioritize_golden_hour.return_value = False
os.path.isfile = lambda p: True if "golden_hour.png" in p else orig_isfile(p)
try:
    t_10_05 = datetime(2026, 9, 9, 10, 5, 0)
    assert ctrl._golden_hour_wants_in(t_10_05) is False, "Must not want in when setting is disabled"
finally:
    os.path.isfile = orig_isfile

# 2. Enabled in settings, but template missing on disk
ctrl._settings.get_prioritize_golden_hour.return_value = True
os.path.isfile = lambda p: False if "golden_hour.png" in p else orig_isfile(p)
try:
    assert ctrl._golden_hour_wants_in(t_10_05) is False, "Must not want in when template is missing"
finally:
    os.path.isfile = orig_isfile

# 3. Enabled and template present
os.path.isfile = lambda p: True if "golden_hour.png" in p else orig_isfile(p)
try:
    # Initially fresh: wants in at 10:05
    assert ctrl._golden_hour_wants_in(t_10_05) is True, "Must want in initially when enabled and template present"

    # Mark played in 10:00-10:30 rotation
    ctrl._golden_hour_played_interval = interval_key(t_10_05)

    # In the same rotation (10:10, 10:29:59), should NOT want in
    t_10_10 = datetime(2026, 9, 9, 10, 10, 0)
    t_10_29 = datetime(2026, 9, 9, 10, 29, 59)
    assert ctrl._golden_hour_wants_in(t_10_10) is False, "Must not want in after being played in same rotation"
    assert ctrl._golden_hour_wants_in(t_10_29) is False, "Must not want in at end of same rotation"

    # Boundary crossing: 10:30:00 (new rotation window)
    t_10_30 = datetime(2026, 9, 9, 10, 30, 0)
    assert ctrl._golden_hour_wants_in(t_10_30) is True, "Must want in when crossing into :30 boundary"

    # Mark attempted (carousel scanned, badge not found) in 10:30-11:00 rotation
    ctrl._golden_hour_attempted_interval = interval_key(t_10_30)

    # In the same rotation (10:35, 10:59:59), should NOT want in
    t_10_35 = datetime(2026, 9, 9, 10, 35, 0)
    t_10_59 = datetime(2026, 9, 9, 10, 59, 59)
    assert ctrl._golden_hour_wants_in(t_10_35) is False, "Must not want in after attempt in same rotation"
    assert ctrl._golden_hour_wants_in(t_10_59) is False, "Must not want in at end of attempted rotation"

    # Boundary crossing: 11:00:00 (new rotation window)
    t_11_00 = datetime(2026, 9, 9, 11, 0, 0)
    assert ctrl._golden_hour_wants_in(t_11_00) is True, "Must want in when crossing into :00 boundary"

    # 4. Queue-based task check
    ctrl._settings.get_prioritize_golden_hour.return_value = False
    ctrl._golden_hour_played_interval = None
    ctrl._golden_hour_attempted_interval = None
    ctrl._tasks = [{"mode": "Story", "stage": "Golden Hour", "macro": "gh_op"}]
    assert ctrl._golden_hour_wants_in(t_11_00) is True, "Must want in when Story Golden Hour task is queued"
    assert ctrl._golden_hour_task()["macro"] == "gh_op"

finally:
    os.path.isfile = orig_isfile

print("Golden Hour rotation test: OK")
