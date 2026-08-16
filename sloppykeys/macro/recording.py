"""Walk path + full input recording and replay.

Walk Path Recording:
  Polls WASD + sprint keys at ~30ms, logging only state transitions with timestamps.
  Stored as JSON in data/paths/<name>.json. Replayed by sleeping between events.

Input Recording:
  Polls mouse position + button state + keyboard at ~10ms. Coords converted to
  1152×756 reference space at capture time. Events outside game bounds are dropped.
  Stored in data/recordings/<name>.json.

Both recorders run on a daemon thread and are start/stop controlled from the bridge.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from sloppykeys.core.win32.bindings import (
    VK_LBUTTON,
    get_cursor_pos,
    is_key_down,
)

# WASD key codes
VK_W = 0x57
VK_A = 0x41
VK_S = 0x53
VK_D = 0x44
VK_SHIFT = 0x10  # sprint

WALK_KEYS = {"w": VK_W, "a": VK_A, "s": VK_S, "d": VK_D, "shift": VK_SHIFT}
WALK_POLL_MS = 30
INPUT_POLL_MS = 10

# Reference viewport size — coords are stored relative to this.
REF_W = 1152
REF_H = 756

RectProvider = Callable[[], tuple[int, int, int, int] | None]


@dataclass
class WalkEvent:
    """One state transition in a walk path."""
    t: float  # time offset from start (seconds)
    key: str  # which key
    down: bool  # pressed or released


@dataclass
class InputEvent:
    """One event in a full input recording."""
    t: float
    kind: str  # "move", "click", "release", "key_down", "key_up"
    x: int = 0  # in 1152×756 space
    y: int = 0
    button: str = ""
    key: str = ""


class WalkRecorder:
    """Records WASD state transitions on a background thread."""

    def __init__(self, name: str, app_root: str) -> None:
        self._name = name
        self._app_root = app_root
        self._events: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    @property
    def is_recording(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._events = []
        self._running = True
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> str:
        """Stop recording, save, return the path name."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._save()
        return self._name

    def _poll_loop(self) -> None:
        prev_state: dict[str, bool] = {k: False for k in WALK_KEYS}
        while self._running:
            t = time.perf_counter() - self._start_time
            for name, vk in WALK_KEYS.items():
                pressed = is_key_down(vk)
                if pressed != prev_state[name]:
                    prev_state[name] = pressed
                    self._events.append({"t": round(t, 4), "key": name, "down": pressed})
            time.sleep(WALK_POLL_MS / 1000.0)

    def _save(self) -> None:
        folder = os.path.join(self._app_root, "paths")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{self._name}.json")
        payload = {"name": self._name, "events": self._events}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass


class InputRecorder:
    """Records mouse + keyboard on a background thread."""

    def __init__(self, name: str, app_root: str, roblox_rect: RectProvider) -> None:
        self._name = name
        self._app_root = app_root
        self._rect = roblox_rect
        self._events: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    @property
    def is_recording(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._events = []
        self._running = True
        self._start_time = time.perf_counter()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> str:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._save()
        return self._name

    def _poll_loop(self) -> None:
        prev_pos = (0, 0)
        prev_lmb = False
        while self._running:
            t = time.perf_counter() - self._start_time
            rect = self._rect()
            if rect is None:
                time.sleep(INPUT_POLL_MS / 1000.0)
                continue

            rx, ry, rw, rh = rect
            pos = get_cursor_pos()
            if pos is None:
                time.sleep(INPUT_POLL_MS / 1000.0)
                continue

            cx, cy = pos
            # Check if cursor is within game bounds
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                # Convert to reference space
                ref_x = round((cx - rx) * REF_W / rw)
                ref_y = round((cy - ry) * REF_H / rh)

                if (ref_x, ref_y) != prev_pos:
                    self._events.append({"t": round(t, 4), "kind": "move", "x": ref_x, "y": ref_y})
                    prev_pos = (ref_x, ref_y)

                lmb = is_key_down(VK_LBUTTON)
                if lmb != prev_lmb:
                    prev_lmb = lmb
                    kind = "click" if lmb else "release"
                    self._events.append({"t": round(t, 4), "kind": kind, "x": ref_x, "y": ref_y})

            time.sleep(INPUT_POLL_MS / 1000.0)

    def _save(self) -> None:
        folder = os.path.join(self._app_root, "recordings")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{self._name}.json")
        payload = {"name": self._name, "events": self._events}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass


def replay_walk_script(app_root: str, name: str) -> str:
    """Generate an AHK v2 script that replays a walk path recording.

    Presses/releases WASD keys with the original timing preserved.
    """
    path = os.path.join(app_root, "paths", f"{name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""

    events = data.get("events", [])
    if not events:
        return ""

    AHK_KEYS = {"w": "w", "a": "a", "s": "s", "d": "d", "shift": "LShift"}
    lines = [
        "#Requires AutoHotkey v2.0",
        "#SingleInstance Force",
        'if !WinExist("ahk_exe RobloxPlayerBeta.exe")',
        "    ExitApp(1)",
        'if !WinActive("ahk_exe RobloxPlayerBeta.exe") {',
        '    WinActivate("ahk_exe RobloxPlayerBeta.exe")',
        '    if !WinWaitActive("ahk_exe RobloxPlayerBeta.exe", , 3)',
        "        ExitApp(2)",
        "    Sleep(150)",
        "}",
    ]

    prev_t = 0.0
    for ev in events:
        t = ev.get("t", 0.0)
        key = ev.get("key", "")
        down = ev.get("down", True)
        ahk_key = AHK_KEYS.get(key, "")
        if not ahk_key:
            continue
        wait_ms = max(0, round((t - prev_t) * 1000))
        if wait_ms > 0:
            lines.append(f"Sleep({wait_ms})")
        state = "down" if down else "up"
        lines.append("Send(\"{" + ahk_key + " " + state + "}\")")
        prev_t = t

    # Release all keys at the end
    for ahk_key in AHK_KEYS.values():
        lines.append("Send(\"{" + ahk_key + " up}\")")
    lines.append("ExitApp(0)")
    return "\n".join(lines)


def replay_input_script(app_root: str, name: str) -> str:
    """Generate an AHK v2 script that replays a full input recording.

    Moves the mouse and clicks with original timing. Coordinates are converted from
    1152×756 reference space to screen space at runtime using the Roblox window position.
    """
    path = os.path.join(app_root, "recordings", f"{name}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""

    events = data.get("events", [])
    if not events:
        return ""

    # AHK script that reads the Roblox client rect at start and scales coords
    lines = [
        "#Requires AutoHotkey v2.0",
        "#SingleInstance Force",
        'CoordMode("Mouse", "Screen")',
        'if !WinExist("ahk_exe RobloxPlayerBeta.exe")',
        "    ExitApp(1)",
        'if !WinActive("ahk_exe RobloxPlayerBeta.exe") {',
        '    WinActivate("ahk_exe RobloxPlayerBeta.exe")',
        '    if !WinWaitActive("ahk_exe RobloxPlayerBeta.exe", , 3)',
        "        ExitApp(2)",
        "    Sleep(150)",
        "}",
        "; Get client area position",
        'hwnd := WinExist("ahk_exe RobloxPlayerBeta.exe")',
        "pt := Buffer(8, 0)",
        "NumPut('Int', 0, pt, 0)",
        "NumPut('Int', 0, pt, 4)",
        'DllCall("ClientToScreen", "Ptr", hwnd, "Ptr", pt)',
        "cx := NumGet(pt, 0, 'Int')",
        "cy := NumGet(pt, 4, 'Int')",
        "; Get client size",
        "rect := Buffer(16, 0)",
        'DllCall("GetClientRect", "Ptr", hwnd, "Ptr", rect)',
        "cw := NumGet(rect, 8, 'Int')",
        "ch := NumGet(rect, 12, 'Int')",
        "",
    ]

    prev_t = 0.0
    for ev in events:
        t = ev.get("t", 0.0)
        kind = ev.get("kind", "")
        wait_ms = max(0, round((t - prev_t) * 1000))
        if wait_ms > 0:
            lines.append(f"Sleep({wait_ms})")

        if kind == "move":
            rx, ry = ev.get("x", 0), ev.get("y", 0)
            lines.append(f"MouseMove(cx + ({rx} * cw) // {REF_W}, cy + ({ry} * ch) // {REF_H}, 0)")
        elif kind == "click":
            lines.append('Click("Left Down")')
        elif kind == "release":
            lines.append('Click("Left Up")')
        prev_t = t

    lines.append('Click("Left Up")')
    lines.append("ExitApp(0)")
    return "\n".join(lines)


def list_walk_paths(app_root: str) -> list[str]:
    """Names of all recorded walk paths."""
    folder = os.path.join(app_root, "paths")
    if not os.path.isdir(folder):
        return []
    names = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".json"):
            names.append(f[:-5])
    return names


def list_input_recordings(app_root: str) -> list[str]:
    """Names of all input recordings."""
    folder = os.path.join(app_root, "recordings")
    if not os.path.isdir(folder):
        return []
    names = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".json"):
            names.append(f[:-5])
    return names
