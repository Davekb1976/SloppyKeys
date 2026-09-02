"""Runnable checks for leaving a challenge detour that started no match.

**Two** panels are open at that point — the challenge list over the gamemode chooser, the
chooser over the lobby — and both have to go, or the *next* task's first search runs against
a covered screen. That failure is silent in the worst way: a covered template scores like a
badly cropped one, so `Bag not found (best 0.52 < 0.80)` read as a capture problem when the
bag was simply behind the chooser.

What is pinned here is the safety split. A **searched** close is safe on any screen, so it
runs even where the OCR scan could not confirm what is up; the **blind** fallback coordinate
is only allowed where the scan proved the panel is there. Getting that backwards fires a
click at the lobby, where a stray click reaches the game world.

Nothing captures or clicks: the navigator and controller are built with `__new__` and their
primitives replaced.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_challenge_close.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.challenge import CLOSE_LIST_CLICK  # noqa: E402
from sloppykeys.content.nav_images import (  # noqa: E402
    challenge_close_image,
    close_gamemode_image,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402

CLOSE = challenge_close_image()
CLOSE_MENU = close_gamemode_image()
BLIND = f"blind:{CLOSE_LIST_CLICK[0]},{CLOSE_LIST_CLICK[1]}"


def navigator(on_disk=frozenset()) -> LobbyNavigator:
    """A navigator where `on_disk` decides which templates have been captured."""
    nav = LobbyNavigator.__new__(LobbyNavigator)
    nav._engine = type(
        "Engine", (), {"template_exists": staticmethod(lambda p: p in on_disk)}
    )()
    nav._rect = lambda: (0, 0, 1152, 756)
    nav.search_timeout = 1.0
    nav.trail = []

    def _find_click(path, label, timeout=0.0, fade_wait=0.0):
        nav.trail.append(f"search:{label}")
        return (True, f"clicked {label}")

    def _click_client(rect, coord, button="left", count=1):
        nav.trail.append(f"blind:{coord[0]},{coord[1]}")
        return (True, "clicked")

    nav._find_click = _find_click
    nav._click_client = _click_client
    return nav


# # The list's close: searched when captured, blind only as a fallback
nav = navigator({CLOSE})
ok, message = nav.close_challenge_list()
assert ok, message
assert nav.trail == ["search:Close challenge list"], nav.trail

# Uncaptured, blind allowed: the old coordinate, and the message names the file to add so a
# fallback cannot quietly become permanent.
nav = navigator()
ok, message = nav.close_challenge_list()
assert ok, message
assert nav.trail == [BLIND], nav.trail
assert CLOSE in message, message

# Uncaptured, blind refused: no click at all. This is the panel-never-read path, where
# nothing has proved which screen is up.
nav = navigator()
ok, message = nav.close_challenge_list(fallback=None)
assert not ok
assert nav.trail == [], "an unconfirmed screen must not be clicked blind"

# # The chooser's close has no fallback at all — the lobby is a live screen
nav = navigator()
ok, message = nav.close_gamemode_menu()
assert not ok
assert CLOSE_MENU in message, message
assert nav.trail == [], "a missing template must not become a guessed lobby click"

nav = navigator({CLOSE_MENU})
ok, message = nav.close_gamemode_menu()
assert ok, message
assert nav.trail == ["search:Close gamemode menu"], nav.trail


# # The controller closes both, in order, and never stops after the first
def closer(panel_confirmed: bool, on_disk=frozenset()) -> list[str]:
    ctrl = MacroController.__new__(MacroController)
    nav = navigator(on_disk)
    ctrl._nav = nav
    ctrl._log = lambda _m: None
    ctrl._close_challenge_ui(panel_confirmed=panel_confirmed)
    return nav.trail


# Both captured: two searches, chooser second. Order matters — the list is on top.
assert closer(True, {CLOSE, CLOSE_MENU}) == [
    "search:Close challenge list",
    "search:Close gamemode menu",
]
# Unconfirmed panel, both captured: **still both**, because a search is safe anywhere. This is
# the case that used to leave two panels up and skip the following task.
assert closer(False, {CLOSE, CLOSE_MENU}) == [
    "search:Close challenge list",
    "search:Close gamemode menu",
]
# Nothing captured, panel confirmed: the list falls back to its coordinate, the chooser
# reports and clicks nothing. Today's shipped behaviour until both are captured.
assert closer(True) == [BLIND], closer(True)
# Nothing captured, nothing confirmed: no clicks at all.
assert closer(False) == [], closer(False)

# The chooser close must not be skipped when the list close fails — the chooser is the one
# covering the bag, and the list may already have been closed by hand.
ctrl = MacroController.__new__(MacroController)
nav = navigator({CLOSE_MENU})
nav._find_click = lambda path, label, **kw: (
    nav.trail.append(f"search:{label}") or (False, f"{label} not found")
)
ctrl._nav = nav
ctrl._log = lambda _m: None
ctrl._close_challenge_ui(panel_confirmed=True)
assert nav.trail[-1] == "search:Close gamemode menu", nav.trail

print("challenge close: OK")
