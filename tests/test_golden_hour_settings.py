"""Tests for Golden Hour settings in UnifiedSettings and AppSettings."""

import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.config.unified import DEFAULTS, UnifiedSettings
from sloppykeys.config.settings import (
    AppSettings,
    PRIORITIZE_GOLDEN_HOUR_KEY,
    GOLDEN_HOUR_MACRO_KEY,
)

# 1. Check DEFAULTS in unified.py
assert "prioritize_golden_hour" in DEFAULTS
assert DEFAULTS["prioritize_golden_hour"] is False

assert "golden_hour_repeats" not in DEFAULTS

assert "golden_hour_macro" in DEFAULTS
assert DEFAULTS["golden_hour_macro"] == ""

# 2. Check AppSettings defaults and get/set with a temporary directory
tmp_dir = tempfile.mkdtemp()
try:
    settings = AppSettings(tmp_dir)
    unified = UnifiedSettings(tmp_dir)

    # Verify defaults on fresh directory
    assert settings.get_prioritize_golden_hour() is False
    assert settings.get_golden_hour_macro() == ""

    # Test setting values via AppSettings
    settings.set_prioritize_golden_hour(True)
    assert settings.get_prioritize_golden_hour() is True
    assert unified.get(PRIORITIZE_GOLDEN_HOUR_KEY) is True

    settings.set_golden_hour_macro("auto play")
    assert settings.get_golden_hour_macro() == "auto play"
    assert unified.get(GOLDEN_HOUR_MACRO_KEY) == "auto play"

    # Test setting via UnifiedSettings
    unified.set("prioritize_golden_hour", False)
    assert settings.get_prioritize_golden_hour() is False

    unified.set("golden_hour_macro", "raid spirit")
    assert settings.get_golden_hour_macro() == "raid spirit"

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

print("Golden Hour settings test: OK")
