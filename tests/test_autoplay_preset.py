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
    match_autoplay_preset,
    region_key,
    region_specs,
)
from sloppykeys.content.gamemodes import sanitize_task
from sloppykeys.core.ocr import TextBlock
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

    task_chal = {"mode": "Challenge", "autoplay_preset": "Preset 5"}
    assert sanitize_task(task_chal)["autoplay_preset"] == "Preset 5"

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
        center_x = 500
        center_y = 500

    class DummyBlock:
        text = "Raid 2"
        x, y, w, h = 10, 10, 50, 20

    class DummyEngine:
        def template_exists(self, path): return True
        def capture_bgr(self, box): return "frame"

    class DummyOcr:
        def available(self): return (True, "ok")
        def read_all(self, frame): return [DummyBlock()]

    class DummyNav:
        fade_wait = 0.01
        def _find(self, path, timeout=0.0): return DummyHit()

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


def test_matching() -> None:
    # 1. TextBlock .w and .h properties
    tb = TextBlock(text="Preset5", score=0.99, x=10, y=20, width=55, height=18)
    assert tb.w == 55
    assert tb.h == 18

    # Game scan blocks
    raw_texts = [
        "Presets", "AH", "Portals", "Preset2", "Preset3",
        "Preset4", "Preset5", "Preset6", "Preset7", "Preset8", "Preset9",
    ]
    blocks = [TextBlock(text=t, score=0.98, x=10, y=10, width=50, height=20) for t in raw_texts]

    # 2. "Preset 5" (with space) matches "Preset5" (without space)
    hit, desc = match_autoplay_preset("Preset 5", blocks)
    assert hit is not None
    assert hit.text == "Preset5"
    assert "exact" in desc

    # Case variations and punctuation
    for query in ["Preset 5", "Preset5", "preset 5", "preset-5", "preset_5"]:
        hit, _ = match_autoplay_preset(query, blocks)
        assert hit is not None and hit.text == "Preset5"

    # Other presets
    hit2, _ = match_autoplay_preset("Preset 2", blocks)
    assert hit2 is not None and hit2.text == "Preset2"

    hit_ah, _ = match_autoplay_preset("AH", blocks)
    assert hit_ah is not None and hit_ah.text == "AH"

    hit_portals, _ = match_autoplay_preset("Portals", blocks)
    assert hit_portals is not None and hit_portals.text == "Portals"

    # Strict digits: "Preset 5" must never match "Preset2" or "Presets"
    hit_fail, _ = match_autoplay_preset("Preset 1", blocks)
    assert hit_fail is None

    # 3. Custom renamed preset "test"
    blocks_test = [
        TextBlock(text=t, score=0.95, x=10, y=10, width=50, height=20)
        for t in ["Presets", "AH", "Portals", "Preset2", "test", "Preset6"]
    ]
    for test_query in ["test", "Test", "TEST", "test ", " test"]:
        hit_t, desc_t = match_autoplay_preset(test_query, blocks_test)
        assert hit_t is not None
        assert hit_t.text == "test"

    # Fuzzy match on minor typo / OCR glitch
    hit_fuzzy, desc_f = match_autoplay_preset("tst", blocks_test)
    assert hit_fuzzy is not None and hit_fuzzy.text == "test"
    assert "fuzzy" in desc_f

    # 4. Multi-line wrapped preset names (e.g. 'copyofporta' + 'ls' inside the button card)
    blocks_multiline = [
        TextBlock(text="Portals", score=1.0, x=29, y=19, width=47, height=16),
        TextBlock(text="Preset2", score=1.0, x=147, y=20, width=52, height=14),
        TextBlock(text="copyofporta", score=1.0, x=15, y=135, width=76, height=19),
        TextBlock(text="Ls", score=0.63, x=44, y=149, width=17, height=15),
    ]
    # Searching for "copy of portals" or "copyofportals" MUST match the wrapped card, NEVER "Portals"
    for q in ["copy of portals", "copyofportals", "Copy Of Portals"]:
        hit_copy, desc_c = match_autoplay_preset(q, blocks_multiline)
        assert hit_copy is not None, f"Expected match for {q}"
        assert hit_copy.text == "copyofporta Ls", f"Matched wrong block: {hit_copy.text}"
        assert hit_copy.x == 15 and hit_copy.y == 135
        assert hit_copy.width == 76 and hit_copy.height == 29
        assert "exact" in desc_c

    # Searching for "Portals" matches "Portals", not "copyofporta Ls"
    hit_p, _ = match_autoplay_preset("Portals", blocks_multiline)
    assert hit_p is not None and hit_p.text == "Portals"

    print("OK: match_autoplay_preset robust matching tests (including multiline and copy-of-portals isolation)")


if __name__ == "__main__":
    test_templates()
    test_regions()
    test_sanitize()
    test_controller_lifecycle()
    test_matching()
    print("ALL AUTOPLAY PRESET TESTS PASSED")
