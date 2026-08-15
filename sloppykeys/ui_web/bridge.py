"""pywebview bridge: serves the HTML UI and docks the Roblox window into it.

Launch with: .venv\\Scripts\\python.exe -m sloppykeys.ui_web

Roblox stays its own top-level window. We sit above it (topmost) with a hole cut
out of our shape over the game slot, so its pixels show through and take the
clicks, and we move it so its *client* area lands exactly on that hole -- its
caption ends up above the hole, hidden behind us, never removed. Nothing about
the Roblox window is modified, so closing us cannot take it down and its
toolbar is back the moment we are gone.

Reparenting with SetParent was tried and abandoned: the child dies with the
parent, which is the whole bug this layout avoids. Handing the window move to
the OS caption loop was tried too and does nothing -- WebView2 owns the mouse
capture from another process -- so the drag is tracked here in `_drag_loop`.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import webview  # type: ignore[import-untyped]

from sloppykeys.core.win32.bindings import (
    HWND_NOTOPMOST,
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    VK_LBUTTON,
    get_cursor_pos,
    is_key_down,
    user32,
)
from sloppykeys.core.win32.frameless import (
    find_window_by_title,
    move_to,
    set_cutout_mask,
    set_topmost,
)
from sloppykeys.core.win32.roblox_window import (
    find_roblox_window,
    is_minimized,
    is_window,
    position_window_to_client_rect,
    window_rect,
)

WINDOW_TITLE = "SloppyKeys"

# Fallback game slot in CSS pixels, used until the page reports its own rect.
# Measured against the DOM: the slot renders at (0, 38) sized 1152x756, and at
# 100% display scaling CSS pixels equal window pixels one-for-one.
DEFAULT_SLOT = (0, 38, 1152, 756)

FOLLOW_INTERVAL = 0.016  # ~60Hz; the follower is the only thing carrying Roblox.
SEARCH_INTERVAL = 1.0
DRAG_INTERVAL = 0.008  # ~125Hz, so a drag never misses a displayed frame.


class Api:
    """Methods exposed to JS via pywebview's js_api."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._hwnd: int | None = None
        self._game_hwnd: int | None = None
        self._slot = DEFAULT_SLOT
        self._game_visible = True
        self._docked = False
        self._running = True
        self._dragging = False
        self._last_rect: tuple[int, int, int, int] | None = None

    # ---- Window chrome ----

    def minimize_window(self) -> None:
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
        """Only the Dashboard shows the game; elsewhere we go solid over it.

        Roblox is never moved or hidden for this -- covering it is enough, and
        leaving it where it is means going back to the Dashboard cannot flicker.
        Going solid does occlude it, so coming back re-runs the dock to nudge it
        into presenting frames again.
        """
        self._game_visible = bool(visible)
        self._apply_mask()
        if self._game_visible:
            self._last_rect = None

    def report_slot(self, x: float, y: float, w: float, h: float) -> None:
        """The page tells us where the game slot actually rendered."""
        slot = (int(x), int(y), int(w), int(h))
        if slot[2] <= 0 or slot[3] <= 0 or slot == self._slot:
            return
        self._slot = slot
        self._last_rect = None  # force a reposition against the new slot
        self._apply_mask()

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

    def _host_client_size(self) -> tuple[int, int] | None:
        hwnd = self._host_hwnd()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        return (rect.right - rect.left, rect.bottom - rect.top)

    def _apply_mask(self) -> None:
        """Cut the game slot out of our shape, or go solid again."""
        hwnd = self._host_hwnd()
        size = self._host_client_size()
        if not hwnd or not size:
            return
        show_game = self._game_visible and self._docked
        set_cutout_mask(hwnd, size[0], size[1], self._slot if show_game else None)

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
        """Put Roblox's client area on the slot, directly beneath our window."""
        target = self._slot_on_screen()
        if target is None:
            return False

        # Cut the hole before the game window moves under it. A window whose
        # client area is entirely covered is reported occluded and stops
        # presenting frames until something disturbs it, which reads as a game
        # that only appears once it has been clicked.
        if not self._docked:
            self._docked = True
            self._apply_mask()

        if not position_window_to_client_rect(game_hwnd, *target):
            return False

        # Front of the *normal* band, never "after us": inserting a non-topmost
        # window behind a topmost one promotes it into the topmost band, and a
        # topmost game window rises over our UI the moment it is clicked
        # (measured: WS_EX_TOPMOST set on the Roblox window).
        user32.SetWindowPos(
            game_hwnd,
            HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return True

    def _release_game(self) -> None:
        """Leave Roblox usable on its own: caption fully on screen.

        Its style was never touched, so there is nothing to restore -- but the
        caption sits above the slot, which can be off the top of the screen if
        our window was dragged up there.
        """
        hwnd = self._game_hwnd
        if not is_window(hwnd) or hwnd is None:
            return
        rect = window_rect(hwnd)
        if rect is None:
            return
        if rect[1] >= 0:
            return
        user32.SetWindowPos(hwnd, 0, rect[0], 0, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE)

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
        """Find Roblox, dock it, and keep it under the hole as we move.

        Dragging is handled by `_drag_loop`; this catches every other way the
        window can move (minimise/restore, a shell arrangement) and the initial
        dock once Roblox appears.
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
                    self._game_hwnd = find_roblox_window()
                    if not self._game_hwnd:
                        self._apply_mask()
                        time.sleep(SEARCH_INTERVAL)
                        continue

                host = self._host_hwnd()
                if not host or is_minimized(host):
                    time.sleep(SEARCH_INTERVAL)
                    continue

                rect = window_rect(host)
                if rect is not None and (rect != self._last_rect or not self._docked):
                    if self._dock(self._game_hwnd):
                        self._last_rect = rect
                    elif self._docked:
                        self._docked = False
                        self._apply_mask()
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
        width=1552,
        height=900,
        min_size=(1200, 700),
        frameless=True,
        easy_drag=False,
        on_top=True,
        js_api=api,
    )
    api._window = window

    def on_loaded() -> None:
        hwnd = api._host_hwnd()
        if hwnd:
            set_topmost(hwnd, True)
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
