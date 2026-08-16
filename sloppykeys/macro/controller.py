"""Task-queue-driven macro controller.

Reads the task queue from settings.json, iterates tasks, loads operations,
navigates the lobby, and drives blocks phase by phase. No Qt dependency.

Usage (from the bridge):
    ctrl = MacroController(app_root, log=...)
    ctrl.start()           # begins on a worker thread
    ctrl.stop()            # cooperative stop
    ctrl.run_loop()        # blocks until done/stopped (call from thread)
"""

from __future__ import annotations

import os
import time
import threading
from typing import Callable

from sloppykeys.config.delays import DelaysStore
from sloppykeys.config.keybinds import GameKeyStore
from sloppykeys.config.nav_routes import RouteStore
from sloppykeys.config.operations import load_operation
from sloppykeys.config.settings import AppSettings
from sloppykeys.config.stats import StatsTracker
from sloppykeys.config.unified import UnifiedSettings
from sloppykeys.content.acts import act_coord
from sloppykeys.content.gamemodes import is_custom, selection_complete
from sloppykeys.content.start_stage import difficulty_coord
from sloppykeys.core.ahk import AhkBridge
from sloppykeys.core.image_search import ImageSearchEngine
from sloppykeys.core.win32 import roblox_window as rbx
from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.placement import UnitPlacer, OUTCOME_WON, OUTCOME_LOST

TICK_SLEEP = 0.05
STEP_TIMEOUT = 180.0
MATCH_POLL = 1.0
REOPEN_COOLDOWN = 60.0  # seconds between reopen attempts

RectProvider = Callable[[], tuple[int, int, int, int] | None]


class MacroController:
    """Drives the macro from the task queue without any Qt dependency."""

    def __init__(
        self,
        app_root: str,
        roblox_rect: RectProvider | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._app_root = app_root
        self._log = log or (lambda _m: None)
        self._rect = roblox_rect or self._default_rect

        self._settings = AppSettings(app_root)
        self._engine = ImageSearchEngine(app_root, log=self._log)
        self._ahk = AhkBridge()
        self._nav = LobbyNavigator(
            self._engine, self._ahk, self._rect, log=self._log,
            should_stop=lambda: self._stop_requested,
        )
        self._game_keys = GameKeyStore(app_root).all()
        self._placer = UnitPlacer(
            self._engine, self._ahk, self._rect,
            game_keys=lambda: self._game_keys,
            log=self._log,
            should_stop=lambda: self._stop_requested,
        )
        self._routes = RouteStore(app_root)
        self._delays = DelaysStore(app_root).all()
        self._stats = StatsTracker(app_root)
        self._nav.apply_delays(self._delays)
        self._placer.apply_delays(self._delays)

        self._stop_requested = False
        self._running = False
        self._paused = False
        self._current_task: dict | None = None
        self._cycle = 0
        self._last_reopen_time = 0.0

    @staticmethod
    def _default_rect() -> tuple[int, int, int, int] | None:
        hwnd = rbx.find_roblox_window()
        if hwnd is None:
            return None
        origin = rbx.client_to_screen(hwnd, 0, 0)
        size = rbx.client_size(hwnd)
        if origin is None or size is None:
            return None
        return (origin[0], origin[1], size[0], size[1])

    # -- Public API --

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def current_task(self) -> dict | None:
        return self._current_task

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def start(self) -> str | None:
        """Validate and begin. Returns error string or None."""
        if self._running:
            return "already running"
        tasks = UnifiedSettings(self._app_root).get_tasks()
        if not tasks:
            return "task queue is empty"
        self._stop_requested = False
        self._paused = False
        self._running = True
        self._cycle = 0
        self._log("Macro started — running the task queue.")
        return None

    def stop(self) -> None:
        self._stop_requested = True
        self._paused = False
        self._log("Stop requested.")

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def run_loop(self) -> tuple[bool, str]:
        """Block until finished or stopped. Call from a worker thread."""
        try:
            return self._run()
        finally:
            self._running = False
            self._current_task = None

    # -- Internal --

    def _checkpoint(self) -> bool:
        """True = bail out. Blocks while paused."""
        while self._paused and not self._stop_requested:
            time.sleep(0.15)
        return self._stop_requested

    def _try_reopen_roblox(self) -> bool:
        """If auto-reopen is enabled and Roblox isn't running, relaunch via deep link.

        Throttled to one attempt per REOPEN_COOLDOWN seconds. Returns True if
        Roblox is (or became) available, False if we couldn't recover.
        """
        hwnd = rbx.find_roblox_window()
        if hwnd is not None:
            return True

        unified = UnifiedSettings(self._app_root)
        if not unified.get("auto_reopen_roblox", True):
            return False

        now = time.time()
        if now - self._last_reopen_time < REOPEN_COOLDOWN:
            return False

        self._last_reopen_time = now
        link = unified.get("private_server_link", "")
        if not link or link == "empty":
            self._log("Roblox closed but no private server link — can't reopen.")
            return False

        self._log("Roblox closed mid-run. Relaunching via deep link...")
        import subprocess
        try:
            # Roblox deep links use the roblox:// protocol or the HTTPS share URL
            # which Windows handles via the default browser / Roblox launcher.
            import os as _os
            _os.startfile(link)
        except OSError as exc:
            self._log(f"Failed to launch Roblox: {exc}")
            return False

        # Wait for the window to appear (up to 60s)
        deadline = time.time() + 60.0
        while time.time() < deadline:
            if self._stop_requested:
                return False
            hwnd = rbx.find_roblox_window()
            if hwnd is not None:
                self._log("Roblox reopened successfully.")
                time.sleep(5.0)  # give it a moment to load
                return True
            time.sleep(2.0)

        self._log("Roblox didn't appear within 60s.")
        return False

    def _run(self) -> tuple[bool, str]:
        loop_pass = 0
        while not self._stop_requested:
            tasks = UnifiedSettings(self._app_root).get_tasks()
            if not tasks:
                self._log("Task queue is empty.")
                return (True, "queue empty")

            loop_pass += 1
            if loop_pass > 1:
                self._log(f"Queue finished — restarting (pass {loop_pass}).")

            for i, task in enumerate(tasks, 1):
                if self._checkpoint():
                    return (True, f"stopped after {self._cycle} cycles")
                self._current_task = task
                mode = task.get("mode", "")
                map_name = task.get("map", "")
                stage = task.get("stage", "")
                repeat = max(1, int(task.get("repeat", 1) or 1))
                macro_name = task.get("macro", "")

                self._log(f"Task {i}/{len(tasks)}: {mode} / {map_name} / {stage} × {repeat}")

                for rep in range(repeat):
                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")

                    # Auto-reopen Roblox if it crashed
                    if not self._try_reopen_roblox():
                        if self._stop_requested:
                            return (True, f"stopped after {self._cycle} cycles")
                        self._log("  Roblox unavailable — skipping task.")
                        break

                    # Navigate lobby
                    ok = self._navigate_lobby(mode, map_name, stage)
                    if not ok:
                        if self._stop_requested:
                            return (True, f"stopped after {self._cycle} cycles")
                        self._log(f"  Lobby navigation failed — skipping task.")
                        break

                    # Load and run the macro operation
                    if macro_name:
                        op = load_operation(self._app_root, macro_name)
                        phases = op.get("phases", {})
                    else:
                        phases = {}

                    # Pre Start
                    self._run_phase_linear(phases.get("pre_start", []))
                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")

                    # Start Game
                    self._placer.park()
                    ok, msg = self._nav.click_start_game()
                    if ok:
                        self._stats.start_stage()
                        self._log(f"  Start Game: {msg or 'ok'}")
                    else:
                        self._log(f"  Start Game failed: {msg}")

                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")

                    # Battle + Loops run concurrently until outcome
                    battle_blocks = phases.get("battle", [])
                    loop_a = phases.get("loop_a", [])
                    loop_b = phases.get("loop_b", [])
                    self._run_match(battle_blocks, loop_a, loop_b)

                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")

                    self._cycle += 1

                    # Click Repeat for next match
                    if rep < repeat - 1:
                        ok, msg = self._nav.click_repeat()
                        if not ok:
                            self._log(f"  Repeat: {msg} — falling through.")

        return (True, f"stopped after {self._cycle} cycles")

    def _navigate_lobby(self, mode: str, map_name: str, stage: str) -> bool:
        """Run the lobby chain for a task. Returns True on success."""
        # Check if already in match
        if self._nav.in_match():
            self._log("  Already in a match — skipping lobby.")
            self._run_camera()
            return True

        # Events use route navigation
        if is_custom(mode):
            return self._navigate_route(map_name, stage)

        # Standard lobby chain
        steps = [
            ("Play", lambda: self._nav.click_play()),
            (f"Open {mode}", lambda: self._nav.open_gamemode(mode)),
            (f"Select {map_name}", lambda: self._nav.select_stage(mode, map_name)),
        ]
        if stage and act_coord(mode, stage) is not None:
            steps.append((f"Select {stage}", lambda s=stage: self._nav.select_act(mode, s)))

        if difficulty_coord(mode) is not None:
            diff = self._settings.get_expedition_difficulty()
            steps.append((f"Difficulty {diff}", lambda: self._nav.set_difficulty(mode, diff)))

        hard = self._settings.get_hard_mode()
        steps.append(("Start stage", lambda: self._nav.start_stage(mode, hard)))
        steps.append(("Stage loaded", lambda: self._nav.wait_for_match_ready()))

        for name, action in steps:
            if self._checkpoint():
                return False
            ok, msg = action()
            self._log(f"  {name}: {msg or ('ok' if ok else 'failed')}")
            if not ok:
                return False
            time.sleep(self._nav.click_settle)

        self._run_camera()
        return True

    def _navigate_route(self, map_name: str, act: str) -> bool:
        """Events route navigation."""
        nav_steps = self._routes.steps(map_name, act)
        if not nav_steps:
            self._log(f"  No route for {map_name} / {act}")
            return False
        for ns in nav_steps:
            if self._checkpoint():
                return False
            ok, msg = self._nav.run_route_step(ns)
            self._log(f"  {ns.label or 'route step'}: {msg or ('ok' if ok else 'failed')}")
            if not ok:
                return False
        ok, msg = self._nav.wait_for_match_ready()
        self._log(f"  Stage loaded: {msg or ('ok' if ok else 'failed')}")
        if not ok:
            return False
        self._run_camera()
        return True

    def _run_camera(self) -> None:
        """Camera setup — zoom in, pitch down, zoom out."""
        from sloppykeys.macro.camera import camera_setup_script

        rect = self._rect()
        if rect is None:
            self._log("  Camera: skipped (no Roblox rect)")
            return

        # Centre of the viewport in screen coordinates
        vx, vy, vw, vh = rect
        center_x = vx + vw // 2
        center_y = vy + vh // 2

        script = camera_setup_script(center_x, center_y)
        ok, msg = self._ahk.run(script, wait=True, timeout=15.0)
        self._log(f"  Camera: {msg or ('ok' if ok else 'failed')}")

    def _run_phase_linear(self, blocks: list) -> None:
        """Run a list of blocks sequentially (Pre Start)."""
        for block in blocks:
            if self._checkpoint():
                return
            self._execute_block(block)
            time.sleep(TICK_SLEEP)

    def _run_match(self, battle: list, loop_a: list, loop_b: list) -> None:
        """Tick-based match execution: Battle runs once through, Loop A/B repeat
        continuously, all interleaved with outcome detection.

        Each tick: advance Battle by one block (if not exhausted), then Loop A by
        one, then Loop B by one, then poll for win/loss. This cooperative approach
        means Victory/Defeat detection runs between every block execution.
        """
        self._battle_started_at = time.time()
        self._battle_leave_requested = False

        # Flatten into indexable lists with per-loop state
        battle_idx = 0
        loop_a_idx = 0
        loop_b_idx = 0

        self._log("  Match started — running blocks...")

        while not self._stop_requested:
            if self._checkpoint():
                return

            # Check for leave-at-minute (scans all phases for a leave block)
            if self._battle_leave_requested:
                self._log("  Left match (Leave at Minute).")
                return

            # Advance Battle by one block (if not exhausted)
            if battle_idx < len(battle):
                block = battle[battle_idx]
                done = self._execute_battle_block(block)
                if done:
                    battle_idx += 1

            # Advance Loop A by one block (wraps around)
            if loop_a:
                block = loop_a[loop_a_idx]
                done = self._execute_battle_block(block)
                if done:
                    loop_a_idx = (loop_a_idx + 1) % len(loop_a)

            # Advance Loop B by one block (wraps around)
            if loop_b:
                block = loop_b[loop_b_idx]
                done = self._execute_battle_block(block)
                if done:
                    loop_b_idx = (loop_b_idx + 1) % len(loop_b)

            # Poll for outcome (win/loss)
            outcome = self._check_outcome()
            if outcome is not None:
                result, msg = outcome
                if result == OUTCOME_WON:
                    self._stats.record_win()
                    self._log(f"  Win! ({msg})")
                    self._send_webhook_result("win")
                elif result == OUTCOME_LOST:
                    self._stats.record_loss()
                    self._log(f"  Loss. ({msg})")
                    self._send_webhook_result("loss")
                else:
                    self._log(f"  Match ended: {msg}")
                return

            time.sleep(TICK_SLEEP)

    def _check_outcome(self) -> tuple[str, str] | None:
        """Non-blocking check for win/loss. Returns (outcome, msg) or None."""
        from sloppykeys.core.image_search import ImageProfile
        rect = self._rect()
        if rect is None:
            return None

        win_path = os.path.join(self._app_root, "assets", "match", "game_won.png")
        loss_path = os.path.join(self._app_root, "assets", "match", "game_lost.png")

        profiles = []
        if os.path.isfile(win_path):
            profiles.append(ImageProfile(name="win", image_path=win_path, confidence=0.70))
        if os.path.isfile(loss_path):
            profiles.append(ImageProfile(name="loss", image_path=loss_path, confidence=0.70))

        if not profiles:
            return None

        match = self._engine.find_first(profiles, rect)
        if match is None:
            return None

        if match.profile_name == "win":
            return (OUTCOME_WON, f"matched at {match.score:.2f}")
        else:
            return (OUTCOME_LOST, f"matched at {match.score:.2f}")

    def _execute_battle_block(self, block: dict) -> bool:
        """Execute one block in a tick-based context. Returns True when done
        (move to next block), False to retry this block next tick."""
        btype = block.get("type", "")
        params = block.get("params", {})

        if btype == "upgrade_unit":
            return self._tick_upgrade_unit(block)
        elif btype == "sell_unit":
            return self._tick_sell_unit(block)
        elif btype == "target_priority":
            return self._tick_target_priority(block)
        elif btype == "wait_wave":
            return self._tick_wait_wave(block)
        elif btype == "leave_at_minute":
            return self._tick_leave_at_minute(block)
        else:
            # All other blocks are one-shot (execute and move on)
            self._execute_block(block)
            return True

    def _unit_click_position(self, block: dict) -> tuple[int, int] | None:
        """Resolve a unit block's click position from its index.

        Unit index refers to the Nth place_unit block across all phases. We look
        up the stored position from the operation's pre_start phase. If not found,
        use params.x/y as fallback.
        """
        params = block.get("params", {})
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        if x and y:
            return (x, y)
        # ponytail: index-based lookup from placed units would go here once
        # we track placed positions during pre_start execution.
        return None

    def _game_keybind(self, action: str) -> str:
        """Get the in-game keybind for an action (upgrade, sell, priority, autograde)."""
        unified = UnifiedSettings(self._app_root)
        gk = unified.get("game_keybinds", {})
        defaults = {"upgrade": "t", "sell": "x", "priority": "r", "autograde": "v"}
        return gk.get(action, defaults.get(action, ""))

    def _tick_upgrade_unit(self, block: dict) -> bool:
        """Click the unit, press upgrade key. Repeats up to `times`. If autograde is on, press autograde key after."""
        params = block.get("params", {})
        times = max(1, int(params.get("times", 1) or 1))
        autograde = block.get("autograde", False)

        if not hasattr(self, '_upgrade_state'):
            self._upgrade_state = {}
        state = self._upgrade_state.setdefault(id(block), {"remaining": times})

        pos = self._unit_click_position(block)
        if pos is None:
            self._log("    [block] upgrade: no unit position — skipping")
            return True

        from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        self._ahk.run(key_script(self._game_keybind("upgrade")), wait=True, timeout=3.0)
        time.sleep(0.3)

        state["remaining"] -= 1
        if state["remaining"] <= 0:
            if autograde:
                time.sleep(0.2)
                self._ahk.run(key_script(self._game_keybind("autograde")), wait=True, timeout=3.0)
            del self._upgrade_state[id(block)]
            return True
        return False

    def _tick_sell_unit(self, block: dict) -> bool:
        """Click the unit, press sell key. One-shot."""
        pos = self._unit_click_position(block)
        if pos is None:
            self._log("    [block] sell: no unit position — skipping")
            return True

        from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        self._ahk.run(key_script(self._game_keybind("sell")), wait=True, timeout=3.0)
        return True

    def _tick_target_priority(self, block: dict) -> bool:
        """Click the unit, press priority key. One-shot."""
        pos = self._unit_click_position(block)
        if pos is None:
            self._log("    [block] target priority: no unit position — skipping")
            return True

        from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        self._ahk.run(key_script(self._game_keybind("priority")), wait=True, timeout=3.0)
        time.sleep(0.2)
        return True

    def _tick_wait_wave(self, block: dict) -> bool:
        """Wait until the wave counter reaches the target. Polls OCR every 2s."""
        params = block.get("params", {})
        target = max(1, int(params.get("wave", 1) or 1))

        # Throttle: only check every 2 seconds
        if not hasattr(self, '_wave_check_time'):
            self._wave_check_time = 0.0
        now = time.time()
        if now < self._wave_check_time:
            return False  # not time to check yet

        self._wave_check_time = now + 2.0

        # Try to read the wave number via OCR
        try:
            from sloppykeys.core.ocr import OcrReader
            import mss
            import numpy as np

            rect = self._rect()
            if rect is None:
                return False
            # Wave HUD is in the top-center area of the viewport
            # Approximate region: x=420..580, y=15..55 in 1152x756 space
            vx, vy, vw, vh = rect
            wave_x = vx + int(420 * vw / 1152)
            wave_y = vy + int(15 * vh / 756)
            wave_w = int(160 * vw / 1152)
            wave_h = int(40 * vh / 756)

            with mss.mss() as sct:
                mon = {"left": wave_x, "top": wave_y, "width": wave_w, "height": wave_h}
                img = np.array(sct.grab(mon))[:, :, :3]

            ocr = OcrReader()
            text = ocr.read_text(img)
            # Parse "Wave X/Y" or just a number
            import re
            numbers = re.findall(r"\d+", text)
            if numbers:
                current = int(numbers[0])
                if current >= target:
                    self._log(f"    [block] wave {current} reached target {target}")
                    return True
        except Exception:
            pass  # OCR failed, retry next tick

        return False

    def _tick_leave_at_minute(self, block: dict) -> bool:
        """Check if elapsed stage time exceeds the threshold. If so, leave."""
        params = block.get("params", {})
        minutes = max(0, float(params.get("minutes", 10) or 10))

        started = getattr(self, '_battle_started_at', None) or time.time()
        elapsed_min = (time.time() - started) / 60.0

        if elapsed_min < minutes:
            return True  # not time yet, but this block is "done" for this tick — passive check

        # Time to leave
        self._log(f"    [block] leave at minute {minutes:.1f} — elapsed {elapsed_min:.1f}min, leaving")
        self._battle_leave_requested = True
        # Try to click the leave button
        from sloppykeys.macro.input_scripts import nudge_click_script
        # Look for the "to lobby" or "return" button — simple approach: press Esc or use a known position
        # ponytail: for now just set the flag; the lobby navigator handles the actual leave
        return True

    def _send_webhook_result(self, result: str) -> None:
        """Send a Discord webhook notification for a match result with screenshot."""
        unified = UnifiedSettings(self._app_root)
        webhook_url = unified.get("discord_webhook", "")
        if not webhook_url:
            return

        from sloppykeys.core.webhook import DiscordWebhook, COLOR_WIN, COLOR_LOSS

        hook = DiscordWebhook(
            url_provider=lambda: webhook_url,
            log=self._log,
        )
        if not hook.enabled:
            return

        task = self._current_task or {}
        mode = task.get("mode", "—")
        map_name = task.get("map", "—")
        stage = task.get("stage", "—")
        wins = self._stats.wins
        losses = self._stats.losses
        total = wins + losses
        rate = f"{round(wins * 100 / total)}%" if total > 0 else "—"

        title = "Stage Won" if result == "win" else "Stage Lost"
        color = COLOR_WIN if result == "win" else COLOR_LOSS
        fields = [
            ("Stage", f"{mode} / {map_name} / {stage}"),
            ("Cycle", str(self._cycle + 1)),
            ("Session", f"{wins}W – {losses}L ({rate})"),
        ]

        # Capture a screenshot of the result screen
        screenshot = self._capture_screenshot()

        hook.send(
            title=title,
            fields=fields,
            color=color,
            image_png=screenshot,
        )

    def _execute_block(self, block: dict) -> None:
        """Run one block based on its type."""
        btype = block.get("type", "")
        params = block.get("params", {})

        if btype == "place_unit":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            hotkey = block.get("hotkey", "")
            if x and y:
                from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
                # Press the unit slot hotkey to select it, then click the position
                if hotkey:
                    self._ahk.run(key_script(hotkey), wait=True, timeout=5.0)
                    time.sleep(0.3)
                self._ahk.run(nudge_click_script(x, y, spread=SPREAD_TIGHT), wait=True, timeout=5.0)

        elif btype == "upgrade_unit":
            idx = int(params.get("index", 1))
            # ponytail: upgrade logic will be fleshed out with the full block executor
            self._log(f"    [block] upgrade unit #{idx}")

        elif btype == "sell_unit":
            idx = int(params.get("index", 1))
            self._log(f"    [block] sell unit #{idx}")

        elif btype == "target_priority":
            idx = int(params.get("index", 1))
            self._log(f"    [block] target priority #{idx}")

        elif btype == "wait_ms":
            ms = max(0, int(params.get("ms", 500)))
            time.sleep(ms / 1000.0)

        elif btype == "wait_wave":
            wave = int(params.get("wave", 1))
            # ponytail: wave OCR gate — one look per tick, not implemented yet
            self._log(f"    [block] wait for wave {wave}")

        elif btype == "leave_at_minute":
            minutes = int(params.get("minutes", 10))
            # ponytail: checked per tick against stage clock
            self._log(f"    [block] leave at minute {minutes}")

        elif btype == "click":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            if x and y:
                from sloppykeys.macro.input_scripts import nudge_click_script
                self._ahk.run(nudge_click_script(x, y), wait=True, timeout=5.0)

        elif btype == "send_key":
            key = block.get("key", "")
            hold_ms = int(params.get("hold_ms", 0))
            if key:
                from sloppykeys.macro.input_scripts import key_script
                self._ahk.run(key_script(key, hold_ms=hold_ms), wait=True, timeout=5.0)

        elif btype == "walk":
            # Replay a recorded walk path
            path_name = block.get("pathName", "")
            if path_name:
                from sloppykeys.macro.recording import replay_walk_script
                script = replay_walk_script(self._app_root, path_name)
                if script:
                    self._ahk.run(script, wait=True, timeout=30.0)
                else:
                    self._log(f"    [block] walk path '{path_name}' not found or empty")
            else:
                self._log(f"    [block] walk (no path name set)")

        elif btype == "record":
            # Replay a recorded input sequence (mouse+keyboard via SendInput)
            rec_name = block.get("recordingName", "")
            if rec_name:
                from sloppykeys.macro.recording import load_recording, replay_recording
                data = load_recording(self._app_root, rec_name)
                events = data.get("events", [])
                if events:
                    self._log(f"    [block] replaying recording '{rec_name}' ({len(events)} events)")
                    stop = threading.Event()
                    # Wire stop_requested to the event
                    def _check_stop():
                        while not self._stop_requested and not stop.is_set():
                            time.sleep(0.1)
                        stop.set()
                    checker = threading.Thread(target=_check_stop, daemon=True)
                    checker.start()
                    hwnd = rbx.find_roblox_window()
                    replay_recording(events, hwnd=hwnd, stop_event=stop)
                    stop.set()  # signal checker to exit
                else:
                    self._log(f"    [block] recording '{rec_name}' has no events")
            else:
                self._log(f"    [block] record (no recording name set)")

        elif btype == "detect":
            # Image detection with then/else branching
            image_name = block.get("image", "")
            threshold = float(block.get("threshold", 0.8))
            loop = block.get("loop", False)
            loop_attempts = int(block.get("loopAttempts", 5))
            then_blocks = block.get("then", [])
            else_blocks = block.get("else", [])

            if not image_name:
                self._log("    [block] detect: no image specified")
                return

            from sloppykeys.core.image_search import ImageProfile

            # Resolve the image path: check assets/ subfolders
            image_path = image_name
            if not os.path.isabs(image_path):
                # Try common locations
                for subdir in ("assets/match", "assets/lobby", "assets/detect", "assets"):
                    candidate = os.path.join(self._app_root, subdir, image_name)
                    if not candidate.endswith(".png"):
                        candidate += ".png"
                    if os.path.isfile(candidate):
                        image_path = candidate
                        break

            profile = ImageProfile(
                name=image_name,
                image_path=image_path,
                confidence=threshold,
            )

            found = False
            attempts = loop_attempts if loop else 1
            for attempt in range(attempts):
                if self._checkpoint():
                    return
                rect = self._rect()
                if rect is None:
                    time.sleep(0.5)
                    continue
                match = self._engine.find_first([profile], rect)
                if match is not None:
                    found = True
                    break
                if loop and attempt < attempts - 1:
                    time.sleep(0.5)

            if found:
                for tb in then_blocks:
                    if self._checkpoint():
                        return
                    self._execute_block(tb)
                    time.sleep(TICK_SLEEP)
            else:
                for eb in else_blocks:
                    if self._checkpoint():
                        return
                    self._execute_block(eb)
                    time.sleep(TICK_SLEEP)

    def _capture_screenshot(self) -> bytes | None:
        """Capture the current Roblox screen as PNG bytes for webhook attachment."""
        try:
            import mss
            import cv2
            import numpy as np
        except ImportError:
            return None

        rect = self._rect()
        if rect is None:
            return None

        x, y, w, h = rect
        monitor = {"left": x, "top": y, "width": w, "height": h}
        try:
            with mss.mss() as sct:
                img = np.array(sct.grab(monitor))
            bgr = img[:, :, :3]
            ok, buf = cv2.imencode(".png", bgr)
            if ok:
                return buf.tobytes()
        except Exception:
            pass
        return None
