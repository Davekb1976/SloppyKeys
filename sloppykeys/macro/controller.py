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
        """Camera setup."""
        from sloppykeys.macro.camera import camera_setup_script
        from sloppykeys.core.win32.display import refresh_hz_for_window

        hwnd = rbx.find_roblox_window()
        hz = refresh_hz_for_window(hwnd) if hwnd else 60
        script = camera_setup_script(hz)
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
        """Tick battle once through + loops until outcome detected.

        Uses wait_for_outcome which blocks and polls internally at 200ms.
        This is the simpler approach: just call it with the full timeout and
        let it handle keep-alive clicks and the win/loss detection loop.
        """
        self._log("  Waiting for match result...")
        outcome, msg = self._placer.wait_for_outcome()
        if outcome == OUTCOME_WON:
            self._stats.record_win()
            self._log(f"  Win! ({msg})")
        elif outcome == OUTCOME_LOST:
            self._stats.record_loss()
            self._log(f"  Loss. ({msg})")
        else:
            self._log(f"  Match ended: {msg}")

    def _execute_block(self, block: dict) -> None:
        """Run one block based on its type."""
        btype = block.get("type", "")
        params = block.get("params", {})

        if btype == "place_unit":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            hotkey = block.get("hotkey", "")
            if x and y and hotkey:
                from sloppykeys.macro.input_scripts import nudge_click_script, key_script
                # Press the unit hotkey, then click the position
                self._ahk.run(key_script(hotkey), wait=True, timeout=5.0)
                time.sleep(0.3)
                self._ahk.run(nudge_click_script(x, y), wait=True, timeout=5.0)

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
            # ponytail: replay a recorded walk path
            self._log(f"    [block] walk")

        elif btype == "detect":
            # ponytail: image detection with then/else branching
            self._log(f"    [block] detect (not yet implemented)")
