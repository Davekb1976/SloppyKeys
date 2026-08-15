"""pywebview bridge: serves the HTML UI and exposes the macro backend.

Launch with: .venv\\Scripts\\python.exe -m sloppykeys.ui_web.bridge

This runs alongside the existing PySide6 app during migration — both entry
points stay functional until the migration is complete and the PySide6 code
is removed.

The window is frameless (custom titlebar in the DOM). Roblox is positioned as
a native HWND over the WebView's game-slot div by reading the slot's screen
coordinates and calling SetWindowPos on each move/resize.
"""

from __future__ import annotations

import os
import sys
import time
import threading

import webview  # type: ignore[import-untyped]

from sloppykeys.core.win32.roblox_window import (
    find_roblox_window,
    is_minimized,
    is_window,
    position_window_to_client_rect,
)


# The game slot is 1152x756. Its position relative to the WebView's client area
# is fixed by the CSS layout: left edge at 0, top edge below the 38px titlebar.
GAME_SLOT_X = 0
GAME_SLOT_Y = 38
GAME_SLOT_W = 1152
GAME_SLOT_H = 756


class Api:
    """Methods exposed to JS via pywebview's js_api."""

    def __init__(self, window: webview.Window) -> None:
        self._window = window
        self._start_time = time.time()
        self._roblox_hwnd: int | None = None
        self._game_visible = True
        self._dock_thread: threading.Thread | None = None
        self._running = True

    def minimize_window(self) -> None:
        self._window.minimize()

    def close_window(self) -> None:
        self._running = False
        self._window.destroy()

    def set_game_visible(self, visible: bool) -> None:
        """Show or hide the Roblox window when switching screens."""
        self._game_visible = bool(visible)
        if not visible and self._roblox_hwnd and is_window(self._roblox_hwnd):
            # Move it off-screen so the full-page screen is unobstructed.
            position_window_to_client_rect(
                self._roblox_hwnd, -9999, -9999, GAME_SLOT_W, GAME_SLOT_H
            )

    def get_version(self) -> str:
        from sloppykeys.version import VERSION
        return VERSION

    def _get_webview_hwnd(self) -> int | None:
        """Get the native HWND of the pywebview window."""
        try:
            import ctypes
            from ctypes import wintypes
            # pywebview on Windows uses a WinForms window. Its title is the window title.
            hwnd = ctypes.windll.user32.FindWindowW(None, "SloppyKeys")
            return hwnd if hwnd else None
        except Exception:
            return None

    def _get_game_slot_screen_pos(self) -> tuple[int, int] | None:
        """Screen position of the game-slot div's top-left corner."""
        import ctypes
        from ctypes import wintypes

        webview_hwnd = self._get_webview_hwnd()
        if not webview_hwnd:
            return None
        # The game slot starts at (0, 38) in the window's client area.
        point = wintypes.POINT(GAME_SLOT_X, GAME_SLOT_Y)
        if not ctypes.windll.user32.ClientToScreen(webview_hwnd, ctypes.byref(point)):
            return None
        return (point.x, point.y)

    def _dock_roblox_loop(self) -> None:
        """Background thread: finds Roblox and keeps it positioned over the game slot."""
        while self._running:
            time.sleep(0.5)
            if not self._game_visible:
                continue

            # Find Roblox if not already tracked
            if not self._roblox_hwnd or not is_window(self._roblox_hwnd):
                self._roblox_hwnd = find_roblox_window()
                if not self._roblox_hwnd:
                    continue

            if is_minimized(self._roblox_hwnd):
                continue

            pos = self._get_game_slot_screen_pos()
            if pos is None:
                continue

            position_window_to_client_rect(
                self._roblox_hwnd, pos[0], pos[1], GAME_SLOT_W, GAME_SLOT_H
            )


def main() -> None:
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(ui_dir, "index.html")

    api = Api.__new__(Api)
    api._start_time = time.time()

    window = webview.create_window(
        title="SloppyKeys",
        url=html_path,
        width=1552,
        height=900,
        min_size=(1200, 700),
        frameless=True,
        easy_drag=False,
        js_api=api,
    )
    api._window = window

    def on_loaded():
        version = api.get_version()
        window.evaluate_js(
            f'document.getElementById("version-badge").textContent = "v{version}";'
        )
        # Start the Roblox docking loop once the UI is ready.
        api._dock_thread = threading.Thread(target=api._dock_roblox_loop, daemon=True)
        api._dock_thread.start()

    window.events.loaded += on_loaded
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
