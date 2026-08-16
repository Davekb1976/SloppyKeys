"""Full input recording and replay.

Records mouse movement, clicks, scroll, and keyboard input inside the Roblox
viewport. Positions are stored in 1152×756 reference space. Replay uses
SendInput for mouse and the keyboard package for keys, with 1ms timer
resolution.

Uses the `keyboard` and `mouse` packages for global hooks — they handle the
Windows hook chain, message pump, and thread safety correctly. Raw ctypes
SetWindowsHookEx is fragile (a single mistake in CallNextHookEx bricks all
input system-wide); these packages are battle-tested wrappers.

Walk Path Recording:
  Simpler recorder that only captures WASD + shift state transitions via polling.
  Good for movement paths. Stored in paths/<name>.json.

Input Recording (Record block):
  Full mouse + keyboard via global hooks. Captures everything inside the game
  viewport. Stored in recordings/<name>.json.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
from typing import Callable

from sloppykeys.core.win32.bindings import (
    get_cursor_pos,
    is_key_down,
    user32,
)
from sloppykeys.core.win32.roblox_window import (
    client_to_screen,
    client_size,
    find_roblox_window,
    is_window,
)

# Reference viewport — all coords stored relative to this.
REF_W = 1152
REF_H = 756

# Walk path polling
VK_W, VK_A, VK_S, VK_D, VK_SHIFT = 0x57, 0x41, 0x53, 0x44, 0x10
WALK_KEYS = {"w": VK_W, "a": VK_A, "s": VK_S, "d": VK_D, "shift": VK_SHIFT}
WALK_POLL_MS = 30

# Input recording throttle: mouse move events faster than this are dropped.
_MOVE_MIN_INTERVAL = 0.008

# Mouse buttons we care about.
_MOUSE_BUTTONS = {"left", "right", "middle"}

# Windows multimedia timer for 1ms precision during replay.
_winmm = ctypes.windll.winmm if sys.platform == "win32" else None


class RecordingAlreadyActive(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Walk Path Recorder (polling, WASD only)
# ═══════════════════════════════════════════════════════════════════════════

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
        _write_atomic(path, {"name": self._name, "events": self._events})


# ═══════════════════════════════════════════════════════════════════════════
# Full Input Recorder (hooks via keyboard/mouse packages)
# ═══════════════════════════════════════════════════════════════════════════

class InputRecorder:
    """Records mouse and keyboard input inside the Roblox viewport.

    Uses the `keyboard` and `mouse` packages for global hooks.
    Producer/consumer: hook callbacks enqueue raw data, a worker processes it.
    """

    def __init__(self, app_root: str) -> None:
        self._app_root = app_root
        self._events: list[dict] = []
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._worker: threading.Thread | None = None
        self._start_time: float | None = None
        self._last_move_t: float = -1.0
        self._buttons_down: set[str] = set()
        self._keys_down: set[str] = set()
        self._hwnd: int | None = None
        self._kb_hook = None
        self._mouse_hook = None

    @property
    def is_recording(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Begin recording. Returns False if Roblox isn't found."""
        hwnd = find_roblox_window()
        if not hwnd:
            return False

        import keyboard as kb_lib
        import mouse as mouse_lib

        self._hwnd = hwnd
        self._events = []
        self._start_time = None
        self._last_move_t = -1.0
        self._buttons_down = set()
        self._keys_down = set()
        self._running = True

        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

        self._kb_hook = kb_lib.hook(self._on_key_event)
        self._mouse_hook = mouse_lib.hook(self._on_mouse_event)
        return True

    def stop(self) -> list[dict]:
        """Stop recording and return the event list (unsaved)."""
        if not self._running:
            return []

        self._running = False
        import keyboard as kb_lib
        import mouse as mouse_lib

        # Unhook
        try:
            if self._kb_hook is not None:
                kb_lib.unhook(self._kb_hook)
        except (KeyError, ValueError):
            pass
        try:
            if self._mouse_hook is not None:
                mouse_lib.unhook(self._mouse_hook)
        except (KeyError, ValueError):
            pass
        self._kb_hook = None
        self._mouse_hook = None

        # Drain the queue
        self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=2.0)

        # Close out anything still held
        end_t = self._elapsed(time.perf_counter())
        for button in sorted(self._buttons_down):
            self._events.append({"t": end_t, "type": "up", "button": button})
        self._buttons_down.clear()
        for key in sorted(self._keys_down):
            self._events.append({"t": end_t, "type": "keyup", "key": key})
        self._keys_down.clear()

        self._events.sort(key=lambda ev: ev["t"])
        events = self._events
        self._events = []
        return events

    # ── Hook callbacks (minimal work, just enqueue) ──

    def _on_key_event(self, event) -> None:
        if not self._running:
            return
        name = getattr(event, "name", None)
        event_type = getattr(event, "event_type", None)
        if not name or event_type not in ("down", "up"):
            return
        self._queue.put(("key", event_type, name, time.perf_counter()))

    def _on_mouse_event(self, event) -> None:
        if not self._running:
            return
        import mouse as mouse_lib
        now = time.perf_counter()

        if isinstance(event, mouse_lib.MoveEvent):
            self._queue.put(("move", event.x, event.y, now))
        elif isinstance(event, mouse_lib.ButtonEvent):
            event_type = event.event_type
            if event_type == mouse_lib.DOUBLE:
                event_type = mouse_lib.DOWN
            if event.button not in _MOUSE_BUTTONS:
                return
            if event_type not in (mouse_lib.DOWN, mouse_lib.UP):
                return
            pos = mouse_lib.get_position()
            self._queue.put(("button", event_type, event.button, pos, now))
        elif isinstance(event, mouse_lib.WheelEvent):
            pos = mouse_lib.get_position()
            self._queue.put(("wheel", event.delta, pos, now))

    # ── Worker thread ──

    def _process_queue(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._process_item(item)

    def _process_item(self, item: tuple) -> None:
        kind = item[0]

        if kind == "key":
            _, event_type, name, now = item
            key = str(name).lower()
            if event_type == "down":
                if key in self._keys_down:
                    return  # auto-repeat, skip
                self._keys_down.add(key)
                self._events.append({"t": self._elapsed(now), "type": "keydown", "key": key})
            else:
                if key not in self._keys_down:
                    return  # stray up
                self._keys_down.discard(key)
                self._events.append({"t": self._elapsed(now), "type": "keyup", "key": key})

        elif kind == "move":
            _, x, y, now = item
            t = self._elapsed(now)
            if t - self._last_move_t < _MOVE_MIN_INTERVAL:
                return
            ref = self._screen_to_ref(x, y)
            if ref is None or not self._in_bounds(*ref):
                return
            self._last_move_t = t
            self._events.append({"t": t, "type": "move", "x": round(ref[0], 1), "y": round(ref[1], 1)})

        elif kind == "button":
            import mouse as mouse_lib
            _, event_type, button, pos, now = item
            if event_type == mouse_lib.UP:
                if button not in self._buttons_down:
                    return
                self._buttons_down.discard(button)
                self._events.append({"t": self._elapsed(now), "type": "up", "button": button})
                return
            # DOWN — always emit a move at the click position right before the
            # down, even if the move throttle would have suppressed it. This
            # guarantees that during replay, the cursor is exactly where the
            # click needs to land (Roblox acts on its last processed move).
            if button in self._buttons_down:
                self._events.append({"t": self._elapsed(now), "type": "up", "button": button})
            ref = self._screen_to_ref(*pos)
            if ref is None or not self._in_bounds(*ref):
                self._buttons_down.discard(button)
                return
            # Force a move event at this position (click target)
            self._events.append({"t": self._elapsed(now), "type": "move", "x": round(ref[0], 1), "y": round(ref[1], 1)})
            self._last_move_t = self._elapsed(now)
            self._buttons_down.add(button)
            self._events.append({"t": self._elapsed(now), "type": "down", "button": button})

        elif kind == "wheel":
            _, delta, pos, now = item
            ref = self._screen_to_ref(*pos)
            if ref is None or not self._in_bounds(*ref):
                return
            self._events.append({"t": self._elapsed(now), "type": "scroll", "delta": int(round(delta * 120))})

    # ── Helpers ──

    def _elapsed(self, now: float) -> float:
        if self._start_time is None:
            self._start_time = now
        return round(now - self._start_time, 4)

    def _screen_to_ref(self, screen_x: int, screen_y: int) -> tuple[float, float] | None:
        hwnd = self._hwnd
        if not hwnd or not is_window(hwnd):
            return None
        origin = client_to_screen(hwnd, 0, 0)
        size = client_size(hwnd)
        if not origin or not size:
            return None
        cx, cy = origin
        cw, ch = size
        if cw <= 0 or ch <= 0:
            return None
        return ((screen_x - cx) * REF_W / cw, (screen_y - cy) * REF_H / ch)

    def _in_bounds(self, rx: float, ry: float) -> bool:
        return -1 <= rx <= REF_W + 1 and -1 <= ry <= REF_H + 1


# ═══════════════════════════════════════════════════════════════════════════
# Replay (uses SendInput for mouse — games listen to the input stack, not
# SetCursorPos which is what the mouse package uses internally)
# ═══════════════════════════════════════════════════════════════════════════

# SendInput structures (replay only)
import ctypes.wintypes as wt

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_ULONG_PTR = ctypes.c_size_t
_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_VIRTUALDESK = 0x4000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_MIDDLEDOWN = 0x0020
_MOUSEEVENTF_MIDDLEUP = 0x0040
_MOUSEEVENTF_WHEEL = 0x0800
_KEYEVENTF_SCANCODE = 0x0008
_KEYEVENTF_KEYUP = 0x0002
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", _ULONG_PTR)]


class _KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", _ULONG_PTR)]


class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyBdInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("_u",)
    _fields_ = [("type", ctypes.c_ulong), ("_u", _InputUnion)]


def _send(inp: _Input) -> None:
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))


def _screen_to_absolute(x: int, y: int) -> tuple[int, int]:
    """Convert screen coords to SendInput's 0–65535 absolute range on the virtual desktop."""
    vx = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    vy = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    vw = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    vh = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    abs_x = ((x - vx) * 65536 + 32768) // vw if vw else 0
    abs_y = ((y - vy) * 65536 + 32768) // vh if vh else 0
    return (max(0, min(65535, abs_x)), max(0, min(65535, abs_y)))


def _si_move(x: int, y: int) -> None:
    """Move cursor via SendInput (games see this as real hardware input)."""
    ax, ay = _screen_to_absolute(x, y)
    inp = _Input(type=_INPUT_MOUSE)
    inp.mi = _MouseInput(dx=ax, dy=ay, mouseData=0,
                         dwFlags=_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
                         time=0, dwExtraInfo=0)
    _send(inp)


_BTN_DOWN = {"left": _MOUSEEVENTF_LEFTDOWN, "right": _MOUSEEVENTF_RIGHTDOWN, "middle": _MOUSEEVENTF_MIDDLEDOWN}
_BTN_UP = {"left": _MOUSEEVENTF_LEFTUP, "right": _MOUSEEVENTF_RIGHTUP, "middle": _MOUSEEVENTF_MIDDLEUP}


def _si_button(button: str, down: bool) -> None:
    flags = (_BTN_DOWN if down else _BTN_UP).get(button, 0)
    if not flags:
        return
    inp = _Input(type=_INPUT_MOUSE)
    inp.mi = _MouseInput(dx=0, dy=0, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)
    _send(inp)


def _si_scroll(delta: int) -> None:
    inp = _Input(type=_INPUT_MOUSE)
    inp.mi = _MouseInput(dx=0, dy=0, mouseData=delta, dwFlags=_MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=0)
    _send(inp)


def _si_key(vk: int, up: bool) -> None:
    scan = _user32.MapVirtualKeyW(vk, 0)
    flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if up else 0)
    inp = _Input(type=_INPUT_KEYBOARD)
    inp.ki = _KeyBdInput(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    _send(inp)


def _vk_from_name(key_name: str) -> int | None:
    """Resolve a key name (from recording) to a VK code."""
    import keyboard as kb_lib
    try:
        sc = kb_lib.key_to_scan_codes(key_name)
        if sc:
            # scan_code_to_vk
            vk = _user32.MapVirtualKeyW(sc[0], 3)  # MAPVK_VSC_TO_VK_EX
            return vk if vk else None
    except (ValueError, IndexError):
        pass
    return None


def replay_recording(
    events: list[dict],
    hwnd: int | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Replay a recorded event list with original timing via SendInput.

    SendInput pushes events through the real input stack — games see them
    as actual hardware input (unlike SetCursorPos which some games ignore).
    Uses MOUSEEVENTF_VIRTUALDESK for multi-monitor correctness.
    """
    if not events:
        return

    if hwnd is None:
        hwnd = find_roblox_window()
    if not hwnd or not is_window(hwnd):
        return

    origin = client_to_screen(hwnd, 0, 0)
    size = client_size(hwnd)
    if not origin or not size:
        return
    left, top = origin
    cw, ch = size
    sx = cw / REF_W
    sy = ch / REF_H

    if _winmm:
        _winmm.timeBeginPeriod(1)

    held_buttons: set[str] = set()
    held_keys: set[int] = set()

    try:
        last_t = 0.0
        for ev in events:
            if stop_event and stop_event.is_set():
                break
            delay = ev.get("t", last_t) - last_t
            if delay > 0:
                if stop_event:
                    if stop_event.wait(delay):
                        break
                else:
                    time.sleep(delay)
            last_t = ev.get("t", last_t)

            etype = ev.get("type")
            if etype == "move":
                screen_x = int(left + ev.get("x", 0) * sx)
                screen_y = int(top + ev.get("y", 0) * sy)
                _si_move(screen_x, screen_y)
            elif etype == "down":
                button = ev.get("button", "left")
                if button in held_buttons:
                    _si_button(button, False)
                _si_button(button, True)
                held_buttons.add(button)
            elif etype == "up":
                button = ev.get("button", "left")
                _si_button(button, False)
                held_buttons.discard(button)
            elif etype == "scroll":
                delta = ev.get("delta", 0)
                if delta:
                    _si_scroll(delta)
            elif etype == "keydown":
                key = ev.get("key", "")
                vk = _vk_from_name(key) if key else None
                if vk:
                    _si_key(vk, up=False)
                    held_keys.add(vk)
            elif etype == "keyup":
                key = ev.get("key", "")
                vk = _vk_from_name(key) if key else None
                if vk:
                    _si_key(vk, up=True)
                    held_keys.discard(vk)
    finally:
        for button in held_buttons:
            _si_button(button, False)
        for vk in held_keys:
            _si_key(vk, up=True)
        if _winmm:
            _winmm.timeEndPeriod(1)


# ═══════════════════════════════════════════════════════════════════════════
# Walk Path Replay (via AHK — keys only, timing preserved)
# ═══════════════════════════════════════════════════════════════════════════

def replay_walk_script(app_root: str, name: str) -> str:
    """Generate an AHK v2 script that replays a walk path recording."""
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

    for ahk_key in AHK_KEYS.values():
        lines.append("Send(\"{" + ahk_key + " up}\")")
    lines.append("ExitApp(0)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════

def _write_atomic(path: str, payload: dict, compact: bool = False) -> None:
    tmp = path + ".tmp"
    try:
        kwargs = {"separators": (",", ":")} if compact else {}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _\-]", "", name or "").strip()
    return cleaned or "recording"


def save_recording(app_root: str, name: str, events: list[dict]) -> str:
    name = (name or "").strip() or "recording"
    folder = os.path.join(app_root, "recordings")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{_safe_name(name)}.json")
    _write_atomic(path, {"name": name, "events": events}, compact=True)
    return name


def load_recording(app_root: str, name: str) -> dict:
    path = os.path.join(app_root, "recordings", f"{_safe_name(name)}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"name": name, "events": []}


def list_recordings(app_root: str) -> list[str]:
    folder = os.path.join(app_root, "recordings")
    if not os.path.isdir(folder):
        return []
    names = []
    for f in sorted(os.listdir(folder)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(folder, f), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                names.append(data.get("name", f[:-5]))
            except (OSError, json.JSONDecodeError):
                names.append(f[:-5])
    return names


def delete_recording(app_root: str, name: str) -> bool:
    """Delete a recording by name."""
    path = os.path.join(app_root, "recordings", f"{_safe_name(name)}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def list_walk_paths(app_root: str) -> list[str]:
    folder = os.path.join(app_root, "paths")
    if not os.path.isdir(folder):
        return []
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))
