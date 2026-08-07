"""AutoHotkey v2 script builders shared by every macro step.

Python decides what to do; these render the script that AHK runs to do it. Kept in
one module because the lobby navigator and the unit placer need the same
primitives, and a second copy of the nudge would drift.

**The nudge**: glide onto the target and wiggle before clicking, instead of
teleporting the cursor there. Roblox only lights up a UI element (and often only
accepts the click) once a hover event lands, and an instant jump frequently
doesn't produce one. The same applies to the scroll wheel over a carousel. Every
click in this project goes through `nudge_click_script` for that reason.

Tested without the wiggle: clicks are ignored, so it stays. What the wiggle costs
is precision — see `NUDGE_SETTLE_MS`.
"""

from __future__ import annotations

ROBLOX_AHK_TARGET = "ahk_exe RobloxPlayerBeta.exe"

BUTTONS = {"left": "Left", "right": "Right", "middle": "Middle"}


def _header(settle_ms: int = 150) -> str:
    """Script preamble: focus Roblox itself so a step doesn't depend on Python
    having focused it, and bail with a distinct exit code if it isn't there.

    The activate and its settle are skipped when Roblox is *already* the active
    window, which it is for every script after the first in a run. Activating an
    already-active window is a no-op, so the `settle_ms` wait after it was pure
    cost: measured 150ms on every script, and a placement step runs three or four.
    """
    return f"""#Requires AutoHotkey v2.0
#SingleInstance Force
CoordMode("Mouse", "Screen")
if !WinExist("{ROBLOX_AHK_TARGET}")
    ExitApp(1)
if !WinActive("{ROBLOX_AHK_TARGET}") {{
    WinActivate("{ROBLOX_AHK_TARGET}")
    if !WinWaitActive("{ROBLOX_AHK_TARGET}", , 3)
        ExitApp(2)
    Sleep({settle_ms})
}}
"""


# Master switch for the nudge. Confirmed needed: without the wiggle, clicks are
# ignored. Off is only useful for re-testing that.
USE_NUDGE = True

# AHK MouseMove speed: 0 is instant, 100 is slowest, 2 is AHK's default. The nudge
# needs *motion* (a teleport produces no hover event), not slowness, and the approach
# move can cross most of the screen — at speed 10 that glide alone was a visible
# chunk of every click. 4 for the approach, 3 for the short wiggle legs: still many
# intermediate mouse events, far less wall time. Raise them if hovers start missing.
APPROACH_SPEED = 4
WIGGLE_SPEED = 3
MOVE_SPEED = 3          # parking / Sequence Move, where no hover is needed
WIGGLE_GAP_MS = 30      # pause between wiggle legs

# How long the cursor sits still on the exact target before the click.
#
# This is the fix for "it placed the unit where the wiggle was, not where I
# clicked". Roblox reads the cursor from its own last processed mouse-move, not
# from the OS at click time, so if the click arrives while the wiggle's motion is
# still being consumed, the game acts on a stale position. Landing on the target
# as the *final* movement and then holding still gives Roblox a frame to catch up.
# Raise it if a placement still lands off-target — that is the *first* knob to undo
# if accuracy regresses, since it is the one this value was introduced to fix.
#
# **It is a frame count, not a duration.** Roblox drains those queued moves per rendered
# frame, so the wait that matters is N frames — and N frames is a different number of
# milliseconds on every monitor. 200ms was tuned on a 165Hz panel, which is ~33 frames; the
# same 200ms on a 60Hz panel is only 12 frames, so the click fired while Roblox was still
# catching up and landed on a stale position. That is why the macro placed units correctly
# on one monitor and not another at identical resolution and scaling.
NUDGE_SETTLE_FRAMES = 33
TUNED_REFRESH_HZ = 165
# Never go below the value that was actually tuned, and never wait absurdly long on a
# mis-reported refresh rate.
NUDGE_SETTLE_MIN_MS = 200
NUDGE_SETTLE_MAX_MS = 900

# The refresh rate of the monitor Roblox is on. Module state rather than a parameter on
# every builder: there is exactly one Roblox window on exactly one monitor at a time, and
# threading it through ten call sites would say the same thing ten times. MainWindow sets
# it when Roblox attaches and when the window changes screen.
_refresh_hz = TUNED_REFRESH_HZ


def set_refresh_hz(hz: int) -> None:
    """Tell the script builders how fast the game's monitor refreshes."""
    global _refresh_hz
    _refresh_hz = max(1, int(hz))


def refresh_hz() -> int:
    return _refresh_hz


def nudge_settle_ms(hz: int | None = None) -> int:
    """`NUDGE_SETTLE_FRAMES` worth of milliseconds at the game monitor's refresh rate.

    Returns exactly `NUDGE_SETTLE_MS`-equivalent (200ms) at the 165Hz it was tuned on, so
    the monitor it already worked on behaves identically.
    Clamped both ways: the floor keeps the tuned value as a minimum, the ceiling stops a
    bogus 1Hz reading from adding a second to every click.
    """
    rate = max(1, int(_refresh_hz if hz is None else hz))
    return max(NUDGE_SETTLE_MIN_MS, min(NUDGE_SETTLE_MAX_MS, round(NUDGE_SETTLE_FRAMES * 1000 / rate)))


# Wiggle amplitude in pixels.
#
# WIDE is for lobby UI: a card is large, so swinging well outside it and coming
# back guarantees a fresh mouse-enter.
#
# TIGHT is for anything in the 3D world — placing a unit on the ground, or clicking
# a placed one. A wide swing leaves the model entirely, so the hover it generates
# belongs to the ground or to whatever is behind the unit, and the click that
# follows selects nothing; for a placement it moves the ghost off the stored point.
# Staying within a few pixels keeps every event where it belongs. A tight spread
# also switches the wiggle to the x axis — see _nudge.
SPREAD_WIDE = 24
SPREAD_TIGHT = 3

# Gap between repeated clicks in one script (priority cycling, difficulty cycling).
# Only applied between clicks — see nudge_click_script.
CLICK_GAP_MS = 120


def _nudge(x: int, y: int, spread: int = SPREAD_WIDE) -> str:
    """Move onto the point, with or without the wiggle (see USE_NUDGE).

    The wiggle always ends exactly on the target, so the most recent position
    Roblox can have processed is the one we want — see NUDGE_SETTLE_MS.

    Axis matters, not just amplitude. A tight spread means the target is in the 3D
    world (placing or selecting a unit), and there the vertical screen axis is
    *depth*: a few pixels up the screen is metres further out on the ground plane,
    so a vertical wiggle drags the placement ghost across the map and the hover
    Roblox processes belongs somewhere else entirely. Sideways motion of the same
    size barely changes depth, so world nudges wiggle on x. Lobby UI keeps the
    vertical swing it was tuned with.
    """
    settle = nudge_settle_ms()
    if not USE_NUDGE:
        return f"""
MouseMove({x}, {y}, {APPROACH_SPEED})
Sleep({settle})
"""
    far = max(1, int(spread))
    near = max(1, far // 3)
    if far <= SPREAD_TIGHT:
        first, second, third = (x - far, y), (x + near, y), (x - near, y)
    else:
        first, second, third = (x, y - far), (x, y + near), (x, y - near)
    return f"""
; Approach, wiggle to trigger the hover state, then land on the target last and
; hold — the hold is what keeps the click off the wiggle point.
MouseMove({first[0]}, {first[1]}, {APPROACH_SPEED})
Sleep({WIGGLE_GAP_MS})
MouseMove({second[0]}, {second[1]}, {WIGGLE_SPEED})
Sleep({WIGGLE_GAP_MS})
MouseMove({third[0]}, {third[1]}, {WIGGLE_SPEED})
Sleep({WIGGLE_GAP_MS})
MouseMove({x}, {y}, {WIGGLE_SPEED})
Sleep({settle})
"""


def _park_wiggle(x: int, y: int, spread: int = SPREAD_WIDE) -> str:
    """Retreat to (x, y) with motion, not a teleport.

    A single `MouseMove` to the corner was not enough: the cursor arrived, and Roblox still
    drew the tooltip raised by the click before it, covering the button the next search had
    to find. Roblox only drops a hover when it *processes* a move off the element, and one
    jump can be consumed as a single event on the wrong frame. Three legs landing on the
    park point give it the leave it needs — the same reasoning as `_nudge`, for the opposite
    purpose.

    Wiggles **inward on x**. The park point is the client's top-left corner, so a vertical
    swing (what `_nudge` uses) would leave the client area entirely, and a leave off the
    *window* is not a leave off the button.

    No trailing sleep: whatever follows is an image search that polls on a deadline, so it
    can absorb one stale frame far cheaper than every click can pay a fixed wait.
    """
    far = max(1, int(spread))
    near = max(1, far // 3)
    return f"""; Retreat with motion so Roblox processes the mouse-leave and drops the tooltip.
MouseMove({x + far}, {y}, {MOVE_SPEED})
Sleep({WIGGLE_GAP_MS})
MouseMove({x + near}, {y}, {MOVE_SPEED})
Sleep({WIGGLE_GAP_MS})
MouseMove({x}, {y}, {MOVE_SPEED})
"""


def nudge_click_script(
    x: int,
    y: int,
    button: str = "left",
    count: int = 1,
    spread: int = SPREAD_WIDE,
    park: tuple[int, int] | None = None,
) -> str:
    """Move onto (x, y) with the nudge, then click. Screen coordinates.

    Use `spread=SPREAD_TIGHT` for anything in the 3D world (see the constants).

    `park` retreats the cursor once the click is done, in the *same* script, with a wiggle
    (`_park_wiggle`) rather than a jump. Lobby UI needs it: the cursor left sitting on a
    button keeps that button hovered, and Roblox then draws a tooltip over its neighbours —
    which is how a Select Stage search failed while the button was plainly on screen. A
    plain move there was **not** enough; the tooltip survived it. A separate parking script
    would work too but costs another AHK launch per click, and it can be forgotten at a call
    site.

    The `CLICK_GAP_MS` pause before parking is not cosmetic: Roblox acts on its own last
    processed mouse-move, so a move issued in the same breath as the click risks the click
    being applied at the parked position — the same failure as the wiggle overshoot that
    `NUDGE_SETTLE_FRAMES` exists for. Off by default, so in-world clicks (placement,
    selecting a unit) are unchanged.
    """
    which = BUTTONS.get(str(button).lower(), "Left")
    times = max(1, int(count))
    # The gap goes *between* clicks, not after the last one: a trailing sleep only
    # delays ExitApp, and Python already waits `settle` after the script returns.
    tail = ""
    if park is not None:
        tail = f"Sleep({CLICK_GAP_MS})\n{_park_wiggle(int(park[0]), int(park[1]))}"
    return f"""{_header()}{_nudge(x, y, spread)}
Loop {times} {{
    if (A_Index > 1)
        Sleep({CLICK_GAP_MS})
    Click("{which}")
}}
{tail}ExitApp(0)
"""


def move_script(x: int, y: int) -> str:
    """Park the cursor somewhere harmless, with the retreat wiggle.

    Wiggles for the same reason the post-click park does: whatever was hovered — including
    something the *user* left hovered before pressing F1 — only drops its tooltip when
    Roblox processes a move off it.

    No trailing sleep: the moves are delivered when MouseMove returns, and the search that
    follows polls on a deadline.
    """
    return f"""{_header(0)}
{_park_wiggle(x, y)}ExitApp(0)
"""


def point_at_script(x: int, y: int) -> str:
    """Put the cursor on a screen point. No activation, no click, no wiggle.

    Deliberately **not** `_header`, which is wrong twice for a diagnostic. It activates
    Roblox and waits up to 3s for the switch — and moving the mouse needs no focus at all,
    so that wait bought nothing and cost more than the whole script: pressed from the macro's
    own window, with Roblox behind a frameless always-on-top window, `WinWaitActive` ran its
    full 3s and the caller timed out at 5.

    Nor should it steal focus. This exists to show *where* a template matched, and raising
    the game over the window the button lives in would hide the answer.

    Glides rather than teleports (`MouseMove` speed 10) because the point is for a person to
    watch it arrive.
    """
    return f"""#Requires AutoHotkey v2.0
#SingleInstance Force
CoordMode("Mouse", "Screen")
MouseMove({int(x)}, {int(y)}, 10)
ExitApp(0)
"""


def scroll_script(cx: int, cy: int, park_x: int, park_y: int, notches: int) -> str:
    """Wheel over (cx, cy), then park at (park_x, park_y).

    One notch at a time: a single `{WheelDown N}` is often dropped. Parking
    afterwards matters because a hovered card changes appearance and stops
    matching its template.
    """
    direction = "WheelDown" if notches >= 0 else "WheelUp"
    count = abs(int(notches))
    return f"""{_header(120)}{_nudge(cx, cy)}
Loop {count} {{
    Send("{{{direction}}}")
    Sleep(70)
}}
Sleep(120)
{_park_wiggle(park_x, park_y)}ExitApp(0)
"""


def key_script(key: str, count: int = 1, hold_ms: int = 0, gap_ms: int = 120) -> str:
    """Press one key `count` times. Callers must pass a key already validated by
    `config.keybinds.sanitize_game_key` — this interpolates it into a Send()."""
    times = max(1, int(count))
    # The gap separates presses; it is not a tail. A single press used to pay it for
    # nothing, on every slot key, priority press and upgrade press.
    gap = max(0, int(gap_ms))
    if hold_ms > 0:
        body = f"""
Loop {times} {{
    if (A_Index > 1)
        Sleep({gap})
    Send("{{{key} down}}")
    Sleep({max(1, int(hold_ms))})
    Send("{{{key} up}}")
}}
"""
    else:
        body = f"""
Loop {times} {{
    if (A_Index > 1)
        Sleep({gap})
    Send("{{{key}}}")
}}
"""
    return f"{_header(80)}{body}ExitApp(0)\n"


def drag_script(x: int, y: int, to_x: int, to_y: int, button: str = "left") -> str:
    """Press at (x, y), glide to (to_x, to_y), release. Absolute coordinates, so
    this is for UI dragging — camera rotation uses raw deltas (see camera.py)."""
    which = BUTTONS.get(str(button).lower(), "Left")
    return f"""{_header()}{_nudge(x, y)}
Click("{which} Down")
Sleep(120)
MouseMove({to_x}, {to_y}, 8)
Sleep(120)
Click("{which} Up")
ExitApp(0)
"""
