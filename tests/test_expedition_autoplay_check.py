"""Runnable test for Expedition Autoplay detection and controller bypass logic."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.operations import (
    operation_has_autoplay,
    list_operations_with_autoplay,
)
from sloppykeys.macro.controller import MacroController


def test_operation_autoplay_detection() -> None:
    tmp_dir = tempfile.mkdtemp()
    try:
        ops_dir = os.path.join(tmp_dir, "operations")
        os.makedirs(ops_dir, exist_ok=True)

        # 1. Operation with autoplay block in standard phases format
        with open(os.path.join(ops_dir, "op_with_ap.json"), "w") as f:
            json.dump({
                "name": "op_with_ap",
                "phases": {
                    "battle": [
                        {"type": "place_unit", "params": {"x": 100, "y": 200}},
                        {"type": "autoplay", "params": {}},
                    ]
                }
            }, f)

        # 2. Operation without autoplay block
        with open(os.path.join(ops_dir, "op_clean.json"), "w") as f:
            json.dump({
                "name": "op_clean",
                "phases": {
                    "battle": [
                        {"type": "place_unit", "params": {"x": 100, "y": 200}},
                        {"type": "upgrade_unit", "params": {"index": 1}},
                    ]
                }
            }, f)

        # 3. Operation named "auto play" (even if empty)
        with open(os.path.join(ops_dir, "auto play.json"), "w") as f:
            json.dump({"name": "auto play", "phases": {}}, f)

        # 4. Malformed list operation (should not crash)
        with open(os.path.join(ops_dir, "malformed.json"), "w") as f:
            json.dump([1, 2, 3], f)

        assert operation_has_autoplay(tmp_dir, "op_with_ap") is True
        assert operation_has_autoplay(tmp_dir, "op_clean") is False
        assert operation_has_autoplay(tmp_dir, "auto play") is True
        assert operation_has_autoplay(tmp_dir, "malformed") is False
        assert operation_has_autoplay(tmp_dir, "nonexistent") is False

        ap_list = list_operations_with_autoplay(tmp_dir)
        assert set(ap_list) == {"op_with_ap", "auto play"}
        print("OK: operation_autoplay_detection")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_controller_skips_in_expedition() -> None:
    ctrl = MacroController.__new__(MacroController)
    logs = []
    ctrl._log = lambda msg: logs.append(msg)
    ctrl._current_task = {"mode": "Expedition", "macro": "op_with_ap", "autoplay_preset": "Preset 1"}

    # 1. _ensure_autoplay_preset should skip immediately for Expedition
    ok_preset = ctrl._ensure_autoplay_preset()
    assert ok_preset is True
    assert any("Expedition mode has no in-game Auto Play feature" in m for m in logs)

    # 2. _tick_autoplay should skip immediately for Expedition
    logs.clear()
    block = {"type": "autoplay", "params": {}}
    ok_tick = ctrl._tick_autoplay(block)
    assert ok_tick is True
    assert any("Expedition mode has no in-game Auto Play button" in m for m in logs)

    # 3. If mode is Story, _ensure_autoplay_preset should not skip on mode check
    logs.clear()
    ctrl._current_task = {"mode": "Story", "autoplay_preset": ""}
    ok_story = ctrl._ensure_autoplay_preset()
    assert ok_story is True
    assert not any("Expedition" in m for m in logs)

    print("OK: test_controller_skips_in_expedition")


if __name__ == "__main__":
    test_operation_autoplay_detection()
    test_controller_skips_in_expedition()
    print("ALL EXPEDITION AUTOPLAY CHECKS PASSED")
