"""Runnable test for Autoplay Preset Selector logic.

Tests:
1. Expected template paths include autoplay_settings and close_gray.
2. OCR region specs and override application.
3. Task schema sanitization.
4. Controller lifecycle (carryover on same preset / repeat, select on different preset, reset on lobby).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import (
    autoplay_settings_image,
    autoplay_close_image,
    expected_paths,
)
from sloppykeys.content.autoplay_regions import (
    AUTOPLAY_PRESETS_DEFAULT_REGION,
    autoplay_presets_region,
    apply_region_overrides,
    region_key,
    region_specs,
)
from sloppykeys.content.gamemodes import sanitize_task
from sloppykeys.macro.controller import MacroController


def test_templates() -> None:
    settings_img = autoplay_settings_image()
    close_img = autoplay_close_image()
    assert "autoplay_settings.png" in settings_img
    assert "close_gray.png" in close_img

    paths = [p.replace("\\", "/") for p in expected_paths()]
    assert settings_img.replace("\\", "/") in paths
    assert close_img.replace("\\", "/") in paths
    print("OK: autoplay preset templates registered in expected_paths")


def test_regions() -> None:
    key = region_key("presets")
    assert key == "autoplay_presets"
    assert autoplay_presets_region() == AUTOPLAY_PRESETS_DEFAULT_REGION

    specs = region_specs()
    assert len(specs) == 1
    assert specs[0][0] == key
    assert specs[0][2] == AUTOPLAY_PRESETS_DEFAULT_REGION

    custom = (100, 200, 300, 400)
    apply_region_overrides({key: custom})
    assert autoplay_presets_region() == custom

    # Reset
    apply_region_overrides({})
    assert autoplay_presets_region() == AUTOPLAY_PRESETS_DEFAULT_REGION
    print("OK: autoplay preset regions and overrides")


def test_sanitize() -> None:
    task = {"mode": "Raid", "autoplay_preset": "  Raid 2  "}
    sanitized = sanitize_task(task)
    assert sanitized["autoplay_preset"] == "Raid 2"

    task_empty = {"mode": "Story"}
    assert sanitize_task(task_empty)["autoplay_preset"] == ""
    print("OK: sanitize_task preserves autoplay_preset")


def test_controller_lifecycle() -> None:
    ctrl = MacroController.__new__(MacroController)
    ctrl._log = lambda *args: None
    ctrl._equipped_autoplay_preset = None
    ctrl._camera_set = True

    # 1. Blank task -> skips without touching state
    assert ctrl._ensure_autoplay_preset({"autoplay_preset": ""}) is True
    assert ctrl._equipped_autoplay_preset is None

    # 2. Mocking engine & OCR for preset selection
    class DummyHit:
        center = (500, 500)

    class DummyBlock:
        text = "Raid 2"
        x, y, w, h = 10, 10, 50, 20

    class DummyEngine:
        def template_exists(self, path): return True
        def find(self, path, timeout=0.0): return DummyHit()
        def capture_bgr(self, box): return "frame"

    class DummyOcr:
        def available(self): return (True, "ok")
        def read_all(self, frame): return [DummyBlock()]

    class DummyNav:
        fade_wait = 0.01

    class DummyAhk:
        def __init__(self): self.runs = []
        def run(self, script, wait=True, timeout=0.0): self.runs.append(script)

    ctrl._engine = DummyEngine()
    ctrl._ocr = DummyOcr()
    ctrl._nav = DummyNav()
    ctrl._ahk = DummyAhk()
    ctrl._rect = lambda: (0, 0, 1152, 756)

    # 3. First run with "Raid 2" -> selects and equips
    task_raid = {"autoplay_preset": "Raid 2"}
    ok = ctrl._ensure_autoplay_preset(task_raid)
    assert ok is True
    assert ctrl._equipped_autoplay_preset == "Raid 2"
    assert len(ctrl._ahk.runs) >= 2  # clicked settings + clicked preset

    # 4. Second run with same preset (Repeat Stage) -> carries over without running AHK scripts!
    ctrl._ahk.runs.clear()
    ok2 = ctrl._ensure_autoplay_preset(task_raid)
    assert ok2 is True
    assert ctrl._equipped_autoplay_preset == "Raid 2"
    assert len(ctrl._ahk.runs) == 0, "must not click on repeat when preset is already active"

    # 5. Switching to a different preset "Story 1" -> selects new preset
    class DummyBlockStory:
        text = "Story 1"
        x, y, w, h = 10, 10, 50, 20

    ctrl._ocr.read_all = lambda frame: [DummyBlockStory()]
    task_story = {"autoplay_preset": "Story 1"}
    ok3 = ctrl._ensure_autoplay_preset(task_story)
    assert ok3 is True
    assert ctrl._equipped_autoplay_preset == "Story 1"
    assert len(ctrl._ahk.runs) >= 2

    # 6. Back to lobby clears equipped preset
    ctrl._nav.back_to_lobby = lambda: (True, "ok")
    ctrl._back_to_lobby()
    assert ctrl._equipped_autoplay_preset is None
    print("OK: controller autoplay preset lifecycle and repeat carryover")


if __name__ == "__main__":
    test_templates()
    test_regions()
    test_sanitize()
    test_controller_lifecycle()
    print("ALL AUTOPLAY PRESET TESTS PASSED")
