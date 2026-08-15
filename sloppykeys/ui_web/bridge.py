"""pywebview bridge: serves the HTML UI and docks the Roblox window into it.

Launch with: .venv\\Scripts\\python.exe -m sloppykeys.ui_web

Roblox stays its own top-level window. We sit above it (topmost) with a hole cut
out of our shape over the game slot, so its pixels show through and take the
clicks, and we move it so its *client* area lands exactly on that hole -- its
caption ends up above the hole, hidden behind us, never removed. Nothing about
the Roblox window is modified, so closing us cannot take it down and its
toolbar is back the moment we are gone.

Reparenting with SetParent was tried and abandoned: the child dies with the
parent, which is the whole bug this layout avoids.
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
    SWP_NOACTIVATE,
    SWP_NOMOVE,
    SWP_NOSIZE,
    user32,
)
from sloppykeys.core.win32.frameless import (
    begin_caption_drag,
    find_window_by_title,
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
        """Start an OS-driven window move. Returns when the drag ends."""
        hwnd = self._host_hwnd()
        if hwnd:
            begin_caption_drag(hwnd)

    # ---- Screens ----

    def set_game_visible(self, visible: bool) -> None:
        """Only the Dashboard shows the game; elsewhere we go solid over it.

        Roblox is never moved or hidden for this -- covering it is enough, and
        leaving it where it is means going back to the Dashboard cannot flicker.
        """
        self._game_visible = bool(visible)
        self._apply_mask()

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
        if not position_window_to_client_rect(game_hwnd, *target):
            return False
        host = self._host_hwnd()
        if host:
            # Insert Roblox right after us in z-order so it sits under the hole
            # rather than under whatever else happens to be on the desktop.
            user32.SetWindowPos(
                game_hwnd, host, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
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

    def _follow_loop(self) -> None:
        """Find Roblox, dock it, and keep it under the hole as we move.

        Polling our own rect from Python is what makes a drag smooth: the OS
        move loop repositions us with no round trip, and this thread carries
        Roblox within a frame of it.
        """
        while self._running:
            try:
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
                        if not self._docked:
                            self._docked = True
                            self._apply_mask()
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
