"""Camera setup step.

Sets a consistent top-down-ish camera before matching:
  1. right-click drag downward to pitch the camera down
  2. hold O to zoom out   (~zoom_ms)

There used to be a hold-I zoom-in in front of the drag, which cost a second full
`zoom_ms` — half the sequence — to reach first person before pitching. The pitch is a
rotation and the zoom-out that follows goes to the same extreme either way, so the
camera should land in the same place without it.

Produces an AutoHotkey v2 script; AHK performs the actual input. The script
focuses Roblox itself (WinActivate) so it doesn't depend on Python having
focused it first, and drags from the given viewport-centre screen coordinate so
the right-drag lands on the game.

The pitch amount is a raw-delta total, not a true angle — Roblox maps mouse
travel to rotation and that mapping depends on sensitivity, so `pitch_delta` is a
calibration knob, not a spec value (ponytail: naming the real-hardware corner).

The right-drag uses raw relative mouse input (mouse_event MOUSEEVENTF_MOVE)
instead of AHK's MouseMove "R". Roblox's right-drag captures and recenters the
cursor every frame; absolute cursor moves fight that recentre and come out
jittery / reversed, while raw deltas are read cleanly as camera rotation.
Positive delta drags the mouse DOWN, which pitches the Roblox camera down.
"""

from __future__ import annotations

ROBLOX_AHK_TARGET = "ahk_exe RobloxPlayerBeta.exe"

# mouse_event flags
_MOVE = 0x0001
_RIGHTDOWN = 0x0008
_RIGHTUP = 0x0010

# Total downward raw-mouse travel for the pitch drag. Retuning this invalidates
# every placement coordinate already captured, since a stored pixel only points
# at the same ground while the camera angle stays the same.
PITCH_DELTA = 1000


def camera_setup_script(
    center_x: int,
    center_y: int,
    zoom_ms: int = 3000,
    pitch_delta: int = PITCH_DELTA,
    pitch_steps: int = 40,
) -> str:
    step = max(1, round(pitch_delta / max(1, pitch_steps)))
    return f"""#Requires AutoHotkey v2.0
#SingleInstance Force

if !WinExist("{ROBLOX_AHK_TARGET}")
    ExitApp(1)
WinActivate("{ROBLOX_AHK_TARGET}")
if !WinWaitActive("{ROBLOX_AHK_TARGET}", , 3)
    ExitApp(2)
Sleep(300)

; 0) Centre the cursor so the drag starts over the world rather than over a HUD
; element, and glide rather than teleport: Roblox acts on the last mouse move it
; rendered, and a jump can be read as one instant rotation.
MouseMove({center_x}, {center_y}, 10)
Sleep(150)

; 1) Right-drag down to pitch the camera down (raw relative mouse deltas).
; No cursor move first: it is already centred and the mouse may be locked.
DllCall("mouse_event", "UInt", {_RIGHTDOWN}, "Int", 0, "Int", 0, "UInt", 0, "UPtr", 0)
Sleep(150)
Loop {pitch_steps} {{
    DllCall("mouse_event", "UInt", {_MOVE}, "Int", 0, "Int", {step}, "UInt", 0, "UPtr", 0)
    Sleep(15)
}}
Sleep(150)
DllCall("mouse_event", "UInt", {_RIGHTUP}, "Int", 0, "Int", 0, "UInt", 0, "UPtr", 0)
Sleep(300)

; 2) Zoom out — hold O
Send("{{o down}}")
Sleep({zoom_ms})
Send("{{o up}}")

ExitApp(0)
"""
