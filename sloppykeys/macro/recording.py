"""Full input recording and replay via low-level Windows hooks.

Records mouse movement, clicks, scroll, and keyboard input inside the Roblox
viewport. Positions are stored in 1152×756 reference space. Replay converts
back to screen coords and uses SendInput for precise timing.

Uses SetWindowsHookEx (WH_KEYBOARD_LL / WH_MOUSE_LL) via ctypes — no external
dependency. The hooks run on a dedicated thread with its own message pump
(PeekMessage loop) so hook callbacks return fast and never block the UI.

Walk Path Recording:
  Simpler recorder that only captures WASD + shift state transitions via polling.
  Good for movement paths. Stored in paths/<name>.json.

Input Recording (Record block):
  Full mouse + keyboard via global hooks. Captures everything inside the game
  viewport. Stored in recordings/<name>.json.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import threading
import time
from typing import Callable

from sloppykeys.core.win32.bindings import (
    VK_LBUTTON,
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
# 125Hz comfortably beats a 60Hz display.
_MOVE_MIN_INTERVAL = 0.008

# Windows hooks
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A

LLKHF_INJECTED = 0x00000010

# Hook callback type
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)

# For PeekMessage
PM_REMOVE = 0x0001

RectProvider = Callable[[], tuple[int, int, int, int] | None]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


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
        payload = {"name": self._name, "events": self._events}
        _write_atomic(path, payload)


# ═══════════════════════════════════════════════════════════════════════════
# Full Input Recorder (hooks, mouse + keyboard)
# ═══════════════════════════════════════════════════════════════════════════

class InputRecorder:
    """Records mouse and keyboard input inside the Roblox viewport using
    low-level Windows hooks. Producer/consumer pattern: hook callbacks
    enqueue minimal data, a worker thread processes it.
    """

    def __init__(self, app_root: str) -> None:
        self._app_root = app_root
        self._events: list[dict] = []
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._hook_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._start_time: float | None = None
        self._last_move_t: float = -1.0
        self._buttons_down: set[str] = set()
        self._keys_down: set[int] = set()
        self._hwnd: int | None = None
        # Must hold references to prevent GC of the callback
        self._kb_hook: int | None = None
        self._mouse_hook: int | None = None
        self._kb_proc: HOOKPROC | None = None
        self._mouse_proc: HOOKPROC | None = None

    @property
    def is_recording(self) -> bool:
        return self._running

    def start(self) -> bool:
        """Begin recording. Returns False if Roblox isn't found."""
        hwnd = find_roblox_window()
        if not hwnd:
            return False
        self._hwnd = hwnd
        self._events = []
        self._start_time = None
        self._last_move_t = -1.0
        self._buttons_down = set()
        self._keys_down = set()
        self._running = True

        self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()

        self._hook_thread = threading.Thread(target=self._hook_loop, daemon=True)
        self._hook_thread.start()
        return True

    def stop(self) -> list[dict]:
        """Stop recording and return the event list (unsaved)."""
        self._running = False
        # The hook loop will exit its message pump and unhook
        if self._hook_thread:
            self._hook_thread.join(timeout=3.0)
        # Signal worker to finish
        self._queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=2.0)

        # Close out anything still held
        end_t = self._elapsed(time.perf_counter())
        for button in sorted(self._buttons_down):
            self._events.append({"t": end_t, "type": "up", "button": button})
        self._buttons_down.clear()
        for vk in sorted(self._keys_down):
            self._events.append({"t": end_t, "type": "keyup", "vk": vk})
        self._keys_down.clear()

        # Sort by timestamp (hooks can interleave slightly)
        self._events.sort(key=lambda ev: ev["t"])
        events = self._events
        self._events = []
        return events

    def _elapsed(self, now: float) -> float:
        if self._start_time is None:
            self._start_time = now
        return round(now - self._start_time, 4)

    def _screen_to_ref(self, screen_x: int, screen_y: int) -> tuple[float, float] | None:
        """Convert screen coords to 1152×756 reference space. None if outside."""
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
        rx = (screen_x - cx) * REF_W / cw
        ry = (screen_y - cy) * REF_H / ch
        return (rx, ry)

    def _in_bounds(self, rx: float, ry: float) -> bool:
        return -1 <= rx <= REF_W + 1 and -1 <= ry <= REF_H + 1

    # ── Hook thread: installs hooks, runs message pump, unhooks on stop ──

    def _hook_loop(self) -> None:
        """Runs on its own thread. Installs LL hooks and pumps messages."""
        self._kb_proc = HOOKPROC(self._kb_callback)
        self._mouse_proc = HOOKPROC(self._mouse_callback)

        self._kb_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kb_proc, None, 0
        )
        self._mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc, None, 0
        )

        msg = wt.MSG()
        while self._running:
            # PeekMessage keeps hooks alive without blocking
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.001)  # yield, don't spin

        # Unhook
        if self._kb_hook:
            user32.UnhookWindowsHookEx(self._kb_hook)
            self._kb_hook = None
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = None

    def _kb_callback(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and self._running:
            info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            # Skip injected events (our own replay)
            if not (info.flags & LLKHF_INJECTED):
                vk = info.vkCode
                now = time.perf_counter()
                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    self._queue.put(("keydown", vk, now))
                elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                    self._queue.put(("keyup", vk, now))
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _mouse_callback(self, nCode: int, wParam: int, lParam: int) -> int:
        if nCode >= 0 and self._running:
            info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            now = time.perf_counter()
            x, y = info.pt.x, info.pt.y

            if wParam == WM_MOUSEMOVE:
                self._queue.put(("move", x, y, now))
            elif wParam == WM_LBUTTONDOWN:
                self._queue.put(("down", "left", x, y, now))
            elif wParam == WM_LBUTTONUP:
                self._queue.put(("up", "left", x, y, now))
            elif wParam == WM_RBUTTONDOWN:
                self._queue.put(("down", "right", x, y, now))
            elif wParam == WM_RBUTTONUP:
                self._queue.put(("up", "right", x, y, now))
            elif wParam == WM_MBUTTONDOWN:
                self._queue.put(("down", "middle", x, y, now))
            elif wParam == WM_MBUTTONUP:
                self._queue.put(("up", "middle", x, y, now))
            elif wParam == WM_MOUSEWHEEL:
                # High word of mouseData is the delta (signed)
                delta = ctypes.c_short(info.mouseData >> 16).value
                self._queue.put(("scroll", delta, x, y, now))

        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    # ── Worker thread: processes the queue ──

    def _process_queue(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            self._process_item(item)

    def _process_item(self, item: tuple) -> None:
        kind = item[0]

        if kind == "move":
            _, x, y, now = item
            t = self._elapsed(now)
            if t - self._last_move_t < _MOVE_MIN_INTERVAL:
                return
            ref = self._screen_to_ref(x, y)
            if ref is None or not self._in_bounds(*ref):
                return
            self._last_move_t = t
            self._events.append({"t": t, "type": "move", "x": round(ref[0], 1), "y": round(ref[1], 1)})

        elif kind == "down":
            _, button, x, y, now = item
            # Heal orphaned down: if already held, synthesize an up first
            if button in self._buttons_down:
                self._events.append({"t": self._elapsed(now), "type": "up", "button": button})
            ref = self._screen_to_ref(x, y)
            if ref is None or not self._in_bounds(*ref):
                self._buttons_down.discard(button)
                return
            self._buttons_down.add(button)
            self._events.append({"t": self._elapsed(now), "type": "down", "button": button})

        elif kind == "up":
            _, button, _x, _y, now = item
            # Only record up if we recorded the down
            if button not in self._buttons_down:
                return
            self._buttons_down.discard(button)
            self._events.append({"t": self._elapsed(now), "type": "up", "button": button})

        elif kind == "scroll":
            _, delta, x, y, now = item
            ref = self._screen_to_ref(x, y)
            if ref is None or not self._in_bounds(*ref):
                return
            self._events.append({"t": self._elapsed(now), "type": "scroll", "delta": delta})

        elif kind == "keydown":
            _, vk, now = item
            if vk in self._keys_down:
                return  # auto-repeat, skip
            self._keys_down.add(vk)
            self._events.append({"t": self._elapsed(now), "type": "keydown", "vk": vk})

        elif kind == "keyup":
            _, vk, now = item
            if vk not in self._keys_down:
                return  # stray up without a recorded down
            self._keys_down.discard(vk)
            self._events.append({"t": self._elapsed(now), "type": "keyup", "vk": vk})


# ═══════════════════════════════════════════════════════════════════════════
# Replay
# ═══════════════════════════════════════════════════════════════════════════

# Windows multimedia timer for 1ms precision
try:
    _winmm = ctypes.windll.winmm
except (OSError, AttributeError):
    _winmm = None

# SendInput structures
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("union", _INPUT_UNION)]


def _send_input(inp: INPUT) -> None:
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _move_to(screen_x: int, screen_y: int) -> None:
    """Move cursor to absolute screen coordinates via SendInput."""
    # Normalize to 0–65535 range
    cx = ctypes.windll.user32.GetSystemMetrics(0)
    cy = ctypes.windll.user32.GetSystemMetrics(1)
    dx = int(screen_x * 65535 / cx)
    dy = int(screen_y * 65535 / cy)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dx = dx
    inp.union.mi.dy = dy
    inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    _send_input(inp)


def _mouse_button(button: str, down: bool) -> None:
    flags = {
        ("left", True): MOUSEEVENTF_LEFTDOWN,
        ("left", False): MOUSEEVENTF_LEFTUP,
        ("right", True): MOUSEEVENTF_RIGHTDOWN,
        ("right", False): MOUSEEVENTF_RIGHTUP,
        ("middle", True): MOUSEEVENTF_MIDDLEDOWN,
        ("middle", False): MOUSEEVENTF_MIDDLEUP,
    }.get((button, down), 0)
    if not flags:
        return
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.dwFlags = flags
    _send_input(inp)


def _scroll(delta: int) -> None:
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi.mouseData = delta
    inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
    _send_input(inp)


def _key_event(vk: int, up: bool) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    _send_input(inp)


def replay_recording(
    events: list[dict],
    hwnd: int | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Replay a recorded event list with original timing.

    Converts reference-space coords back to screen coords using the game
    window rect at the START of replay. Uses SendInput directly (not AHK)
    for maximum precision. 1ms timer resolution via timeBeginPeriod.
    """
    if not events:
        return

    # Get the game window geometry for coord conversion
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
    sx = cw / REF_W  # scale factor ref → screen
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
                _move_to(screen_x, screen_y)
            elif etype == "down":
                button = ev.get("button", "left")
                if button in held_buttons:
                    _mouse_button(button, False)
                _mouse_button(button, True)
                held_buttons.add(button)
            elif etype == "up":
                button = ev.get("button", "left")
                _mouse_button(button, False)
                held_buttons.discard(button)
            elif etype == "scroll":
                _scroll(ev.get("delta", 0))
            elif etype == "keydown":
                vk = ev.get("vk", 0)
                if vk:
                    _key_event(vk, up=False)
                    held_keys.add(vk)
            elif etype == "keyup":
                vk = ev.get("vk", 0)
                if vk:
                    _key_event(vk, up=True)
                    held_keys.discard(vk)
    finally:
        # Always release everything on exit
        for button in held_buttons:
            _mouse_button(button, False)
        for vk in held_keys:
            _key_event(vk, up=True)
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

    # Release all keys at the end
    for ahk_key in AHK_KEYS.values():
        lines.append("Send(\"{" + ahk_key + " up}\")")
    lines.append("ExitApp(0)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════

def _write_atomic(path: str, payload: dict, compact: bool = False) -> None:
    """Write JSON atomically (tmp → fsync → replace)."""
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


def save_recording(app_root: str, name: str, events: list[dict]) -> str:
    """Save a recording to disk. Returns the name."""
    name = (name or "").strip() or "recording"
    folder = os.path.join(app_root, "recordings")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{_safe_name(name)}.json")
    _write_atomic(path, {"name": name, "events": events}, compact=True)
    return name


def load_recording(app_root: str, name: str) -> dict:
    """Load a recording by name."""
    path = os.path.join(app_root, "recordings", f"{_safe_name(name)}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"name": name, "events": []}


def delete_recording(app_root: str, name: str) -> bool:
    path = os.path.join(app_root, "recordings", f"{_safe_name(name)}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def list_recordings(app_root: str) -> list[str]:
    """Names of all input recordings."""
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


def list_walk_paths(app_root: str) -> list[str]:
    """Names of all recorded walk paths."""
    folder = os.path.join(app_root, "paths")
    if not os.path.isdir(folder):
        return []
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))


def _safe_name(name: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9 _\-]", "", name or "").strip()
    return cleaned or "recording"
