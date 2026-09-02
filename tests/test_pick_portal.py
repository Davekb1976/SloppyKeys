"""Runnable checks for the end of a Portals match: the picker chain, and the tail that
decides between queueing the next run, repeating, and leaving.

Two things are asserted. The picker chain (`pick_portal`) is shared by both entry points —
the bag confirms with Activate Portal, the result screen with Select — so its ordering and
every refusal are pinned here. And the tail (`_portals_after_match`) takes Select Portal after
**either** outcome: a run measured `Loss. (defeat screen 0.96)` followed by Select Portal at
`1.00`, so which button is on screen is not an outcome signal and this no longer treats it as
one. `click_repeat` is the fallback for not finding it, nothing more.

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
# One SendText per character, paced — sent as one string the field dropped letters. The
# characters and their order are what matter here; the pacing itself is pinned in
# tests/test_search_text.py.
typed = "".join(
    line[10:-2]
    for line in "\n".join(ahk.scripts).splitlines()
    if line.startswith("SendText(")
)
assert typed == "Summer Portal", typed

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


# # The tail: one path out, plus what the next rep is allowed to skip
class TailNav:
    """A result screen. Which buttons it offers is the knob — deliberately *not* the outcome,
    which this no longer infers from anything."""

    def __init__(self, select_portal: bool, repeat: bool = True) -> None:
        self.select_portal = select_portal
        self.repeat = repeat
        self.calls: list[str] = []

    def click_select_portal(self):
        self.calls.append("select_portal")
        if self.select_portal:
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
        return (True, "clicked Repeat") if self.repeat else (False, "Repeat not found (0.07)")

    def back_to_lobby(self):
        self.calls.append("back_to_lobby")
        return (True, "left the stage")


def tail(select_portal: bool, again: bool, repeat: bool = True, task=None):
    """Returns the fake navigator and the `_stage_continued` flag left behind."""
    ctrl = MacroController.__new__(MacroController)
    nav = TailNav(select_portal, repeat=repeat)
    ctrl._nav = nav
    ctrl._log = lambda _m: None
    ctrl.run_camera = lambda: None
    ctrl._stage_continued = False
    ctrl._portals_after_match(task if task is not None else {"search": "Summer"}, again=again)
    return nav, ctrl._stage_continued


# Another rep to come: queue the next portal, never touch Repeat, never leave. Identical after a
# win and after a loss — the outcome is not what this branches on.
nav, continued = tail(select_portal=True, again=True)
assert nav.calls == ["select_portal", "pick:Summer", "wait_ready"], nav.calls
# The next match starts in the world this one ended in, so its walk and camera must be skipped.
# Without this flag the recording replays from where it already finished and the raw-delta pitch
# is applied twice, which moves the ground out from under every placement coordinate.
assert continued, "a run queued from the result screen continues in place"

# Select Portal missing: Repeat is the fallback. It also starts the next match in place.
nav, continued = tail(select_portal=False, again=True)
assert nav.calls == ["select_portal", "repeat"], nav.calls
assert continued, "Repeat replays the same stage without leaving it"

# Neither button there: the lobby is the way out, and that *does* reset the world.
nav, continued = tail(select_portal=False, repeat=False, again=True)
assert nav.calls == ["select_portal", "repeat", "back_to_lobby"], nav.calls
assert not continued, "leaving means the next run walks and sets the camera again"

# Last rep, either way: leave through the lobby without starting anything.
for select_portal in (True, False):
    nav, continued = tail(select_portal=select_portal, again=False)
    assert nav.calls == ["back_to_lobby"], (select_portal, nav.calls)
    assert not continued, (select_portal, "the next task must not inherit a skipped walk")

# No portal name on the task: nothing safe to type, so it cannot queue and falls back instead of
# opening a picker it has nothing to put in.
nav, continued = tail(select_portal=True, again=True, task={})
assert nav.calls == ["repeat"], nav.calls

# # The two readers of `_stage_continued`. A flag that is set and never read fails silently, so
# # neither consumer is taken on trust.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def walk_block(continued: bool) -> FakeAhk:
    ctrl = MacroController.__new__(MacroController)
    ctrl._ahk = FakeAhk()
    ctrl._log = lambda _m: None
    ctrl._app_root = REPO
    ctrl._current_task = {"mode": "Portals", "map": "Summer", "stage": ""}
    ctrl._stage_continued = continued
    ctrl._execute_block({"type": "walk_path", "mode": "auto"})
    return ctrl._ahk


# Flag down, so the shipped Summer recording resolves through the table and replays. This half
# is what keeps the other honest: without it a skip could pass for the wrong reason.
assert walk_block(continued=False).scripts, "auto walk_path must resolve Portals/Summer"
# Flag up: no script at all, not merely a shorter one.
assert walk_block(continued=True).scripts == [], "a continued run must not walk a second time"


def lobby_camera(continued: bool) -> bool:
    """True when `_navigate_lobby`'s in-match shortcut ran the camera."""
    ctrl = MacroController.__new__(MacroController)
    ran: list[int] = []
    ctrl._nav = type("InMatchNav", (), {"in_match": staticmethod(lambda: True)})()
    ctrl._log = lambda _m: None
    ctrl.run_camera = lambda: ran.append(1)
    ctrl._stage_continued = continued
    assert ctrl._navigate_lobby("Portals", "Summer", "") is True
    return bool(ran)


assert lobby_camera(continued=False), "an ordinary Repeat lands on a reset camera — set it"
assert not lobby_camera(continued=True), "pitching an already-set camera doubles the raw delta"

print("pick portal: OK")
