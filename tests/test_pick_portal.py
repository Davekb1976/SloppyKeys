"""Runnable checks for the end of a Portals match: the picker chain, and the tail that
decides between queueing the next run, repeating, and leaving.

Two things are asserted. The picker chain (`pick_portal`) is shared by both entry points —
the bag confirms with Activate Portal, the victory screen with Select — so its ordering and
every refusal are pinned here. And the tail (`_portals_after_match`) reads the outcome purely
from which button is on screen, because Portals is the only mode whose *victory* screen has
no Repeat: a win consumes the portal and offers Select Portal, a loss keeps it and offers
Repeat.

The refusals matter more than the happy paths. Confirming a portal consumes it, so a chain
that types a repaired name or clicks an unmeasured coordinate spends the wrong item while the
log still reads like a working run.

Nothing here captures or clicks: the navigator and controller are built with `__new__` and
their primitives replaced.

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
from sloppykeys.macro.controller import MacroController  # noqa: E402
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


# # The tail: which button is on screen is the whole outcome signal
class TailNav:
    """Offers Select Portal on a win, Repeat on a loss, Back to Lobby always."""

    def __init__(self, won: bool) -> None:
        self.won = won
        self.calls: list[str] = []

    def click_select_portal(self):
        self.calls.append("select_portal")
        if self.won:
            return (True, "clicked Select Portal")
        return (False, "Select Portal not found (best 0.09 < 0.80)")

    def pick_portal(self, name, confirm_path, confirm_label):
        self.calls.append(f"pick:{name}")
        return (True, "typed and confirmed")

    def wait_for_match_ready(self, timeout=None):
        self.calls.append("wait_ready")
        return (True, "stage loaded")

    def click_repeat(self, timeout=None):
        self.calls.append("repeat")
        if self.won:
            # A won Portals screen has no Repeat at all — that asymmetry is the point.
            return (False, "Repeat not found (best 0.07 < 0.80)")
        return (True, "clicked Repeat")

    def back_to_lobby(self):
        self.calls.append("back_to_lobby")
        return (True, "left the stage")


def tail(won: bool, again: bool, task=None) -> TailNav:
    ctrl = MacroController.__new__(MacroController)
    nav = TailNav(won)
    ctrl._nav = nav
    ctrl._log = lambda _m: None
    ctrl.run_camera = lambda: None
    ctrl._portals_after_match(task if task is not None else {"search": "Summer"}, again=again)
    return nav


# A win with another rep to come: queue the next portal, never touch Repeat, never leave.
nav = tail(won=True, again=True)
assert nav.calls == ["select_portal", "pick:Summer", "wait_ready"], nav.calls

# A loss with another rep to come: no Select Portal, so Repeat replays the portal it kept.
nav = tail(won=False, again=True)
assert nav.calls == ["select_portal", "repeat"], nav.calls

# Last rep, either way: leave through the lobby without starting anything.
for won in (True, False):
    nav = tail(won=won, again=False)
    assert nav.calls == ["back_to_lobby"], (won, nav.calls)

# No portal name on the task: nothing to type, so it cannot queue — and on a win there is no
# Repeat either, so it leaves rather than clicking blindly.
nav = tail(won=True, again=True, task={})
assert nav.calls == ["repeat", "back_to_lobby"], nav.calls

print("pick portal: OK")
