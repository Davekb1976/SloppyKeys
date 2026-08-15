"""pywebview bridge: serves the HTML UI and exposes the macro backend.

Launch with: .venv\\Scripts\\python.exe -m sloppykeys.ui_web.bridge

This runs alongside the existing PySide6 app during migration — both entry
points stay functional until the migration is complete and the PySide6 code
is removed.

The window is frameless (custom titlebar in the DOM). The Roblox HWND
positioning will be added once the bridge is proven to load and communicate.
"""

from __future__ import annotations

import os
import sys
import time

import webview  # type: ignore[import-untyped]


class Api:
    """Methods exposed to JS via pywebview's js_api."""

    def __init__(self, window: webview.Window) -> None:
        self._window = window
        self._start_time = time.time()

    def minimize_window(self) -> None:
        self._window.minimize()

    def close_window(self) -> None:
        self._window.destroy()

    def set_game_visible(self, visible: bool) -> None:
        """Placeholder: will show/hide the Roblox HWND when viewport is wired."""
        pass

    def get_version(self) -> str:
        from sloppykeys.version import VERSION
        return VERSION


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

    window.events.loaded += on_loaded
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
