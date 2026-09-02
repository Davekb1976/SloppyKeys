"""Runnable checks for the portal picker chain: search field, type, confirm.

Shared by both entry points — the bag confirms with Activate Portal, the victory screen with
Select — so this asserts the ordering and every refusal. Nothing here captures or clicks: the
navigator is built with `__new__` and its find/click primitives are replaced.

The refusals matter more than the happy path. Confirming a portal consumes it, so a chain
that types a repaired name or clicks an unmeasured coordinate spends the wrong item while
the log still reads like a working run.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_pick_portal.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content import portals as portals_table  # noqa: E402
from sloppykeys.content.nav_images import (  # noqa: E402
    portal_search_image,
    portal_select_image,
)
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402

SEARCH = portal_search_image()
CONFIRM = portal_select_image()


class FakeAhk:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def available(self) -> bool:
        return True

    def run(self, script: str, wait: bool = False, timeout: float = 0.0):
        self.scripts.append(script)
        return (True, "ran")


def navigator(confirm_after_typing: bool, ahk=None) -> LobbyNavigator:
    """A navigator whose confirm button appears either straight after typing or only
    after the result slot is clicked."""
    nav = LobbyNavigator.__new__(LobbyNavigator)
    nav._ahk = ahk or FakeAhk()
    nav._log = lambda _m: None
    nav._rect = lambda: (0, 0, 1152, 756)
    nav.search_timeout = 1.0
    nav.panel_fade_wait = 0.0
    nav.click_settle = 0.0
    nav.park_client = (8, 8)
    nav.trail: list[str] = []
    nav.slot_clicked = False

    def _find_click(path, label, timeout=0.0, fade_wait=0.0):
        nav.trail.append(f"click:{label}")
        if path == CONFIRM and not (confirm_after_typing or nav.slot_clicked):
            return (False, f"{label} not found (best 0.10 < 0.80)")
        return (True, f"clicked {label}")

    def _find(path, timeout=0.0, region=None):
        if path == CONFIRM and (confirm_after_typing or nav.slot_clicked):
            return object()  # any truthy match
        return None

    def _click_client(rect, coord, button="left", count=1):
        nav.slot_clicked = True
        nav.trail.append(f"slot:{coord[0]},{coord[1]}")
        return (True, "clicked")

    nav._find_click = _find_click
    nav._find = _find
    nav._click_client = _click_client
    return nav


def reset_slot(coord=None) -> None:
    portals_table.apply_point_overrides(
        {} if coord is None else {portals_table.slot_key(1): coord}
    )


# # The panel's confirm is already lit after typing: no tile click at all
reset_slot()
ahk = FakeAhk()
nav = navigator(confirm_after_typing=True, ahk=ahk)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert ok, message
assert nav.trail == ["click:Portal search", "click:Select"], nav.trail
assert not nav.slot_clicked, "the tile must not be clicked when the confirm is already up"
assert 'SendText("Summer Portal")' in "".join(ahk.scripts), ahk.scripts

# # The confirm only appears once the filtered tile is selected
reset_slot((640, 300))
nav = navigator(confirm_after_typing=False)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert ok, message
assert nav.trail == ["click:Portal search", "slot:640,300", "click:Select"], nav.trail

# # Same case, but the slot was never measured: refuse and name the fix
reset_slot()
nav = navigator(confirm_after_typing=False)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert not ok
assert "Click Points" in message, message
assert "typed 'Summer Portal'" in message, message
assert not nav.slot_clicked, "an unset point must not become a click"

# # A name that cannot be typed safely never reaches SendText
reset_slot((640, 300))
for bad in ('Summer" MsgBox("x', "Summer`nMsgBox", "", "   ", "a" * 41):
    ahk = FakeAhk()
    nav = navigator(confirm_after_typing=True, ahk=ahk)
    ok, message = nav.pick_portal(bad, CONFIRM, "Select")
    assert not ok, repr(bad)
    assert "not a usable portal name" in message, message
    assert ahk.scripts == [], "a rejected name must fire no script at all"
    assert nav.trail == [], "and must not even open the search field"

# # The search field is what the chain looks for first, by its own template
reset_slot((640, 300))
nav = navigator(confirm_after_typing=True)
seen: list[str] = []
original = nav._find_click


def spy(path, label, timeout=0.0, fade_wait=0.0):
    seen.append(path)
    return original(path, label, timeout=timeout, fade_wait=fade_wait)


nav._find_click = spy
assert nav.pick_portal("Summer", CONFIRM, "Select")[0]
assert seen == [SEARCH, CONFIRM], seen

reset_slot()
print("pick portal: OK")
