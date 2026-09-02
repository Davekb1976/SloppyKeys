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

import contextlib
import json
import os
import sys
import threading
import time
from datetime import datetime

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
    set_window_below,
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
from sloppykeys.config.settings import (
    EMPTY_VALUE,
    PRIVATE_SERVER_KEY,
    parse_private_server_link,
)
from sloppykeys.config.unified import UnifiedSettings
from sloppykeys.core.updates import (
    RELEASES_URL,
    Release,
    clear_downloads,
    download,
    expected_sha,
    installed_by_setup,
    latest_release,
    launch_installer,
    update_dir,
)
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
# How long a just-revealed game window needs before mss sees a painted frame.
GAME_REVEAL_SETTLE = 0.4
# The game is left alone for this long after startup, because the boot loader is a fullscreen
# DOM overlay and the game paints over all DOM content — docked on the slot it would punch a
# rectangle of Roblox through the middle of the loading screen. `_follow_loop` does not dock
# at all while it holds, it only pushes the game under our window: docking early also stripped
# Roblox's frame before the UI was up, so a session closed during the loader left it borderless
# and looking permanently fullscreen. Kept in step with the loader in `index.html`, whose hard
# cap is the same 5s; longer here would leave the Dashboard briefly gameless, shorter would
# show the game through the tail of the fade.
BOOT_COVER_SECONDS = 5.0

# The run log, back on disk. It had become UI-only when the Qt window went, so the log panel
# was the whole record: a finished session left nothing to read, and a run that misbehaved
# over a hundred cycles could not be diagnosed afterwards at all. Rotated once at startup
# rather than by size, so each file is exactly one session — this run in `log.txt`, the one
# before it in `log.prev.txt`. Both are gitignored.
LOG_NAME = "log.txt"
LOG_PREV_NAME = "log.prev.txt"
# The macro worker, the hotkey loop and the UI thread all log, and a torn line is worse than
# a slow one. `ponytail:` one lock for the whole file — fine at a few lines a second; if the
# log ever becomes chatty enough to matter, hand the writes to a queue and one writer thread.
_LOG_LOCK = threading.Lock()


class Api:
    """Methods exposed to JS via pywebview's js_api."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._hwnd: int | None = None
        self._game_hwnd: int | None = None
        self._game_style: int | None = None
        self._slot = DEFAULT_SLOT
        self._game_visible = True
        # Covered until the boot loader is gone. Timed rather than driven by the page: the
        # loader is deliberately independent of the bridge, and a gate that waits for a
        # callback would leave the game covered for good if that callback never came.
        self._booting = True
        self._boot_until = time.monotonic() + BOOT_COVER_SECONDS
        self._docked = False
        self._running = True
        self._dragging = False
        self._last_rect: tuple[int, int, int, int] | None = None
        # The release the update check found, held so Install doesn't have to ask again.
        self._pending_release: Release | None = None
        # Megabytes already pushed to the page, so the download reports once per MB.
        self._update_mb = -1
        # Macro controller — created lazily in on_loaded once app_root is known.
        self._ctrl: MacroController | None = None
        self._app_root: str | None = None
        self._run_thread: threading.Thread | None = None
        # Hotkey edge detection
        self._key_down: dict[str, bool] = {"start": False, "stop": False}
        # While the user is rebinding a key in the UI, suppress the hotkey loop so
        # the key being assigned doesn't also fire its action. Timestamped so an
        # abandoned capture (clicked, then clicked away) can't wedge hotkeys off.
        self._capture_until: float = 0.0

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
        """Only the Dashboard shows the game; elsewhere it is covered, not hidden.

        The game rides the topmost band over our slot, so leaving the band is not
        enough — HWND_NOTOPMOST lands it at the top of the normal band, still above
        the page. It gets tucked directly beneath our window instead, which covers
        it because our window is opaque and the slot sits inside it.

        Deliberately *not* SW_HIDE: that works, but it unmaps the window and takes
        its taskbar button with it, so the game vanishes from the taskbar every time
        the user opens a modal.
        """
        self._game_visible = bool(visible)
        if not self._docked or not is_window(self._game_hwnd) or self._game_hwnd is None:
            return
        SW_SHOWNOACTIVATE = 4
        user32.ShowWindow(self._game_hwnd, SW_SHOWNOACTIVATE)
        if visible:
            set_topmost(self._game_hwnd, True)
        else:
            set_topmost(self._game_hwnd, False)
            host = self._host_hwnd()
            if host:
                set_window_below(self._game_hwnd, host)

    @contextlib.contextmanager
    def _game_revealed(self):
        """Guarantee the game window is on screen for the duration of a capture.

        Every screen but the Dashboard hides it with SW_HIDE, so mss would grab
        whatever sits behind it. Reveals only when it was hidden, waits for one
        painted frame, and restores the previous state on the way out — so a
        caller already on the Dashboard pays nothing.
        """
        was_visible = self._game_visible
        if not was_visible:
            self.set_game_visible(True)
            time.sleep(GAME_REVEAL_SETTLE)
        try:
            yield
        finally:
            if not was_visible:
                self.set_game_visible(False)

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
        """Gamemodes the user can select (farm targets + Challenge)."""
        from sloppykeys.content.gamemodes import FARM_GAMEMODE_NAMES

        return FARM_GAMEMODE_NAMES + ["Challenge"]

    def get_maps(self, gamemode: str) -> list[str]:
        """Maps for a gamemode. Events reads from the route store."""
        from sloppykeys.content.gamemodes import is_custom, maps_for

        if is_custom(gamemode) and self._app_root:
            from sloppykeys.config.nav_routes import RouteStore

            return RouteStore(self._app_root).maps()
        return maps_for(gamemode)

    def get_difficulty_options(self, gamemode: str) -> list[str]:
        """What the task builder's Difficulty control offers for a gamemode: 1-3 where the
        game has a cycling button, Normal/Hard everywhere else. Derived from the table, so
        adding a cycling gamemode there is the whole change."""
        from sloppykeys.content.start_stage import difficulty_options

        return difficulty_options(gamemode)

    def get_targets(self, gamemode: str, map_name: str) -> list[str]:
        """Acts/targets for a gamemode+map combo."""
        from sloppykeys.content.gamemodes import is_custom, targets_for

        if is_custom(gamemode) and self._app_root:
            from sloppykeys.config.nav_routes import RouteStore

            return RouteStore(self._app_root).acts(map_name)
        return targets_for(gamemode, map_name)

    def get_mode_fields(self, gamemode: str) -> dict:
        """Which Task Builder rows this gamemode can actually use.

        One call instead of the page hard-coding mode names: every answer is derived from
        `content/`, so a mode that gains an act list or a Hard Mode coordinate gains its row
        with no change here or in `app.js`.

        A row that does nothing is worse than a missing one — it reads as a setting that was
        applied. Expedition's Stage dropdown could only ever say "—" (it has no act
        dimension), and Raid, Events and Portals all offered Easy/Hard with no toggle for the
        macro to click.
        """
        from sloppykeys.content.gamemodes import has_targets, labels_for, search_label
        from sloppykeys.content.start_stage import has_difficulty

        map_label, target_label = labels_for(gamemode)
        return {
            "map_label": map_label,
            "target_label": target_label,
            # `has_targets` is True for a custom mode even with an empty table: Events reads
            # its acts from routes.json.
            "stage": has_targets(gamemode),
            "difficulty": has_difficulty(gamemode),
            "extract": gamemode == "Expedition",
            "search_label": search_label(gamemode),
        }

    def get_priority_options(self) -> list:
        """Targeting priorities **in the game's cycle order**, so the planner's dropdown
        and the runner's press count come from one list. A dropdown that omitted an entry
        would make every option after it press the wrong number of times."""
        from sloppykeys.content.units import PRIORITY_OPTIONS

        return list(PRIORITY_OPTIONS)

    # ---- Detect block templates (assets/detect) ----

    def list_detect_images(self) -> list:
        """Templates the detect block can search for, with thumbnails for the preview.

        Their own folder rather than the navigation categories: these are the user's
        own crops for their own macros, and mixing them in would make a missing
        navigation template indistinguishable from a personal one.
        """
        if not self._app_root:
            return []
        import base64

        folder = os.path.join(self._app_root, "assets", "detect")
        if not os.path.isdir(folder):
            return []
        out = []
        for fname in sorted(os.listdir(folder)):
            if not fname.lower().endswith(".png"):
                continue
            try:
                with open(os.path.join(folder, fname), "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
            except OSError:
                continue
            out.append({
                "name": fname[:-4],
                "path": f"assets/detect/{fname}",
                "data_uri": f"data:image/png;base64,{b64}",
            })
        return out

    def save_detect_image(self, name: str, x: int, y: int, w: int, h: int) -> dict:
        """Crop the cached snapshot into `assets/detect/<name>.png`.

        The name is sanitised through the same helper every other display-name-to-path
        conversion uses, and refused outright if nothing usable survives.
        """
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        from sloppykeys.config.unit_configs import safe_component

        clean = safe_component(str(name or "").strip())[:60].strip()
        # `safe_component` maps illegal characters to "-", so ".." and "///" survive as
        # "-" and "---" — safely inside the folder, but a file nobody meant to make.
        # Require something nameable rather than repairing it into junk.
        if not any(ch.isalnum() for ch in clean):
            return {"ok": False, "reason": "invalid name"}
        return self.save_image_crop(f"assets/detect/{clean}.png", x, y, w, h)

    def delete_detect_image(self, name: str) -> dict:
        """Delete one detect template."""
        if not self._app_root:
            return {"ok": False}
        target = self._template_path(f"assets/detect/{name}.png")
        if target is None:
            return {"ok": False, "reason": "bad name"}
        try:
            os.remove(target)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "reason": str(exc)}

    # ---- Challenge ----

    def get_challenge_info(self) -> dict:
        """Clock-derived challenge facts. No capture, so it is safe to poll and
        works from any screen — the rotation boundary is wall clock, not OCR."""
        from sloppykeys.content.challenge import next_daily_reset_at, next_interval_at

        now = time.localtime()
        nxt = next_interval_at()
        daily = next_daily_reset_at()
        secs = max(0, int(nxt.timestamp() - time.mktime(now)))
        return {
            "ok": True,
            "next_reroll": nxt.strftime("%H:%M"),
            "reroll_in": f"{secs // 60}m {secs % 60:02d}s",
            "next_daily": daily.strftime("%H:%M"),
        }

    def scan_challenge(self) -> dict:
        """OCR the three challenge rows once. The panel has to be open — the reads
        are only trusted when at least one limit parsed as `n/10`, which nothing
        else on screen produces in those boxes.

        Reveals the game for the capture like every other grab, and runs off the
        caller's thread since RapidOCR on nine boxes is slow.
        """
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}

        def _run():
            from sloppykeys.core.image_search import ImageSearchEngine
            from sloppykeys.macro.challenge import ChallengeScanner

            try:
                engine = ImageSearchEngine(self._app_root, log=lambda _m: None)
                scanner = ChallengeScanner(engine, self._roblox_client_rect)
                with self._game_revealed():
                    reads, panel_open = scanner.scan_if_open()
            except Exception as exc:
                self._log_to_ui(f"[Challenge] Scan failed: {exc}")
                self._push_challenge({"ok": False, "reason": str(exc)})
                return

            if not panel_open:
                self._log_to_ui("[Challenge] No panel found — open the Challenge UI first.")
                self._push_challenge({"ok": False, "reason": "panel not open"})
                return

            for r in reads:
                self._log_to_ui(f"[Challenge] {r.summary()}")
            self.push_challenge_reads(reads)

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def push_challenge_reads(self, reads: list) -> None:
        """Show these reads on the Dashboard's challenge card.

        Public because the **run** calls it too, through
        `MacroController(on_challenge_reads=...)`: the card used to update only for the Scan
        button, so it read "Not scanned" while the macro was playing challenges off a scan of
        its own. One formatter, so the two paths cannot drift.
        """
        self._push_challenge(
            {
                "ok": True,
                "slots": [
                    {
                        "slot": r.slot,
                        "state": r.state,
                        "map": r.map_name,
                        "limit": r.limit_text,
                    }
                    for r in reads
                ],
            }
        )

    def _push_challenge(self, payload: dict) -> None:
        """Hand a scan result to the page. json.dumps, not an f-string — Python's
        True/False and None are not JS literals."""
        import json as _json

        if not self._window:
            return
        try:
            self._window.evaluate_js(
                f"window.onChallengeScan && window.onChallengeScan({_json.dumps(payload)});"
            )
        except Exception as exc:
            self._log_to_ui(f"[Challenge] Could not update the panel: {exc}")

    def _roblox_client_rect(self) -> tuple[int, int, int, int] | None:
        """(x, y, w, h) of the game's client area in screen coords, the shape the
        scanner and the search engine both expect."""
        hwnd = self._game_hwnd
        if not hwnd or not is_window(hwnd):
            hwnd = find_roblox_window()
        if not hwnd:
            return None
        from sloppykeys.core.win32.roblox_window import client_size, client_to_screen

        origin = client_to_screen(hwnd, 0, 0)
        size = client_size(hwnd)
        if not origin or not size:
            return None
        return (origin[0], origin[1], size[0], size[1])

    # ---- Settings (unified, auto-save) ----

    def get_settings(self) -> dict:
        """All settings with defaults merged. Called from JS to populate the Settings screen."""
        if not self._app_root:
            return {}
        return UnifiedSettings(self._app_root).get_all()

    def join_private_server(self) -> dict:
        """Launch Roblox straight into the private server the user saved in Settings.

        Goes through `parse_private_server_link` rather than handing the stored string to the
        shell. A share URL opened directly lands in a browser tab with a Join button; the
        parsed `roblox://` deep link starts the client itself, which is the whole point of
        having the parser. It builds the URI from a code it has already matched against
        `_CODE_PATTERN`, so what reaches the shell is constructed here rather than pasted —
        a whitelist, not an escape.
        """
        if not self._app_root:
            return {"ok": False, "reason": "still starting up"}
        link = str(UnifiedSettings(self._app_root).get(PRIVATE_SERVER_KEY, "") or "").strip()
        if not link or link.lower() == EMPTY_VALUE:
            return {"ok": False, "reason": "No private server link saved — add one in Settings."}
        uri, error = parse_private_server_link(link)
        if error or not uri:
            return {"ok": False, "reason": error or "That private server link could not be read."}
        try:
            os.startfile(uri)
        except OSError as exc:
            return {"ok": False, "reason": f"Failed to launch Roblox: {exc}"}
        self._log_to_ui("Joining the private server...")
        return {"ok": True}

    # ---- Updates ----
    #
    # `core/updates.py` has done the work since before the Qt window was deleted; what went
    # with that window was every caller. The setting stayed, so "Check for updates on
    # startup" was a checkbox that saved a value nothing read.
    #
    # Courtesy feature rules, from that module's own docstring: the check runs on a worker,
    # never blocks the page, never runs during a macro run, and a failure is a line in the
    # log rather than a dialog.

    def check_for_update(self, manual: bool = False) -> dict:
        """Ask GitHub whether there is a newer release. Answers through `window.on*`.

        An automatic check that finds nothing says nothing — the point is to be silent when
        there is no news. A manual one always answers, or the button looks broken.
        """
        if not self._app_root:
            return {"ok": False, "reason": "still starting up"}
        threading.Thread(
            target=self._update_check, args=(bool(manual),), daemon=True
        ).start()
        return {"ok": True}

    def _update_check(self, manual: bool) -> None:
        # Anything a previous update left in %TEMP% goes now. The app quits the moment it
        # hands over to the installer, so on the way in is the only chance it gets.
        clear_downloads()
        release, reason = latest_release()
        if release is None:
            if manual:
                self._push_js(
                    "window.onUpdateStatus",
                    {"ok": not reason, "message": reason or "SloppyKeys is up to date."},
                )
            elif reason:
                self._log_to_ui(f"Update check: {reason}")
            return
        self._pending_release = release
        self._push_js(
            "window.onUpdateAvailable",
            {
                "version": release.version,
                "page_url": release.page_url,
                # Only a copy this installer installed is offered an in-place update. A
                # portable-zip or dev copy running it would land a second install in
                # %LOCALAPPDATA% and go on launching the old one, so it gets the page.
                "can_install": bool(release.setup_url)
                and installed_by_setup(self._app_root or ""),
            },
        )

    def install_update(self) -> dict:
        """Download the pending release, verify it, run it, and quit so it can replace us."""
        release = self._pending_release
        if release is None:
            return {"ok": False, "reason": "nothing to install — check for an update first"}
        if not release.setup_url:
            return {"ok": False, "reason": "that release publishes no installer"}
        if self._ctrl is not None and self._ctrl.is_running:
            return {"ok": False, "reason": "stop the macro before installing an update"}
        self._update_mb = -1
        threading.Thread(target=self._run_update, args=(release,), daemon=True).start()
        return {"ok": True}

    def _run_update(self, release: Release) -> None:
        digest, reason = expected_sha(release)
        if not digest:
            # No published hash means no automatic install. Running an unverified exe to be
            # helpful is not a trade worth making; the release page is the honest fallback.
            self._push_js(
                "window.onUpdateStatus",
                {"ok": False, "message": f"Can't verify the download: {reason}"},
            )
            return
        dest = os.path.join(update_dir(), release.setup_name)
        ok, message = download(release.setup_url, dest, digest, self._push_update_progress)
        if not ok:
            self._push_js("window.onUpdateStatus", {"ok": False, "message": message})
            return
        ok, message = launch_installer(dest)
        if not ok:
            self._push_js("window.onUpdateStatus", {"ok": False, "message": message})
            return
        # Inno's restart manager needs this exe gone before it can replace it, and the
        # installer is already running. Hand the game its frame back first — quitting while
        # Roblox is still stripped is what leaves it looking permanently fullscreen.
        self._push_js(
            "window.onUpdateStatus", {"ok": True, "message": "Installing — SloppyKeys will close."}
        )
        self._running = False
        self._release_game()
        if self._window:
            self._window.destroy()

    def _push_update_progress(self, got: int) -> None:
        """One push per megabyte.

        `download` calls back every 256KB, which is ~400 bridge round trips for a 100MB
        installer. A megabyte is fine for a progress line and costs about 100.
        """
        megabytes = got // (1024 * 1024)
        if megabytes == self._update_mb:
            return
        self._update_mb = megabytes
        self._push_js("window.onUpdateProgress", {"mb": megabytes})

    def open_release_page(self) -> dict:
        """Open the release in the browser — the fallback for a portable or dev copy."""
        release = self._pending_release
        try:
            os.startfile(release.page_url if release else RELEASES_URL)
        except OSError as exc:
            return {"ok": False, "reason": f"Failed to open the release page: {exc}"}
        return {"ok": True}

    def _push_js(self, handler: str, payload) -> None:
        """Call a `window.on*` handler with one JSON argument.

        `json.dumps`, never an f-string: Python's `False` interpolated straight into JS
        crashed the run loop once with `False is not defined`.
        """
        if self._window is None:
            return
        self._window.evaluate_js(f"{handler} && {handler}({json.dumps(payload)});")

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

    def begin_hotkey_capture(self) -> dict:
        """Suppress the global hotkey loop while the UI captures a key to rebind.
        Auto-expires after 10s so an abandoned capture can't wedge hotkeys off."""
        self._capture_until = time.time() + 10.0
        return {"ok": True}

    def end_hotkey_capture(self) -> dict:
        """Re-enable the global hotkey loop after a rebind completes or cancels."""
        self._capture_until = 0.0
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

    # ---- Game Keybinds (in-game keys the macro presses) ----

    # Every table of OCR boxes, in the order the editor shows them. `where` says which
    # screen the boxes live on, which is the one thing a tester has to get right before a
    # read means anything. Add a table here and the OCR tab grows a section for it.
    _REGION_GROUPS = (
        ("challenge", "Challenge Panel", "the Challenge panel must be open"),
        ("match", "In Match", "a stage must be running"),
    )

    @staticmethod
    def _region_tables():
        from sloppykeys.content import challenge as _challenge
        from sloppykeys.content import match_regions as _match

        return {"challenge": _challenge, "match": _match}

    def get_vision_region_specs(self) -> list:
        """Every editable OCR box, tagged with the group whose screen it belongs to."""
        tables = self._region_tables()
        out = []
        for group, label, where in self._REGION_GROUPS:
            for key, spec_label, default in tables[group].region_specs():
                out.append({
                    "key": key,
                    "label": spec_label,
                    "default": list(default),
                    "group": group,
                    "groupLabel": label,
                    "groupWhere": where,
                })
        return out

    def get_vision_regions(self) -> dict:
        """Current region overrides from settings."""
        if not self._app_root:
            return {}
        settings = UnifiedSettings(self._app_root)
        return settings.get("vision_regions", {})

    def _apply_region_overrides(self, regions: dict) -> None:
        """Push the stored boxes into every table. Each ignores keys that aren't its own,
        so one dict serves them all."""
        for table in self._region_tables().values():
            table.apply_region_overrides(regions)

    def apply_stored_overrides(self) -> dict:
        """Load the user's measured boxes and per-template thresholds into the modules that
        read them.

        Called once at startup. Without it the tables held their defaults until the user
        happened to edit something, so a run used the shipped boxes and the shipped 0.70
        while the Settings screen showed the corrected values — the edits looked saved and
        silently did nothing. `points` was worse: it had no editor at all in this UI and was
        never applied, so a corrected act coordinate in settings.json did nothing whatsoever.
        """
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        regions = settings.get("vision_regions", {})
        if isinstance(regions, dict):
            self._apply_region_overrides(regions)
        points = settings.get("points", {})
        if isinstance(points, dict) and points:
            self._apply_point_overrides(points)
        thresholds = settings.get("image_thresholds", {})
        if isinstance(thresholds, dict) and thresholds:
            from sloppykeys.core.image_search import apply_confidence_overrides

            apply_confidence_overrides(thresholds)
        return {
            "ok": True,
            "regions": len(regions or {}),
            "points": len(points or {}),
            "thresholds": len(thresholds or {}),
        }

    # ---- Click points (acts, Hard Mode, the difficulty cycle) ----
    #
    # A coordinate the macro clicks blind, so being 20px out doesn't fail: it clicks the act
    # above the one you asked for and farms the wrong stage. Grouped by the screen they are
    # picked on, because all of Story's seven acts come off one screenshot of the act list
    # and the count differs per gamemode.

    _POINT_GROUPS = (
        ("acts", "Acts", "open the gamemode and a map, so the act list is on screen"),
        ("start", "Start panel", "select an act, so the Hard Mode / difficulty panel is up"),
        (
            "portal",
            "Bag grid",
            "open the bag and the Portals tab, then search a portal so one result is showing",
        ),
    )

    @staticmethod
    def _point_tables():
        from sloppykeys.content import acts as _acts
        from sloppykeys.content import portals as _portals
        from sloppykeys.content import start_stage as _start

        return {"acts": _acts, "start": _start, "portal": _portals}

    @staticmethod
    def _point_specs() -> list[tuple[str, str, str, str, tuple[int, int]]]:
        """(kind, key, gamemode, label, default) for every editable click point."""
        from sloppykeys.content.acts import act_specs
        from sloppykeys.content.portals import point_specs as portal_specs
        from sloppykeys.content.start_stage import point_specs

        rows = [("acts", *spec) for spec in act_specs()]
        rows += [("start", *spec) for spec in point_specs()]
        rows += [("portal", *spec) for spec in portal_specs()]
        return rows

    def list_vision_points(self) -> dict:
        """Editable click points, grouped by the screen they are picked on."""
        stored = self.get_vision_points()
        groups: dict[str, dict] = {}
        labels = {kind: (label, where) for kind, label, where in self._POINT_GROUPS}
        for kind, key, gamemode, label, default in self._point_specs():
            group_key = f"{kind}.{gamemode}"
            group_label, where = labels[kind]
            group = groups.setdefault(group_key, {
                "key": group_key,
                "gamemode": gamemode,
                "label": f"{gamemode} · {group_label}",
                "where": where,
                "points": [],
            })
            saved = stored.get(key)
            point = saved if isinstance(saved, (list, tuple)) and len(saved) >= 2 else default
            group["points"].append({
                "key": key,
                "label": label,
                "x": int(point[0]),
                "y": int(point[1]),
                "edited": saved is not None,
            })
        return {"ok": True, "groups": list(groups.values()), "viewport": [VIEWPORT_W, VIEWPORT_H]}

    def get_vision_points(self) -> dict:
        """Current click-point overrides from settings."""
        if not self._app_root:
            return {}
        stored = UnifiedSettings(self._app_root).get("points", {})
        return stored if isinstance(stored, dict) else {}

    def _apply_point_overrides(self, points: dict) -> None:
        """Push the stored points into every table; each ignores keys that aren't its own."""
        clean = {}
        for key, value in (points or {}).items():
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                try:
                    clean[str(key)] = (int(value[0]), int(value[1]))
                except (TypeError, ValueError):
                    continue  # dropped, not repaired: a half-read point clicks somewhere else
        for table in self._point_tables().values():
            table.apply_point_overrides(clean)

    def set_vision_point(self, key: str, x: int, y: int) -> dict:
        """Set one click point, in 1152x756 client space. Auto-saves and applies live."""
        if not self._app_root:
            return {"ok": False}
        known = {spec[1] for spec in self._point_specs()}
        if str(key) not in known:
            # Whitelisted rather than sanitised: an unknown key would sit in settings.json
            # forever, matching nothing, and read as a calibration that had been saved.
            return {"ok": False, "reason": "unknown point"}
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError):
            return {"ok": False, "reason": "not a coordinate"}
        if not (0 <= px < VIEWPORT_W and 0 <= py < VIEWPORT_H):
            return {"ok": False, "reason": "outside the viewport"}
        settings = UnifiedSettings(self._app_root)
        points = settings.get("points", {})
        if not isinstance(points, dict):
            points = {}
        points[str(key)] = [px, py]
        settings.set("points", points)
        self._apply_point_overrides(points)
        return {"ok": True, "x": px, "y": py}

    def reset_vision_points(self, group: str = "") -> dict:
        """Clear the overrides for one group, or all of them when `group` is empty."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        points = settings.get("points", {})
        if not isinstance(points, dict):
            points = {}
        if group:
            keys = {
                spec[1] for spec in self._point_specs()
                if f"{spec[0]}.{spec[2]}" == group
            }
            points = {k: v for k, v in points.items() if k not in keys}
        else:
            points = {}
        settings.set("points", points)
        self._apply_point_overrides(points)
        return {"ok": True}

    def set_vision_region(self, key: str, box: list) -> dict:
        """Set one OCR box override."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        regions = settings.get("vision_regions", {})
        regions[key] = tuple(box[:4])
        settings.set("vision_regions", regions)
        self._apply_region_overrides(regions)
        return {"ok": True}

    def reset_vision_regions(self) -> dict:
        """Clear all region overrides (revert to defaults)."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        settings.set("vision_regions", {})
        self._apply_region_overrides({})
        # The saved previews are crops of the boxes just discarded, so they'd show the user
        # a picture of coordinates that no longer exist.
        folder = self._region_preview_dir()
        for spec in self.get_vision_region_specs():
            try:
                os.remove(os.path.join(folder, f"{spec['key']}.png"))
            except OSError:
                pass
        return {"ok": True}

    # ---- Region previews ----
    #
    # The crop each box cuts out, kept as a PNG under assets/regions/. On disk because the
    # screens these boxes live on (the Challenge panel, a running stage) are almost never
    # up when Settings is opened, so the alternative to a saved crop is grabbing the game
    # at launch for a picture of the wrong screen. Written whenever a capture already
    # happened for this tab; read back on render, with no capture at all.

    def _region_preview_dir(self) -> str:
        return os.path.join(self._app_root or "", "assets", "regions")

    def _known_region_key(self, key) -> str:
        """The key as a filename, or "" — whitelisted against the tables, since it comes
        from the page and becomes a path."""
        if not isinstance(key, str):
            return ""
        return key if any(s["key"] == key for s in self.get_vision_region_specs()) else ""

    @staticmethod
    def _crop_region(img, box):
        """Slice a 1152×756-space box out of a captured client image, clamped to it."""
        ih, iw = img.shape[:2]
        x = min(max(0, int(box[0] * iw / VIEWPORT_W)), iw - 1)
        y = min(max(0, int(box[1] * ih / VIEWPORT_H)), ih - 1)
        w = min(max(1, int(box[2] * iw / VIEWPORT_W)), iw - x)
        h = min(max(1, int(box[3] * ih / VIEWPORT_H)), ih - y)
        return img[y:y + h, x:x + w].copy()

    def _write_region_preview(self, key: str, crop) -> str:
        """Save one crop and return it as a data URI. Empty string if it can't be written."""
        import base64

        import cv2

        safe = self._known_region_key(key)
        if not safe:
            return ""
        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            return ""
        png = buf.tobytes()
        try:
            os.makedirs(self._region_preview_dir(), exist_ok=True)
            with open(os.path.join(self._region_preview_dir(), f"{safe}.png"), "wb") as f:
                f.write(png)
        except OSError as exc:
            self._log_to_ui(f"Failed to save region preview: {exc}")
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")

    def get_region_previews(self) -> dict:
        """Every saved crop as a data URI, keyed by region. No capture."""
        import base64

        out = {}
        folder = self._region_preview_dir()
        if not os.path.isdir(folder):
            return out
        for spec in self.get_vision_region_specs():
            path = os.path.join(folder, f"{spec['key']}.png")
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
            except OSError:
                continue
            out[spec["key"]] = f"data:image/png;base64,{b64}"
        return out

    def save_region_preview(self, key: str, box: list) -> dict:
        """Crop the last snapshot — the one the Set modal drew on — and save it as this
        box's preview. No capture, so it does nothing before the first grab."""
        if not self._known_region_key(key):
            return {"ok": False, "reason": "unknown region"}
        img = getattr(self, "_cached_snapshot", None)
        if img is None:
            return {"ok": False, "reason": "no snapshot yet"}
        try:
            box = [int(v) for v in list(box)[:4]]
        except (TypeError, ValueError):
            return {"ok": False, "reason": "bad box"}
        if len(box) < 4:
            return {"ok": False, "reason": "bad box"}
        uri = self._write_region_preview(key, self._crop_region(img, box))
        return {"ok": bool(uri), "data_uri": uri}

    def preview_ocr_regions(self, group: str = "") -> dict:
        """Grab the game once and save a preview for every box in one section. Its screen
        has to be up — which is what the section's note says."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        cap = self._capture_client_image()
        if cap is None:
            return {"ok": False, "reason": "Roblox not running or not visible"}
        img, _vw, _vh = cap
        regions = UnifiedSettings(self._app_root).get("vision_regions", {})
        previews = {}
        for spec in self.get_vision_region_specs():
            if group and spec["group"] != group:
                continue
            box = list(regions.get(spec["key"], spec["default"]))
            uri = self._write_region_preview(spec["key"], self._crop_region(img, box))
            if uri:
                previews[spec["key"]] = uri
        return {"ok": True, "previews": previews}

    def test_ocr_region(self, key: str, box: list) -> dict:
        """Capture the Roblox screen and OCR the given region. Returns the text read."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        try:
            import mss
            import numpy as np
            import cv2
            from sloppykeys.core.ocr import OcrReader
            from sloppykeys.core.win32.roblox_window import client_to_screen, client_size, is_window

            # Use the tracked game HWND (works even when hidden for screen capture)
            hwnd = self._game_hwnd
            if not hwnd or not is_window(hwnd):
                from sloppykeys.core.win32.roblox_window import find_roblox_window
                hwnd = find_roblox_window()
            if not hwnd:
                return {"ok": False, "reason": "Roblox not running"}

            origin = client_to_screen(hwnd, 0, 0)
            size = client_size(hwnd)
            if not origin or not size:
                return {"ok": False, "reason": "can't read Roblox geometry"}

            vx, vy = origin
            vw, vh = size
            x = vx + int(box[0] * vw / 1152)
            y = vy + int(box[1] * vh / 756)
            w = max(1, int(box[2] * vw / 1152))
            h = max(1, int(box[3] * vh / 756))

            with mss.mss() as sct:
                mon = {"left": x, "top": y, "width": w, "height": h}
                img = np.array(sct.grab(mon))[:, :, :3].copy()

            ocr = OcrReader()
            ok_avail, msg = ocr.available()
            if not ok_avail:
                return {"ok": False, "reason": msg}
            result = ocr.read_line(img)
            return {"ok": True, "text": result.text or "(empty)", "score": round(result.score, 3)}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}

    def _capture_client_image(self):
        """Grab the full Roblox client area as a BGR numpy image while it's visible.
        Returns (img, vw, vh) or None. Capturing once up front means the OCR pass
        doesn't depend on the game staying on screen."""
        try:
            import mss
            import numpy as np
            from sloppykeys.core.win32.roblox_window import (
                client_to_screen, client_size, is_window, find_roblox_window,
            )
            hwnd = self._game_hwnd
            if not hwnd or not is_window(hwnd):
                hwnd = find_roblox_window()
            if not hwnd:
                return None
            origin = client_to_screen(hwnd, 0, 0)
            size = client_size(hwnd)
            if not origin or not size:
                return None
            vx, vy = origin
            vw, vh = size
            with self._game_revealed(), mss.mss() as sct:
                mon = {"left": vx, "top": vy, "width": vw, "height": vh}
                img = np.array(sct.grab(mon))[:, :, :3].copy()
            return img, vw, vh
        except Exception:
            return None

    def test_ocr_all(self, group: str = "") -> dict:
        """Capture the game once (synchronously, while visible), then OCR the regions from
        that snapshot off-thread. Returns after the capture, so the caller can restore the
        Settings screen without racing the read.

        `group` limits it to one table — only one group's screen is ever up, so testing
        all of them at once guarantees half the rows read nonsense.
        """
        if not self._app_root:
            return {"ok": False}
        group_filter = group or None

        cap = self._capture_client_image()
        if cap is None:
            self._log_to_ui("[OCR] Capture failed — is Roblox running and visible?")
            return {"ok": False}
        img, vw, vh = cap

        def _run():
            import json as _json

            from sloppykeys.core.ocr import OcrReader
            ocr = OcrReader()
            ok_avail, msg = ocr.available()
            if not ok_avail:
                self._log_to_ui(f"[OCR] {msg}")
                return
            regions = UnifiedSettings(self._app_root).get("vision_regions", {})
            # Every group, so a Match box is testable too. Only one group's screen can be
            # up at a time, so the other's rows are expected to read as junk.
            specs = [(s["key"], s["default"]) for s in self.get_vision_region_specs()
                     if group_filter in (None, s["group"])]
            for key, default in specs:
                crop = self._crop_region(img, list(regions.get(key, default)))
                result = ocr.read_line(crop)
                # The crop rides back with the read, and lands in assets/regions/ on the
                # way: a wrong box reads as junk text either way, and only the picture says
                # whether it was aimed at the digits or at the border beside them.
                payload = {
                    "key": key,
                    "text": result.text or "(empty)",
                    "score": round(result.score, 3),
                    "data_uri": self._write_region_preview(key, crop),
                }
                if self._window:
                    self._window.evaluate_js(
                        "window.onOcrRegionResult && "
                        f"window.onOcrRegionResult({_json.dumps(payload)});"
                    )
            self._log_to_ui("[OCR] Scan complete.")

        import threading
        threading.Thread(target=_run, daemon=True).start()
        self._log_to_ui("[OCR] Scanning all regions...")
        return {"ok": True}

    # ---- Game Keybinds (in-game keys the macro presses) ----

    def get_game_keybinds(self) -> dict:
        """The in-game keybind mapping."""
        if not self._app_root:
            return {}
        settings = UnifiedSettings(self._app_root)
        return settings.get("game_keybinds", {
            "upgrade": "t", "sell": "x", "priority": "r", "autograde": "v"
        })

    def set_game_keybind(self, action: str, key: str) -> dict:
        """Set one in-game keybind."""
        if not self._app_root:
            return {"ok": False}
        settings = UnifiedSettings(self._app_root)
        gk = settings.get("game_keybinds", {
            "upgrade": "t", "sell": "x", "priority": "r", "autograde": "v"
        })
        gk[action] = key.lower()
        settings.set("game_keybinds", gk)
        return {"ok": True}

    # ---- Task Queue ----

    def get_tasks(self) -> list:
        """The ordered task queue."""
        if not self._app_root:
            return []
        return UnifiedSettings(self._app_root).get_tasks()

    # ---- Task Queue Presets ----

    def list_task_presets(self) -> list:
        """Names of all saved task queue presets."""
        if not self._app_root:
            return []
        folder = os.path.join(self._app_root, "presets")
        if not os.path.isdir(folder):
            return []
        import json as _json
        names = []
        for f in sorted(os.listdir(folder)):
            if f.endswith(".json"):
                try:
                    with open(os.path.join(folder, f), "r", encoding="utf-8") as fh:
                        data = _json.load(fh)
                    names.append(data.get("name", f[:-5]))
                except (OSError, ValueError):
                    names.append(f[:-5])
        return names

    def save_task_preset(self, name: str, tasks: list) -> dict:
        """Save the current task queue as a named preset."""
        if not self._app_root:
            return {"ok": False}
        import json as _json, re as _re
        folder = os.path.join(self._app_root, "presets")
        os.makedirs(folder, exist_ok=True)
        slug = _re.sub(r"[^A-Za-z0-9 _\-]", "", name or "").strip() or "preset"
        path = os.path.join(folder, f"{slug}.json")
        payload = {"name": name, "tasks": tasks}
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return {"ok": True}
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return {"ok": False}

    def load_task_preset(self, name: str) -> dict:
        """Load a saved task queue preset by name."""
        if not self._app_root:
            return {"ok": False, "tasks": []}
        import json as _json, re as _re
        folder = os.path.join(self._app_root, "presets")
        # Find by display name
        if os.path.isdir(folder):
            for f in os.listdir(folder):
                if not f.endswith(".json"):
                    continue
                path = os.path.join(folder, f)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = _json.load(fh)
                    if data.get("name") == name:
                        return {"ok": True, "tasks": data.get("tasks", [])}
                except (OSError, ValueError):
                    continue
        return {"ok": False, "tasks": []}

    def delete_task_preset(self, name: str) -> dict:
        """Delete a task queue preset by name."""
        if not self._app_root:
            return {"ok": False}
        import json as _json
        folder = os.path.join(self._app_root, "presets")
        if not os.path.isdir(folder):
            return {"ok": False}
        for f in os.listdir(folder):
            if not f.endswith(".json"):
                continue
            path = os.path.join(folder, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = _json.load(fh)
                if data.get("name") == name:
                    os.remove(path)
                    return {"ok": True}
            except (OSError, ValueError):
                continue
        return {"ok": False}

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
        """Category folders under assets/reference/."""
        if not self._app_root:
            return []
        ref = os.path.join(self._app_root, "assets", "reference")
        if not os.path.isdir(ref):
            return []
        return sorted(
            d for d in os.listdir(ref)
            if os.path.isdir(os.path.join(ref, d))
        )

    def list_maps(self, category: str) -> list:
        """Map image names in a category (scans subfolders recursively)."""
        if not self._app_root:
            return []
        folder = os.path.join(self._app_root, "assets", "reference", category)
        if not os.path.isdir(folder):
            return []
        maps = []
        for dirpath, _dirs, files in os.walk(folder):
            for f in sorted(files):
                if f.lower().endswith(".png"):
                    # Use relative path from the category folder as the map name
                    rel = os.path.relpath(os.path.join(dirpath, f), folder)
                    maps.append(rel[:-4].replace("\\", "/"))
        return maps

    def get_map_image(self, category: str, name: str) -> dict:
        """Base64 data URI of a map image for the position picker.

        `name` can carry separators — "Villian Invasion/Act 1" for a per-act backdrop — so
        it goes through `_template_path`, which is what keeps a `..` in either argument from
        reading a PNG anywhere on disk. Both come from the page, so both are untrusted.
        """
        if not self._app_root:
            return {"ok": False}
        import base64

        rel = f"assets/reference/{category}/{name}.png"
        path = self._template_path(rel)
        if path is None or not os.path.isfile(path):
            return {"ok": False, "reason": "not found"}
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            return {"ok": True, "data_uri": f"data:image/png;base64,{b64}"}
        except OSError as exc:
            return {"ok": False, "reason": str(exc)}

    def get_roblox_snapshot(self) -> dict:
        """Capture the live Roblox window as a base64 PNG for position picking.
        Also caches the raw BGR array for save_image_crop.

        Refuses while Roblox is minimized: mss grabs a screen *rectangle*, and a minimized
        window reports coordinates near -32000, so the grab succeeds and hands back a
        picture of nothing — which reads as a bad capture rather than a missing window.
        """
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

        from sloppykeys.core.win32.roblox_window import (
            client_size,
            client_to_screen,
            is_minimized,
        )

        if is_minimized(hwnd):
            return {"ok": False, "reason": "Roblox is minimized"}

        # Read the geometry **inside** the reveal, not before it: the window is moved onto
        # the slot as part of being shown, so an origin read while it was still tucked away
        # can point at where it used to be.
        with self._game_revealed(), mss.mss() as sct:
            origin = client_to_screen(hwnd, 0, 0)
            size = client_size(hwnd)
            if not origin or not size:
                return {"ok": False, "reason": "couldn't read Roblox geometry"}
            monitor = {
                "left": origin[0], "top": origin[1], "width": size[0], "height": size[1]
            }
            img = np.array(sct.grab(monitor))

        bgr = img[:, :, :3].copy()
        self._cached_snapshot = bgr  # cache for save_image_crop

        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            return {"ok": False, "reason": "encode failed"}
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        return {"ok": True, "data_uri": f"data:image/png;base64,{b64}"}

    # ---- Image Manager ----

    # Widest a grid thumbnail is drawn, so anything bigger is shrunk before it crosses the
    # bridge. The map references are full 1152x756 client shots: sending them whole made one
    # Image Manager open a 19.6 MB payload, 19.5 MB of which was the ten maps.
    THUMB_MAX_W = 320
    # Below this, encoding is skipped entirely and the file is passed through byte for byte.
    # Every template crop is a few KB, so they never pay for a decode.
    THUMB_PASSTHROUGH_BYTES = 64 * 1024

    def _thumb_data_uri(self, path: str) -> str:
        """Data URI for a grid thumbnail, downscaled if the file is large.

        Cached on mtime, so reopening the manager costs nothing until a capture rewrites the
        file. Downscaled thumbs go out as JPEG: a screenshot is photographic, and PNG of one
        is ~7x the bytes for a picture drawn 320px wide.
        """
        import base64

        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return ""
        cache = getattr(self, "_thumb_cache", None)
        if cache is None:
            cache = self._thumb_cache = {}
        hit = cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]

        with open(path, "rb") as f:
            raw = f.read()
        uri = ""
        if len(raw) > self.THUMB_PASSTHROUGH_BYTES:
            try:
                import cv2
                import numpy as np

                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if img is not None and img.shape[1] > self.THUMB_MAX_W:
                    scale = self.THUMB_MAX_W / img.shape[1]
                    small = cv2.resize(
                        img, (self.THUMB_MAX_W, max(1, round(img.shape[0] * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
                        uri = f"data:image/jpeg;base64,{b64}"
            except ImportError:
                pass
        if not uri:
            uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        cache[path] = (stamp, uri)
        return uri

    def list_vision_templates(self) -> dict:
        """All searchable image names organized by category, with thumbnails and thresholds."""
        if not self._app_root:
            return {"ok": False, "categories": []}
        import base64

        # `kind` says what the folder holds. Everything is a searched template except the
        # map references, which are whole-screen backdrops the position picker draws
        # placement coordinates on — no threshold, nothing to test, and a capture saves the
        # full frame instead of a crop.
        IMAGE_CATEGORIES = {
            "lobby": ("Lobby Navigation", "template"),
            "match": ("Match State", "template"),
            "gamemodes": ("Gamemode Cards", "template"),
            "stages": ("Stage Selection", "template"),
            "challenge": ("Challenge", "template"),
            "events": ("Events", "template"),
            "portals": ("Portals", "template"),
            "reference": ("Maps", "map"),
        }
        # This table is not a display detail: the missing-template pass below filters
        # `expected_paths()` by `assets/<key>/`, so an expected path whose folder has no
        # entry here is dropped silently and its card never appears to capture into.

        # Read current thresholds from settings
        from sloppykeys.core.image_search import DEFAULT_CONFIDENCE

        settings = UnifiedSettings(self._app_root)
        thresholds = settings.get("image_thresholds", {})
        # From the engine, not a copy. This was three hardcoded 0.70s — here, in
        # `set_image_threshold` and in `test_image_search` — so raising the engine's default
        # would have left every slider, every "is this an override" test and the Test button
        # all reporting against the old number.
        default_threshold = DEFAULT_CONFIDENCE

        categories = []
        images_root = os.path.join(self._app_root, "assets")

        # Collect all expected template paths so we can mark missing ones. Map references
        # come from the same schema: an uncaptured backdrop is only a fallback to a live
        # capture, but without a card here there is nowhere to capture it — which is why
        # Expedition had no maps at all.
        from sloppykeys.content.nav_images import expected_paths, map_reference_paths
        expected = set()
        try:
            expected = set(p.replace("\\", "/") for p in expected_paths())
            expected |= set(p.replace("\\", "/") for p in map_reference_paths())
        except Exception:
            pass

        found_paths = set()

        for key, (label, kind) in IMAGE_CATEGORIES.items():
            folder = os.path.join(images_root, key)
            names = []
            # Walk recursively to find all PNGs (some categories have subfolders)
            if os.path.isdir(folder):
                for dirpath, _dirs, files in os.walk(folder):
                    for fname in sorted(files):
                        if not fname.lower().endswith(".png"):
                            continue
                        name = fname[:-4]
                        path = os.path.join(dirpath, fname)
                        rel = os.path.relpath(path, self._app_root).replace("\\", "/")
                        found_paths.add(rel)
                        # Subfolder between the category and the file, e.g. "story" for
                        # assets/stages/story/school_grounds.png. Story, Expedition and
                        # Challenge all offer School Grounds, so the bare name alone
                        # shows three identical-looking cards.
                        group = os.path.relpath(dirpath, folder).replace("\\", "/")
                        group = "" if group == "." else group
                        try:
                            names.append({
                                "name": name,
                                "group": group,
                                "file": fname,
                                # The template's identity everywhere: the threshold key the
                                # search engine looks up, and the file a crop overwrites.
                                "path": rel,
                                "data_uri": self._thumb_data_uri(path),
                                "threshold": float(thresholds.get(rel, default_threshold)),
                                "missing": False,
                            })
                        except OSError:
                            continue

            # Add missing expected templates for this category
            prefix = f"assets/{key}/"
            for ep in sorted(expected):
                if not ep.startswith(prefix):
                    continue
                rel_full = ep
                if rel_full in found_paths:
                    continue
                # This template is expected but missing
                fname = os.path.basename(ep)
                name = fname[:-4] if fname.endswith(".png") else fname
                group = ep[len(prefix):-len(fname)].strip("/")
                names.append({
                    "name": name,
                    "group": group,
                    "file": fname,
                    "path": ep,
                    "data_uri": "",
                    "threshold": float(thresholds.get(ep, default_threshold)),
                    "missing": True,
                })

            if names:
                categories.append({"key": key, "label": label, "kind": kind, "names": names})

        return {"ok": True, "categories": categories, "default_threshold": default_threshold}

    def _template_path(self, rel: str) -> str | None:
        """Validate a template path coming from the page and return it absolute.

        Rejects rather than repairs: this both names a settings key and picks the file a
        crop overwrites, so a traversal would let the page write outside `assets/`.
        """
        rel = str(rel or "").replace("\\", "/").strip()
        if not rel.startswith("assets/") or not rel.endswith(".png"):
            return None
        root = os.path.realpath(os.path.join(self._app_root, "assets"))
        target = os.path.realpath(os.path.join(self._app_root, rel))
        if os.path.commonpath([root, target]) != root:
            return None
        return target

    def set_image_threshold(self, path: str, value: float) -> dict:
        """Set one template's match threshold. Auto-saves.

        Keyed by the template's **relative path**, because that is what
        `image_search.confidence_for` looks up. Keying by bare filename meant the
        slider wrote a setting the engine never read, and that Story's and
        Expedition's same-named stage shared one value.
        """
        if not self._app_root:
            return {"ok": False}
        if self._template_path(path) is None:
            return {"ok": False, "reason": "bad template path"}
        key = str(path).replace("\\", "/").strip()
        settings = UnifiedSettings(self._app_root)
        thresholds = settings.get("image_thresholds", {})
        if not isinstance(thresholds, dict):
            thresholds = {}
        from sloppykeys.core.image_search import DEFAULT_CONFIDENCE

        default = DEFAULT_CONFIDENCE
        if abs(float(value) - default) < 0.01:
            thresholds.pop(key, None)
        else:
            thresholds[key] = max(0.50, min(1.0, float(value)))
        settings.set("image_thresholds", thresholds)
        # Apply live to the search engine
        if self._ctrl and hasattr(self._ctrl, '_engine'):
            from sloppykeys.core.image_search import apply_confidence_overrides
            apply_confidence_overrides(thresholds)
        return {"ok": True}

    def test_image_search(self, image_path: str) -> dict:
        """Test-search one image against the live Roblox screen. Returns match info."""
        if not self._app_root:
            return {"ok": False, "best": 0}
        from sloppykeys.core.image_search import (
            DEFAULT_CONFIDENCE,
            ImageProfile,
            ImageSearchEngine,
            best_score,
        )
        from sloppykeys.core.win32.roblox_window import find_roblox_window, client_to_screen, client_size

        hwnd = find_roblox_window()
        if not hwnd:
            return {"ok": False, "best": 0, "reason": "Roblox not found"}

        origin = client_to_screen(hwnd, 0, 0)
        size = client_size(hwnd)
        if not origin or not size:
            return {"ok": False, "best": 0, "reason": "can't read Roblox geometry"}

        rect = (origin[0], origin[1], size[0], size[1])
        # `image_path` is already `assets/...`, the same identity the grid and the
        # threshold use. Joining "assets" again here doubled the prefix.
        full_path = self._template_path(image_path)
        if full_path is None or not os.path.isfile(full_path):
            return {"ok": False, "best": 0, "reason": f"file not found: {image_path}"}

        # Read the threshold under the same path key the search engine looks up.
        settings = UnifiedSettings(self._app_root)
        thresholds = settings.get("image_thresholds", {})
        key = str(image_path).replace("\\", "/").strip()
        name = os.path.splitext(os.path.basename(image_path))[0]
        threshold = float(thresholds.get(key, DEFAULT_CONFIDENCE))

        # Use the controller's engine if available, else create a temporary one
        engine = self._ctrl._engine if self._ctrl else ImageSearchEngine(self._app_root)

        profile = ImageProfile(name=name, image_path=full_path, confidence=threshold)
        match = engine.find_first([profile], rect)

        if match:
            return {"ok": True, "score": match.score, "x": match.center_x, "y": match.center_y, "threshold": threshold}

        # Get best score for diagnostics (search with minimum threshold)
        low_profile = ImageProfile(name=name, image_path=full_path, confidence=0.01)
        low_match = engine.find_first([low_profile], rect)
        best = low_match.score if low_match else 0
        return {"ok": False, "best": best, "threshold": threshold}

    def save_image_crop(self, path: str, x: int, y: int, w: int, h: int) -> dict:
        """Crop from the cached snapshot and save it, OVERWRITING that template.

        Takes the template's relative path, not category+name: a stage lives at
        `assets/stages/<gamemode>/<stage>.png`, and joining category+name dropped the
        gamemode folder, so a recaptured stage landed flat in `assets/stages/` where
        `nav_images.stage_image` never looks for it.
        """
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        target = self._template_path(path)
        if target is None:
            return {"ok": False, "reason": "bad template path"}
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

        os.makedirs(os.path.dirname(target), exist_ok=True)
        cv2.imwrite(target, crop)
        return {"ok": True, "path": target}

    def save_map_reference(self, path: str) -> dict:
        """Save the cached snapshot **whole** as a map reference.

        No crop, unlike every other image here: the position picker draws placement
        coordinates on these, so a reference has to be the full client area or the
        coordinates read off it land somewhere else in the stage.
        """
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        target = self._template_path(path)
        if target is None:
            return {"ok": False, "reason": "bad reference path"}
        img = getattr(self, "_cached_snapshot", None)
        if img is None:
            return {"ok": False, "reason": "no cached snapshot — capture first"}
        try:
            import cv2
        except ImportError:
            return {"ok": False, "reason": "cv2 not available"}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        cv2.imwrite(target, img)
        return {"ok": True, "path": target}

    def run_camera_setup(self) -> dict:
        """Run the camera step on its own, so a map reference can be captured at the same
        angle the macro plays at.

        Off-thread: it is several seconds of AHK input. Refused mid-run — two camera
        scripts fighting would leave the pitch somewhere neither of them intended.
        """
        if self._ctrl is None:
            return {"ok": False, "reason": "backend not ready"}
        if self._ctrl.is_running:
            return {"ok": False, "reason": "macro is running"}

        def _run():
            self._ctrl.run_camera()
            # The caller has the game revealed for the duration; tell it when to put the
            # cover back, since only the page knows what is open over it.
            if self._window:
                self._window.evaluate_js("window.onCameraDone && window.onCameraDone();")

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    # ---- Walk Path Recording ----

    def start_walk_recording(self, name: str) -> dict:
        """Begin recording WASD keypresses."""
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.macro.recording import WalkRecorder
        if not hasattr(self, '_walk_recorder'):
            self._walk_recorder = None
        if self._walk_recorder and self._walk_recorder.is_recording:
            return {"ok": False, "error": "already recording"}
        self._walk_recorder = WalkRecorder(name, self._app_root)
        self._walk_recorder.start()
        return {"ok": True}

    def stop_walk_recording(self) -> dict:
        """Stop recording the walk path (keeps it in memory, not saved yet)."""
        if not hasattr(self, '_walk_recorder') or not self._walk_recorder:
            return {"ok": False}
        self._pending_walk_name = self._walk_recorder.stop()
        self._walk_recorder = None
        return {"ok": True}

    def rename_walk_path(self, name: str) -> dict:
        """Rename the pending walk path to the user's chosen name and save."""
        if not self._app_root:
            return {"ok": False}
        pending = getattr(self, '_pending_walk_name', None)
        if not pending:
            return {"ok": False, "reason": "no pending walk path"}
        import os, shutil
        from sloppykeys.macro.recording import _safe_name
        old_path = os.path.join(self._app_root, "paths", f"{pending}.json")
        new_slug = _safe_name(name)
        new_path = os.path.join(self._app_root, "paths", f"{new_slug}.json")
        if os.path.isfile(old_path) and old_path != new_path:
            # Rename by reading + rewriting with new name
            import json
            try:
                with open(old_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["name"] = name
                with open(new_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.remove(old_path)
            except OSError:
                pass
        self._pending_walk_name = None
        return {"ok": True, "name": new_slug}

    def discard_walk_path(self) -> dict:
        """Discard the pending walk path recording."""
        import os
        pending = getattr(self, '_pending_walk_name', None)
        if pending and self._app_root:
            path = os.path.join(self._app_root, "paths", f"{pending}.json")
            try:
                os.remove(path)
            except OSError:
                pass
        self._pending_walk_name = None
        return {"ok": True}

    def start_input_recording(self) -> dict:
        """Begin recording full mouse+keyboard input via hooks."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        from sloppykeys.macro.recording import InputRecorder
        if not hasattr(self, '_input_recorder'):
            self._input_recorder = None
        if self._input_recorder and self._input_recorder.is_recording:
            return {"ok": False, "reason": "already recording"}
        self._input_recorder = InputRecorder(self._app_root)
        ok = self._input_recorder.start()
        if not ok:
            self._input_recorder = None
            return {"ok": False, "reason": "Roblox not found"}
        return {"ok": True}

    def stop_input_recording(self) -> dict:
        """Stop recording. Returns event count (not yet saved)."""
        if not hasattr(self, '_input_recorder') or not self._input_recorder:
            return {"ok": False, "count": 0}
        self._pending_recording_events = self._input_recorder.stop()
        self._input_recorder = None
        return {"ok": True, "count": len(self._pending_recording_events)}

    def save_pending_recording(self, name: str) -> dict:
        """Save the stopped recording under the given name."""
        if not self._app_root:
            return {"ok": False}
        events = getattr(self, '_pending_recording_events', None)
        if not events:
            return {"ok": False, "reason": "no pending recording"}
        from sloppykeys.macro.recording import save_recording
        saved = save_recording(self._app_root, name, events)
        self._pending_recording_events = None
        return {"ok": True, "name": saved}

    def discard_pending_recording(self) -> dict:
        """Discard the stopped recording without saving."""
        self._pending_recording_events = None
        return {"ok": True}

    def test_recording(self, name: str) -> dict:
        """Replay a saved recording immediately (for testing)."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        from sloppykeys.macro.recording import load_recording, replay_recording
        from sloppykeys.core.win32.roblox_window import find_roblox_window

        data = load_recording(self._app_root, name)
        events = data.get("events", [])
        if not events:
            return {"ok": False, "reason": f"recording '{name}' is empty or not found"}
        hwnd = find_roblox_window()
        if not hwnd:
            return {"ok": False, "reason": "Roblox not found"}
        # Run on a thread so it doesn't block the bridge
        import threading
        stop = threading.Event()
        def _run():
            replay_recording(events, hwnd=hwnd, stop_event=stop)
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=120.0)
        return {"ok": True}

    def test_walk_path(self, name: str) -> dict:
        """Replay a saved walk path via AHK (for testing)."""
        if not self._app_root:
            return {"ok": False, "reason": "no app root"}
        from sloppykeys.macro.recording import replay_walk_script
        from sloppykeys.core.ahk import AhkBridge

        script = replay_walk_script(self._app_root, name)
        if not script:
            return {"ok": False, "reason": f"path '{name}' is empty or not found"}
        ahk = AhkBridge()
        if not ahk.available():
            return {"ok": False, "reason": "AutoHotkey not found"}
        ok, msg = ahk.run(script, wait=True, timeout=60.0)
        return {"ok": ok, "reason": msg if not ok else ""}

    def delete_recording(self, name: str) -> dict:
        """Delete a saved recording by name."""
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.macro.recording import delete_recording
        ok = delete_recording(self._app_root, name)
        return {"ok": ok}

    def list_walk_paths(self) -> list:
        """Names of all recorded walk paths."""
        if not self._app_root:
            return []
        from sloppykeys.macro.recording import list_walk_paths
        return list_walk_paths(self._app_root)

    def delete_walk_path(self, name: str) -> dict:
        """Delete the user's own recording of a walk path.

        `shipped` says the name still resolves afterwards, i.e. deleting only dropped an
        override and Auto is back on the shipped default.
        """
        if not self._app_root:
            return {"ok": False}
        from sloppykeys.macro.recording import delete_walk_path, walk_path_file
        ok = delete_walk_path(self._app_root, name)
        return {"ok": ok, "shipped": bool(walk_path_file(self._app_root, name))}

    def get_walk_defaults(self) -> list:
        """The Auto table: which walk path each target uses, and whether it exists on disk.

        A missing recording is a state the UI shows, not an error — the name is what it has
        to be recorded under for Auto to pick it up.
        """
        from sloppykeys.content.walk_paths import DEFAULT_WALK_PATHS
        from sloppykeys.macro.recording import walk_path_file

        if not self._app_root:
            return []
        return [
            {
                "target": target,
                "path": name,
                "missing": not walk_path_file(self._app_root, name),
            }
            for target, name in DEFAULT_WALK_PATHS.items()
        ]

    def list_input_recordings(self) -> list:
        """Names of all input recordings."""
        if not self._app_root:
            return []
        from sloppykeys.macro.recording import list_recordings
        return list_recordings(self._app_root)

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
        self._push_status()
        return {"ok": True}

    def resume_macro(self) -> dict:
        """Resume a paused macro."""
        if self._ctrl is None:
            return {"ok": False}
        self._ctrl.resume()
        self._push_status()
        return {"ok": True}

    def toggle_pause(self) -> dict:
        """Toggle pause/resume. The server decides the state, not the client."""
        if self._ctrl is None or not self._ctrl.is_running:
            return {"ok": False}
        if self._ctrl._paused:
            self._ctrl.resume()
        else:
            self._ctrl.pause()
        self._push_status()
        return {"ok": True, "paused": self._ctrl._paused}

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
        """Push macro state + stats to the frontend."""
        if self._window is None:
            return
        status = self.get_macro_status()
        running_js = "true" if status["running"] else "false"
        self._window.evaluate_js(
            f'window.onMacroStatus && window.onMacroStatus({running_js}, {status["cycle"]}, '
            f'"{status["target"]}", "{status["phase"]}");'
        )
        # Also push latest stats
        if self._ctrl:
            snap = self._ctrl._stats.snapshot()
            won_js = "true" if snap.last_run == "Win" else "false"
            self._window.evaluate_js(
                f'window.onMatchResult && window.onMatchResult({won_js}, '
                f'{snap.wins}, {snap.losses});'
            )

    def _log_to_ui(self, msg: str) -> None:
        """Push a log line to the frontend, and keep a copy on disk.

        The file is written first and outside the window guard on purpose: a line logged
        before the page is up, or after it has gone, is exactly the kind worth having.
        """
        self._write_log(msg)
        if self._window is None:
            return
        safe = msg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        self._window.evaluate_js(f'window.addLog && window.addLog("{safe}");')

    def _write_log(self, msg: str) -> None:
        """Append one timestamped line. Never raises: losing the log must not stop a run."""
        if self._app_root is None:
            return
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with _LOG_LOCK, open(
                os.path.join(self._app_root, LOG_NAME), "a", encoding="utf-8"
            ) as handle:
                handle.write(f"[{stamp}] {msg}\n")
        except OSError as exc:
            print(f"Failed to write the log: {exc}", file=sys.stderr)

    def _rotate_log(self) -> None:
        """Move the previous session's log aside. Called once, after `_app_root` resolves."""
        if self._app_root is None:
            return
        current = os.path.join(self._app_root, LOG_NAME)
        try:
            if os.path.exists(current):
                os.replace(current, os.path.join(self._app_root, LOG_PREV_NAME))
        except OSError as exc:
            print(f"Failed to rotate the log: {exc}", file=sys.stderr)

    # ---- Hotkey polling ----

    def _hotkey_loop(self) -> None:
        """Poll F1/F2 globally so Start/Stop work without clicking buttons."""
        if self._app_root is None:
            return
        keybinds = KeybindStore(self._app_root)
        start_kb = keybinds.get("start")
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
                # Skip only while the user is actively rebinding a key, so the
                # key being assigned doesn't also trigger its mapped action.
                if time.time() < self._capture_until:
                    time.sleep(HOTKEY_INTERVAL)
                    continue

                # Start key — rising edge
                start_down = kb_pressed(start_kb)
                if start_down and not self._key_down["start"]:
                    if self._ctrl and not self._ctrl.is_running:
                        # Start the macro from the task queue
                        error = self._ctrl.start()
                        if error:
                            self._log_to_ui(f"Can't start: {error}")
                        else:
                            self._run_thread = threading.Thread(target=self._macro_run_loop, daemon=True)
                            self._run_thread.start()
                            self._push_status()
                    elif self._ctrl and self._ctrl.is_running:
                        self._log_to_ui("Already running — use the stop key.")
                self._key_down["start"] = start_down

                # Pause key — rising edge (toggle)
                pause_kb = keybinds.get("pause")
                pause_down = kb_pressed(pause_kb)
                if pause_down and not self._key_down.get("pause", False):
                    if self._ctrl and self._ctrl.is_running:
                        if self._ctrl._paused:
                            self._ctrl.resume()
                            self._log_to_ui("Resumed.")
                        else:
                            self._ctrl.pause()
                            self._log_to_ui("Paused.")
                        self._push_status()
                self._key_down["pause"] = pause_down

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

                # Reload (F4) — restart the macro process
                reload_kb = keybinds.get("reload")
                reload_down = kb_pressed(reload_kb)
                if reload_down and not self._key_down.get("reload", False):
                    self._reload()
                self._key_down["reload"] = reload_down
            except Exception:
                pass
            time.sleep(HOTKEY_INTERVAL)

    # ---- Internal ----

    def _reload(self) -> None:
        """Reload: restart the entire macro process."""
        self._log_to_ui("Reloading...")
        self._running = False
        self._release_game()
        # Relaunch ourselves as a new process, then exit.
        import subprocess
        subprocess.Popen(
            [sys.executable, "-m", "sloppykeys"],
            cwd=self._app_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if self._window:
            self._window.destroy()

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
        user32.ShowWindow(game_hwnd, SW_SHOWNOACTIVATE)
        # `_booting` still counts as covered, though `_follow_loop` no longer docks while it
        # is set: a stray dock during boot must not raise the game over the loading screen.
        if self._game_visible and not self._booting:
            set_topmost(game_hwnd, True)
        else:
            # Covered, not hidden — see set_game_visible. Reasserted each tick
            # because the game can raise itself back up the normal band.
            set_topmost(game_hwnd, False)
            host = self._host_hwnd()
            if host:
                set_window_below(game_hwnd, host)
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
                # The boot window expiring has to *do* something: nothing is docked while
                # booting, and the dock below only fires when the host moved or we are
                # undocked, so without clearing the cached rect the game would never come
                # up over the slot for the rest of the session. `_dock` applies the
                # z-order itself, so there is nothing to re-assert here.
                if self._booting and time.monotonic() >= self._boot_until:
                    self._booting = False
                    self._last_rect = None

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

                # Booting: the loader is a fullscreen DOM overlay and the game paints over
                # all DOM content, so it must not be docked yet. Docking it here stripped
                # its frame and positioned it onto the slot behind the loading screen, and
                # `_dock`'s own ShowWindow raised it back over the page on every tick — the
                # loader flickering behind a Roblox rectangle. Only push it under our
                # window; the dock happens once the loader is gone.
                if self._booting:
                    set_topmost(self._game_hwnd, False)
                    set_window_below(self._game_hwnd, host)
                    time.sleep(FOLLOW_INTERVAL)
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


def resolve_app_root() -> str:
    """The folder holding `assets/`, `settings.json`, `routes.json`, `operations/`, `paths/`.

    **Frozen: the exe's own directory.** `build_exe.py` copies the editable data *next to*
    the exe, not into `_internal/`, because the app writes to all of it. Walking up from
    `__file__` lands in `_internal/` in a frozen build — one folder too deep — so every
    template lookup, every saved operation and the whole of `settings.json` would point at a
    tree the build never populates, and the shipped app would come up with no templates.

    From source, `__file__` is `<root>/sloppykeys/ui_web/bridge.py`, so three levels up is the
    repo root.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
        # WebView2 paints its host white until the first frame of the page, which read as a
        # white flash on launch and on every reload. Matching `--surface-sunken` makes that
        # gap indistinguishable from the loading screen that follows it.
        background_color="#0f0e13",
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
        api._app_root = resolve_app_root()
        # Before the first line is logged, so this session starts a clean file.
        api._rotate_log()
        api._write_log(f"SloppyKeys {api.get_version()} started.")
        api._ctrl = MacroController(
            api._app_root,
            log=api._log_to_ui,
            on_challenge_reads=api.push_challenge_reads,
        )
        # Before anything can read a box or a threshold: the tables hold defaults until
        # the stored values are pushed in.
        applied = api.apply_stored_overrides()
        if applied.get("regions") or applied.get("thresholds") or applied.get("points"):
            api._log_to_ui(
                f"Loaded {applied['regions']} OCR region override(s), "
                f"{applied['points']} click point(s) and "
                f"{applied['thresholds']} image threshold(s)."
            )

        window.evaluate_js(
            'document.getElementById("version-badge").textContent = '
            f'"v{api.get_version()}";'
        )
        # Signal JS that the backend is ready (app_root set, controller built).
        window.evaluate_js("window.onBackendReady && window.onBackendReady();")
        threading.Thread(target=api._follow_loop, daemon=True).start()
        threading.Thread(target=api._hotkey_loop, daemon=True).start()

        # The startup update check. Default on (`config/settings.py::AUTO_UPDATE_KEY`), on its
        # own worker, and silent unless there is something to say. Last in on_loaded so a
        # slow or unreachable GitHub cannot delay the window coming up.
        if UnifiedSettings(api._app_root).get("auto_update", True):
            api.check_for_update()

    def on_closing() -> None:
        # The X button is ours, but an OS-initiated close bypasses it.
        api._running = False
        api._release_game()

    window.events.loaded += on_loaded
    window.events.closing += on_closing
    webview.start(debug=("--debug" in sys.argv))


if __name__ == "__main__":
    main()
