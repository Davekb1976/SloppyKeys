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
from datetime import datetime
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
from sloppykeys.content.start_stage import (
    difficulty_coord,
    difficulty_from_task,
    hard_mode_from_task,
)
from sloppykeys.content.nav_images import (
    autoplay_active_image,
    autoplay_image,
    exp_continue_2_image,
    exp_continue_image,
    exp_extract_confirm_image,
    exp_extract_image,
    exp_upgrade_card_image,
    portal_select_image,
    start_game_image,
)
from sloppykeys.content.walk_paths import default_walk_path
from sloppykeys.core.ahk import AhkBridge
from sloppykeys.core.image_search import ImageSearchEngine
from sloppykeys.core.win32 import roblox_window as rbx
from sloppykeys.macro.expedition import (
    ACCEPT_EXTRACT,
    CARD,
    CARD_DISMISS_CLICK,
    CHECK_INTERVAL,
    CONTINUE,
    CONTINUE_WAVE,
    DECLINE_EXTRACT,
    DISMISS_CARD,
    EXTRACT,
    FOLLOWUP_TIMEOUT,
    NOTHING,
    START_GAME,
    START_WAVE,
    ExpeditionMatch,
    extract_after_from_task,
)
from sloppykeys.macro.challenge import ChallengeTracker
from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.placement import UnitPlacer, OUTCOME_WON, OUTCOME_LOST

TICK_SLEEP = 0.05
REOPEN_COOLDOWN = 60.0  # seconds between reopen attempts

# How many times the `autoplay` block will click before it gives up and lets the match play
# on. A bound rather than a retry-forever: the block's own verification is what makes it
# useful, and a toggle that never reads as active is a template problem no amount of clicking
# fixes — meanwhile every tick spent here is a tick not spent on the outcome poll.
AUTOPLAY_CLICKS = 3
# Gap between a click and the look that checks it. The toggle animates, and two searches is
# ~34ms against a 50ms tick, so looking every tick would burn the budget re-asking a question
# the game has not had time to answer.
AUTOPLAY_RECHECK = 1.0

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
        # What the run remembers about the challenge panel between matches: which rotation it
        # last looked in, which rows it has played, and when those marks expire. One per
        # controller, because the memory has to outlive a single match — a per-match tracker
        # would forget every mark and send the run back to the panel after each one.
        self._challenges = ChallengeTracker()
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
        self._send_webhook_started()
        return None

    def stop(self) -> None:
        self._stop_requested = True
        self._paused = False
        self._log("Stop requested.")

    def pause(self) -> None:
        # Guarded so a second Pause doesn't post a second notification.
        if self._paused:
            return
        self._paused = True
        self._send_webhook_paused(True)

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self._send_webhook_paused(False)

    def run_loop(self) -> tuple[bool, str]:
        """Block until finished or stopped. Call from a worker thread."""
        # Pre-set so the `finally` still reports something if `_run` raises: an unhandled
        # exception is exactly the ending nobody is watching for.
        reason = "stopped unexpectedly"
        try:
            ok, reason = self._run()
            return (ok, reason)
        finally:
            self._running = False
            self._current_task = None
            self._send_webhook_ended(reason)

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

        # Through the parser, not raw. `parse_private_server_link` turns a share URL into the
        # `roblox://` deep link that starts the client; handing the stored URL to the shell
        # opens a browser tab with a Join button instead, so the reopen never completed on
        # its own and the 60s wait below always timed out. The parser existed for this and
        # had no caller.
        from sloppykeys.config.settings import parse_private_server_link

        uri, error = parse_private_server_link(link)
        if error or not uri:
            self._log(f"Can't reopen Roblox: {error or 'the private server link is unusable'}")
            return False

        self._log("Roblox closed mid-run. Relaunching via deep link...")
        try:
            import os as _os
            _os.startfile(uri)
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

                # Challenge mode has its own flow. Reaching it in the queue is not what makes
                # it run — `_challenge_wants_in` does, below — so its own turn is just another
                # opportunity, and it does nothing when the rotation is already spent.
                if mode == "Challenge":
                    if self._challenge_wants_in(task):
                        self._run_challenge_task(task)
                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")
                    continue

                for rep in range(repeat):
                    if self._checkpoint():
                        return (True, f"stopped after {self._cycle} cycles")

                    # **Before every match, not at the queue position.** A rotation lasts 30
                    # minutes; a task with a high repeat count can hold the queue for hours,
                    # so a challenge that waited its turn would miss rotation after rotation.
                    # This is the check that answers "the maps re-rolled mid-match" — it runs
                    # once the match that was in flight has finished, never interrupting one.
                    challenge = self._challenge_task(tasks)
                    if challenge is not None and self._challenge_wants_in(challenge):
                        self._log("  Challenge available — taking it before this match.")
                        self._run_challenge_task(challenge)
                        if self._checkpoint():
                            return (True, f"stopped after {self._cycle} cycles")

                    # Auto-reopen Roblox if it crashed
                    if not self._try_reopen_roblox():
                        if self._stop_requested:
                            return (True, f"stopped after {self._cycle} cycles")
                        self._log(
                            f"  Roblox unavailable — skipping task {i}: {mode} / {map_name}."
                        )
                        break

                    # Navigate lobby
                    ok = self._navigate_lobby(mode, map_name, stage)
                    if not ok:
                        if self._stop_requested:
                            return (True, f"stopped after {self._cycle} cycles")
                        # Named, because a skipped task is otherwise indistinguishable from
                        # the queue repeating: the pass just moves on and the *next* pass
                        # plays the earlier task again, which reads as "it did that map
                        # twice" rather than "this one never started".
                        self._log(
                            f"  Lobby navigation failed — skipping task {i}: "
                            f"{mode} / {map_name} / {stage}."
                        )
                        break

                    # Load and run the macro operation
                    if macro_name:
                        op = load_operation(self._app_root, macro_name)
                        phases = op.get("phases", {})
                    else:
                        phases = {}
                    self._phases = phases

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

                    if mode == "Portals":
                        self._portals_after_match(task, again=rep < repeat - 1)
                    elif mode == "Expedition":
                        # Expedition's result screen has no Repeat. Leave through Back to
                        # Lobby and its confirmation, which lands in the lobby proper, so the
                        # next rep (or the next task) navigates in from Play like a fresh run
                        # instead of the finished-match handover. Done after the last rep too:
                        # the queue must not hand the next task a stage still on screen.
                        ok, msg = self._nav.back_to_lobby()
                        self._log(f"  Back to lobby: {msg}")
                    elif rep < repeat - 1:
                        # Click Repeat for next match
                        ok, msg = self._nav.click_repeat()
                        if not ok:
                            self._log(f"  Repeat: {msg} — falling through.")

        return (True, f"stopped after {self._cycle} cycles")

    def _navigate_lobby(self, mode: str, map_name: str, stage: str) -> bool:
        """Run the lobby chain for a task. Returns True on success."""
        # Check if already in match
        if self._nav.in_match():
            self._log("  Already in a match — skipping lobby.")
            self.run_camera()
            return True

        # Standing on a finished match — a loss, or a win whose Repeat was not taken. Every
        # chain below opens with a click that does not exist on that screen, so leave it
        # first: Match Play → the post-match panel → Change gamemode → the gamemode chooser.
        # That chooser *is* where the cards are, so the lobby's Play is skipped rather than
        # searched for on a screen it is not on. One look to decide, so being in the lobby
        # costs ~17ms and no click.
        from_gamemode_panel = False
        if self._nav.result_screen_up():
            ok, msg = self._nav.leave_match()
            self._log(f"  Leave match: {msg}")
            if not ok:
                return False
            time.sleep(self._nav.click_settle)
            # Not for Events: its route is the user's own recording and starts from the
            # lobby's Events button, so opening the gamemode chooser would land it on the
            # wrong screen.
            if not is_custom(mode):
                ok, msg = self._nav.change_gamemode()
                self._log(f"  Change gamemode: {msg}")
                if not ok:
                    return False
                from_gamemode_panel = True
                time.sleep(self._nav.click_settle)

        # Events use route navigation
        if is_custom(mode):
            return self._navigate_route(map_name, stage)

        # Standard lobby chain
        steps = []
        if not from_gamemode_panel:
            steps.append(("Play", lambda: self._nav.click_play()))
        steps += [
            (f"Open {mode}", lambda: self._nav.open_gamemode(mode)),
            (f"Select {map_name}", lambda: self._nav.select_stage(mode, map_name)),
        ]
        if stage and act_coord(mode, stage) is not None:
            steps.append((f"Select {stage}", lambda s=stage: self._nav.select_act(mode, s)))

        # One field, two controls: a mode with the cycling button gets 1-3 clicks on the way
        # in, and every other mode reads it as Story's Easy/Hard pair, which `start_stage`
        # applies. Per task rather than global for both — two Expedition tasks in one queue
        # can want different difficulties, and the queue is where the rest of the run is
        # chosen. Settings' Hard Mode is the default for a task that never said.
        asked = (self._current_task or {}).get("difficulty")
        hard = False
        if difficulty_coord(mode) is not None:
            diff = difficulty_from_task(asked)
            steps.append((f"Difficulty {diff}", lambda: self._nav.set_difficulty(mode, diff)))
        else:
            hard = hard_mode_from_task(asked, self._settings.get_hard_mode())

        steps.append((f"Start stage{' (hard)' if hard else ''}", lambda: self._nav.start_stage(mode, hard)))
        steps.append(("Stage loaded", lambda: self._nav.wait_for_match_ready()))

        for name, action in steps:
            if self._checkpoint():
                return False
            ok, msg = action()
            self._log(f"  {name}: {msg or ('ok' if ok else 'failed')}")
            if not ok:
                return False
            time.sleep(self._nav.click_settle)

        self.run_camera()
        return True

    def _portals_after_match(self, task: dict, again: bool) -> None:
        """Leave a finished Portals match, setting up the next rep if there is one.

        **Portals is the only mode whose victory screen has no Repeat.** Winning consumes the
        portal and hands out a new one, so that screen offers **Select Portal** instead. A loss
        consumes nothing, so its screen *does* have Repeat — and taking it replays the same
        portal with no trip through the bag and no name to retype.

        So which button is on screen is how this learns how the match ended. Nothing reads the
        banner and `_run_match` needs no change to report it: the two outcomes have disjoint
        controls, which is a stronger signal than a template of the banner would be.

        `again` gates both clicks for the same reason `click_repeat` is gated elsewhere — each
        one starts a match, so taking either after the last rep begins a run the queue never
        asked for. Neither available means leave through the lobby, so the next task is never
        handed a stage still on screen.
        """
        if again:
            if self._portal_next_run(task):
                return
            # No Select Portal, so this was a loss and the portal is still owned. Repeat is
            # on that screen and replays it directly.
            ok, msg = self._nav.click_repeat()
            self._log(f"  Repeat: {msg}")
            if ok:
                return
        ok, msg = self._nav.back_to_lobby()
        self._log(f"  Back to lobby: {msg}")

    def _portal_next_run(self, task: dict) -> bool:
        """Queue the next Portals run from the victory screen. False = go via the lobby.

        Select Portal → the picker's search field → type the portal's name → Select. The
        chain after that is the ordinary handover: `wait_for_match_ready` polls for the
        in-match Start Game, so if this panel needs a Start pressed in between, that poll is
        what will say so rather than this returning a false success.

        **A miss on Select Portal is not a failure**, it is the loss signal — see
        `_portals_after_match`. A portal name that no longer matches anything the account owns
        reads the same way: winning hands out a *different* portal, so the name the task asks
        for may simply be gone, and the caller falls back rather than failing the run.
        """
        name = task.get("search", "")
        if not name:
            self._log("  Portals: no portal name on this task — leaving through the lobby.")
            return False

        ok, msg = self._nav.click_select_portal()
        if not ok:
            # The ordinary loss path, not a fault — so it is logged as the observation it is.
            # It costs the full search timeout, and that is the right trade: reading a
            # slow-drawing victory screen as a loss would give up the Select Portal path and
            # spend a lobby trip, while waiting out a real loss only delays the Repeat click.
            self._log(f"  No Select Portal — reading this as a loss ({msg}).")
            return False
        self._log(f"  Select Portal: {msg}")

        ok, msg = self._nav.pick_portal(name, portal_select_image(), "Select")
        self._log(f"  Pick portal: {msg}")
        if not ok:
            return False

        ok, msg = self._nav.wait_for_match_ready()
        self._log(f"  Stage loaded: {msg}")
        if not ok:
            return False
        self.run_camera()
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
        self.run_camera()
        return True

    def run_camera(self) -> None:
        """Camera setup — pitch down, then zoom out. Public because the Image Manager runs
        it on its own to set the camera before a map reference is captured."""
        from sloppykeys.macro.camera import camera_setup_script

        rect = self._rect()
        if rect is None:
            self._log("  Camera: skipped (no Roblox rect)")
            return

        # Centre of the viewport in screen coordinates
        vx, vy, vw, vh = rect
        center_x = vx + vw // 2
        center_y = vy + vh // 2

        # The delay existed in DELAY_SPEC but nothing read it, so the O hold was always
        # the 3s default no matter what the Delays tab said.
        zoom_ms = int(float(self._delays.get("camera_zoom", 3.0)) * 1000)
        script = camera_setup_script(center_x, center_y, zoom_ms=zoom_ms)
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

        # Flatten into indexable lists with per-loop state
        battle_idx = 0
        loop_a_idx = 0
        loop_b_idx = 0

        self._log("  Match started — running blocks...")

        # Park mode: once Battle is spent and there are no loops, there is nothing left to
        # click, so the cursor retreats to the empty top-left corner and clicks it on a slow
        # schedule. That click is not cosmetic — it keeps Roblox from idle-kicking the
        # session through a long wave, and it is the only sign the macro is alive while it
        # waits for a result. Announced once, because a line per click would bury the log.
        park_interval = max(1.0, float(getattr(self._placer, "won_poll_click", 5.0)))
        parked = False
        last_park_click = 0.0
        # Loop blocks that have had their one run. Keyed by identity, like `_upgrade_state`:
        # the blocks come from the operation loaded for this rep, so the ids hold for the
        # match and a reload starts a fresh set.
        spent_once: set[int] = set()
        # A ceiling, because neither banner appearing is a real state: a missed crop, a
        # result screen dismissed by another player, or an Expedition node that parks the
        # client somewhere no result can come from. Without it this loop spun forever,
        # clicking the corner every 5s, and the task queue never advanced. The same 900s the
        # placer's own wait uses. Timing out records nothing — nobody knows how it ended.
        match_budget = max(1.0, float(getattr(self._placer, "won_timeout", 900.0)))
        match_deadline = time.monotonic() + match_budget

        # Expedition only, and per match: everything below is None for every other gamemode,
        # so no other mode pays a search or changes behaviour.
        self._exp = self._expedition_state()
        self._exp_next_check = 0.0
        self._exp_busy = False

        while not self._stop_requested:
            if self._checkpoint():
                return

            if time.monotonic() >= match_deadline:
                self._log(
                    f"  No result screen in {match_budget / 60:.0f} min — giving up on this "
                    f"match and moving on. Check the Won/Lost templates if it really did end."
                )
                return

            # Before the blocks and before parking: Expedition's own screens are what a
            # placement click would otherwise land on.
            # The Battle phase runs before a node's Continue is pressed, because that Continue
            # advances the run and units placed after it are placed into the next wave.
            handled = (
                self._exp is not None
                and self._expedition_tick(battle_idx < len(battle)) == "handled"
            )

            # `handled` means a panel is up and was clicked, so this tick does nothing else:
            # a block's coordinate and the keep-alive click both land on that panel instead of
            # the board. Only the outcome poll below still runs, because extracting puts the
            # victory screen up and that is what ends the match.
            if not handled:
                # "No loops left" counts a loop whose every block has spent its single run:
                # otherwise the tick spins doing nothing and never parks, so the keep-alive
                # click that stops Roblox idle-kicking the session never happens.
                loops_pending = self._loop_pending(loop_a, spent_once) or self._loop_pending(
                    loop_b, spent_once
                )
                if battle_idx >= len(battle) and not loops_pending:
                    now = time.time()
                    if not parked:
                        self._placer.park()
                        parked = True
                        last_park_click = now
                        self._log(
                            f"  Blocks finished — parked at the corner, clicking every "
                            f"{park_interval:.0f}s until the match ends."
                        )
                    elif now - last_park_click >= park_interval:
                        self._placer.park_click()
                        last_park_click = now

                # Advance Battle by one block (if not exhausted)
                if battle_idx < len(battle):
                    block = battle[battle_idx]
                    done = self._execute_battle_block(block)
                    if done:
                        battle_idx += 1

                # Advance Loop A by one block (wraps around, skipping blocks that have had
                # their one run)
                if loop_a:
                    loop_a_idx = self._advance_loop(loop_a, loop_a_idx, spent_once)

                # Advance Loop B by one block (wraps around)
                if loop_b:
                    loop_b_idx = self._advance_loop(loop_b, loop_b_idx, spent_once)

            # Poll for outcome (win/loss)
            outcome = self._check_outcome()
            if outcome is not None:
                result, msg = outcome
                if result == OUTCOME_WON:
                    self._stats.record(won=True)
                    self._log(f"  Win! ({msg})")
                    self._send_webhook_result("win")
                elif result == OUTCOME_LOST:
                    self._stats.record(won=False)
                    self._log(f"  Loss. ({msg})")
                    self._send_webhook_result("loss")
                else:
                    self._log(f"  Match ended: {msg}")
                return

            time.sleep(TICK_SLEEP)

    @staticmethod
    def _runs_once(block: dict) -> bool:
        """Does this block promise to run only once per match?

        Two promises the Macro Manager makes on screen and the run loop never kept: the `1x`
        toggle on any block, and the unconditional RUNS ONCE badge on `walk_path`. Both were
        stored and drawn while the loop phases wrapped and re-ran them anyway — which on
        Expedition means re-placing a unit that can only ever be placed once, and anywhere
        means re-walking a recorded route from a position nobody recorded it from.

        Battle already runs each block once, so this only changes Loop A and Loop B.
        """
        return bool(block.get("once")) or block.get("type") == "walk_path"

    @classmethod
    def _loop_pending(cls, blocks: list, spent: set[int]) -> bool:
        """Has this loop phase got anything left to run?"""
        return any(not (cls._runs_once(b) and id(b) in spent) for b in blocks)

    def _advance_loop(self, blocks: list, idx: int, spent: set[int]) -> int:
        """Run one block of a loop phase and return the next index.

        A block that has spent its single run is stepped over without executing, so the loop
        keeps cycling whatever is left instead of stalling on it.
        """
        block = blocks[idx]
        if self._runs_once(block) and id(block) in spent:
            return (idx + 1) % len(blocks)
        if not self._execute_battle_block(block):
            return idx  # not finished — same block again next tick
        if self._runs_once(block):
            spent.add(id(block))
        return (idx + 1) % len(blocks)

    def _check_outcome(self) -> tuple[str, str] | None:
        """Non-blocking check for win/loss. Returns (outcome, msg) or None.

        Delegates to the placer rather than building its own profiles: this used to read
        `assets/match/game_won.png` and `game_lost.png` from hardcoded paths at a hardcoded
        0.70, which bypassed both the `nav_images` accessors and the per-template threshold
        from Settings > Vision, and had no margin between the two templates — the exact
        `won 0.57, lost 0.71` misread `_outcome_is_clear` exists to prevent.
        """
        return self._placer.poll_outcome()

    # -- Expedition's mid-match screens --

    def _expedition_state(self) -> ExpeditionMatch | None:
        """A fresh match state for an Expedition task, None for every other gamemode.

        Built per match, so the extract counter starts at zero for each rep — a shared one
        would extract the second run of a repeat the instant it offered.
        """
        task = self._current_task or {}
        if task.get("mode") != "Expedition":
            return None
        after = extract_after_from_task(task.get("extract_after"))
        self._log(f"  Expedition: extracting at offer {after}.")
        return ExpeditionMatch(after)

    def _expedition_tick(self, blocks_pending: bool = False) -> str | None:
        """Handle whatever Expedition screen is up. "handled" when one is, None when clear.

        "handled" is what stops the run loop running a block in the same tick: a checkpoint is
        not the moment to place a unit or click the corner, and a placement coordinate lands on
        the panel instead of the board.

        Throttled, because four template searches is ~70ms and this shares a thread with the
        blocks. **A throttled tick repeats the last answer** rather than reporting a clear
        screen: answering None in the gaps let a block run 19 ticks out of 20 while a Continue
        panel was open, which is exactly the interleaving the "handled" flag exists to stop.

        The searches short-circuit in priority order — nothing behind the upgrade card can be
        clicked, so while it is up nothing else is even looked for.
        """
        now = time.time()
        if now < getattr(self, "_exp_next_check", 0.0):
            return "handled" if self._exp_busy else None
        self._exp_next_check = now + CHECK_INTERVAL

        seen: set[str] = set()
        if self._nav.sighted(exp_upgrade_card_image()):
            seen.add(CARD)
        else:
            if self._nav.sighted(start_game_image()):
                seen.add(START_GAME)
            if self._nav.sighted(exp_extract_image()):
                seen.add(EXTRACT)
            elif self._nav.sighted(exp_continue_image()):
                seen.add(CONTINUE)

        action, note = self._exp.decide(seen, now, blocks_pending)
        self._exp_busy = action != NOTHING
        if action == NOTHING:
            return None
        self._log(f"  [expedition] {note}")

        if action == DISMISS_CARD:
            # No template for the three card faces — they differ every time — so this clicks
            # the middle of the screen, which is the middle card. Harmless if the modal has
            # already auto-selected by itself, which it does after about 12s.
            pos = self._client_to_screen(*CARD_DISMISS_CLICK)
            if pos is not None:
                from sloppykeys.macro.input_scripts import nudge_click_script, SPREAD_TIGHT

                # Nudged like every other click: Roblox ignores one that arrives with no
                # hover. Not parked — in-match the cursor belongs where it clicked.
                self._ahk.run(
                    nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0
                )
            return "handled"

        if action == START_WAVE:
            ok, msg = self._nav.click_start_game(timeout=0.0)
            if ok:
                self._log(f"  Wave {self._exp.note_wave_started()} started: {msg}")
            else:
                self._log(f"  Start Game: {msg}")
            return "handled"

        if action == ACCEPT_EXTRACT:
            # No "win" from here: the victory screen that follows is the ground truth, and the
            # run loop's own outcome poll reads it a tick later. Claiming the win on a click
            # would record a run that the game might not have ended.
            if self._exp_click_pair(exp_extract_image(), exp_extract_confirm_image(), "Extract"):
                return "handled"
            left = self._exp.note_extract_failed()
            self._log(
                f"  Extraction didn't register — continuing this checkpoint instead "
                f"({left} more {'try' if left == 1 else 'tries'} before the run plays on)."
            )
            # Fall through and decline: a failed extract must not leave the run parked on the
            # same screen, and continuing costs one wave and buys another offer.
            action = DECLINE_EXTRACT

        # Declining an extraction and clearing an encounter are the same two clicks: the
        # checkpoint's Continue is the same button the encounter shows, so there is one path
        # for both rather than a template each.
        if action in (DECLINE_EXTRACT, CONTINUE_WAVE):
            label = "Keep going" if action == DECLINE_EXTRACT else "Continue"
            self._exp_click_pair(exp_continue_image(), exp_continue_2_image(), label)
            return "handled"

        return None

    def _exp_click_pair(self, first: str, second: str, label: str) -> bool:
        """Click a node's button, then the one that pops up on the panel it opens.

        **The first button does not go away when clicked** — it is on screen for as long as the
        node is. So it cannot be verified by watching it disappear: `click_until_gone` fired
        three clicks into it in under a second, never left time for the panel to draw, and then
        reported failure, so the second button was never clicked at all.

        The second button appearing is the only proof the first click landed, so that is what
        this waits for. If it never comes, the first button is still there and the next look
        tries again — no state to unwind.
        """
        ok, message = self._nav.click_button(first, label)
        self._log(f"  {label}: {message}")
        if not ok:
            return False
        deadline = time.monotonic() + FOLLOWUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._checkpoint():
                return False
            if self._nav.sighted(second):
                # The second one *is* on a panel that closes, so here "gone" is the right
                # proof and the retry covers a click the client swallowed.
                ok, message = self._nav.click_until_gone(
                    second, f"{label} confirm", fade_wait=self._nav.panel_fade_wait
                )
                self._log(f"  {label} confirm: {message}")
                return ok
            time.sleep(self._nav.search_poll)
        self._log(f"  {label}: no second button appeared in {FOLLOWUP_TIMEOUT:.0f}s — retrying.")
        return False

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
        elif btype == "autoplay":
            return self._tick_autoplay(block)
        else:
            # All other blocks are one-shot (execute and move on)
            self._execute_block(block)
            return True

    def _unit_click_position(self, block: dict) -> tuple[int, int] | None:
        """Resolve a unit block's click position, converted to screen coords.

        Unit-action blocks (upgrade/sell/priority) carry an `index` naming which
        placed unit they act on; resolve it to the Nth place_unit block's coords.
        Falls back to the block's own x/y (legacy blocks that still store coords).
        """
        params = block.get("params", {})
        index = params.get("index")
        if index not in (None, ""):
            src = self._place_unit_by_index(int(index))
            if src is None:
                return None
            sp = src.get("params", {})
            x, y = int(sp.get("x", 0)), int(sp.get("y", 0))
        else:
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
        if x and y:
            return self._client_to_screen(x, y)
        return None

    def _place_unit_by_index(self, n: int) -> dict | None:
        """Return the Nth (1-based) place_unit block across all phases."""
        phases = getattr(self, "_phases", None) or {}
        count = 0
        for phase in ("pre_start", "battle", "loop_a", "loop_b"):
            for b in phases.get(phase, []):
                if b.get("type") == "place_unit":
                    count += 1
                    if count == n:
                        return b
        return None

    def _client_to_screen(self, cx: int, cy: int) -> tuple[int, int] | None:
        """Convert 1152×756 client-space coords to screen coords using the Roblox rect."""
        rect = self._rect()
        if rect is None:
            return None
        vx, vy, vw, vh = rect
        # Scale from reference (1152×756) to actual viewport size, then offset
        screen_x = vx + int(cx * vw / 1152)
        screen_y = vy + int(cy * vh / 756)
        return (screen_x, screen_y)

    def _game_keybind(self, action: str) -> str:
        """Get the in-game keybind for an action (upgrade, sell, priority, autograde)."""
        unified = UnifiedSettings(self._app_root)
        gk = unified.get("game_keybinds", {})
        defaults = {"upgrade": "t", "sell": "x", "priority": "r", "autograde": "v"}
        return gk.get(action, defaults.get(action, ""))

    def _safe_game_key(self, action: str) -> str:
        """The keybind for an action, reduced to one key safe to put in an AHK Send().
        "" when unusable, which callers must treat as "don't press anything"."""
        from sloppykeys.config.keybinds import sanitize_game_key

        return sanitize_game_key(self._game_keybind(action))

    @staticmethod
    def _safe_key(raw: object) -> str:
        """Sanitise a key that came from a saved block. A generated AHK script *is*
        code, so a block field can never reach `Send()` unchecked."""
        from sloppykeys.config.keybinds import sanitize_game_key

        return sanitize_game_key(raw)

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

        # With Auto on, `times` is the auto-upgrade *level*: the key steps through the
        # levels, so pressing it N times selects level N. It replaces the manual presses
        # rather than following them — one interaction, not both.
        if autograde:
            key = self._safe_game_key("autograde")
            if not key:
                self._log("    [block] upgrade: no usable autograde keybind — skipping")
                del self._upgrade_state[id(block)]
                return True
            self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
            time.sleep(0.4)
            self._ahk.run(key_script(key, count=times), wait=True, timeout=3.0 + times)
            self._log(f"    [block] auto upgrade → level {times} ({times}× {key.upper()})")
            del self._upgrade_state[id(block)]
            return True

        key = self._safe_game_key("upgrade")
        if not key:
            self._log("    [block] upgrade: no usable upgrade keybind — skipping")
            del self._upgrade_state[id(block)]
            return True
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        self._ahk.run(key_script(key), wait=True, timeout=3.0)
        time.sleep(0.3)

        state["remaining"] -= 1
        if state["remaining"] <= 0:
            del self._upgrade_state[id(block)]
            return True
        return False

    def _tick_sell_unit(self, block: dict) -> bool:
        """Click the unit, press sell key. One-shot."""
        pos = self._unit_click_position(block)
        if pos is None:
            self._log("    [block] sell: no unit position — skipping")
            return True

        key = self._safe_game_key("sell")
        if not key:
            self._log("    [block] sell: no usable sell keybind — skipping")
            return True
        from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        self._ahk.run(key_script(key), wait=True, timeout=3.0)
        return True

    def _tick_target_priority(self, block: dict) -> bool:
        """Click the unit, then cycle its targeting to the chosen priority.

        The key steps through `PRIORITY_OPTIONS` in order, and a freshly placed unit
        starts on the first entry, so the number of presses is the option's index —
        `First` needs none, `Last` one, and so on.

        ponytail: that only holds while the unit is still on the default. Nothing on
        screen reports the current target, so running this block twice on one unit
        cycles past where it was. Reading it back would need OCR of the unit panel.
        """
        pos = self._unit_click_position(block)
        if pos is None:
            self._log("    [block] target priority: no unit position — skipping")
            return True

        from sloppykeys.content.units import PRIORITY_OPTIONS

        wanted = str(block.get("params", {}).get("priority", "") or "")
        if wanted not in PRIORITY_OPTIONS:
            self._log(f"    [block] target priority: '{wanted}' is not a targeting option — skipping")
            return True
        presses = PRIORITY_OPTIONS.index(wanted)
        if presses == 0:
            self._log(f"    [block] target priority already {wanted} on a fresh unit — no press")
            return True

        from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
        self._ahk.run(nudge_click_script(pos[0], pos[1], spread=SPREAD_TIGHT), wait=True, timeout=5.0)
        time.sleep(0.4)
        key = self._safe_game_key("priority")
        if not key:
            self._log("    [block] target priority: no usable priority keybind — skipping")
            return True
        self._ahk.run(key_script(key, count=presses), wait=True, timeout=3.0 + presses)
        time.sleep(0.2)
        self._log(f"    [block] target priority → {wanted} ({presses}× {key.upper()})")
        return True

    def _tick_autoplay(self, block: dict) -> bool:
        """Turn the game's own Auto Play on, and confirm it went on.

        Two templates, because a toggle that is *found* is not a toggle that is *on*:
        `autoplay.png` is the button, `autoplay_active.png` is the proof. Without the second
        one this block would report success on a click the client swallowed and then place
        nothing for the whole match, which looks exactly like a working run until the result.

        Ordering per tick: check active first, so a match that already has it on costs one
        look and no click, and so a block sitting in a loop phase re-asserts it for free if
        the game ever turns it off. Then click, and let the *next* tick do the checking —
        `AUTOPLAY_RECHECK` apart, because the toggle animates.

        **Deliberately uses the navigator's parking click**, against the usual in-match rule
        that clicks stay where they landed. Here the cursor must leave: it would sit on the
        very button whose *appearance* the next search reads, and a hovered control does not
        match its own template. It parks at the client's top-left corner, the same empty
        ground `UnitPlacer.park_click` already clicks as a keep-alive.

        Not a `detect` block with a click in its Then branch: `detect` throws away where the
        template matched, so that click would be a fixed coordinate, and nothing would verify
        the toggle flipped.
        """
        if not hasattr(self, "_autoplay_state"):
            self._autoplay_state = {}
        state = self._autoplay_state.setdefault(id(block), {"clicks": 0, "next_look": 0.0})

        off_path = autoplay_image()
        active_path = autoplay_active_image()
        # A missing template leaves the block inert instead of stalling the match — the same
        # answer `wait_wave` gives when OCR is unavailable. Checked on the off state only:
        # without it there is nothing to click, and the run has to go on regardless.
        if not self._engine.template_exists(off_path):
            self._log(f"    [block] autoplay: {off_path} not captured — skipping")
            del self._autoplay_state[id(block)]
            return True

        now = time.time()
        if now < state["next_look"]:
            return False  # the toggle is mid-animation; ask again in a moment

        if self._nav.sighted(active_path):
            if state["clicks"]:
                self._log(f"    [block] autoplay is on (after {state['clicks']} click(s))")
            else:
                self._log("    [block] autoplay was already on — no click")
            del self._autoplay_state[id(block)]
            return True

        if state["clicks"] >= AUTOPLAY_CLICKS:
            # Give up rather than spin: either the active crop never matches, or the button
            # is somewhere this template can't see. Both are for the user to fix, and the
            # match is still playable — the plan's own blocks run as normal.
            self._log(
                f"    [block] autoplay: clicked {state['clicks']}× and "
                f"{active_path} never matched — playing on without it"
            )
            del self._autoplay_state[id(block)]
            return True

        ok, message = self._nav.click_button(off_path, "Auto Play")
        state["clicks"] += 1
        state["next_look"] = time.time() + AUTOPLAY_RECHECK
        self._log(f"    [block] autoplay click {state['clicks']}/{AUTOPLAY_CLICKS}: {message}")
        return False

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

        # Read the wave number. `OcrReader.read_line` is the only reader there is —
        # this called a `read_text` that does not exist, and the bare `except` swallowed
        # the AttributeError, so the block never finished and the phase stalled forever.
        try:
            from sloppykeys.core.ocr import OcrReader
            import mss
            import numpy as np

            rect = self._rect()
            if rect is None:
                return False

            ocr = OcrReader()
            ok, msg = ocr.available()
            if not ok:
                # Surfaced, not swallowed: without OCR this block can never complete, so
                # skip it rather than hang the match.
                self._log(f"    [block] wait wave: OCR unavailable ({msg}) — skipping")
                return True

            # Through the accessor, so the user's Settings > OCR measurement is what gets
            # read. The default is an approximation and has never been confirmed in a stage.
            from sloppykeys.content.match_regions import wave_region

            bx, by, bw, bh = wave_region()
            vx, vy, vw, vh = rect
            wave_x = vx + int(bx * vw / 1152)
            wave_y = vy + int(by * vh / 756)
            wave_w = max(1, int(bw * vw / 1152))
            wave_h = max(1, int(bh * vh / 756))

            with mss.mss() as sct:
                mon = {"left": wave_x, "top": wave_y, "width": wave_w, "height": wave_h}
                img = np.array(sct.grab(mon))[:, :, :3].copy()

            read = ocr.read_line(img)
            # OCR reads are approximate, so never require an exact string — take the
            # first run of digits and compare numerically.
            import re
            numbers = re.findall(r"\d+", read.text or "")
            if numbers:
                current = int(numbers[0])
                if current >= target:
                    self._log(f"    [block] wave {current} reached target {target}")
                    return True
        except (OSError, ValueError, AttributeError) as exc:
            self._log(f"    [block] wait wave: read failed: {exc}")

        return False

    def _webhook(self):
        """The configured hook, or None when notifications are off.

        Built per send rather than held on the instance, so editing the URL or the user ID in
        Settings takes effect on the next event instead of at the next restart.
        """
        from sloppykeys.core.webhook import DiscordWebhook

        unified = UnifiedSettings(self._app_root)
        url = unified.get("discord_webhook", "")
        if not url:
            return None
        hook = DiscordWebhook(
            url_provider=lambda: url,
            log=self._log,
            user_id_provider=lambda: unified.get("discord_user_id", ""),
        )
        return hook if hook.enabled else None

    def _task_label(self) -> str:
        task = self._current_task or {}
        mode = task.get("mode", "—")
        map_name = task.get("map", "—")
        stage = task.get("stage", "—")
        return f"{mode} / {map_name} / {stage}"

    def _session_field(self) -> tuple[str, str]:
        snap = self._stats.snapshot()
        return ("Session", f"{snap.wins}W – {snap.losses}L ({snap.win_rate})")

    def _send_lifecycle(self, title: str, color: int, extra: list[tuple[str, str]]) -> None:
        """One run-lifecycle notification: started, paused, resumed, ended.

        Sent from the controller rather than the bridge because the hotkeys and the buttons
        both come through here — notifying at the js_api methods would miss F1/F2 entirely.
        Every one of these mentions the user if an ID is set; `webhook.send` decides that, so
        no event here has a say in it.
        """
        hook = self._webhook()
        if hook is None:
            return
        hook.send(title=title, fields=extra, color=color)

    def _send_webhook_started(self) -> None:
        from sloppykeys.core.webhook import COLOR_START

        tasks = UnifiedSettings(self._app_root).get_tasks()
        first = tasks[0] if tasks else {}
        queued = ", ".join(
            f"{t.get('mode', '?')} / {t.get('map', '?')}" for t in tasks[:3]
        ) or "—"
        if len(tasks) > 3:
            queued += f", +{len(tasks) - 3} more"
        self._send_lifecycle(
            "Macro Started",
            COLOR_START,
            [
                ("Queue", f"{len(tasks)} task(s)"),
                ("Up first", f"{first.get('mode', '—')} / {first.get('map', '—')}"),
                ("Queued", queued),
            ],
        )

    def _send_webhook_paused(self, paused: bool) -> None:
        from sloppykeys.core.webhook import COLOR_PAUSE, COLOR_START

        self._send_lifecycle(
            "Macro Paused" if paused else "Macro Resumed",
            COLOR_PAUSE if paused else COLOR_START,
            [("Stage", self._task_label()), ("Cycle", str(self._cycle)), self._session_field()],
        )

    def _send_webhook_ended(self, reason: str) -> None:
        from sloppykeys.core.webhook import COLOR_END

        snap = self._stats.snapshot()
        self._send_lifecycle(
            "Macro Ended",
            COLOR_END,
            [
                ("Reason", reason or "—"),
                ("Cycles", str(self._cycle)),
                self._session_field(),
                ("Uptime", snap.macro_time),
            ],
        )

    def _send_webhook_result(self, result: str) -> None:
        """Send a Discord webhook notification for a match result with screenshot."""
        from sloppykeys.core.webhook import COLOR_WIN, COLOR_LOSS

        hook = self._webhook()
        if hook is None:
            return

        wins = self._stats.wins
        losses = self._stats.losses
        total = wins + losses
        rate = f"{round(wins * 100 / total)}%" if total > 0 else "—"

        title = "Stage Won" if result == "win" else "Stage Lost"
        color = COLOR_WIN if result == "win" else COLOR_LOSS
        fields = [
            ("Stage", self._task_label()),
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
            hotkey = self._safe_key(block.get("hotkey", ""))
            if x and y:
                from sloppykeys.macro.input_scripts import nudge_click_script, key_script, SPREAD_TIGHT
                # Convert client-space coords to screen coords
                screen_pos = self._client_to_screen(x, y)
                if screen_pos is None:
                    self._log("    [block] place_unit: can't resolve screen position")
                    return
                sx, sy = screen_pos
                if hotkey:
                    self._ahk.run(key_script(hotkey), wait=True, timeout=5.0)
                    time.sleep(0.3)
                self._ahk.run(nudge_click_script(sx, sy, spread=SPREAD_TIGHT), wait=True, timeout=5.0)

        elif btype == "upgrade_unit":
            # Drain the repeat state so a linear-phase upgrade runs to completion.
            while not self._tick_upgrade_unit(block):
                if self._checkpoint():
                    break

        elif btype == "sell_unit":
            self._tick_sell_unit(block)

        elif btype == "target_priority":
            self._tick_target_priority(block)

        elif btype == "wait_ms":
            ms = max(0, int(params.get("ms", 500)))
            time.sleep(ms / 1000.0)

        elif btype == "wait_wave":
            # In a linear phase there is no tick loop, so poll until it clears.
            while not self._tick_wait_wave(block):
                if self._checkpoint():
                    break
                time.sleep(TICK_SLEEP)

        elif btype == "autoplay":
            # Same as above: Pre Start has no tick loop, so drain the click/verify cycle
            # here. Without this branch the block would fall off the end of this chain and
            # be silently counted as done — the way any unknown type is.
            while not self._tick_autoplay(block):
                if self._checkpoint():
                    break
                time.sleep(TICK_SLEEP)

        elif btype == "click":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            if x and y:
                from sloppykeys.macro.input_scripts import nudge_click_script
                screen_pos = self._client_to_screen(x, y)
                if screen_pos:
                    self._ahk.run(nudge_click_script(screen_pos[0], screen_pos[1]), wait=True, timeout=5.0)

        elif btype == "send_key":
            key = self._safe_key(block.get("key", ""))
            # Hold is opt-in: the checkbox gates the duration, so an unticked block taps
            # even if a stale hold_ms is still saved on it.
            hold_ms = max(0, int(params.get("hold_ms", 0) or 0)) if block.get("hold") else 0
            count = max(1, int(params.get("count", 1) or 1))
            if not key:
                self._log(f"    [block] send key: '{block.get('key', '')}' is not a usable key")
                return
            from sloppykeys.macro.input_scripts import key_script
            self._ahk.run(
                key_script(key, count=count, hold_ms=hold_ms),
                wait=True,
                timeout=8.0 + count * (hold_ms / 1000.0),
            )

        elif btype == "walk_path":
            # The pinned pre-start walk. Auto resolves the task's target through the table;
            # Custom names a recording outright. Had no branch here at all, so both modes
            # were silently skipped.
            task = self._current_task or {}
            if block.get("mode") == "custom":
                path_name = str(block.get("pathName", "") or "")
                source = "custom"
            else:
                path_name = default_walk_path(
                    task.get("mode", ""), task.get("map", ""), task.get("stage", "")
                )
                source = "auto"
            if not path_name:
                self._log("    [block] walk path: nothing set for this target — skipping")
                return
            from sloppykeys.macro.recording import replay_walk_script
            script = replay_walk_script(self._app_root, path_name)
            if not script:
                self._log(f"    [block] walk path '{path_name}' ({source}) not found or empty")
                return
            self._log(f"    [block] walking '{path_name}' ({source})")
            self._ahk.run(script, wait=True, timeout=30.0)

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

            # Resolve the image path. `assets/detect` comes first: that is where the
            # block's own Capture button writes, so a name that exists both there and
            # under a navigation folder must resolve to the user's own crop.
            image_path = image_name
            if not os.path.isabs(image_path):
                for subdir in ("assets/detect", "assets/match", "assets/lobby", "assets"):
                    candidate = os.path.join(self._app_root, subdir, image_name)
                    if not candidate.endswith(".png"):
                        candidate += ".png"
                    if os.path.isfile(candidate):
                        image_path = candidate
                        break
                else:
                    self._log(f"    [block] detect: image '{image_name}' not found — treating as not found")

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

    @staticmethod
    def _challenge_task(tasks: list) -> dict | None:
        """The queued Challenge task, or None. The first one wins — a second is the same
        panel with different macro assignments, and honouring both would run the rotation
        twice."""
        for task in tasks:
            if task.get("mode") == "Challenge":
                return task
        return None

    def _challenge_playable(self, task: dict) -> list:
        """Rows this task could run right now, from the last scan.

        Not simply `tracker.candidates()`: a row the panel offers but *this task* declines —
        its slot switched off, or no macro assigned for the map that was read — must not count
        as work, or the run would detour to the panel before every single match, find nothing
        it can do, and come back. The queue would never advance.
        """
        slots = task.get("challenge_slots", [True, True, True])
        macros = task.get("challenge_macros", {})
        playable = []
        for read in self._challenges.candidates():
            index = read.slot - 1
            if index >= len(slots) or not slots[index]:
                continue
            if not macros.get(read.map_name or ""):
                continue
            playable.append(read)
        return playable

    def _challenge_wants_in(self, task: dict, now: datetime | None = None) -> bool:
        """Should a challenge run before the next match?

        **Challenge keeps its queue position for configuration, not for ordering.** The maps
        re-roll every half hour while a target task can hold the queue for hours, so a
        challenge that waited its turn would miss most rotations — which is the whole reason
        the old design ignored its position too.

        Costs nothing until it answers yes: `note_time` and `needs_rescan` are arithmetic on
        the wall clock, no capture and no navigation. `note_time` returning True is the
        mid-match re-roll — it has already cleared the played marks and the stale reads, so
        the panel is worth another look.

        `now` is injectable for the same reason every tracker method takes it: a rotation
        boundary cannot be exercised against the wall clock.
        """
        self._challenges.note_time(now)
        if self._challenges.needs_rescan(now):
            return True
        return bool(self._challenge_playable(task))

    def _run_challenge_task(self, task: dict) -> None:
        """Execute a Challenge task: scan the panel, pick a ready slot, run it."""
        from sloppykeys.macro.challenge import ChallengeScanner
        from sloppykeys.content.challenge import challenge_maps, SLOTS

        challenge_macros = task.get("challenge_macros", {})
        challenge_slots = task.get("challenge_slots", [True, True, True])

        self._log("  Challenge: scanning panel...")

        # Navigate to the challenge panel
        ok = self._navigate_to_challenge()
        if not ok:
            self._log("  Challenge: couldn't reach the challenge panel.")
            return

        # `scan_if_open`, not `scan`. Nothing proves the panel arrived — navigation ends by
        # clicking the Challenge card, and there is no template for the panel because the
        # whole thing is read by OCR. An unreadable limit box comes back `unknown`, which
        # counts as *worth attempting*, so a scan taken on the wrong screen reports three
        # challenges waiting and the row coordinate below then clicks into whatever is up.
        # At least one limit parsing as `n/10` is the only available proof, so it is the wait.
        scanner = ChallengeScanner(self._engine, self._rect, log=self._log)
        deadline = time.monotonic() + max(1.0, self._nav.search_timeout)
        reads, panel_open = scanner.scan_if_open()
        while not panel_open and time.monotonic() < deadline:
            if self._checkpoint():
                return
            time.sleep(0.5)
            reads, panel_open = scanner.scan_if_open()

        # Told before the reads are trusted, so a panel that cannot be read costs **one**
        # detour this rotation rather than one before every match.
        self._challenges.note_scan_attempt()

        if not panel_open:
            self._log(
                "  Challenge: the panel never read as open — not clicking a row blind. "
                "Check the limit boxes in Settings > OCR."
            )
            return
        if not reads:
            self._log("  Challenge: panel scan returned nothing.")
            return
        self._challenges.note_reads(reads)

        # Find a ready slot
        for read in reads:
            if self._checkpoint():
                return
            slot_idx = read.slot - 1
            if slot_idx >= len(challenge_slots) or not challenge_slots[slot_idx]:
                continue  # slot disabled by user
            if self._challenges.is_skipped(read.slot):
                continue  # already played this rotation
            # A property, not a method. Called as `is_candidate()` this raised
            # `TypeError: 'bool' object is not callable` on the first row every time, and
            # nothing catches it here — so the exception unwound the whole run and reported
            # "stopped unexpectedly". No Challenge task had ever got past this line.
            if not read.is_candidate:
                self._log(f"  Challenge slot {read.slot}: not runnable ({read.summary()})")
                continue

            # Determine which macro to use based on the detected map
            map_name = read.map_name or ""
            macro_name = challenge_macros.get(map_name, "")
            self._log(f"  Challenge slot {read.slot}: {map_name} — macro '{macro_name or 'none'}'")

            if not macro_name:
                self._log(f"  Challenge slot {read.slot}: no macro assigned for {map_name} — skipping")
                continue

            # Click the slot to enter
            from sloppykeys.content.challenge import row_click, SELECT_STAGE_CLICK, START_CLICK
            click_pos = row_click(read.slot)
            if click_pos is None:
                self._log(f"  Challenge slot {read.slot}: no click position — skipping")
                continue

            # Click the challenge row
            screen_pos = self._client_to_screen(click_pos[0], click_pos[1])
            if screen_pos:
                from sloppykeys.macro.input_scripts import nudge_click_script
                self._ahk.run(nudge_click_script(screen_pos[0], screen_pos[1]), wait=True, timeout=5.0)
                time.sleep(1.0)

            # Click Select Stage
            ss_pos = self._client_to_screen(SELECT_STAGE_CLICK[0], SELECT_STAGE_CLICK[1])
            if ss_pos:
                self._ahk.run(nudge_click_script(ss_pos[0], ss_pos[1]), wait=True, timeout=5.0)
                time.sleep(1.0)

            # Click Start
            st_pos = self._client_to_screen(START_CLICK[0], START_CLICK[1])
            if st_pos:
                self._ahk.run(nudge_click_script(st_pos[0], st_pos[1]), wait=True, timeout=5.0)
                time.sleep(1.0)

            # Wait for match to load
            ok, msg = self._nav.wait_for_match_ready()
            if not ok:
                self._log(f"  Challenge: stage didn't load — {msg}")
                return

            self.run_camera()

            # Load and run the macro operation
            op = load_operation(self._app_root, macro_name)
            phases = op.get("phases", {})
            self._phases = phases

            # Pre Start
            self._run_phase_linear(phases.get("pre_start", []))
            if self._checkpoint():
                return

            # Start Game
            self._placer.park()
            ok, msg = self._nav.click_start_game()
            if ok:
                self._stats.start_stage()
                self._log(f"  Start Game: {msg or 'ok'}")
            else:
                self._log(f"  Start Game failed: {msg}")

            if self._checkpoint():
                return

            # Match loop
            battle_blocks = phases.get("battle", [])
            loop_a = phases.get("loop_a", [])
            loop_b = phases.get("loop_b", [])
            self._run_match(battle_blocks, loop_a, loop_b)

            self._cycle += 1
            # Retired for this rotation whatever the result, and whatever went wrong getting
            # here. Win or loss is the tracker's own rule — one run of each row per rotation,
            # since replaying a row spends another of the day's ten either way. Marking it
            # here rather than on a win also means a row that failed technically doesn't
            # preempt every following match forever.
            self._challenges.mark_done(read.slot)
            break  # one challenge per detour

    def _navigate_to_challenge(self) -> bool:
        """Navigate lobby to the challenge panel: Play → Challenge card → wait for panel."""
        steps = [
            ("Play", lambda: self._nav.click_play()),
            ("Challenge", lambda: self._nav.open_gamemode("Challenge")),
        ]
        for name, action in steps:
            if self._checkpoint():
                return False
            ok, msg = action()
            self._log(f"  {name}: {msg or ('ok' if ok else 'failed')}")
            if not ok:
                return False
            time.sleep(self._nav.click_settle)
        # No sleep waiting for the panel. The caller's `scan_if_open` loop polls until the
        # panel reads as open, and a deadline search replaces a fixed sleep rather than
        # following one — two seconds here was latency paid on every pass whether the panel
        # had drawn or not, and it proved nothing either way.
        return True

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
