"""Unit placement and the match cycle.

One pass per step: a step runs its whole detail card top to bottom before the next
step starts. Order inside a step:

  wait (before anything) -> place (slot key + click) -> open the unit panel
  -> priority -> upgrades (or auto upgrade) -> sell -> close the panel

Every action on a *placed* unit waits for the unit panel image first
(`images/match/unit_ui.png`). Without that check a missed click sends `r`/`t`/`x`
into the game world instead of the panel, which silently does the wrong thing and
looks like a working macro. If the panel isn't there, the placer clicks away and
tries again rather than pressing keys blind.

All input goes through AHK via `input_scripts`, so every click uses the nudge
(glide + wiggle): Roblox often ignores a click that arrives without motion.

Sequence steps run their own action list instead of the unit fields.
"""

from __future__ import annotations

import re
import time
import os
from typing import Callable

from sloppykeys.content.nav_images import game_lost_image, game_won_image, unit_ui_image
from sloppykeys.content.start_position import PositionMove
from sloppykeys.content.units import (
    ACTION_CLICK,
    ACTION_DRAG,
    ACTION_FIND_CLICK,
    ACTION_KEY,
    ACTION_MOVE,
    ACTION_SCROLL,
    ACTION_WAIT,
    ACTION_WAVE,
    AUTOUPGRADE_CYCLE,
    PRIORITY_OPTIONS,
    WAVE_MAX,
    StepAction,
    UnitStep,
    autoupgrade_is_on,
    autoupgrade_presses,
    slot_index,
)
from sloppykeys.core.image_search import (
    MAX_INSTANCES,
    ImageProfile,
    ImageSearchEngine,
    SearchRegion,
    clamp_confidence,
    confidence_for,
    find_until,
)

from sloppykeys.core.ocr import OcrReader

from .challenge import DIGIT_FIXES, parse_limit
from .input_scripts import (
    SPREAD_TIGHT,
    SPREAD_WIDE,
    drag_script,
    key_script,
    move_script,
    nudge_click_script,
    scroll_script,
)

RectProvider = Callable[[], "tuple[int, int, int, int] | None"]
GameKeysProvider = Callable[[], dict[str, str]]

# Client-space corner the cursor parks on: empty ground, no unit, no UI.
PARK_CLIENT = (8, 8)

# How often to look for a result. A look is ~17ms measured, so this is latency, not
# cost: at 0.2s a win or defeat is reported within a fifth of a second of appearing.
# The keep-alive click runs on its own, slower schedule (`won_poll_click`).
OUTCOME_POLL = 0.2

# How far the winning result template must beat the losing one before the result is
# believed. "Game Won!" and "Game Lost!" share the word "Game" and are matched in
# grayscale, so a crop carrying that prefix scores nearly the same on both screens — and
# a win was once recorded as a defeat by 0.14. Below this margin, keep waiting.
OUTCOME_MARGIN = 0.08

# How a match ended.
OUTCOME_WON = "won"
OUTCOME_LOST = "lost"

# No vertical offset ladder. There used to be one (0, 14, 28, 42 px above the
# stored point, later with a downward rung), on the theory that a model stands
# above the ground point it was placed on. The log disproved it: the only step that
# ever failed was the first placement after the Start Game click, it failed at every
# offset, and the *second pass* — which re-clicks the original point — succeeded.
# A different position was never what fixed it; more time was. So selecting a unit
# now just re-clicks the recorded point with the nudge, `select_attempts` times.

# A fresh unit starts on the first entry of PRIORITY_OPTIONS, and each `r` press
# advances one entry, wrapping. Same shape as the Expedition difficulty button.
PRIORITY_ON_PLACE = 0


def priority_presses(priority: str) -> int:
    """How many `r` presses move a freshly placed unit to `priority`."""
    if not priority or priority not in PRIORITY_OPTIONS:
        return 0
    return (PRIORITY_OPTIONS.index(priority) - PRIORITY_ON_PLACE) % len(PRIORITY_OPTIONS)


class UnitPlacer:
    def __init__(
        self,
        engine: ImageSearchEngine,
        ahk,
        roblox_rect: RectProvider,
        game_keys: GameKeysProvider,
        log: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._engine = engine
        self._ahk = ahk
        self._rect = roblox_rect
        self._game_keys = game_keys
        self._log = log or (lambda _m: None)
        # See `LobbyNavigator.__init__`: cancels waits, never an AHK script in flight.
        self._should_stop = should_stop or (lambda: False)
        # Only Wait for Wave needs OCR, and building the engine costs ~1s and loads three
        # ONNX models — so it is built on first use, like `ChallengeScanner`'s. A plan with
        # no wave gate never pays for it.
        self._ocr: OcrReader | None = None

        self.search_timeout = 6.0    # how long to wait for an expected image
        # No `self.confidence`: the threshold is per template, resolved in `find_until` by
        # `image_search.confidence_for(path)`. See `LobbyNavigator.__init__`.

        # One look costs ~17ms (capture 6ms + match 11ms), measured, so a 250ms gap
        # was almost all latency: it decided how *late* an image is noticed. At
        # 120ms the duty cycle is still ~14%.
        self.search_poll = 0.12
        self.settle = 0.4            # after an action, before the next one
        # Clicks at the recorded point before giving up. 3 covers the one case the
        # log ever showed failing — the first placement of a wave, which starts
        # working a few seconds in — without turning a genuinely bad coordinate into
        # a half-minute stall.
        self.select_attempts = 3
        # Park at the empty corner after every failed click (user's call — two
        # clicks in a row felt slower). Raise it to skip parks if that changes.
        self.select_clicks_per_park = 1
        self.select_timeout = 1.5    # look after a retry click
        # The first look is longer because that click is usually the one that
        # worked and the panel just hadn't drawn yet.
        self.select_first_timeout = 2.0
        self.won_poll_click = 5.0    # seconds between keep-alive clicks while idle
        self.won_timeout = 900.0     # give up waiting for the win screen after this

    @property
    def ocr(self) -> OcrReader:
        if self._ocr is None:
            self._ocr = OcrReader()
        return self._ocr

    def apply_delays(self, delays: dict[str, float]) -> None:
        """Share the Settings > Delays tunables with the lobby navigator."""
        self.search_timeout = float(delays.get("search_timeout", self.search_timeout))
        self.settle = float(delays.get("placement_settle", self.settle))

    # # Primitives
    def _screen(self, x: int, y: int) -> tuple[int, int] | None:
        rect = self._rect()
        if rect is None:
            return None
        return (rect[0] + int(x), rect[1] + int(y))

    def _run(self, script: str, timeout: float = 10.0) -> tuple[bool, str]:
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        return self._ahk.run(script, wait=True, timeout=timeout)

    def _click_client(
        self, x: int, y: int, button: str = "left", spread: int = SPREAD_WIDE
    ) -> tuple[bool, str]:
        point = self._screen(x, y)
        if point is None:
            return (False, "Roblox not found")
        ok, message = self._run(
            nudge_click_script(point[0], point[1], button=button, spread=spread)
        )
        if ok:
            time.sleep(self.settle)
        return (ok, message)

    def _click_screen(
        self, x: int, y: int, button: str = "left", spread: int = SPREAD_WIDE
    ) -> tuple[bool, str]:
        """Click a point already in screen space — where a template matched.

        `ImageMatch` centres are absolute, because the search takes the client rect as its
        origin. Passing one to `_click_client` would add the window offset a second time.
        """
        ok, message = self._run(nudge_click_script(int(x), int(y), button=button, spread=spread))
        if ok:
            time.sleep(self.settle)
        return (ok, message)

    def _press(self, key: str, count: int = 1) -> tuple[bool, str]:
        if not key:
            return (False, "no key bound")
        if count <= 0:
            return (True, "nothing to press")
        # The script's own runtime grows with the press count (key_script sleeps
        # between presses), so the AHK timeout has to grow with it or a long run of
        # presses is killed halfway.
        ok, message = self._run(key_script(key, count=count), timeout=10.0 + count * 0.3)
        if ok:
            time.sleep(self.settle)
        return (ok, message)

    def park(self) -> None:
        """Public: move the cursor off whatever it is hovering, in match.

        Exists because the step *after* placement needs it. A pre-placement step leaves the
        cursor sitting on the unit it just placed, and Roblox draws a tooltip there — which
        covered the Start Game button and failed the search at `best 0.47 < 0.70` with the
        button plainly on screen. Same failure mode as the lobby tooltip that
        `nudge_click_script(park=…)` exists for; in match the cursor belongs on the unit, so
        placement clicks still don't retreat on their own.
        """
        self._park()

    def park_click(self) -> None:
        """Public: click the empty corner. The keep-alive while there is nothing to do.

        Not cosmetic — it is what stops Roblox idle-kicking the session during a long wave,
        and it is the visible sign the macro is alive rather than hung. `won_poll_click` is
        the interval; the corner is empty ground, so the click can't select or place
        anything.
        """
        self._click_client(*PARK_CLIENT)

    def _park(self) -> None:
        point = self._screen(*PARK_CLIENT)
        if point is None or not self._ahk.available():
            return
        self._ahk.run(move_script(point[0], point[1]), wait=True, timeout=5)

    def _find(self, rel_path: str, timeout: float | None = None):
        budget = self.search_timeout if timeout is None else float(timeout)
        return find_until(
            self._engine,
            self._rect,
            rel_path,
            timeout=budget,
            poll=self.search_poll,
            # None, not a fixed number: `find_until` resolves this template's own threshold.
            confidence=None,
            should_stop=self._should_stop,
        )



    # # Unit panel
    def open_unit_panel(self, x: int, y: int) -> tuple[bool, str]:
        """Click a placed unit and confirm its panel is open.

        Same point every time, with the tight wiggle, up to `select_attempts` times,
        parking at the empty corner between tries (every `select_clicks_per_park`
        failures) so a wrong or half-open panel is cleared first.

        Retrying rather than searching nearby is what the log supports: the only
        failure ever recorded was the first placement after Start Game, and it was
        rescued by re-clicking the *same* coordinate seconds later.
        """
        attempts = max(1, self.select_attempts)
        started = time.monotonic()
        for attempt in range(1, attempts + 1):
            ok, message = self._click_client(x, y, spread=SPREAD_TIGHT)
            if not ok:
                return (False, f"unit click failed: {message}")
            budget = self.select_first_timeout if attempt == 1 else self.select_timeout
            if self._find(unit_ui_image(), timeout=budget) is not None:
                elapsed = time.monotonic() - started
                return (
                    True,
                    f"panel open at {x},{y} (click {attempt}/{attempts}, {elapsed:.1f}s)",
                )
            self._log(
                f"Unit panel not detected around {x},{y} — "
                f"click {attempt}/{attempts} at {time.monotonic() - started:.1f}s."
            )
            if attempt < attempts and attempt % max(1, self.select_clicks_per_park) == 0:
                # Only every Nth failure: clears a wrong or half-open panel and
                # gives the next wiggle a fresh approach.
                self._park()
                time.sleep(self.settle)
        return (
            False,
            f"unit panel never appeared around {x},{y} after {attempts} clicks in "
            f"{time.monotonic() - started:.1f}s — either the click isn't selecting "
            "the unit, or unit_ui.png isn't matching an open panel",
        )

    def close_unit_panel(self) -> None:
        """Click the empty corner so the next step starts from a clean screen."""
        self.park_click()

    # # Step execution
    def run_step(self, step: UnitStep) -> tuple[bool, str]:
        """Run one step end to end. The step's own wait happens first."""
        if not step.is_actionable():
            return (True, "nothing to do")

        wait_ms = _as_int(step.wait)
        if wait_ms > 0:
            self._log(f"Step {step.step}: waiting {wait_ms}ms before acting.")
            time.sleep(wait_ms / 1000.0)

        if step.is_sequence():
            return self.run_sequence(step)
        return self.place_unit(step)

    def place_unit(self, step: UnitStep) -> tuple[bool, str]:
        x, y = _as_int(step.x), _as_int(step.y)
        slot = slot_index(step.slot)
        if slot is None:
            return (False, f"step {step.step} has no hotbar slot")

        trail: list[str] = []

        # Select the hotbar slot, then click the ground to place.
        ok, message = self._press(str(slot))
        if not ok:
            return (False, f"slot {slot} keypress failed: {message}")
        # Tight, like selection: this is a click in the 3D world, so the wide lobby
        # wiggle swings the placement ghost off the stored ground point.
        ok, message = self._click_client(x, y, spread=SPREAD_TIGHT)
        if not ok:
            return (False, f"placement click failed: {message}")
        trail.append(f"placed slot {slot} at {x},{y}")

        auto_presses = autoupgrade_presses(step.autoupgrade)

        # Everything below acts on the placed unit, so the panel must be open.
        needs_panel = bool(step.priority) or step.sell or auto_presses > 0 or (
            _as_int(step.upgrades) > 0
        )
        if not needs_panel:
            return (True, ", ".join(trail))

        ok, message = self.open_unit_panel(x, y)
        if not ok:
            return (False, message)
        # Carried into the step's log line: which click opened the panel, and how
        # long it took, is the only way to see selection getting slower or flakier.
        trail.append(message)

        keys = self._game_keys()

        # Priority before upgrades: the user's order, and it keeps the unit from
        # spending a moment attacking the wrong target while upgrades go in.
        if step.priority:
            presses = priority_presses(step.priority)
            ok, message = self._press(keys.get("priority", ""), count=presses)
            if not ok:
                return (False, f"priority failed: {message}")
            trail.append(f"priority {step.priority} ({presses}x)")

        # Auto upgrade is a cycling control: N presses = auto level N, and the 7th
        # press brings it back to off. So the presses go in first, and the manual
        # upgrade level is only pressed when auto isn't left running — including
        # after a full 7-press cycle, which ends on off.
        if auto_presses:
            ok, message = self._press(keys.get("autoupgrade", ""), count=auto_presses)
            if not ok:
                return (False, f"auto upgrade failed: {message}")
            trail.append(
                f"auto upgrade level {auto_presses} ({auto_presses}x)"
                if auto_presses < AUTOUPGRADE_CYCLE
                else f"auto upgrade cycled back to off ({auto_presses}x)"
            )
        if not autoupgrade_is_on(auto_presses):
            levels = _as_int(step.upgrades)
            if levels > 0:
                ok, message = self._press(keys.get("upgrade", ""), count=levels)
                if not ok:
                    return (False, f"upgrade failed: {message}")
                # ponytail: presses are counted, not verified — the macro can't yet
                # read the unit's level back. Upgrade path is OCR on the panel's
                # level text, which would let this confirm instead of assume.
                trail.append(f"+{levels} upgrades (unverified)")

        if step.sell:
            sell_wait = _as_int(step.sell_wait)
            if sell_wait > 0:
                # Let the unit earn first. The panel won't survive that long, so
                # close it, wait, then re-select and re-verify before pressing sell.
                self.close_unit_panel()
                self._log(f"Step {step.step}: waiting {sell_wait}ms before selling.")
                time.sleep(sell_wait / 1000.0)
                ok, message = self.open_unit_panel(x, y)
                if not ok:
                    return (False, f"re-select before sell failed: {message}")
            ok, message = self._press(keys.get("sell", ""))
            if not ok:
                return (False, f"sell failed: {message}")
            trail.append(f"sold after {sell_wait}ms" if sell_wait else "sold")

        self.close_unit_panel()
        return (True, ", ".join(trail))


    def run_sequence(self, step: UnitStep) -> tuple[bool, str]:
        """Run a sequence step's raw actions in order.

        A Wait for Wave action is a **gate**, so it is handled here rather than in
        `run_action`: "skip the rest of the sequence" is only meaningful where the rest of
        the sequence is. A gate that hasn't opened ends the pass successfully — in a During
        match step that means it is tried again on the next interval, which is how an
        ability gets timed to a wave without blocking anything.
        """
        for position, action in enumerate(step.actions, start=1):
            if action.type == ACTION_WAVE:
                ok, reached, message = self.wave_gate(action)
                if not ok:
                    return (False, f"action {position} (wave): {message}")
                if not reached:
                    return (True, f"holding at action {position}: {message}")
                continue
            ok, message = self.run_action(action)
            if not ok:
                return (False, f"action {position} ({action.type}): {message}")
        return (True, f"{len(step.actions)} actions")

    def wave_gate(self, action: StepAction) -> tuple[bool, bool, str]:
        """(ok, reached, message) for a Wait for Wave action. **One look, never a poll.**

        `ok` False is a real fault — no wave set, no region, no OCR — and stops the
        sequence. `reached` False means the wave simply isn't there yet, which is not a
        fault: the step is re-run on its `During match` interval, and that is where
        repetition belongs. Polling here would hold the loop that watches for the result
        screen for as long as the wave took to arrive.
        """
        target = max(0, int(action.wave))
        if target <= 0:
            return (False, False, "no wave set")
        region = action.region()
        if region is None:
            return (False, False, "no region set — the wave counter has to be boxed")
        ready, note = self.ocr.available()
        if not ready:
            return (False, False, note)

        current, text = self._read_wave(region, action.max_wave)
        if current is not None and current >= target:
            return (True, True, f"wave {current} (read '{text}')")
        where = f"wave {current}" if current is not None else f"unreadable '{text}'"
        return (True, False, f"{where}, waiting for {target}")

    def _read_wave(
        self, region: tuple[int, int, int, int], max_wave: int
    ) -> tuple[int | None, str]:
        """OCR the wave box once. Returns (wave or None, the raw text for the log)."""
        rect = self._rect()
        if rect is None:
            return (None, "Roblox not found")
        crop = self._engine.capture_bgr(
            (rect[0] + region[0], rect[1] + region[1], region[2], region[3])
        )
        read = self.ocr.read_line(crop)
        if not read.ok:
            return (None, read.text or "")
        return (parse_wave(read.text, max_wave), read.text)

    def run_action(self, action: StepAction) -> tuple[bool, str]:
        if action.type == ACTION_WAIT:
            time.sleep(max(0, action.wait_ms) / 1000.0)
            return (True, f"waited {action.wait_ms}ms")

        if action.type == ACTION_MOVE:
            point = self._screen(action.x, action.y)
            if point is None:
                return (False, "Roblox not found")
            return self._run(move_script(*point))

        if action.type == ACTION_CLICK:
            return self._click_client(action.x, action.y, button=action.button)

        if action.type == ACTION_FIND_CLICK:
            return self._find_and_click(action)

        if action.type == ACTION_WAVE:
            # Outside a sequence there is nothing to gate, so this reports the read. The
            # gating form is `wave_gate`, called from `run_sequence`.
            ok, reached, message = self.wave_gate(action)
            return (ok, message if not ok else f"{'reached' if reached else 'not yet'}: {message}")

        if action.type == ACTION_DRAG:
            start = self._screen(action.x, action.y)
            end = self._screen(action.to_x, action.to_y)
            if start is None or end is None:
                return (False, "Roblox not found")
            return self._run(drag_script(start[0], start[1], end[0], end[1], action.button))

        if action.type == ACTION_KEY:
            return self._press_raw(action.key, hold_ms=action.hold_ms)

        if action.type == ACTION_SCROLL:
            rect = self._rect()
            if rect is None:
                return (False, "Roblox not found")
            cx = rect[0] + rect[2] // 2
            cy = rect[1] + rect[3] // 2
            park = self._screen(*PARK_CLIENT)
            if park is None:
                return (False, "Roblox not found")
            return self._run(scroll_script(cx, cy, park[0], park[1], action.notches))

        return (False, f"unknown action type '{action.type}'")

    def _find_and_click(self, action: StepAction) -> tuple[bool, str]:
        """Click where a template is, rather than at a fixed coordinate.

        **Not finding it is success, not failure.** An ability on cooldown simply isn't
        on screen, and this action's whole purpose is to run repeatedly and press when it
        can — reporting "not found" as a failed action would stop the run on the first
        poll that came too early.

        Tolerance comes from the template's own threshold (Settings > Vision), because
        that is where every other search in the app reads it from.
        """
        if not action.image:
            return (False, "no image set")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        if not self._engine.template_exists(action.image):
            return (False, f"{action.image} is missing")

        region = action.region()
        profile = ImageProfile(
            name=action.image,
            image_path=action.image,
            region=SearchRegion(*region) if region is not None else None,
            confidence=confidence_for(action.image),
        )
        limit = MAX_INSTANCES if action.click_all else 1
        matches = self._engine.find_instances(profile, rect, limit=limit)
        if not matches:
            return (True, "not on screen")

        # Left to right, not by score: two instances of one button are usually a row, and
        # pressing them in reading order is what a person would do — and what the user can
        # predict from the log when one of them does the wrong thing.
        matches.sort(key=lambda match: (match.center_x, match.center_y))
        clicked: list[str] = []
        for match in matches:
            if self._should_stop():
                break
            ok, message = self._click_screen(
                match.center_x, match.center_y, button=action.button
            )
            if not ok:
                return (False, f"click at {match.center_x},{match.center_y}: {message}")
            clicked.append(f"{match.center_x},{match.center_y} ({match.score:.2f})")
        return (True, f"clicked {' + '.join(clicked)}")

    def _press_raw(self, key: str, hold_ms: int = 0) -> tuple[bool, str]:
        """Press a sequence action's key. Sanitised the same way as game keys,
        since it lands in a generated AHK Send()."""
        from sloppykeys.config.keybinds import sanitize_game_key

        clean = sanitize_game_key(key)
        if not clean:
            return (False, f"unusable key '{key}'")
        # A hold is a sleep inside the script: the AHK timeout must cover it, or a
        # 3s hold dies against the 10s default once the header's own waits are
        # counted. This is why a long-hold sequence action could fail silently.
        ok, message = self._run(
            key_script(clean, hold_ms=hold_ms), timeout=10.0 + max(0, hold_ms) / 1000.0
        )
        if ok:
            time.sleep(self.settle)
        return (ok, message)

    def run_moves(self, moves: "list[PositionMove]") -> tuple[bool, str]:
        """Hold each movement key in turn to walk the character into position.

        Runs once per run, right after the camera step — the placement coordinates
        of a target like Raid / Spirit City / Act 2 are measured from where the
        character ends up, not from spawn. Reuses the sequence-action key press, so
        the same sanitising and settle apply.
        """
        usable = [move for move in moves if move.is_actionable()]
        if not usable:
            return (True, "no movement for this target")
        for position, move in enumerate(usable, start=1):
            ok, message = self._press_raw(move.key, hold_ms=move.hold_ms)
            if not ok:
                return (False, f"move {position} ({move.key} {move.hold_ms}ms): {message}")
        seconds = sum(move.hold_ms for move in usable) / 1000.0
        return (True, f"{len(usable)} moves, {seconds:.1f}s of walking")

    # # Match cycle
    def wait_for_outcome(
        self, timeout: float | None = None, match_steps: "list[UnitStep] | None" = None
    ) -> tuple[str, str]:
        """Park the cursor and idle until the match ends.

        Returns (outcome, message) where outcome is OUTCOME_WON, OUTCOME_LOST, or
        "" on timeout. Clicks the empty corner every `won_poll_click` seconds:
        that's not cosmetic, it keeps Roblox from idle-kicking the session and
        shows the user the macro is alive rather than hung.

        The loss template is optional — with no `game_lost.png` on disk a defeat
        simply isn't recognised and this waits out its budget.

        `match_steps` are the plan's During match steps, and this is the only place they
        can run. The run loop advances one step at a time and waits for it to return, so a
        repeating step in the chain would hold the whole run and stop anything looking for
        the result. Here the two share one loop: each pass looks for the outcome **first**,
        so a result is never delayed behind an ability press, then runs whichever steps
        are due. A press counts as activity, so it also defers the keep-alive click.
        """
        budget = self.won_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, budget)
        self._park()
        clicks = 0
        last_click = time.monotonic()
        schedule = _MatchSchedule(match_steps or [])
        while True:
            # Both screens matched against **one capture**, rather than polling for the
            # win for `won_poll_click` seconds and then taking a single look for the
            # loss. That ordering sampled defeat far less often than victory, so a loss
            # screen that comes and goes between two win polls was missed entirely — and
            # a challenge lost with one unit placed is exactly that case. One capture,
            # two templates, best score wins.
            # Look often, click rarely. A look is ~17ms, so polling at OUTCOME_POLL means
            # a result shows up within a fifth of a second; the keep-alive click only has
            # to happen often enough to look active. Tying the two together (a click
            # between every look) is what made the result take seconds to appear.
            match = self._find_outcome()
            if match is not None and not self._outcome_is_clear(match):
                # Both templates scored, and too close together to tell apart. Observed in
                # game: a *win* screen scoring `won 0.57, lost 0.71`, which counted a
                # loss, skipped the challenge and sent the wrong embed. When the margin is
                # this thin the match is luck, so keep waiting — the banner animates in,
                # and a later frame is usually decisive.
                match = None
            if match is not None:
                lost = match.profile_name == game_lost_image()
                # Score of the *other* template too: both banners share a region and
                # differ only in the word, so a close runner-up means the crops aren't
                # discriminating and a defeat could read as a victory.
                return (
                    OUTCOME_LOST if lost else OUTCOME_WON,
                    f"{'defeat' if lost else 'win'} screen ({match.score:.2f}) "
                    f"at {match.left},{match.top} — {self._outcome_scores()}"
                    f"{schedule.trail()}",
                )
            now = time.monotonic()
            if now >= deadline:
                return (
                    "",
                    f"no result within {budget:.0f}s ({clicks} keep-alives)"
                    f"{schedule.trail()}",
                )
            # Before the keep-alive click, not after: this loop can idle for the whole
            # length of a match, so it decides how long F1 takes to be obeyed. Checking
            # here also means a stop never fires one more click into the game.
            if self._should_stop():
                return (
                    "",
                    f"stopped by user after {clicks} keep-alives{schedule.trail()}",
                )
            # After the outcome look and the stop check, before the keep-alive: a due step
            # is real activity, so firing one makes the courtesy click unnecessary.
            if schedule.run_due(now, self._run_match_step):
                last_click = time.monotonic()
                continue
            if now - last_click >= max(1.0, self.won_poll_click):
                self._click_client(*PARK_CLIENT)
                clicks += 1
                last_click = time.monotonic()
            time.sleep(OUTCOME_POLL)

    def _run_match_step(self, step: UnitStep) -> bool:
        """One pass of a During match step. False means it should stop being scheduled.

        A failure here does **not** end the run. The match is still playable without an
        ability, and stopping mid-match would abandon a run that was going to win; the step
        is dropped from the schedule and said once in the log, so a broken template doesn't
        repeat the same complaint every 200ms for the rest of the match.
        """
        if step.is_sequence():
            ok, message = self.run_sequence(step)
        else:
            ok, message = self.place_unit(step)
        if not ok:
            self._log(f"During match step {step.step} failed, not repeating it: {message}")
            return False
        self._log(f"During match step {step.step}: {message}")
        return True

    def poll_outcome(self) -> tuple[str, str] | None:
        """One look for the end of the match. None while it is undecided.

        The non-blocking half of `wait_for_outcome`, for a caller that owns its own tick
        loop and interleaves this with other work. Sharing `_outcome_profiles` and
        `_outcome_is_clear` is the entire point: the run loop used to carry its own copy of
        this that built profiles from hardcoded paths at a fixed 0.70, so Settings > Vision
        changed what the tester reported and nothing about a run, and the `won 0.57,
        lost 0.71` misread had no margin to catch it.

        Never clicks and never sleeps, so the caller decides the poll rate and owns the
        keep-alive.
        """
        match = self._find_outcome()
        if match is None or not self._outcome_is_clear(match):
            return None
        lost = match.profile_name == game_lost_image()
        return (
            OUTCOME_LOST if lost else OUTCOME_WON,
            f"{'defeat' if lost else 'win'} screen ({match.score:.2f}) — {self._outcome_scores()}",
        )

    def _find_outcome(self):
        """One look for either end-of-match screen. Returns the better match, or None.

        A missing `game_lost.png` simply never matches, which is the documented
        behaviour — the win still ends the cycle.
        """
        rect = self._rect()
        if rect is None:
            return None
        return self._engine.find_first(self._outcome_profiles(), rect)

    def _outcome_is_clear(self, match) -> bool:
        """Did the winning template beat the other by enough to be believed?

        The two banners read "Game Won!" and "Game Lost!" in the same place, and matching
        is grayscale, so the coloured background that makes them obvious to a human is
        discarded. Crops that include the shared "Game " score almost identically on both
        screens; requiring a margin turns that from a wrong answer into a wait.
        """
        rect = self._rect()
        if rect is None:
            return False
        scores = sorted(
            (
                found.score
                for found in self._engine.find_all(
                    self._outcome_profiles(), rect, confidence=0.0
                )
            ),
            reverse=True,
        )
        if len(scores) < 2:
            return True  # only one template on disk: nothing to confuse it with
        return (scores[0] - scores[1]) >= OUTCOME_MARGIN

    def _outcome_profiles(self) -> list[ImageProfile]:
        """The win and defeat screens, each at **its own** tolerance.

        `confidence_for(path)`, not `ImageProfile`'s default: Settings > Vision offers a
        threshold row for Won and Lost and its Test button reports against that number, but
        this list took the 0.70 default, so tuning either one changed what the tester said
        and nothing about the run. Every other search resolves the per-template threshold
        inside `find_until`; these two are built by hand because the outcome is a race
        between two templates, which is the only reason they were ever different.
        """
        return [
            ImageProfile(
                name=path,
                image_path=self._engine.to_absolute_path(path),
                confidence=confidence_for(path),
            )
            for path in (game_won_image(), game_lost_image())
        ]

    def _outcome_scores(self) -> str:
        """Best score for each end-of-match template right now, threshold ignored.

        Diagnostic only. `find_all` with confidence 0 reports what the match *would* have
        scored, which is the number that separates "wrong crop" from "wrong screen" —
        guessing between those two is what made a missed defeat unexplainable.
        """
        rect = self._rect()
        if rect is None:
            return "Roblox not found"
        scores = {
            match.profile_name: match.score
            for match in self._engine.find_all(self._outcome_profiles(), rect, confidence=0.0)
        }
        parts = []
        for path, label in ((game_won_image(), "won"), (game_lost_image(), "lost")):
            score = scores.get(path)
            present = os.path.isfile(self._engine.to_absolute_path(path))
            if not present:
                parts.append(f"{label} template missing")
            else:
                parts.append(f"{label} {score:.2f}" if score is not None else f"{label} no read")
        return ", ".join(parts)

    # There is no `press_game_key` or `wait_for_win`. Both were public only so a Macro Tester
    # row could drive them, and that surface went with Qt. The run presses keys through
    # `_press` and reads the result through `poll_outcome`.


def split_steps(steps: list[UnitStep]) -> tuple[list[UnitStep], list[UnitStep]]:
    """Split enabled steps into (pre-placement, during-wave), order preserved.

    Pre-placement steps run before the Start Game click, because that gap is the
    only time the wave hasn't started; everything else runs after it.

    **During match steps are in neither list.** They don't become chain steps at all —
    `wait_for_outcome` repeats them from its own loop, so including them here would run
    them once at the top of the wave *and* leave them scheduled.
    """
    chain = [step for step in steps if not step.during_match]
    pre = [step for step in chain if step.preplacement]
    during = [step for step in chain if not step.preplacement]
    return (pre, during)


class _MatchSchedule:
    """When each During match step is next due, for `wait_for_outcome`'s loop.

    Per-step clocks rather than one shared tick: a 2s ability and a 30s ultimate in the
    same plan have nothing to say to each other, and a shared interval would make the
    slower one dictate the faster.

    One step per pass, in step order. Running the whole list in one pass would send a
    burst of clicks with no look at the screen between them, which is how a result gets
    missed for as long as the burst takes.
    """

    def __init__(self, steps: list[UnitStep]) -> None:
        # `wait` is the interval for these steps, not a delay before acting. Floored at
        # OUTCOME_POLL so there is always a look at the screen between two presses —
        # without it, a step left at 0 fires back-to-back and a result can only be noticed
        # in the gaps between AHK scripts.
        self._due: list[tuple[UnitStep, float]] = [
            (step, max(OUTCOME_POLL, _as_int(step.wait) / 1000.0)) for step in steps
        ]
        self._next: dict[int, float] = {}
        self._ran: dict[int, int] = {}
        self._dropped: set[int] = set()

    def run_due(self, now: float, run: Callable[[UnitStep], bool]) -> bool:
        """Run the first step that's due. True if one ran."""
        for step, interval in self._due:
            if step.step in self._dropped:
                continue
            if now < self._next.get(step.step, 0.0):
                continue
            self._next[step.step] = now + interval
            self._ran[step.step] = self._ran.get(step.step, 0) + 1
            if not run(step):
                self._dropped.add(step.step)
            return True
        return False

    def trail(self) -> str:
        """What ran, for the result line. Empty when the plan has no such steps."""
        if not self._ran:
            return "" if not self._due else " — no during-match step fired"
        parts = ", ".join(
            f"step {number} x{count}" for number, count in sorted(self._ran.items())
        )
        return f" — during match: {parts}"


def parse_wave(text: str, max_wave: int = 0) -> int | None:
    """The current wave from an OCR'd counter. None when it can't be read confidently.

    Two shapes, because the counter is drawn differently from stage to stage:

    - `"12/25"` — `parse_limit` handles it, digit confusions and separator misreads
      included. With `max_wave` set, a total that disagrees is a *misread*, not a
      different map, so the read is refused rather than acted on.
    - `"12"`, `"Wave 12"` — a bare number, and only safe because `max_wave` bounds it: a
      counter on a 25-wave map cannot say 125, so that reading is rejected instead of
      opening a gate 100 waves early.

    Refuses rather than guesses, for the same reason `parse_limit` does — this decides
    when an ability fires, and a wrong number is worse than no number.
    """
    current, total = parse_limit(text)
    if current is not None:
        if max_wave > 0 and total != max_wave:
            return None
        return current if current > 0 else None

    compact = re.sub(r"[^0-9a-zA-Z|]+", "", text or "").translate(DIGIT_FIXES)
    numbers = re.findall(r"\d{1,3}", compact)
    if len(numbers) != 1:
        return None
    value = int(numbers[0])
    ceiling = max_wave if max_wave > 0 else WAVE_MAX
    if not 1 <= value <= ceiling:
        return None
    return value


def _as_int(value: object, default: int = 0) -> int:
    """Step fields are stored as text ("" means unset), so read them defensively."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
