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

print("team loadout tests: OK")
