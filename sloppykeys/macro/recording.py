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
            # DOWN
            if button in self._buttons_down:
                # Heal orphaned down
                self._events.append({"t": self._elapsed(now), "type": "up", "button": button})
            ref = self._screen_to_ref(*pos)
            if ref is None or not self._in_bounds(*ref):
                self._buttons_down.discard(button)
                return
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
# Replay (uses SendInput for mouse, keyboard package for keys)
# ═══════════════════════════════════════════════════════════════════════════

def replay_recording(
    events: list[dict],
    hwnd: int | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Replay a recorded event list with original timing.

    Converts reference-space coords back to screen coords. Uses 1ms timer
    resolution. Always releases all held buttons/keys on exit.
    """
    if not events:
        return
    import keyboard as kb_lib
    import mouse as mouse_lib

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

    # Map key names to VK codes for keyboard
    def _vk_for(key_name: str) -> int | None:
        """Resolve a key name to its VK code."""
        try:
            return kb_lib.key_to_scan_codes(key_name)[0]
        except (ValueError, IndexError):
            return None

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
                mouse_lib.move(screen_x, screen_y, absolute=True, duration=0)
            elif etype == "down":
                button = ev.get("button", "left")
                if button in held_buttons:
                    mouse_lib.release(button)
                mouse_lib.press(button)
                held_buttons.add(button)
            elif etype == "up":
                button = ev.get("button", "left")
                mouse_lib.release(button)
                held_buttons.discard(button)
            elif etype == "scroll":
                delta = ev.get("delta", 0)
                if delta:
                    mouse_lib.wheel(delta / 120)
            elif etype == "keydown":
                key = ev.get("key", "")
                if key:
                    try:
                        kb_lib.press(key)
                        held_keys.add(key)
                    except ValueError:
                        pass
            elif etype == "keyup":
                key = ev.get("key", "")
                if key:
                    try:
                        kb_lib.release(key)
                        held_keys.discard(key)
                    except ValueError:
                        pass
    finally:
        for button in held_buttons:
            try:
                mouse_lib.release(button)
            except Exception:
                pass
        for key in held_keys:
            try:
                kb_lib.release(key)
            except Exception:
                pass
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


def list_walk_paths(app_root: str) -> list[str]:
    folder = os.path.join(app_root, "paths")
    if not os.path.isdir(folder):
        return []
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))
