"""pywebview bridge: serves the HTML UI and docks the Roblox window into it.

Launch with: .venv\\Scripts\\python.exe -m sloppykeys.ui_web

Docking is inverted layering, not embedding. Roblox stays its own top-level
window and rides the topmost band, sized and positioned exactly over the game
slot; our window sits in the normal band underneath. Visually the game is inside
the UI, but nothing is ever parented, so closing the macro cannot take Roblox
down with it. Its frame is stripped while docked -- it floats above us, so there
is nothing to hide a caption behind -- and restored on the way out.

Two other layouts were measured and rejected on this stack:

* SetParent. Windows destroys child windows with their parent, so quitting the
  macro killed the game.
* A literal hole cut with SetWindowRgn, which is how the PySide6 window does it.
  The region is accepted -- GetWindowRgnBox reports the hole -- but WebView2
  composites through DirectComposition and ignores GDI window regions, so the
  page keeps painting over the slot.
"""

from __future__ import annotations

import os
import sys
import threading
import time

import webview  # type: ignore[import-untyped]

from sloppykeys.core.win32.bindings import (
    SW_RESTORE,
    SWP_NOACTIVATE,
    SWP_NOSIZE,
    VK_LBUTTON,
    get_cursor_pos,
    is_key_down,
    user32,
)
from sloppykeys.core.win32.frameless import (
    find_window_by_title,
    fit_and_centre,
    move_to,
    set_topmost,
)
from sloppykeys.core.win32.roblox_window import (
    activate_window,
    find_roblox_window,
    is_frameless,
    is_minimized,
    is_window,
    position_window_to_client_rect,
    recover_frame,
    restore_frame,
    strip_frame,
    window_rect,
)
from sloppykeys.config.keybinds import DEFAULTS as KEYBIND_DEFAULTS, KeybindStore
from sloppykeys.config.unified import UnifiedSettings
from sloppykeys.content.units import UnitPlan
from sloppykeys.macro.controller import MacroController

WINDOW_TITLE = "SloppyKeys"

# The viewport is pinned at this size: every coordinate, template and config in
# the project was captured against it. See coding-standards.md.
VIEWPORT_W = 1152
VIEWPORT_H = 756

TITLEBAR_H = 38
PANEL_W = 384
LOG_H = 156

# Fixed window size: just enough for titlebar + game + a compact log.
WANT_W = VIEWPORT_W + PANEL_W
WANT_H = TITLEBAR_H + VIEWPORT_H + LOG_H

# Fallback slot in CSS pixels until the page reports its own rect. Measured
# against the DOM: at 100% display scaling CSS pixels are window pixels.
DEFAULT_SLOT = (0, TITLEBAR_H, VIEWPORT_W, VIEWPORT_H)

FOLLOW_INTERVAL = 0.016  # ~60Hz
SEARCH_INTERVAL = 1.0
DRAG_INTERVAL = 0.008  # ~125Hz, so a drag never misses a displayed frame.
HOTKEY_INTERVAL = 0.04  # ~25Hz, same cadence as the PySide6 window's 40ms timer.


class Api:
    """Methods exposed to JS via pywebview's js_api."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._hwnd: int | None = None
        self._game_hwnd: int | None = None
        self._game_style: int | None = None
        self._slot = DEFAULT_SLOT
        self._game_visible = True
        self._docked = False
        self._running = True
        self._dragging = False
        self._last_rect: tuple[int, int, int, int] | None = None
        # Macro controller — created lazily in on_loaded once app_root is known.
        self._ctrl: MacroController | None = None
        self._app_root: str | None = None
        self._run_thread: threading.Thread | None = None
        # Hotkey edge detection
        self._key_down: dict[str, bool] = {"start": False, "stop": False}

    # ---- Window chrome ----

    def minimize_window(self) -> None:
        # Release the game fully (frame + z-order) while we're away; the follow
        # loop re-docks automatically when we restore.
        self._release_game()
        if self._window:
            self._window.minimize()

    def close_window(self) -> None:
        self._running = False
        self._release_game()
        if self._window:
            self._window.destroy()

    def enter_compact(self) -> None:
        """Compact mode: shrink window to game + strip, drop the side panel."""
        if not self._window:
            return
        compact_w = VIEWPORT_W
        compact_h = TITLEBAR_H + VIEWPORT_H + 50
        try:
            self._window.resize(compact_w, compact_h)
        except Exception as exc:
            self._log_to_ui(f"[Compact] resize failed: {exc}")
            # Fallback: native Win32
            hwnd = self._host_hwnd()
            if hwnd:
                from sloppykeys.core.win32.roblox_window import window_rect as _wr
                rect = _wr(hwnd)
                if rect:
                    user32.SetWindowPos(hwnd, 0, rect[0], rect[1], compact_w, compact_h, 0x0004)

    def exit_compact(self) -> None:
        """Exit compact mode: restore full window size, keeping current position."""
        if not self._window:
            return
        try:
            self._window.resize(WANT_W, WANT_H)
        except Exception as exc:
            self._log_to_ui(f"[Compact] resize failed: {exc}")

    def begin_drag(self) -> None:
        """Start dragging the window. Returns at once; the loop runs on a thread.

        Handing the move to the OS caption loop does not work here: WebView2
        holds the mouse capture in its own process, so the loop on our thread
        never receives a mouse move and the window sits still. Reading the
        cursor globally needs no capture, and running the loop in Python keeps
        the per-frame cost off the JS bridge.
        """
        if self._dragging:
            return
        self._dragging = True
        threading.Thread(target=self._drag_loop, daemon=True).start()

    # ---- Screens ----

    def set_game_visible(self, visible: bool) -> None:
        """Only the Dashboard shows the game.

        Hiding it with ShowWindow(SW_HIDE) is the only reliable way to keep it
        from showing through on other screens: the game is topmost and our
        window is in the normal band, so demoting alone doesn't cover it when
        nothing else sits between them. ShowWindow is outside-the-window only.
        """
        self._game_visible = bool(visible)
        if not self._docked or not is_window(self._game_hwnd) or self._game_hwnd is None:
            return
        SW_HIDE = 0
        SW_SHOWNOACTIVATE = 4
        if visible:
            user32.ShowWindow(self._game_hwnd, SW_SHOWNOACTIVATE)
            set_topmost(self._game_hwnd, True)
        else:
            set_topmost(self._game_hwnd, False)
            user32.ShowWindow(self._game_hwnd, SW_HIDE)

    def report_slot(self, x: float, y: float, w: float, h: float) -> None:
        """The page tells us where the game slot actually rendered."""
        slot = (int(x), int(y), int(w), int(h))
        if slot[2] <= 0 or slot[3] <= 0 or slot == self._slot:
            return
        self._slot = slot
        self._last_rect = None  # force a reposition against the new slot

    def get_version(self) -> str:
        from sloppykeys.version import VERSION

        return VERSION

    # ---- Gamemode data ----

    def get_gamemodes(self) -> list[str]:
        """Farm-target gamemodes the user can select."""
        from sloppykeys.content.gamemodes import FARM_GAMEMODE_NAMES

        return FARM_GAMEMODE_NAMES

    def get_maps(self, gamemode: str) -> list[str]:
        """Maps for a gamemode. Events reads from the route store."""
        from sloppykeys.content.gamemodes import is_custom, maps_for

        if is_custom(gamemode) and self._app_root:
            from sloppykeys.config.nav_routes import RouteStore

            return RouteStore(self._app_root).maps()
        return maps_for(gamemode)

    def get_targets(self, gamemode: str, map_name: str) -> list[str]:
        """Acts/targets for a gamemode+map combo."""
        from sloppykeys.content.gamemodes import is_custom, targets_for

        if is_custom(gamemode) and self._app_root:
            from sloppykeys.config.nav_routes import RouteStore

            return RouteStore(self._app_root).acts(map_name)
        return targets_for(gamemode, map_name)

    def get_config_path(self, gamemode: str, map_name: str, target: str) -> str:
        """The unit plan config path for the current selection."""
        if not self._app_root or not gamemode or not map_name:
            return ""
        from sloppykeys.content.gamemodes import has_targets

        parts = [self._app_root, "configs", gamemode, map_name]
        if has_targets(gamemode) and target:
            parts = [self._app_root, "configs", gamemode, map_name, target + ".json"]
        else:
            parts = [self._app_root, "configs", gamemode, map_name + ".json"]
        import os

        path = os.path.join(*parts)
        return path if os.path.isfile(path) else ""

    # ---- Settings (unified, auto-save) ----

    def get_settings(self) -> dict:
        """All settings with defaults merged. Called from JS to populate the Settings screen."""
        if not self._app_root:
            return {}
        return UnifiedSettings(self._app_root).get_all()

    def set_setting(self, key: str, value) -> dict:
        """Write one setting immediately. No save button needed."""
        if not self._app_root:
            return {"ok": False}
        ok = UnifiedSettings(self._app_root).set(key, value)
        return {"ok": ok}

    def get_hotkeys(self) -> dict:
        """Current hotkey bindings with display names."""
        if not self._app_root:
            return {}
        return UnifiedSettings(self._app_root).get_hotkeys()

    def reset_hotkeys(self) -> dict:
        """Reset all hotkeys to defaults."""
        if not self._app_root:
            return {"ok": False}
        hotkeys = UnifiedSettings(self._app_root).reset_hotkeys()
        return {"ok": True, "hotkeys": hotkeys}

    def set_hotkey(self, action: str, vk: int, ctrl: bool = False, shift: bool = False, alt: bool = False) -> dict:
        """Set a single hotkey binding."""
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.config.keybinds import ACTIONS, Keybind, KeybindStore

        if action not in ACTIONS:
            return {"ok": False, "error": "unknown action"}
        store = KeybindStore(self._app_root)
        store.set(action, Keybind(vk=int(vk), ctrl=bool(ctrl), shift=bool(shift), alt=bool(alt)))
        return {"ok": True}

    def get_delays(self) -> dict:
        """Current delay values."""
        if not self._app_root:
            return {}
        return UnifiedSettings(self._app_root).get_delays()

    def set_delay(self, key: str, value: float) -> dict:
        """Write one delay immediately."""
        if not self._app_root:
            return {"ok": False}
        ok = UnifiedSettings(self._app_root).set_delay(key, value)
        return {"ok": ok}

    # ---- Task Queue ----

    def get_tasks(self) -> list:
        """The ordered task queue."""
        if not self._app_root:
            return []
        return UnifiedSettings(self._app_root).get_tasks()

    def add_task(self, task: dict) -> dict:
        """Append a new task to the queue. Assigns an id if missing."""
        if not self._app_root:
            return {"ok": False}
        import time as _time

        if not task.get("id"):
            task["id"] = f"t{int(_time.time() * 1000)}"
        tasks = UnifiedSettings(self._app_root).get_tasks()
        tasks.append(task)
        ok = UnifiedSettings(self._app_root).set_tasks(tasks)
        return {"ok": ok, "id": task["id"]}

    def update_task(self, task_id: str, changes: dict) -> dict:
        """Update fields on a task by id. Auto-saves."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        tasks = settings.get_tasks()
        for t in tasks:
            if t.get("id") == task_id:
                t.update(changes)
                return {"ok": settings.set_tasks(tasks)}
        return {"ok": False, "error": "not found"}

    def remove_task(self, task_id: str) -> dict:
        """Remove a task by id."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        tasks = [t for t in settings.get_tasks() if t.get("id") != task_id]
        return {"ok": settings.set_tasks(tasks)}

    def reorder_tasks(self, ids: list) -> dict:
        """Reorder the queue to match the given id list."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        old = {t.get("id"): t for t in settings.get_tasks()}
        reordered = [old[tid] for tid in ids if tid in old]
        return {"ok": settings.set_tasks(reordered)}

    def clear_tasks(self) -> dict:
        """Remove all tasks."""
        if not self._app_root:
            return {"ok": False}
        return {"ok": UnifiedSettings(self._app_root).set_tasks([])}

    # ---- Macro Operations ----

    def list_operations(self) -> list:
        """Names of all saved macro operations."""
        if not self._app_root:
            return []
        from sloppykeys.config.operations import list_operations

        return list_operations(self._app_root)

    def load_operation(self, name: str) -> dict:
        """Load a macro operation by name."""
        if not self._app_root:
            return {"name": "", "phases": {}}
        from sloppykeys.config.operations import load_operation

        return load_operation(self._app_root, name)

    def save_operation(self, name: str, phases: dict) -> dict:
        """Save a macro operation."""
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.config.operations import save_operation

        ok = save_operation(self._app_root, name, phases)
        return {"ok": ok}

    def delete_operation(self, name: str) -> dict:
        """Delete a macro operation."""
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.config.operations import delete_operation

        ok = delete_operation(self._app_root, name)
        return {"ok": ok}

    # ---- Position Picker (map images) ----

    def list_map_categories(self) -> list:
        """Category folders under images/reference/."""
        if not self._app_root:
            return []
        ref = os.path.join(self._app_root, "images", "reference")
        if not os.path.isdir(ref):
            return []
        return sorted(
            d for d in os.listdir(ref)
            if os.path.isdir(os.path.join(ref, d))
        )

    def list_maps(self, category: str) -> list:
        """Map image names in a category (without .png extension)."""
        if not self._app_root:
            return []
        folder = os.path.join(self._app_root, "images", "reference", category)
        if not os.path.isdir(folder):
            return []
        return sorted(
            f[:-4] for f in os.listdir(folder)
            if f.lower().endswith(".png")
        )

    def get_map_image(self, category: str, name: str) -> dict:
        """Base64 data URI of a map image for the position picker."""
        if not self._app_root:
            return {"ok": False}
        import base64

        path = os.path.join(self._app_root, "images", "reference", category, name + ".png")
        if not os.path.isfile(path):
            return {"ok": False, "reason": "not found"}
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return {"ok": True, "data_uri": f"data:image/png;base64,{b64}"}
        except OSError as exc:
            return {"ok": False, "reason": str(exc)}

    def get_roblox_snapshot(self) -> dict:
        """Capture the live Roblox window as a base64 PNG for position picking.
        Also caches the raw BGR array for save_image_crop."""
        import base64

        try:
            import mss
            import cv2
            import numpy as np
        except ImportError:
            return {"ok": False, "reason": "mss/cv2 not available"}

        hwnd = find_roblox_window()
        if not hwnd:
            return {"ok": False, "reason": "Roblox not found"}

        from sloppykeys.core.win32.roblox_window import client_to_screen, client_size

        origin = client_to_screen(hwnd, 0, 0)
        size = client_size(hwnd)
        if not origin or not size:
            return {"ok": False, "reason": "couldn't read Roblox geometry"}

        monitor = {"left": origin[0], "top": origin[1], "width": size[0], "height": size[1]}
        with mss.mss() as sct:
            img = np.array(sct.grab(monitor))

        bgr = img[:, :, :3].copy()
        self._cached_snapshot = bgr  # cache for save_image_crop

        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            return {"ok": False, "reason": "encode failed"}
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return {"ok": True, "data_uri": f"data:image/png;base64,{b64}"}

    # ---- Image Manager ----

    def list_vision_templates(self) -> dict:
        """All searchable image names organized by category, with thumbnails and thresholds."""
        if not self._app_root:
            return {"ok": False, "categories": []}
        import base64

        IMAGE_CATEGORIES = {
            "lobby": "Lobby Navigation",
            "match": "Match State",
            "gamemodes": "Gamemode Cards",
            "stages": "Stage Selection",
            "challenge": "Challenge",
            "events": "Events",
            "actions": "Actions",
        }

        # Read current thresholds from settings
        settings = UnifiedSettings(self._app_root)
        thresholds = settings.get("image_thresholds", {})
        default_threshold = 0.70

        categories = []
        images_root = os.path.join(self._app_root, "images")

        for key, label in IMAGE_CATEGORIES.items():
            folder = os.path.join(images_root, key)
            if not os.path.isdir(folder):
                continue
            names = []
            for fname in sorted(os.listdir(folder)):
                if not fname.lower().endswith(".png"):
                    continue
                name = fname[:-4]
                path = os.path.join(folder, fname)
                try:
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("ascii")
                    names.append({
                        "name": name,
                        "file": fname,
                        "data_uri": f"data:image/png;base64,{b64}",
                        "threshold": float(thresholds.get(name, default_threshold)),
                    })
                except OSError:
                    continue
            if names:
                categories.append({"key": key, "label": label, "names": names})

        return {"ok": True, "categories": categories, "default_threshold": default_threshold}

    def set_image_threshold(self, name: str, value: float) -> dict:
        """Set a per-image match threshold. Auto-saves."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        thresholds = settings.get("image_thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}
        default = 0.70
        if abs(float(value) - default) < 0.01:
            thresholds.pop(name, None)
        else:
            thresholds[name] = max(0.50, min(1.0, float(value)))
        settings.set("image_thresholds", thresholds)
        # Apply live to the search engine
        if self._ctrl and hasattr(self._ctrl, '_engine'):
            from sloppykeys.core.image_search import apply_confidence_overrides
            apply_confidence_overrides(self._ctrl._engine, thresholds)
        return {"ok": True}

    def save_image_crop(self, category: str, name: str, x: int, y: int, w: int, h: int) -> dict:
        """Crop from the cached snapshot and save it as a variant for `name`."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        if not hasattr(self, '_cached_snapshot') or self._cached_snapshot is None:
            return {"ok": False, "reason": "no cached snapshot — capture first"}
        try:
            import cv2
            import numpy as np
        except ImportError:
            return {"ok": False, "reason": "cv2 not available"}

        full = self._cached_snapshot
        x, y, w, h = int(x), int(y), int(w), int(h)
        if w < 4 or h < 4:
            return {"ok": False, "reason": "selection too small"}
        if y + h > full.shape[0] or x + w > full.shape[1]:
            return {"ok": False, "reason": "selection out of bounds"}
        crop = full[y:y+h, x:x+w]
        if crop.size == 0:
            return {"ok": False, "reason": "crop is empty"}

        # Save to images/<category>/<name>_<n>.png
        folder = os.path.join(self._app_root, "images", category)
        os.makedirs(folder, exist_ok=True)
        existing = [f for f in os.listdir(folder) if f.startswith(name) and f.endswith(".png")]
        idx = len(existing) + 1
        filename = f"{name}_{idx}.png"
        path = os.path.join(folder, filename)
        cv2.imwrite(path, crop)
        return {"ok": True, "path": path}

    # ---- Macro control ----

    def start_macro(self, *args) -> dict:
        """Start the macro — runs the task queue. No selector args needed."""
        if self._ctrl is None:
            return {"ok": False, "error": "controller not ready"}
        if self._ctrl.is_running:
            return {"ok": False, "error": "already running"}

        error = self._ctrl.start()
        if error:
            return {"ok": False, "error": error}

        self._run_thread = threading.Thread(target=self._macro_run_loop, daemon=True)
        self._run_thread.start()
        self._push_status()
        return {"ok": True}

    def stop_macro(self) -> dict:
        """Stop the running macro. Called from JS Stop button."""
        if self._ctrl is None or not self._ctrl.is_running:
            return {"ok": False, "error": "not running"}
        self._ctrl.stop()
        return {"ok": True}

    def pause_macro(self) -> dict:
        """Pause the running macro."""
        if self._ctrl is None or not self._ctrl.is_running:
            return {"ok": False}
        self._ctrl.pause()
        return {"ok": True}

    def resume_macro(self) -> dict:
        """Resume a paused macro."""
        if self._ctrl is None:
            return {"ok": False}
        self._ctrl.resume()
        return {"ok": True}

    def get_macro_status(self) -> dict:
        """Poll macro state from JS."""
        if self._ctrl is None:
            return {"running": False, "cycle": 0, "target": "", "phase": "idle"}
        task = self._ctrl.current_task
        target = ""
        if task:
            target = " / ".join(
                p for p in (task.get("mode"), task.get("map"), task.get("stage")) if p
            )
        return {
            "running": self._ctrl.is_running,
            "cycle": self._ctrl.cycle,
            "target": target,
            "phase": "paused" if (self._ctrl.is_running and self._ctrl._paused) else ("running" if self._ctrl.is_running else "idle"),
        }

    def _macro_run_loop(self) -> None:
        """Worker thread driving the runner."""
        try:
            ok, msg = self._ctrl.run_loop()  # type: ignore[union-attr]
            self._log_to_ui(f"Macro finished: {msg}")
        except Exception as exc:
            self._log_to_ui(f"Macro crashed: {exc}")
        finally:
            self._run_thread = None
            self._push_status()

    def _push_status(self) -> None:
        """Push macro state to the frontend."""
        if self._window is None:
            return
        status = self.get_macro_status()
        running_js = "true" if status["running"] else "false"
        self._window.evaluate_js(
            f'window.onMacroStatus && window.onMacroStatus({running_js}, {status["cycle"]}, '
            f'"{status["target"]}", "{status["phase"]}");'
        )

    def _log_to_ui(self, msg: str) -> None:
        """Push a log line to the frontend."""
        if self._window is None:
            return
        safe = msg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        self._window.evaluate_js(f'window.addLog && window.addLog("{safe}");')

    # ---- Hotkey polling ----

    def _hotkey_loop(self) -> None:
        """Poll F1/F2 globally so Start/Stop work without clicking buttons."""
        if self._app_root is None:
            return
        keybinds = KeybindStore(self._app_root)
        start_kb = keybinds.get("start_stop")
        stop_kb = keybinds.get("stop")

        def kb_pressed(kb) -> bool:
            if not is_key_down(kb.vk):
                return False
            if kb.ctrl and not is_key_down(0x11):
                return False
            if kb.shift and not is_key_down(0x10):
                return False
            if kb.alt and not is_key_down(0x12):
                return False
            return True

        while self._running:
            try:
                # Start key — rising edge
                start_down = kb_pressed(start_kb)
                if start_down and not self._key_down["start"]:
                    if self._ctrl and not self._ctrl.is_running:
                        self._log_to_ui("Start hotkey: select gamemode in the UI first.")
                    elif self._ctrl and self._ctrl.is_running:
                        self._log_to_ui("Already running — use the stop key.")
                self._key_down["start"] = start_down

                # Stop key — rising edge
                stop_down = kb_pressed(stop_kb)
                if stop_down and not self._key_down["stop"]:
                    if self._ctrl and self._ctrl.is_running:
                        self._ctrl.stop()
                        self._log_to_ui("Stop requested; finishing current step.")
                        self._push_status()
                self._key_down["stop"] = stop_down

                # F6 — Image Manager (rising edge)
                im_kb = keybinds.get("image_manager")
                f6_down = kb_pressed(im_kb)
                if f6_down and not self._key_down.get("f6", False):
                    if self._window:
                        self._window.evaluate_js("window.openImageManager && window.openImageManager();")
                self._key_down["f6"] = f6_down

                # F7 — Compact mode toggle (rising edge)
                compact_kb = keybinds.get("compact_mode")
                f7_down = kb_pressed(compact_kb)
                if f7_down and not self._key_down.get("f7", False):
                    if self._window:
                        self._window.evaluate_js("window.toggleCompact && window.toggleCompact();")
                self._key_down["f7"] = f7_down
            except Exception:
                pass
            time.sleep(HOTKEY_INTERVAL)

    # ---- Internal ----

    def _host_hwnd(self) -> int | None:
        if self._hwnd and is_window(self._hwnd):
            return self._hwnd
        if self._window is None:
            return None
        self._hwnd = find_window_by_title(self._window.title)
        return self._hwnd

    def _slot_on_screen(self) -> tuple[int, int, int, int] | None:
        """The slot in screen coordinates, or None if we cannot be measured."""
        hwnd = self._host_hwnd()
        if not hwnd or is_minimized(hwnd):
            return None
        rect = window_rect(hwnd)
        if rect is None:
            return None
        x, y, w, h = self._slot
        return (rect[0] + x, rect[1] + y, w, h)

    def _dock(self, game_hwnd: int) -> bool:
        """Float the game over the slot, frame stripped, without stealing focus."""
        target = self._slot_on_screen()
        if target is None:
            return False

        if not self._docked:
            style = strip_frame(game_hwnd)
            if style is None:
                return False
            self._game_style = style
            self._docked = True

        if not position_window_to_client_rect(game_hwnd, *target):
            return False

        SW_SHOWNOACTIVATE = 4
        if self._game_visible:
            user32.ShowWindow(game_hwnd, SW_SHOWNOACTIVATE)
            set_topmost(game_hwnd, True)
        else:
            set_topmost(game_hwnd, False)
            user32.ShowWindow(game_hwnd, 0)  # SW_HIDE
        return True

    def _release_game(self) -> None:
        """Hand the game window back: frame on, out of the topmost band, usable.

        Nothing was ever parented, so there is no detach to confirm -- only the
        frame and the z-order to undo.
        """
        hwnd = self._game_hwnd
        if hwnd is None or not is_window(hwnd):
            return
        set_topmost(hwnd, False)
        if self._game_style is not None:
            restore_frame(hwnd, self._game_style, VIEWPORT_W, VIEWPORT_H)
            self._game_style = None
        rect = window_rect(hwnd)
        if rect is not None and rect[1] < 0:
            # The caption sat above the slot; keep it on screen.
            user32.SetWindowPos(hwnd, 0, rect[0], 0, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)
        if is_minimized(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        activate_window(hwnd)
        self._docked = False

    def _drag_loop(self) -> None:
        """Track the cursor until the button comes up, moving both windows.

        The game window is moved in the same iteration as ours rather than left
        to the follower thread, so the two never land a frame apart.
        """
        try:
            hwnd = self._host_hwnd()
            origin = window_rect(hwnd) if hwnd else None
            grab = get_cursor_pos()
            if not hwnd or origin is None or grab is None:
                return

            while self._running and is_key_down(VK_LBUTTON):
                cursor = get_cursor_pos()
                current = window_rect(hwnd)
                if cursor is None or current is None:
                    break
                x = origin[0] + cursor[0] - grab[0]
                y = origin[1] + cursor[1] - grab[1]
                if (x, y) != (current[0], current[1]):
                    move_to(hwnd, x, y)
                    if self._docked and self._game_hwnd:
                        slot_x, slot_y, slot_w, slot_h = self._slot
                        position_window_to_client_rect(
                            self._game_hwnd, x + slot_x, y + slot_y, slot_w, slot_h
                        )
                time.sleep(DRAG_INTERVAL)
        except OSError as exc:
            print(f"Failed to drag the window: {exc}", file=sys.stderr)
        finally:
            self._dragging = False
            self._last_rect = window_rect(self._hwnd) if self._hwnd else None

    def _follow_loop(self) -> None:
        """Find the game, dock it, and keep it over the slot as we move.

        Dragging is handled by `_drag_loop`; this catches every other way the
        window can move and the initial dock once the game appears.
        """
        while self._running:
            try:
                if self._dragging:
                    # The drag loop is moving both windows; two threads calling
                    # SetWindowPos on the same pair only fight each other.
                    time.sleep(DRAG_INTERVAL)
                    continue

                if not is_window(self._game_hwnd):
                    self._docked = False
                    self._game_style = None
                    self._game_hwnd = find_roblox_window()
                    if not self._game_hwnd:
                        time.sleep(SEARCH_INTERVAL)
                        continue

                host = self._host_hwnd()
                if not host or is_minimized(host):
                    # Minimized: release the game so it regains its toolbar.
                    # The loop will re-dock when we restore.
                    if self._docked:
                        self._release_game()
                    self._last_rect = None
                    time.sleep(SEARCH_INTERVAL)
                    continue

                rect = window_rect(host)
                if rect is not None and (rect != self._last_rect or not self._docked):
                    if self._dock(self._game_hwnd):
                        self._last_rect = rect
                    else:
                        self._docked = False
            except OSError as exc:  # a window vanishing mid-call
                print(f"Failed to sync the game window: {exc}", file=sys.stderr)
                self._docked = False
            time.sleep(FOLLOW_INTERVAL)


def main() -> None:
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(ui_dir, "index.html")

    api = Api()
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=html_path,
        width=WANT_W,
        height=WANT_H,
        min_size=(VIEWPORT_W, TITLEBAR_H + VIEWPORT_H + 50),
        frameless=True,
        easy_drag=False,
        on_top=True,
        js_api=api,
    )
    api._window = window

    def on_loaded() -> None:
        hwnd = api._host_hwnd()
        if hwnd:
            fit_and_centre(hwnd, WANT_W, WANT_H)
            # Keep topmost just long enough to be seen, then drop. Delaying
            # ensures the Form is fully shown before we demote.
            import time as _time
            _time.sleep(0.3)
            set_topmost(hwnd, False)

        # If a previous session was force-killed, Roblox may still be running
        # without its frame. Fix it before we dock so our strip_frame gets a
        # clean baseline to save/restore.
        rbx = find_roblox_window()
        if rbx and is_frameless(rbx):
            recover_frame(rbx, VIEWPORT_W, VIEWPORT_H)
            set_topmost(rbx, False)

        # Init the macro controller.
        api._app_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))
        api._ctrl = MacroController(
            api._app_root,
            log=api._log_to_ui,
        )

        window.evaluate_js(
            'document.getElementById("version-badge").textContent = '
            f'"v{api.get_version()}";'
        )
        # Signal JS that the backend is ready (app_root set, controller built).
        window.evaluate_js("window.onBackendReady && window.onBackendReady();")
        threading.Thread(target=api._follow_loop, daemon=True).start()
        threading.Thread(target=api._hotkey_loop, daemon=True).start()

    def on_closing() -> None:
        # The X button is ours, but an OS-initiated close bypasses it.
        api._running = False
        api._release_game()

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
