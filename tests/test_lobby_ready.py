"""Runnable checks for LobbyNavigator.wait_for_lobby and lobby loading synchronization.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_lobby_ready.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.core.image_search import ImageMatch
from sloppykeys.macro.lobby import LobbyNavigator


class MockEngine:
    def __init__(self, existing_paths: set[str] | None = None):
        self.existing = existing_paths or set()

    def template_exists(self, path: str) -> bool:
        return path in self.existing


class MockAhk:
    def available(self) -> bool:
        return True

    def run(self, *args, **kwargs):
        return (True, "ok")


# 1. When templates don't exist, wait_for_lobby skips cleanly
nav = LobbyNavigator(
    engine=MockEngine(),
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
ok, msg = nav.wait_for_lobby()
assert ok is True
assert "skipping lobby wait" in msg

# 2. When play.png exists and matches, returns immediately
from sloppykeys.content.nav_images import play_image, teams_units_icon_image

engine_with_play = MockEngine({play_image()})
nav_play = LobbyNavigator(
    engine=engine_with_play,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
nav_play._find = lambda path, **kw: ImageMatch(
    profile_name="play", score=1.0, center_x=294, center_y=543, left=250, top=500, width=88, height=86
)
ok, msg = nav_play.wait_for_lobby()
assert ok is True
assert "lobby loaded" in msg
assert "1.00" in msg

# 3. When units_icon exists and matches, returns immediately
engine_with_units = MockEngine({teams_units_icon_image()})
nav_units = LobbyNavigator(
    engine=engine_with_units,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
nav_units._find = lambda path, **kw: ImageMatch(
    profile_name="units", score=0.95, center_x=50, center_y=700, left=30, top=680, width=40, height=40
)
ok, msg = nav_units.wait_for_lobby()
assert ok is True
assert "lobby loaded" in msg
assert "0.95" in msg

# 4. Respects _should_stop
nav_stopped = LobbyNavigator(
    engine=engine_with_play,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
    should_stop=lambda: True,
)
nav_stopped._find = lambda path, **kw: None
ok, msg = nav_stopped.wait_for_lobby()
assert ok is False
assert "stopped by user" in msg

# 5. Times out when deadline expires
nav_timeout = LobbyNavigator(
    engine=engine_with_play,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
nav_timeout.lobby_ready_timeout = 0.001
nav_timeout.search_poll = 0.001
nav_timeout.lobby_ready_poll = 0.001
nav_timeout._find = lambda path, **kw: None
ok, msg = nav_timeout.wait_for_lobby()
assert ok is False
assert "not found within" in msg

# 6. back_to_lobby calls wait_for_lobby
nav_back = LobbyNavigator(
    engine=engine_with_play,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
nav_back._find_click = lambda path, label, **kw: (True, f"clicked {label}")
nav_back.wait_for_lobby = lambda: (True, "lobby ready")
ok, msg = nav_back.back_to_lobby()
assert ok is True
assert "lobby ready" in msg

# 7. click_play calls wait_for_lobby
nav_click_play = LobbyNavigator(
    engine=engine_with_play,
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
nav_click_play.wait_for_lobby = lambda: (True, "lobby ready")
nav_click_play._find_click = lambda path, label, **kw: (True, f"clicked {label}")
ok, msg = nav_click_play.click_play()
assert ok is True
assert "clicked Play" in msg

# 8. equip_team in lobby calls wait_for_lobby; in_match does not
nav_equip = LobbyNavigator(
    engine=MockEngine({teams_units_icon_image()}),
    ahk=MockAhk(),
    roblox_rect=lambda: (0, 0, 1152, 756),
)
lobby_waited = {"called": False}
nav_equip.wait_for_lobby = lambda: (lobby_waited.update({"called": True}), (True, "ok"))[1]
nav_equip._find_click = lambda path, label, **kw: (True, "ok")
nav_equip._find = lambda path, **kw: None

# In-lobby: must call wait_for_lobby
lobby_waited["called"] = False
nav_equip.equip_team(1, in_match=False)
assert lobby_waited["called"] is True, "equip_team in lobby must call wait_for_lobby"

# In-match: must NOT call wait_for_lobby
lobby_waited["called"] = False
nav_equip.equip_team(1, in_match=True)
assert lobby_waited["called"] is False, "equip_team in match must NOT call wait_for_lobby"

print("lobby ready: OK")
