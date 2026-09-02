"""Runnable checks for the route into a Portals run, and that it isn't the Play chain.

Portals has no card in the intermission menu: it is entered from the inventory bag, in the
lobby. Without its own branch the run fell through to `click_play` and then searched for a
`gamemodes/portals.png` that deliberately does not exist, so a Portals task clicked Play and
went nowhere.

No framework, no capture, no input: both classes are built with `__new__`.

`.venv\\Scripts\\python.exe tests\\test_enter_portal.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import (  # noqa: E402
    portal_activate_image,
    portal_bag_image,
    portals_tab_image,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402


class SpyNav(LobbyNavigator):
    def __init__(self, start_found: bool = True) -> None:  # noqa: D107 - test double
        self.calls: list[tuple] = []
        self.panel_fade_wait = 1.0
        self.search_timeout = 6.0
        self.click_settle = 0.0
        self._start_found = start_found

    def _find_click(self, path, label, timeout=0.0, fade_wait=0.0):
        self.calls.append((label, path, fade_wait))
        return (True, f"clicked {label}")

    def pick_portal(self, name, confirm_path, confirm_label):
        self.calls.append(("pick", name, confirm_path))
        return (True, f"typed {name}")

    def click_start_match(self, fallback=None, fade_wait=0.0):
        self.calls.append(("start", fade_wait))
        if self._start_found:
            return (True, "clicked Start")
        return (False, "Start not found (best 0.12 < 0.80)")


# # The chain, in order, with the picker confirming on Activate Portal
nav = SpyNav()
ok, message = nav.enter_portal("Summer Portal")
assert ok, message
assert [c[0] for c in nav.calls] == ["Bag", "Portals tab", "pick", "start"], nav.calls
assert nav.calls[0][1] == portal_bag_image(), nav.calls[0]
assert nav.calls[1][1] == portals_tab_image(), nav.calls[1]
# The tab arrives from the bag click, so it cannot be clicked the instant it matches.
assert nav.calls[1][2] == nav.panel_fade_wait, nav.calls[1]
# The bag button is already on screen, so it pays no fade wait.
assert nav.calls[0][2] == 0.0, nav.calls[0]
assert nav.calls[2] == ("pick", "Summer Portal", portal_activate_image()), nav.calls[2]

# # A missing Start fails the step
# Activating a portal reveals the same Start every other mode uses, and pressing it is what
# loads the stage — confirmed in game. Passing over a miss would hand the caller a 60s
# wait_for_match_ready that cannot succeed, and the log would blame the stage rather than the
# button nobody found.
nav = SpyNav(start_found=False)
ok, message = nav.enter_portal("Summer Portal")
assert not ok, message
assert "start:" in message, message

# # A failed leg stops the chain before anything is typed or activated
class DeadBag(SpyNav):
    def _find_click(self, path, label, timeout=0.0, fade_wait=0.0):
        self.calls.append((label, path, fade_wait))
        return (False, "Bag not found (best 0.20 < 0.80)")


nav = DeadBag()
ok, message = nav.enter_portal("Summer Portal")
assert not ok and "bag:" in message, message
assert [c[0] for c in nav.calls] == ["Bag"], nav.calls


# # The controller refuses a Portals task with no portal name rather than opening the bag
class Ctrl(MacroController):
    def __init__(self, task) -> None:  # noqa: D107 - test double
        self._current_task = task
        self._log = lambda _m: None
        self.entered = []
        self._nav = self

    def enter_portal(self, name):
        self.entered.append(name)
        return (True, "entered")

    def wait_for_match_ready(self, timeout=None):
        return (True, "loaded")

    # `_ensure_camera` gates on this, and the bag chain must set the camera: entering from the
    # bag means we were in the lobby, which is where the pitch resets.
    _camera_set = False

    def run_camera(self):
        self._camera_set = True
        return None


ctrl = Ctrl({"mode": "Portals", "map": "Summer", "search": ""})
assert ctrl._navigate_portal() is False, "no name must not open the bag"
assert ctrl.entered == [], ctrl.entered

ctrl = Ctrl({"mode": "Portals", "map": "Summer", "search": "Summer Portal"})
assert ctrl._navigate_portal() is True
assert ctrl.entered == ["Summer Portal"], ctrl.entered

print("enter portal: OK")
