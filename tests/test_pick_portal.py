"""Runnable checks for the end of a Portals match: the picker chain, and the tail that
decides between queueing the next run, repeating, and leaving.

Two things are asserted. The picker chain (`pick_portal`) is shared by both entry points —
the bag confirms with Activate Portal, the result screen with Select — so its ordering and
every refusal are pinned here. And the tail (`_portals_after_match`) takes Select Portal after
**either** outcome: the defeat screen carries Repeat Stage *and* Select Portal side by side, so
which button is on screen is not an outcome signal and this no longer treats it as one.
`click_repeat` is the fallback for not finding it, nothing more.

The tail also decides what the next match may skip. Repeat Stage and Select Portal both
re-enter without a lobby trip, and the lobby is what resets position and camera — so both keep
**both**, and neither the walk nor the pitch may run again. Back to Lobby is the route that
resets them. Getting this wrong walked the Summer recording from the spot it had already
finished on, every rep.

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
from sloppykeys.content.nav_images import portal_select_image  # noqa: E402
from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402

# There is deliberately no SEARCH template any more — see the module docstring.
CONFIRM = portal_select_image()


class FakeAhk:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def available(self) -> bool:
        return True

    def run(self, script: str, wait: bool = False, timeout: float = 0.0):
        self.scripts.append(script)
        return (True, "ran")


class FakeMatch:
    """What `_find` hands back: absolute centre plus a score, and a label so the trail can
    name which template was clicked without the click site knowing."""

    def __init__(self, label: str, x: int, y: int, score: float = 0.99) -> None:
        self.label = label
        self.center_x = x
        self.center_y = y
        self.score = score


# Where the fake search field is found. Not the tile and not the confirm, so a click landing
# here is distinguishable from every other click in the chain.
FIELD_AT = (500, 120)


def navigator(confirm_after_typing: bool, ahk=None) -> LobbyNavigator:
    """A navigator whose confirm button appears either straight after typing or only
    after the result slot is clicked. The search field is always found — it is the gate."""
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
        # The confirm is found from the start: it is the gate proving *this* picker is open,
        # and it really is on screen before the tile is touched — that is what the two
        # releases of skipped tile clicks demonstrated.
        if path == CONFIRM:
            return FakeMatch("Select", 986, 643)
        return None

    def _click(match):
        nav.trail.append(f"click:{match.label}@{match.center_x},{match.center_y}")
        return (True, f"clicked at {match.center_x},{match.center_y}")

    def _click_client(rect, coord, button="left", count=1):
        # The search field *and* the tile are both measured points now, so both arrive here and
        # the trail records coordinates rather than names — that is what tells them apart.
        nav.trail.append(f"blind:{coord[0]},{coord[1]}")
        if tuple(coord) not in (BAG_FIELD, MATCH_FIELD):
            nav.slot_clicked = True
        return (True, "clicked")

    nav._find_click = _find_click
    nav._find = _find
    nav._click = _click
    nav._click_client = _click_client
    return nav


# The search field is a **required** point now, one per panel, so every case has to supply one
# or it refuses before reaching what the case is actually about.
BAG_FIELD = (500, 120)
MATCH_FIELD = (620, 140)


def reset_slot(coord=None, bag_field=BAG_FIELD, match_field=MATCH_FIELD) -> None:
    overrides: dict[str, tuple[int, int]] = {}
    if coord is not None:
        overrides[portals_table.slot_key(1)] = coord
    if bag_field is not None:
        overrides[portals_table.search_key()] = bag_field
    if match_field is not None:
        overrides[portals_table.search_key(True)] = match_field
    portals_table.apply_point_overrides(overrides)


# # The tile is clicked even when the confirm is already lit — that is the whole ordering.
# # This asserted the opposite for two releases: it looked for the confirm first and skipped the
# # tile whenever it was found, and it was always found, so the tile was never clicked in any
# # run. The button is not proof of *which* portal it would activate — the search filters the
# # grid without selecting anything — so skipping the tile confirms whatever was selected before.
reset_slot()
ahk = FakeAhk()
nav = navigator(confirm_after_typing=True, ahk=ahk)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert ok, message
assert nav.trail == ["blind:500,120", "blind:394,253", "click:Select"], nav.trail
assert nav.slot_clicked, "the tile must be clicked before the portal is confirmed"
# One SendText per character, paced — sent as one string the field dropped letters. The
# characters and their order are what matter here; the pacing itself is pinned in
# tests/test_search_text.py.
typed = "".join(
    line[10:-2]
    for line in "\n".join(ahk.scripts).splitlines()
    if line.startswith("SendText(")
)
assert typed == "Summer Portal", typed

# # A stored override moves the tile, and the confirm follows it
reset_slot((640, 300))
nav = navigator(confirm_after_typing=False)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert ok, message
assert nav.trail == ["blind:500,120", "blind:640,300", "click:Select"], nav.trail

# # Same case, but the slot reads as unmeasured: refuse and name the fix. The bag's slot 1
# # ships a measured default, so the way to be unset is to store `UNSET`.
reset_slot(portals_table.UNSET)
nav = navigator(confirm_after_typing=False)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select")
assert not ok
assert "Click Points" in message, message
assert "Bag result slot 1" in message, "the refusal must name which grid to measure"
# The refusal still says the name was already typed — the portal is not spent, but the field
# holds it. Terse now (`search '<name>'`), because six verbose steps joined made one
# ~300-character success line; a failure keeps the diagnostic that follows this part.
assert "search 'Summer Portal'" in message, message
assert not nav.slot_clicked, "an unset point must not become a click"

# # The in-match grid is a **different** point. Both ship measured now, so what matters is
# # that `in_match` reaches the right one — the two differ only in x, so a chain that ignored
# # the flag would click a tile 100px away and spend whatever portal is sitting there.
reset_slot()
assert portals_table.slot_coord(1) == (394, 253), "the bag's shipped default"
assert portals_table.slot_coord(1, in_match=True) == (294, 253), "the in-match one"
nav = navigator(confirm_after_typing=False)
assert nav.pick_portal("Summer Portal", CONFIRM, "Select", in_match=True)[0]
# Note the **field** differs too: each panel's field is its own point, which is the whole
# reason the template had to go — the two fields are pixel-identical, so only position separates
# them, and the in-match one was being matched at 1.00 on the wrong box.
assert nav.trail == ["blind:620,140", "blind:294,253", "click:Select"], nav.trail
# Same call without the flag takes the bag's field and the bag's tile.
nav = navigator(confirm_after_typing=False)
assert nav.pick_portal("Summer Portal", CONFIRM, "Activate Portal")[0]
assert nav.trail == ["blind:500,120", "blind:394,253", "click:Activate Portal"], nav.trail

# # Each grid reads its own stored key, so measuring one cannot move the other.
reset_slot()
portals_table.apply_point_overrides(
    {
        portals_table.slot_key(1, True): (700, 410),
        portals_table.search_key(): BAG_FIELD,
        portals_table.search_key(True): MATCH_FIELD,
    }
)
assert portals_table.slot_coord(1) == (394, 253), "the bag falls back to its own default"
assert portals_table.slot_coord(1, in_match=True) == (700, 410)
nav = navigator(confirm_after_typing=False)
assert nav.pick_portal("Summer Portal", CONFIRM, "Select", in_match=True)[0]
assert nav.trail == ["blind:620,140", "blind:700,410", "click:Select"], nav.trail

# # An in-match slot stored as UNSET still refuses and names its own row, not the bag's.
portals_table.apply_point_overrides(
    {
        portals_table.slot_key(1, True): portals_table.UNSET,
        portals_table.search_key(True): MATCH_FIELD,
    }
)
nav = navigator(confirm_after_typing=False)
ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select", in_match=True)
assert not ok
assert "In-match result slot 1" in message, message
assert not nav.slot_clicked, "an unset point must not fall back to the other grid's"

# # A search field **stored as UNSET** refuses, and names which panel to measure
# # Both fields ship a measured default now, so the way to be uncalibrated is to store UNSET —
# # the same shape the slot case above uses. The refusal has to survive that: a guess focuses
# # nothing, and the portal name then goes into the world where `r`, `t` and `x` are priority,
# # upgrade and sell.
for in_match, row in ((False, "Bag search field"), (True, "In-match search field")):
    reset_slot(bag_field=portals_table.UNSET, match_field=portals_table.UNSET)
    ahk = FakeAhk()
    nav = navigator(confirm_after_typing=True, ahk=ahk)
    ok, message = nav.pick_portal("Summer Portal", CONFIRM, "Select", in_match=in_match)
    assert not ok, in_match
    assert row in message, (in_match, message)
    assert "Click Points" in message, message
    assert nav.trail == [], "nothing may be clicked"
    assert ahk.scripts == [], "and nothing typed"

# # The **confirm button** is the gate now, not the field. Without it the picker never opened,
# # so nothing is clicked and nothing is typed — this is what replaces the old template check.
reset_slot()
ahk = FakeAhk()
closed = navigator(confirm_after_typing=True, ahk=ahk)
closed._find = lambda path, timeout=0.0, region=None: None
ok, message = closed.pick_portal("Summer Portal", CONFIRM, "Select", in_match=True)
assert not ok, "a picker that never opened must not be typed into"
assert "Select" in message and "never opened" in message, message
assert closed.trail == [], "no click before the picker is proved to be up"
assert ahk.scripts == [], "and no typing"

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

# # What the chain searches for, and in what order. The **confirm** goes first: it is the proof
# # the picker is open, and it is the only template involved now — the field and the tile are
# # both measured points. A search for anything else before typing would be the old bug back.
reset_slot((640, 300))
nav = navigator(confirm_after_typing=True)
seen: list[str] = []
original_find = nav._find


def spy(path, timeout=0.0, region=None):
    seen.append(path)
    return original_find(path, timeout=timeout, region=region)


nav._find = spy
assert nav.pick_portal("Summer", CONFIRM, "Select")[0]
assert seen and seen[0] == CONFIRM, seen
assert set(seen) == {CONFIRM}, ("only the confirm is searched", seen)

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

    def pick_portal(self, name, confirm_path, confirm_label, in_match=False):
        # `in_match` recorded, not ignored: the result screen's grid is a different point, and
        # passing the bag's would click a tile the task never asked for.
        self.calls.append(f"pick:{name}:{'match' if in_match else 'bag'}")
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
    """Returns the fake navigator and both flags left behind: `_kept_position`, `_camera_set`.

    `_camera_set` starts True the way it would after any earlier match, so a route that leaves
    it True is one that carried the pitch over.
    """
    ctrl = MacroController.__new__(MacroController)
    nav = TailNav(select_portal, repeat=repeat)
    ctrl._nav = nav
    ctrl._log = lambda _m: None
    ctrl.run_camera = lambda: None
    ctrl._kept_position = False
    ctrl._camera_set = True
    ctrl._portals_after_match(task if task is not None else {"search": "Summer"}, again=again)
    return nav, ctrl._kept_position, ctrl._camera_set


# Another rep to come: queue the next portal, never touch Repeat, never leave. Identical after a
# win and after a loss — the outcome is not what this branches on.
nav, kept, camera = tail(select_portal=True, again=True)
assert nav.calls == ["select_portal", "pick:Summer:match", "wait_ready"], nav.calls
# Same playfield, no lobby in between, so the character never moved and the camera never reset.
# This asserted the opposite for one release and the walk ran on every rep because of it.
assert kept, "Select Portal re-enters in place — the next rep must not walk"
assert camera, "Select Portal never reaches the lobby, so the pitch carries over"

# Select Portal missing: Repeat is the fallback, and Repeat Stage keeps position and camera.
nav, kept, camera = tail(select_portal=False, again=True)
assert nav.calls == ["select_portal", "repeat"], nav.calls
assert kept, "Repeat Stage drops you back in on the spot — no second walk"
assert camera, "Repeat Stage never reaches the lobby either"

# Neither button there: the lobby is the way out. That is the one route that resets both.
nav, kept, camera = tail(select_portal=False, repeat=False, again=True)
assert nav.calls == ["select_portal", "repeat", "back_to_lobby"], nav.calls
assert not kept, "leaving means the next run walks"
assert not camera, "the lobby is where the camera resets — pitch it again on the way back in"

# Last rep, either way: leave through the lobby without starting anything.
for select_portal in (True, False):
    nav, kept, camera = tail(select_portal=select_portal, again=False)
    assert nav.calls == ["back_to_lobby"], (select_portal, nav.calls)
    assert not kept, (select_portal, "the next task must not inherit a skipped walk")
    assert not camera, (select_portal, "nor a camera flag from before the lobby trip")

# No portal name on the task: nothing safe to type, so it cannot queue and falls back instead of
# opening a picker it has nothing to put in.
nav, kept, camera = tail(select_portal=True, again=True, task={})
assert nav.calls == ["repeat"], nav.calls
assert kept, "the fallback is still Repeat Stage, so the position is still kept"

# # The readers of both flags. A flag that is set and never read fails silently, so neither
# # consumer is taken on trust.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def walk_block(kept_position: bool) -> FakeAhk:
    ctrl = MacroController.__new__(MacroController)
    ctrl._ahk = FakeAhk()
    ctrl._log = lambda _m: None
    ctrl._app_root = REPO
    ctrl._current_task = {"mode": "Portals", "map": "Summer", "stage": ""}
    ctrl._kept_position = kept_position
    ctrl._execute_block({"type": "walk_path", "mode": "auto"})
    return ctrl._ahk


# Respawned, so the shipped Summer recording resolves through the table and replays. This half
# is what keeps the other honest: without it a skip could pass for the wrong reason.
assert walk_block(kept_position=False).scripts, "auto walk_path must resolve Portals/Summer"
# Position kept: no script at all, not merely a shorter one.
assert walk_block(kept_position=True).scripts == [], "Repeat Stage must not walk a second time"


def lobby_camera(camera_set: bool) -> bool:
    """True when `_navigate_lobby`'s in-match shortcut ran the camera."""
    ctrl = MacroController.__new__(MacroController)
    ran: list[int] = []
    ctrl._nav = type("InMatchNav", (), {"in_match": staticmethod(lambda: True)})()
    ctrl._log = lambda _m: None
    ctrl.run_camera = lambda: ran.append(1)
    ctrl._camera_set = camera_set
    assert ctrl._navigate_lobby("Portals", "Summer", "") is True
    return bool(ran)


# Started with the game already in a match: nothing has pitched yet, so it must.
assert lobby_camera(camera_set=False), "the first match of a run still needs the camera"
# Straight into another match without a lobby trip: the pitch carried over.
assert not lobby_camera(camera_set=True), "re-pitching a set camera doubles the raw delta"


# # `run_camera` is what records the camera as set, and only when AHK reports the script ran.
def camera_flag(ahk_ok: bool) -> bool:
    ctrl = MacroController.__new__(MacroController)
    ctrl._log = lambda _m: None
    ctrl._rect = lambda: (0, 0, 1152, 756)
    ctrl._delays = {"camera_zoom": 0.0}
    ctrl._ahk = type("Ahk", (), {"run": staticmethod(lambda *a, **k: (ahk_ok, "ran"))})()
    ctrl._camera_set = False
    ctrl.run_camera()
    return ctrl._camera_set


assert camera_flag(ahk_ok=True), "a camera that ran must be recorded as set"
# Otherwise a failed pitch reads as done and every later match skips it.
assert not camera_flag(ahk_ok=False), "a camera that failed must not be recorded as set"

print("pick portal: OK")
