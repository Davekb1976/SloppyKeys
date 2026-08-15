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
    is_minimized,
    is_window,
    position_window_to_client_rect,
    restore_frame,
    strip_frame,
    window_rect,
)

WINDOW_TITLE = "SloppyKeys"

# The viewport is pinned at this size: every coordinate, template and config in
# the project was captured against it. See coding-standards.md.
VIEWPORT_W = 1152
VIEWPORT_H = 756

TITLEBAR_H = 38
PANEL_W = 384
LOG_H = 220

# What the layout wants. fit_and_centre clamps it to the work area and reports
# what it actually got, so a short screen shrinks the log rather than clipping it.
WANT_W = VIEWPORT_W + PANEL_W
WANT_H = TITLEBAR_H + VIEWPORT_H + LOG_H

# Fallback slot in CSS pixels until the page reports its own rect. Measured
# against the DOM: at 100% display scaling CSS pixels are window pixels.
DEFAULT_SLOT = (0, TITLEBAR_H, VIEWPORT_W, VIEWPORT_H)

FOLLOW_INTERVAL = 0.016  # ~60Hz
SEARCH_INTERVAL = 1.0
DRAG_INTERVAL = 0.008  # ~125Hz, so a drag never misses a displayed frame.


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

    # ---- Window chrome ----

    def minimize_window(self) -> None:
        # Drop the game out of the topmost band first, or it stays floating over
        # the desktop with the UI it belongs to gone.
        self._set_game_topmost(False)
        if self._window:
            self._window.minimize()

    def close_window(self) -> None:
        self._running = False
        self._release_game()
        if self._window:
            self._window.destroy()

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

        Elsewhere the game is demoted out of the topmost band so our own
        content covers it. It is never moved or hidden, so coming back to the
        Dashboard costs one z-order change and cannot flicker.
        """
        self._game_visible = bool(visible)
        self._set_game_topmost(self._game_visible)

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

    def _set_game_topmost(self, on: bool) -> None:
        if self._docked and is_window(self._game_hwnd) and self._game_hwnd:
            set_topmost(self._game_hwnd, on)

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
        set_topmost(game_hwnd, self._game_visible)
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
                    # A minimized window reports coordinates near -32000; docking
                    # against that would fling the game off screen.
                    self._set_game_topmost(False)
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
        min_size=(WANT_W, TITLEBAR_H + VIEWPORT_H),
        frameless=True,
        easy_drag=False,
        js_api=api,
    )
    api._window = window

    def on_loaded() -> None:
        hwnd = api._host_hwnd()
        if hwnd:
            # pywebview sizes the Form before the frame comes off, so the client
            # area lands short of what was asked for -- set the real size here,
            # where the window rect and the client rect are the same thing.
            fit_and_centre(hwnd, WANT_W, WANT_H)
        window.evaluate_js(
            'document.getElementById("version-badge").textContent = '
            f'"v{api.get_version()}";'
        )
        threading.Thread(target=api._follow_loop, daemon=True).start()

    def on_closing() -> None:
        # The X button is ours, but an OS-initiated close bypasses it.
        api._running = False
        api._release_game()

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
