"""Runnable checks for Team Loadout (Teams 1-8).

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_team_loadout.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.gamemodes import sanitize_task
from sloppykeys.content.nav_images import (
    teams_paths,
    expected_paths,
    teams_units_icon_image,
    teams_btn_image,
    teams_load_btn_image,
    teams_confirm_image,
    teams_include_image,
    teams_close_image,
    unit_teams_header_image,
)

# 1. Test task sanitization for team field
for team_num in range(1, 9):
    task = {"mode": "Story", "team": str(team_num)}
    clean = sanitize_task(task)
    assert clean.get("team") == str(team_num), f"Expected team {team_num}, got {clean.get('team')}"

# Invalid team values should sanitize to ""
for invalid in ["0", "9", "10", "abc", "", None, 99]:
    task = {"mode": "Story", "team": invalid}
    clean = sanitize_task(task)
    assert clean.get("team") == "", f"Expected empty team for {invalid!r}, got {clean.get('team')!r}"

# Missing team field should default to ""
task_no_team = {"mode": "Story"}
assert sanitize_task(task_no_team).get("team") == ""

# 2. Test nav_images paths and accessors
expected_team_templates = [
    teams_units_icon_image(),
    teams_btn_image(),
    teams_load_btn_image(),
    teams_confirm_image(),
    teams_include_image(),
    unit_teams_header_image(),
]
for p in expected_team_templates:
    assert "\\" not in p, f"Path has backslashes: {p}"
    assert p.startswith("assets/teams/"), f"Path not in assets/teams/: {p}"

# teams_close_image() reuses the existing lobby close.png
from sloppykeys.content.nav_images import close_panel_image
assert teams_close_image() == close_panel_image()
assert teams_close_image() == "assets/lobby/close.png"

assert set(teams_paths()) == set(expected_team_templates)
assert all(p in expected_paths() for p in expected_team_templates)

# 3. Test LobbyNavigator.equip_team validation
from sloppykeys.macro.lobby import LobbyNavigator

class DummyEngine:
    def template_exists(self, _path: str) -> bool:
        return False
    def find_instances(self, *args, **kwargs):
        return []

class DummyAhk:
    def available(self) -> bool:
        return True
    def run(self, *args, **kwargs):
        return (True, "ok")

nav = LobbyNavigator(
    engine=DummyEngine(),
    ahk=DummyAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)

# Out-of-bounds team numbers should be rejected immediately
ok, msg = nav.equip_team(0)
assert not ok and "invalid team number" in msg
ok, msg = nav.equip_team(9)
assert not ok and "invalid team number" in msg

# Missing template should report clearly
ok, msg = nav.equip_team(1)
assert not ok and "missing" in msg.lower()

# 4. Test Controller _ensure_team_equipped caching logic
class MockNavigator:
    def __init__(self):
        self.equipped_calls = []

    def in_match(self) -> bool:
        return False

    def equip_team(self, team_num: int, in_match: bool = False) -> tuple[bool, str]:
        self.equipped_calls.append((team_num, in_match))
        return (True, f"Team #{team_num} equipped")

# Create a lightweight stub controller to test caching behavior
class ControllerStub:
    def __init__(self):
        self._equipped_team = None
        self._current_task = None
        self._nav = MockNavigator()
        self.logs = []

    def _log(self, msg: str):
        self.logs.append(msg)

# Borrow _ensure_team_equipped method directly from MacroController
from sloppykeys.macro.controller import MacroController
ControllerStub._ensure_team_equipped = MacroController._ensure_team_equipped

stub = ControllerStub()

# No team specified -> returns True, no calls made
assert stub._ensure_team_equipped({"mode": "Story"}) is True
assert len(stub._nav.equipped_calls) == 0
assert stub._equipped_team is None

# Empty team -> returns True, no calls made
assert stub._ensure_team_equipped({"mode": "Story", "team": ""}) is True
assert len(stub._nav.equipped_calls) == 0

# Equip Team 1
assert stub._ensure_team_equipped({"mode": "Story", "team": "1"}) is True
assert len(stub._nav.equipped_calls) == 1
assert stub._nav.equipped_calls[0] == (1, False)
assert stub._equipped_team == 1

# Calling again with Team 1 -> should skip equipping completely (state caching)
assert stub._ensure_team_equipped({"mode": "Story", "team": "1"}) is True
assert len(stub._nav.equipped_calls) == 1  # No additional call!

# Switching to Team 3 -> triggers re-equipping
assert stub._ensure_team_equipped({"mode": "Story", "team": "3"}) is True
assert len(stub._nav.equipped_calls) == 2
assert stub._nav.equipped_calls[1] == (3, False)
assert stub._equipped_team == 3

# Reset on start() simulation
stub._equipped_team = None
assert stub._ensure_team_equipped({"mode": "Story", "team": "3"}) is True
assert len(stub._nav.equipped_calls) == 3

# 5. Test team number regex matching
import re
from sloppykeys.core.ocr import TextBlock
from sloppykeys.core.image_search import ImageMatch

team_num_re = re.compile(r"\bteam\s*#?\s*([1-8])\b", re.IGNORECASE)
assert team_num_re.search("Team #1").group(1) == "1"
assert team_num_re.search("Team 8").group(1) == "8"
assert team_num_re.search("Team#3").group(1) == "3"
assert team_num_re.search("Team # 5").group(1) == "5"
assert team_num_re.search("Team DPS") is None
assert team_num_re.search("Save Team") is None
assert team_num_re.search("Load Team") is None
assert team_num_re.search("Team #10") is None

# 6. Test LobbyNavigator.equip_team with OCR row matching
import numpy as np

class MockOcr:
    def __init__(self, block_sequence):
        self.seq = list(block_sequence)
        self.call_count = 0
    def available(self):
        return (True, "ok")
    def read_all(self, frame):
        idx = min(self.call_count, len(self.seq) - 1)
        self.call_count += 1
        return self.seq[idx]

class MockScanEngine:
    def __init__(self, matches):
        self.matches = matches
    def template_exists(self, p):
        return True
    def to_absolute_path(self, p):
        return p
    def capture_bgr(self, rect):
        return np.zeros((10, 10, 3), dtype=np.uint8)
    def find_instances(self, profile, rect, limit=6):
        return self.matches

class RecordingAhk:
    def __init__(self):
        self.scripts = []
    def available(self):
        return True
    def run(self, script, wait=True, timeout=8):
        self.scripts.append(script)
        return (True, "ok")

blocks_f1 = [
    TextBlock(text="Unit Teams", score=0.96, x=56, y=35, width=97, height=23),
    TextBlock(text="Team #1", score=0.92, x=83, y=92, width=51, height=15),
    TextBlock(text="Team #2", score=0.95, x=83, y=217, width=54, height=15),
]
load_matches = [
    ImageMatch(profile_name="load_team", score=0.99, center_x=630, center_y=167, left=597, top=159, width=67, height=16),
    ImageMatch(profile_name="load_team", score=0.95, center_x=630, center_y=292, left=597, top=284, width=67, height=16),
]

mock_ocr = MockOcr([blocks_f1])
mock_engine = MockScanEngine(load_matches)
mock_ahk = RecordingAhk()

test_nav = LobbyNavigator(
    engine=mock_engine,
    ahk=mock_ahk,
    roblox_rect=lambda: (0, 0, 1152, 756),
    ocr=mock_ocr,
)
test_nav.scroll_settle = 0.001
test_nav.click_settle = 0.001
test_nav._find_click = lambda path, label, **kw: (True, "ok")
test_nav._find = lambda path, **kw: ImageMatch(profile_name="header", score=0.99, center_x=95, center_y=39, left=61, top=21, width=69, height=36)

ok, msg = test_nav.equip_team(2)
assert ok is True, f"Expected success, got: {msg}"
assert "Team #2 equipped" in msg
# Load Team click must be for Team 2 (y=292), not Team 1 (y=167)
assert "292" in mock_ahk.scripts[0]
assert "630" in mock_ahk.scripts[0]

# 7. Test scroll-down then equip
blocks_f2 = [
    TextBlock(text="Team #4", score=0.94, x=83, y=92, width=51, height=15),
    TextBlock(text="Team #5", score=0.97, x=83, y=217, width=54, height=15),
]
mock_ocr_scroll = MockOcr([blocks_f1, blocks_f2])
mock_ahk_scroll = RecordingAhk()
scroll_nav = LobbyNavigator(
    engine=mock_engine,
    ahk=mock_ahk_scroll,
    roblox_rect=lambda: (0, 0, 1152, 756),
    ocr=mock_ocr_scroll,
)
scroll_nav.scroll_settle = 0.001
scroll_nav.click_settle = 0.001
scroll_nav._find_click = lambda path, label, **kw: (True, "ok")
scroll_nav._find = lambda path, **kw: ImageMatch(profile_name="header", score=0.99, center_x=95, center_y=39, left=61, top=21, width=69, height=36)

ok, msg = scroll_nav.equip_team(5)
assert ok is True, f"Expected success, got: {msg}"
assert "Team #5 equipped" in msg
assert "WheelDown" in mock_ahk_scroll.scripts[0]
assert "292" in mock_ahk_scroll.scripts[1]

print("team loadout tests: OK")
