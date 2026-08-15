"""Headless macro controller: owns the runner and its dependencies.

Extracted from ui/window.py so the pywebview bridge can start/stop macro runs
without pulling in PySide6. The PySide6 window still works independently — it
builds its own MacroRunner. This controller is the new UI's equivalent.

Usage:
    ctrl = MacroController(app_root, roblox_rect=..., log=...)
    ctrl.start(target, plan)
    # ... on another thread:
    ctrl.run_loop()  # blocks until finished/stopped
    ctrl.stop()
"""

from __future__ import annotations

import time
from typing import Callable

from sloppykeys.config.delays import DelaysStore
from sloppykeys.config.keybinds import GameKeyStore
from sloppykeys.config.nav_routes import RouteStore
from sloppykeys.config.settings import AppSettings
from sloppykeys.config.start_position import StartPositionStore
from sloppykeys.config.stats import StatsTracker
from sloppykeys.content.acts import act_coord
from sloppykeys.content.gamemodes import CHALLENGE, is_custom, selection_complete
from sloppykeys.content.start_stage import difficulty_coord
from sloppykeys.content.units import UnitPlan
from sloppykeys.core.ahk import AhkBridge
from sloppykeys.core.image_search import ImageSearchEngine
from sloppykeys.core.win32 import roblox_window as rbx
from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.placement import UnitPlacer, split_steps
from sloppykeys.macro.runner import MacroRunner, MacroStep, MacroTarget, Phase, StepResult

RUN_TICK_SLEEP = 0.05
RUN_STEP_TIMEOUT = 180.0

ENTRY_LOBBY = "lobby"
ENTRY_MODE_PANEL = "mode_panel"

RectProvider = Callable[[], tuple[int, int, int, int] | None]


class MacroController:
    """Drives the macro runner without any Qt dependency."""

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
        self._runner = MacroRunner(log=self._log)
        self._nav = LobbyNavigator(
            self._engine,
            self._ahk,
            self._rect,
            log=self._log,
            should_stop=lambda: self._runner.stop_requested,
        )
        self._game_keys = GameKeyStore(app_root).all()
        self._placer = UnitPlacer(
            self._engine,
            self._ahk,
            self._rect,
            game_keys=lambda: self._game_keys,
            log=self._log,
            should_stop=lambda: self._runner.stop_requested,
        )
        self._routes = RouteStore(app_root)
        self._delays = DelaysStore(app_root).all()
        self._position_store = StartPositionStore(app_root)
        self._stats = StatsTracker(app_root)
        self._nav.apply_delays(self._delays)
        self._placer.apply_delays(self._delays)

        self._entry_screen = ENTRY_LOBBY

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
        return self._runner.is_running

    @property
    def cycle(self) -> int:
        return self._runner.cycle

    @property
    def phase(self) -> Phase:
        return self._runner.phase

    @property
    def target(self) -> MacroTarget:
        return self._runner.target

    @property
    def stop_requested(self) -> bool:
        return self._runner.stop_requested

    def start(self, target: MacroTarget, plan: UnitPlan) -> str | None:
        """Build the step chain and start the runner. Returns an error, or None."""
        if self._runner.is_running:
            return "already running"
        if not selection_complete(target.gamemode, target.map_name, target.target):
            return "incomplete selection"
        if not plan.enabled_steps():
            return "no enabled unit steps"

        steps, error = self._build_run_steps(target)
        if error:
            return error

        loop_from = len(steps)
        steps += self._build_match_steps(plan)

        # Activate the game window
        hwnd = rbx.find_roblox_window()
        if hwnd:
            rbx.activate_window(hwnd)

        self._runner.start(target, steps, loop_from=loop_from)
        self._log(
            f"Started on {target.label()} — "
            f"{loop_from} lobby steps, {len(steps) - loop_from} repeating."
        )
        return None

    def stop(self) -> None:
        """Request a cooperative stop. The run loop ends between steps."""
        if self._runner.is_running:
            self._runner.request_stop()
            self._log("Stop requested; finishing the current step first.")

    def run_loop(self) -> tuple[bool, str]:
        """Block until the runner finishes or is stopped. Call from a worker thread."""
        while self._runner.is_running and self._runner.phase is not Phase.FINISHED:
            if self._runner.stop_requested:
                cycles = self._runner.cycle
                self._runner.stop()
                return (True, f"stopped after {cycles} cycles")
            self._runner.tick()
            time.sleep(RUN_TICK_SLEEP)

        cycles = self._runner.cycle
        finished = self._runner.phase is Phase.FINISHED
        self._runner.stop()
        if finished:
            return (True, f"complete after {cycles} cycles")
        return (False, "a step failed")

    # -- Step builders --

    def _nav_step(self, name: str, call, settle: bool = True, timeout: float | None = None) -> MacroStep:
        def action() -> StepResult:
            ok, message = call()
            self._log(f"  {name}: {message or ('ok' if ok else 'failed')}")
            if not ok:
                return StepResult.FAILED
            if settle:
                time.sleep(self._nav.click_settle)
            return StepResult.DONE

        budget = RUN_STEP_TIMEOUT if timeout is None else max(RUN_STEP_TIMEOUT, timeout)
        return MacroStep(name=name, action=action, timeout_seconds=budget)

    def _placement_step(self, step: UnitStep) -> MacroStep:
        def action() -> StepResult:
            ok = self._placer.execute_step(step)
            return StepResult.DONE if ok else StepResult.FAILED

        return MacroStep(
            name=f"Place {step.name or 'unit'}",
            action=action,
            timeout_seconds=RUN_STEP_TIMEOUT,
        )

    def _build_run_steps(self, target: MacroTarget) -> tuple[list[MacroStep], str]:
        """Lobby chain through to a loaded stage with the camera set."""
        gamemode = target.gamemode
        stage = target.map_name
        act = target.target

        entry: list[MacroStep] = []
        if self._entry_screen == ENTRY_MODE_PANEL:
            entry.append(
                self._nav_step("Change gamemode", self._nav.change_gamemode, settle=False)
            )

        camera_step = self._nav_step(
            "Set camera", lambda: self._camera_setup(), settle=False
        )
        after_camera = [camera_step] + self._position_steps(target)

        if self._nav.in_match():
            self._log("Already in a match — skipping lobby, starting at camera.")
            return (after_camera, "")

        if is_custom(gamemode):
            route, error = self._route_steps(stage, act)
            if error:
                return ([], error)
            route.append(
                self._nav_step("Stage loaded", self._nav.wait_for_match_ready, settle=False)
            )
            return (route + after_camera, "")

        steps = entry + [
            self._nav_step("Play", self._nav.click_play, settle=False),
            self._nav_step(
                f"Open {gamemode}", lambda: self._nav.open_gamemode(gamemode), settle=False
            ),
            self._nav_step(f"Select {stage}", lambda: self._nav.select_stage(gamemode, stage)),
        ]

        if act:
            if act_coord(gamemode, act) is None:
                return ([], f"no act coordinates for {gamemode} / {act}")
            steps.append(self._nav_step(f"Select {act}", lambda: self._nav.select_act(gamemode, act)))

        if difficulty_coord(gamemode) is not None:
            difficulty = self._settings.get_expedition_difficulty()
            steps.append(
                self._nav_step(f"Difficulty {difficulty}", lambda: self._nav.set_difficulty(gamemode, difficulty))
            )

        hard_mode = self._settings.get_hard_mode()
        steps += [
            self._nav_step(
                "Start stage", lambda: self._nav.start_stage(gamemode, hard_mode), settle=False
            ),
            self._nav_step("Stage loaded", self._nav.wait_for_match_ready, settle=False),
        ]
        return (steps + after_camera, "")

    def _build_match_steps(self, plan: UnitPlan) -> list[MacroStep]:
        """The repeating cycle: place units, start game, wait for outcome."""
        pre, during = split_steps(plan.enabled_steps())

        steps = [self._placement_step(step) for step in pre]
        steps.append(self._nav_step("Start Game", self._start_game, settle=False))
        steps += [self._placement_step(step) for step in during]
        steps.append(self._outcome_step())
        steps.append(self._repeat_step())
        return steps

    def _start_game(self) -> tuple[bool, str]:
        self._placer.park()
        ok, message = self._nav.click_start_game()
        if ok:
            self._stats.start_stage()
        return (ok, message)

    def _outcome_step(self) -> MacroStep:
        def action() -> StepResult:
            result = self._placer.wait_for_outcome()
            if result == OUTCOME_WON:
                self._stats.record_win()
                self._log("  Win!")
            elif result == OUTCOME_LOST:
                self._stats.record_loss()
                self._log("  Loss.")
            else:
                self._log("  Outcome unknown (timeout or stop).")
            return StepResult.DONE

        return MacroStep(name="Wait for outcome", action=action, timeout_seconds=self._placer.won_timeout + 10)

    def _repeat_step(self) -> MacroStep:
        def action() -> StepResult:
            ok, msg = self._nav.click_repeat()
            if not ok:
                self._log(f"  Repeat: {msg} — falling through to Start Game.")
            return StepResult.DONE

        return MacroStep(name="Repeat", action=action, timeout_seconds=30, optional=True)

    def _camera_setup(self) -> tuple[bool, str]:
        from sloppykeys.macro.camera import camera_setup_script
        from sloppykeys.core.win32.display import refresh_hz_for_window

        hwnd = rbx.find_roblox_window()
        hz = refresh_hz_for_window(hwnd) if hwnd else 60
        script = camera_setup_script(hz)
        ok, msg = self._ahk.run(script, wait=True, timeout=15.0)
        return (ok, msg)

    def _position_steps(self, target: MacroTarget) -> list[MacroStep]:
        """Walk presets for targets that need the character moved from spawn."""
        from sloppykeys.content.start_position import walk_for

        walk = walk_for(target.gamemode, target.map_name, target.target)
        if not walk:
            return []
        from sloppykeys.macro.input_scripts import walk_script
        from sloppykeys.content.start_position import total_hold_ms

        def do_walk() -> tuple[bool, str]:
            script = walk_script(walk)
            hold = total_hold_ms(walk)
            timeout = (hold / 1000.0) + 5.0
            return self._ahk.run(script, wait=True, timeout=timeout)

        return [self._nav_step("Walk to position", do_walk, settle=False)]

    def _route_steps(self, stage: str, act: str) -> tuple[list[MacroStep], str]:
        """Events route steps from routes.json."""
        route = self._routes.steps_for(stage, act)
        if not route:
            return ([], f"no route for {stage} / {act}")

        steps: list[MacroStep] = []
        for rs in route:
            steps.append(self._nav_step(
                rs.get("Name", "route step"),
                lambda bound=rs: self._nav.execute_route_step(bound),
                settle=False,
                timeout=float(rs.get("Timeout", RUN_STEP_TIMEOUT)),
            ))
        return (steps, "")
