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

import time
import os
from typing import Callable

from sloppykeys.content.nav_images import game_lost_image, game_won_image, unit_ui_image
from sloppykeys.content.start_position import PositionMove
from sloppykeys.content.units import (
    ACTION_CLICK,
    ACTION_DRAG,
    ACTION_KEY,
    ACTION_MOVE,
    ACTION_SCROLL,
    ACTION_WAIT,
    AUTOUPGRADE_CYCLE,
    PRIORITY_OPTIONS,
    StepAction,
    UnitStep,
    autoupgrade_is_on,
    autoupgrade_presses,
    slot_index,
)
from sloppykeys.core.image_search import (
    ImageProfile,
    ImageSearchEngine,
    clamp_confidence,
    confidence_for,
    find_until,
)

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

    def press_game_key(self, action: str, count: int = 1) -> tuple[bool, str]:
        """Send one of the in-game keys (priority / upgrade / sell / autoupgrade).
        Public so a Macro Tester row can exercise a single key on its own."""
        key = self._game_keys().get(action, "")
        if not key:
            return (False, f"no key bound for '{action}'")
        ok, message = self._press(key, count=count)
        return (ok, message if not ok else f"pressed '{key}' x{max(1, count)}")

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
        self._click_client(*PARK_CLIENT)

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
        """Run a sequence step's raw actions in order."""
        for position, action in enumerate(step.actions, start=1):
            ok, message = self.run_action(action)
            if not ok:
                return (False, f"action {position} ({action.type}): {message}")
        return (True, f"{len(step.actions)} actions")

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
    def wait_for_outcome(self, timeout: float | None = None) -> tuple[str, str]:
        """Park the cursor and idle until the match ends.

        Returns (outcome, message) where outcome is OUTCOME_WON, OUTCOME_LOST, or
        "" on timeout. Clicks the empty corner every `won_poll_click` seconds:
        that's not cosmetic, it keeps Roblox from idle-kicking the session and
        shows the user the macro is alive rather than hung.

        The loss template is optional — with no `game_lost.png` on disk a defeat
        simply isn't recognised and this waits out its budget.
        """
        budget = self.won_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, budget)
        self._park()
        clicks = 0
        last_click = time.monotonic()
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
                    f"at {match.left},{match.top} — {self._outcome_scores()}",
                )
            now = time.monotonic()
            if now >= deadline:
                return ("", f"no result within {budget:.0f}s ({clicks} keep-alives)")
            # Before the keep-alive click, not after: this loop can idle for the whole
            # length of a match, so it decides how long F1 takes to be obeyed. Checking
            # here also means a stop never fires one more click into the game.
            if self._should_stop():
                return ("", f"stopped by user after {clicks} keep-alives")
            if now - last_click >= max(1.0, self.won_poll_click):
                self._click_client(*PARK_CLIENT)
                clicks += 1
                last_click = time.monotonic()
            time.sleep(OUTCOME_POLL)

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

    def wait_for_win(self, timeout: float | None = None) -> tuple[bool, str]:
        """(ok, message) form for a Macro Tester row. A defeat is a pass too: the
        row is checking that the macro can *see* the end of a match."""
        outcome, message = self.wait_for_outcome(timeout)
        if not outcome:
            return (False, message)
        return (True, f"{outcome}: {message}")


def split_steps(steps: list[UnitStep]) -> tuple[list[UnitStep], list[UnitStep]]:
    """Split enabled steps into (pre-placement, during-wave), order preserved.

    Pre-placement steps run before the Start Game click, because that gap is the
    only time the wave hasn't started; everything else runs after it.
    """
    pre = [step for step in steps if step.preplacement]
    during = [step for step in steps if not step.preplacement]
    return (pre, during)


def _as_int(value: object, default: int = 0) -> int:
    """Step fields are stored as text ("" means unset), so read them defensively."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
