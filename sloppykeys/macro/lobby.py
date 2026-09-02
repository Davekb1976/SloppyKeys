"""Lobby / intermission navigation.

Flow:
  1. find Play  -> move + click        (opens the intermission menu)
  2. find the selected gamemode's card -> move + click
  3. scroll to the target stage, find it -> move + click   (enters the stage)

Image search runs in Python (capture the Roblox client area, template match);
the actual mouse moves/clicks/scrolls go through AHK. Match centres come back in
screen coordinates, which is exactly what AHK needs with CoordMode Screen.

Each step is small and returns (ok, message), which the controller logs one line at a
time — so a failed chain names the step that failed and the score it reached, rather
than reporting that navigation didn't work.
"""

from __future__ import annotations

import time
from typing import Callable

from sloppykeys.content.acts import act_coord
from sloppykeys.content.challenge import (
    CHANGE_GAMEMODE_CLICK,
    CLOSE_LIST_CLICK,
    row_click,
    SELECT_STAGE_CLICK,
    START_CLICK,
)
from sloppykeys.content.gamemodes import CHALLENGE
from sloppykeys.content.start_stage import (
    difficulty_clicks,
    difficulty_coord,
    start_coords,
)
from sloppykeys.content.nav_images import (
    back_lobby_image,
    close_gamemode_image,
    close_panel_image,
    events_image,
    gamemode_image,
    match_play_image,
    play_image,
    portal_activate_image,
    portal_bag_image,
    portal_search_image,
    portal_select_portal_image,
    portals_tab_image,
    repeat_image,
    return_lobby_confirm_image,
    select_stage_image,
    stage_image,
    start_game_image,
    start_match_image,
    win_change_image,
)
from sloppykeys.content.portals import slot_coord
from sloppykeys.content.nav_route import (
    KIND_CLICK,
    KIND_EXPECT,
    KIND_FIND,
    KIND_SCROLL,
    KIND_WAIT,
    NavStep,
)
from sloppykeys.core.image_search import (
    DEFAULT_CONFIDENCE,
    ImageMatch,
    ImageSearchEngine,
    confidence_for,
    best_score,
    find_until,
)


from sloppykeys.config.keybinds import sanitize_search_text

from .input_scripts import move_script, nudge_click_script, scroll_script, type_text_script

# screen-rect provider -> (x, y, w, h) of the Roblox client area, or None.
RectProvider = Callable[[], "tuple[int, int, int, int] | None"]


class LobbyNavigator:
    def __init__(
        self,
        engine: ImageSearchEngine,
        ahk,
        roblox_rect: RectProvider,
        log: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._engine = engine
        self._ahk = ahk
        self._rect = roblox_rect
        self._log = log or (lambda _m: None)
        # Checked inside every poll loop so F1 stops a run *during* a step, not after it.
        # Only waits are abandoned — never an AHK script, which could be holding a key or a
        # mouse button and would leave the input stuck if killed mid-press.
        self._should_stop = should_stop or (lambda: False)
        # A click triggers a transition (loading screen, slide/fade-in), so a
        # search that follows one polls until a deadline instead of looking once.
        # Attempt counts were the old approach and they coupled the wait to the
        # cooldown: two looks 1.5s apart is a 1.5s budget, and a menu that
        # animates in slower than that failed the step.
        self.search_timeout = 6.0  # how long to keep looking for an expected image
        # Gap between looks. A look is ~17ms measured (capture 6ms + match 11ms), so
        # this value is mostly just how late an image gets noticed.
        self.search_poll = 0.12
        self.click_settle = 1.5   # wait after a click before the next step
        self.scroll_settle = 1.5  # wait after a scroll before searching again
        # Wait *before* the change-gamemode click. Every other blind click in here lands
        # on a screen something has already proven is up; that one lands on the panel a
        # finished match fades into, and it has no working template (`win_change.png`
        # never matched). Nothing can verify it, so it gets a wait instead.
        self.panel_fade_wait = 1.0
        # There is no `join_wait`. It was a 5s sleep after the lobby Start click, paid
        # immediately before `wait_for_match_ready`, which polls the same screen for up to
        # 60s and returns the instant it appears — so it bought nothing and cost 5s twice a
        # match. A deadline poll replaces a fixed sleep, it does not follow one.
        # Readiness is polled up to this long rather than assumed.
        self.match_ready_timeout = 60.0
        self.match_ready_poll = 1.0
        # Where to move the cursor before a search so no card is left hovered.
        # Client-space; top-left corner is usually empty of stage cards.
        self.park_client = (8, 8)
        # No `self.confidence`. The threshold is **per template**, resolved inside
        # `find_until` by `image_search.confidence_for(path)`: `DEFAULT_CONFIDENCE` (0.80)
        # unless the Image Manager overrides that one image. The *global* tolerance setting
        # that used to live here was removed for good reason — it drifted to 0.57 and
        # matched wrong screens — and there is no auto calibrate. A template that can't clear
        # the default is usually still the wrong crop.


    def apply_delays(self, delays: dict[str, float]) -> None:
        """Live-update tunable timings (from Settings > Delays).

        Takes the whole dict, keyed by DELAY_SPEC, so adding a tunable stays a
        one-line data edit instead of a signature change here and at both callers.
        """
        cooldown = float(delays.get("image_search_cooldown", self.click_settle))
        self.click_settle = cooldown
        self.scroll_settle = cooldown
        self.search_timeout = float(delays.get("search_timeout", self.search_timeout))
        self.panel_fade_wait = float(delays.get("panel_fade_wait", self.panel_fade_wait))

    # # Primitives
    def _find(
        self,
        rel_path: str,
        timeout: float = 0.0,
        region: tuple[int, int, int, int] | None = None,
    ) -> ImageMatch | None:
        """Search for a template, polling until `timeout` seconds have passed.

        A deadline rather than an attempt count: what matters is how long the UI
        is given to finish animating in, not how many times we looked. timeout=0
        is a single look, for a screen already known to be up. `region` (client
        x, y, w, h) restricts the search to a band of the client area.
        """
        return find_until(
            self._engine,
            self._rect,
            rel_path,
            timeout=timeout,
            poll=self.search_poll,
            region=region,
            # None, not a fixed number: `find_until` resolves this template's own threshold.
            confidence=None,
            should_stop=self._should_stop,
        )

    def _miss(
        self, rel_path: str, label: str, region: tuple[int, int, int, int] | None = None
    ) -> str:
        """Why a search failed, with the number that distinguishes the two reasons.

        `Play not found` on its own is unactionable. `Play not found (best 0.66 < 0.70)`
        says the crop is right and the tolerance is too tight; `(best 0.08 < 0.70)` says
        this isn't the screen anyone thought it was. One extra match, on failure only.
        """
        score = best_score(self._engine, self._rect, rel_path, region=region)
        if score is None:
            return f"{label} not found (nothing captured)"
        # The template's own threshold, so the log names the number that actually rejected
        # this match rather than the global default.
        needed = confidence_for(rel_path)
        tuned = "" if needed == DEFAULT_CONFIDENCE else " (tuned)"
        return f"{label} not found (best {score:.2f} < {needed:.2f}{tuned})"

    def _click(self, match: ImageMatch) -> tuple[bool, str]:
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        return self._ahk.run(
            nudge_click_script(match.center_x, match.center_y, park=self._park_point()),
            wait=True,
            timeout=8,
        )

    def _park_point(self) -> tuple[int, int] | None:
        """Screen point every lobby click retreats to, or None if Roblox has gone.

        Every click in here parks, because the cursor left on a button keeps it hovered and
        Roblox draws a tooltip that covers the *next* button — a Select Stage search failed
        on a tooltip raised by the click before it. In-match clicks deliberately don't park:
        there the cursor belongs where the unit is.
        """
        rect = self._rect()
        if rect is None:
            return None
        return (rect[0] + self.park_client[0], rect[1] + self.park_client[1])

    def _scroll(self, notches: int) -> tuple[bool, str]:
        return self._scroll_at(None, notches)

    def _scroll_at(
        self, point: tuple[int, int] | None, notches: int
    ) -> tuple[bool, str]:
        """Wheel at a client-space point, or the client centre when point is None.

        A point matters when the screen has more than one scrollable list: the
        events sidebar scrolls independently of the act cards, and the wheel goes
        to whichever one is under the cursor.
        """
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        if point is None:
            cx = rect[0] + rect[2] // 2
            cy = rect[1] + rect[3] // 2
        else:
            cx = rect[0] + point[0]
            cy = rect[1] + point[1]
        px = rect[0] + self.park_client[0]
        py = rect[1] + self.park_client[1]
        return self._ahk.run(scroll_script(cx, cy, px, py, notches), wait=True, timeout=8)

    def click_start_match(
        self, fallback: tuple[int, int] | None = None, fade_wait: float = 0.0
    ) -> tuple[bool, str]:
        """Find and click the lobby's Start button — the last click before the stage loads.

        A **search**, not a coordinate, because the panel it sits on is a different height
        for every stage, so its position moves. That is also why one implementation serves
        Story, Raid, Expedition and Challenge: the button is identical, only its place
        changes. Events routes can reference `images/lobby/start_match.png` in a FIND step
        for the same reason.

        `fallback` is the old fixed coordinate, used only when the template isn't on disk
        yet. Without it, adding this would break every gamemode until the PNG is captured —
        and a run that stops at Start with "not found" is indistinguishable from a broken
        chain.

        **`fade_wait` is required wherever Start arrives from the Select Stage click.**
        Start does not exist until that click lands, so the search cannot hit a stale
        button — but it *can* hit a button still fading in, which matches at 0.96 while
        being unclickable, because normalized correlation ignores a uniform brightness
        scale. Measured: `clicked Start at 944,606 (0.96)` followed by
        `Start Game not found within 60.0s`, with `start_match.png` still scoring 0.954 on
        screen 55s later — the click was swallowed and the lobby never left. See
        `_find_click`.
        """
        path = start_match_image()
        if self._engine.template_exists(path):
            return self._find_click(
                path, "Start", timeout=self.search_timeout, fade_wait=fade_wait
            )
        if fallback is None:
            return (False, f"{path} is missing and there is no fallback coordinate")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        ok, message = self._click_client(rect, fallback)
        if not ok:
            return (False, message)
        return (
            True,
            f"clicked Start at {fallback[0]},{fallback[1]} "
            f"(fixed coordinate — add {path} so it is searched instead)",
        )

    def click_select_stage(
        self, fallback: tuple[int, int] | None = None
    ) -> tuple[bool, str]:
        """Find and click the lobby's **Select Stage** button.

        This is the click that opens the panel Start sits on, so it must come first —
        Start does not exist until the stage is selected, which is why "Start wasn't
        there" was the original symptom when this step was missing.

        Searched rather than clicked blind for the same reason as Start: it lives on the
        stage/act panel, and that panel is a different height per stage, so the button
        moves. One implementation serves Story, Raid, Expedition and Challenge.

        Not `select_stage()` — that picks the *map card* from the stage list, an earlier
        step entirely. `fallback` is the old fixed coordinate, used only while the
        template is missing, so adding the search can't break a gamemode before the PNG
        is captured.
        """
        path = select_stage_image()
        if self._engine.template_exists(path):
            return self._find_click(path, "Select Stage", timeout=self.search_timeout)
        if fallback is None:
            return (False, f"{path} is missing and there is no fallback coordinate")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        ok, message = self._click_client(rect, fallback)
        if not ok:
            return (False, message)
        return (
            True,
            f"clicked Select Stage at {fallback[0]},{fallback[1]} "
            f"(fixed coordinate — add {path} so it is searched instead)",
        )

    def _park(self) -> None:
        """Move the cursor off the cards so nothing is left hovered before a search."""
        rect = self._rect()
        if rect is None or not self._ahk.available():
            return
        px = rect[0] + self.park_client[0]
        py = rect[1] + self.park_client[1]
        self._ahk.run(move_script(px, py), wait=True, timeout=5)

    # # Steps
    def find_play(self) -> tuple[bool, str]:
        return self._find_report(play_image(), "Play")

    def find_events(self) -> tuple[bool, str]:
        """Look for the lobby Events button without clicking it."""
        return self._find_report(events_image(), "Events")

    def select_challenge_row(self, slot: int) -> tuple[bool, str]:
        """Click challenge row 1-3 to select it.

        A fixed coordinate, so nothing proves it landed — the caller re-reads the panel
        to see what happened. That is why it is separate from `start_challenge`.
        """
        point = row_click(int(slot))
        if point is None:
            return (False, f"no click point for challenge row {slot}")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        ok, message = self._click_client(rect, point)
        return (ok, f"row {slot} at {point[0]},{point[1]}" if ok else message)

    def start_challenge(self, slot: int) -> tuple[bool, str]:
        """Row -> stage -> Start, the three clicks that begin challenge `slot`.

        Selecting the stage is the step that makes Start exist, so these cannot be
        reordered or skipped. All three are fixed coordinates on screens with no template
        to confirm them, so each gets a settle and the caller verifies the outcome by
        waiting for the match to load.
        """
        # `_click_client` here takes (rect, coord) — the *screen* rect first, unlike
        # `UnitPlacer._click_client(x, y)`. Passing a bare x,y made it index an int and
        # the step died with "'int' object is not subscriptable".
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")

        # Every leg is reported, like `start_stage`'s trail. This used to return only the
        # Start message, so a leg that fell back to a **fixed coordinate** said so into a
        # string nobody read — and a stale coordinate is exactly what a mysteriously
        # misplaced click looks like. If a leg says "(fixed coordinate", that is the bug.
        trail: list[str] = []

        ok, message = self.select_challenge_row(slot)
        if not ok:
            return (False, f"row {slot}: {message}")
        trail.append(f"row {slot}: {message}")
        # **This settle stays**, even though a search follows it. Picking a row changes
        # *which challenge* is armed, and nothing on screen proves the change registered —
        # so if Select Stage is already visible for the previous row, searching immediately
        # can click it before the row swap lands and start the wrong challenge. A wrong run
        # costs minutes; this costs `image_search_cooldown` once.

        # Same searched Select Stage as every other gamemode; `SELECT_STAGE_CLICK` is the
        # fallback until the template exists.
        ok, message = self.click_select_stage(SELECT_STAGE_CLICK)
        if not ok:
            return (False, f"stage select: {message}")
        trail.append(message)

        # No blind settle before the *search* — it polls, so sleeping first is pure latency.
        # The wait belongs **after** the button is found, which is what `fade_wait` does:
        # Start is arriving from the Select Stage click above and matches while still fading.
        # Same searched Start as every other gamemode — the challenge panel's height varies
        # with the map too. `START_CLICK` stays as the fallback until the template exists.
        ok, message = self.click_start_match(START_CLICK, fade_wait=self.panel_fade_wait)
        if not ok:
            return (False, f"start: {message}")
        trail.append(message)
        # No sleep here: the caller's next step is `wait_for_match_ready`, a 60s poll.
        return (True, " \u2192 ".join(trail))

    def change_gamemode(self) -> tuple[bool, str]:
        """On the panel a finished match leaves you on, open the gamemode chooser.

        **Searched** (`images/match/win_change.png`), because finding the control is the only
        thing that proves this panel has actually arrived — the panel fades in after Match
        Play, and a click fired mid-fade is swallowed, which surfaces one step later as the
        following card search failing. A deadline search returns the instant the panel is up
        and needs no `panel_fade_wait` at all.

        `CHANGE_GAMEMODE_CLICK` remains the fallback for a missing template. Both paths pay
        `panel_fade_wait` now: **the search was not the proof it was assumed to be.** It
        matched `win_change.png` at 0.93 one second after Match Play and clicked into a
        panel still fading in; the click was swallowed and the run died at the next step
        with `Challenge card not found (best 0.42)`. See `_find_click` for why a score
        cannot detect this.
        """
        path = win_change_image()
        if self._engine.template_exists(path):
            return self._find_click(
                path,
                "Change gamemode",
                timeout=self.search_timeout,
                fade_wait=self.panel_fade_wait,
            )
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        if self.panel_fade_wait > 0:
            time.sleep(self.panel_fade_wait)
        ok, message = self._click_client(rect, CHANGE_GAMEMODE_CLICK)
        if not ok:
            return (False, message)
        time.sleep(self.click_settle)
        return (
            True,
            f"change gamemode at {CHANGE_GAMEMODE_CLICK[0]},{CHANGE_GAMEMODE_CLICK[1]} "
            f"(fixed coordinate, waited {self.panel_fade_wait:.1f}s — add {path} so it is "
            f"searched instead)",
        )

    def close_challenge_list(
        self, fallback: tuple[int, int] | None = CLOSE_LIST_CLICK
    ) -> tuple[bool, str]:
        """Close the challenge list, putting the gamemode chooser back within reach.

        The list is a panel *over* the gamemode chooser, so leaving it is its own close
        button — not `change_gamemode`, which belongs to the panel a finished match lands on.
        Using the wrong one here left the macro on the challenge list and the following card
        search found nothing.

        The template is `lobby/close.png`, the X shared by every panel in the gamemode UI
        rather than one cropped per panel, with `CLOSE_LIST_CLICK` as the fallback while it is
        uncaptured — the same arrangement as `select_stage`/`start_match`. The search is what
        lets this be called on a screen the OCR scan could **not** confirm: pass
        `fallback=None` there, so a miss reports instead of firing a blind click at an unknown
        screen.

        Closing this is only half of leaving — see `close_gamemode_menu`.
        """
        path = close_panel_image()
        if self._engine.template_exists(path):
            return self._find_click(path, "Close challenge list", timeout=self.search_timeout)
        if fallback is None:
            return (False, f"{path} is missing and a blind click is not safe here")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        ok, message = self._click_client(rect, fallback)
        if not ok:
            return (False, message)
        # No settle: the caller's next step is another search, which polls until the panel is
        # gone. An early first look costs one 17ms miss, not a wrong click.
        return (
            True,
            f"closed the challenge list at {fallback[0]},{fallback[1]} "
            f"(fixed coordinate — add {path} so it is searched instead)",
        )

    def close_gamemode_menu(self) -> tuple[bool, str]:
        """Close the gamemode chooser, landing in the lobby proper.

        The second half of leaving a challenge detour. The chooser is itself a panel over the
        lobby, and **the inventory bag is on the lobby** — so stopping after
        `close_challenge_list` leaves a Portals task searching for the bag against the panel
        covering it, which is the `Bag not found (best 0.52 < 0.80)` skip. Modes that pick a
        card off the chooser never noticed.

        No fallback coordinate on purpose: none has been measured, and the lobby is a live
        screen where a blind click reaches the world. A miss reports and the caller carries
        on — the next task's own chain will fail loudly enough if this mattered.
        """
        path = close_gamemode_image()
        if not self._engine.template_exists(path):
            return (False, f"{path} is missing — capture it in the Image Manager")
        return self._find_click(path, "Close gamemode menu", timeout=self.search_timeout)

    def leave_match(self) -> tuple[bool, str]:
        """Click the in-match Play button on a finished match, which continues out of it.

        `match_play.png` is the smaller Play that only exists once you are in a stage —
        not the lobby's. It is how a result screen is left without going through the
        settings menu, and it lands on the gamemode panel, so the next task's chain
        starts from there rather than from the lobby.
        """
        return self._find_click(match_play_image(), "Match Play", timeout=self.search_timeout)

    def back_to_lobby(self) -> tuple[bool, str]:
        """Leave a finished stage the long way: Back to Lobby, then its confirmation.

        `leave_match` continues out through the in-stage Play and lands on the gamemode
        panel, which suits a task switch. This lands in the **lobby**, so the next run
        starts from Play like a fresh one — which is what Expedition needs, its victory
        screen having no Repeat to take.

        The confirmation is a dialog opened by the click before it, so it gets the fade
        wait: found is not clickable.
        """
        ok, message = self._find_click(
            back_lobby_image(), "Back to Lobby", timeout=self.search_timeout
        )
        if not ok:
            return (False, message)
        confirm_ok, confirm_message = self._find_click(
            return_lobby_confirm_image(),
            "Return to Lobby",
            timeout=self.search_timeout,
            fade_wait=self.panel_fade_wait,
        )
        if not confirm_ok:
            return (False, f"Back to Lobby clicked but {confirm_message}")
        return (True, f"{message} \u2192 {confirm_message}")

    def open_challenges(self) -> tuple[bool, str]:
        """Lobby -> Play -> the Challenges card.

        Challenges sit behind the **lobby** Play button (`images/lobby/play.png`), in the
        same gamemode menu as Story and Raid — not on the lobby itself, and not behind
        the in-match `match_play` button, which is a different, smaller Play that only
        exists once you are in a stage.

        So this is two existing steps composed: the Play click, then the card, matched
        from `images/gamemodes/challenge.png` like any other gamemode. No new mechanism —
        an earlier attempt clicked the word by OCR, which was solving a problem that
        doesn't exist once the card has a template.
        """
        ok, message = self.click_play()
        if not ok:
            return (False, f"Play: {message}")
        # No settle: `open_gamemode` parks then searches on a deadline, and the Challenge
        # card doesn't exist until Play opens the menu, so there is nothing stale to hit.
        # Both clicks in the returned message: this is two steps behind one log line, and
        # "Open challenges: Challenge card not found" left it ambiguous whether Play had
        # even worked.
        card_ok, card_message = self.open_gamemode(CHALLENGE)
        return (card_ok, f"Play {message} \u2192 {card_message}")

    def click_play(self) -> tuple[bool, str]:
        return self._find_click(play_image(), "Play", timeout=self.search_timeout)

    def open_gamemode(self, gamemode: str) -> tuple[bool, str]:
        # The gamemode menu can lag behind the Play click / loading screen, and
        # the cursor from the Play click may be hovering a card — park it first.
        self._park()
        return self._find_click(
            gamemode_image(gamemode), f"{gamemode} card", timeout=self.search_timeout
        )

    def select_stage(
        self, gamemode: str, stage: str, max_scrolls: int = 8, notches: int = 8
    ) -> tuple[bool, str]:
        path = stage_image(gamemode, stage)
        # No search region. There was a per-gamemode stage-label band
        # (`STAGE_SEARCH_REGIONS`), removed at the user's request: it was one more thing to
        # hand-measure per gamemode, it went stale the moment the viewport size changed, and
        # a band shorter than the template makes the match silently impossible. The cost is
        # a whole-client search per look, which is ~17ms.
        region = None
        # Clear any hover left by the gamemode click before the first look.
        self._park()
        # The first look owns the whole wait for the stage screen to slide/fade in.
        # Scrolling a screen that hasn't finished animating moves the list past the
        # stage before it was ever searchable, which is why the chain failed here
        # while the standalone test (screen already up) passed. Later looks are
        # single-shot: the list is up by then, we're only scrolling it into view.
        for attempt in range(max_scrolls + 1):
            match = self._find(
                path, timeout=self.search_timeout if attempt == 0 else 0.0, region=region
            )
            if match is not None:
                ok, message = self._click(match)
                if ok:
                    return (True, f"clicked {stage} ({match.score:.2f})")
                return (False, f"found {stage} but click failed: {message}")
            if attempt < max_scrolls:
                ok, message = self._scroll(notches)
                if not ok:
                    return (False, f"scroll failed: {message}")
                time.sleep(self.scroll_settle)
        return (False, f"{self._miss(path, stage, region)} after {max_scrolls} scrolls")

    def select_act(self, gamemode: str, act: str) -> tuple[bool, str]:
        """Click a fixed-position act. Coordinates are client-space; add the
        Roblox client origin to get the screen point AHK clicks."""
        coord = act_coord(gamemode, act)
        if coord is None:
            return (False, f"no act coordinates for {gamemode} / {act}")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        screen_x = rect[0] + coord[0]
        screen_y = rect[1] + coord[1]
        # Parks like every other lobby click: an act row left hovered draws a tooltip over
        # the Select Stage button that the next step has to find.
        ok, message = self._ahk.run(
            nudge_click_script(
                screen_x,
                screen_y,
                park=(rect[0] + self.park_client[0], rect[1] + self.park_client[1]),
            ),
            wait=True,
            timeout=8,
        )
        return (True, f"clicked {act}") if ok else (False, f"{act} click failed: {message}")

    def run_to_stage(self, gamemode: str, stage: str) -> tuple[bool, str]:
        for label, step in (
            ("Play", self.click_play),
            (f"{gamemode}", lambda: self.open_gamemode(gamemode)),
        ):
            ok, message = step()
            if not ok:
                return (False, f"{label}: {message}")
            time.sleep(self.click_settle)
        return self.select_stage(gamemode, stage)

    def run_to_act(self, gamemode: str, stage: str, act: str) -> tuple[bool, str]:
        ok, message = self.run_to_stage(gamemode, stage)
        if not ok:
            return (False, message)
        time.sleep(self.click_settle)
        return self.select_act(gamemode, act)

    def _click_client(
        self,
        rect,
        coord: tuple[int, int],
        button: str = "left",
        count: int = 1,
    ) -> tuple[bool, str]:
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        return self._ahk.run(
            nudge_click_script(
                rect[0] + coord[0],
                rect[1] + coord[1],
                button=button,
                count=count,
                # Park from the rect we already have rather than re-reading it.
                park=(rect[0] + self.park_client[0], rect[1] + self.park_client[1]),
            ),
            wait=True,
            timeout=8,
        )

    def set_difficulty(self, gamemode: str, difficulty: int) -> tuple[bool, str]:
        """Cycle the difficulty button up to `difficulty`.

        One button that advances 1 -> 2 -> 3 -> 1, reading 1 when the menu opens,
        so this clicks (difficulty - 1) times and does nothing for difficulty 1.
        """
        coord = difficulty_coord(gamemode)
        if coord is None:
            return (False, f"{gamemode} has no difficulty selector")
        clicks = difficulty_clicks(difficulty)
        if clicks == 0:
            return (True, f"difficulty {difficulty} (already default, no clicks)")
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")
        for index in range(clicks):
            ok, message = self._click_client(rect, coord)
            if not ok:
                return (False, f"difficulty click {index + 1}/{clicks} failed: {message}")
            time.sleep(self.click_settle)
        return (True, f"difficulty {difficulty} ({clicks} clicks)")

    def start_stage(self, gamemode: str, hard_mode: bool) -> tuple[bool, str]:
        """After an act is selected: (optional) Hard Mode, Select Stage, Start.

        **A gamemode needs no entry in `START_COORDS` to get here.** Select Stage and Start
        are template searches and one implementation serves every mode; the table only holds
        Story's Hard Mode toggle plus missing-template fallbacks. Requiring an entry is what
        stopped an Expedition run dead at `no start sequence for Expedition`, one step after
        the stage was correctly selected.
        """
        coords = start_coords(gamemode) or {}
        rect = self._rect()
        if rect is None:
            return (False, "Roblox not found")

        trail: list[str] = []
        if hard_mode and "hard_mode" in coords:
            cx, cy = coords["hard_mode"]
            self._log(f"Hard Mode: click ({cx},{cy})")
            ok, message = self._click_client(rect, coords["hard_mode"])
            if not ok:
                return (False, f"hard mode click failed: {message}")
            trail.append("hard")
            # **This settle stays.** The toggle's *state* has no template, so nothing
            # verifies it, and Select Stage is already on screen — searching immediately
            # could commit the run before Roblox registered the toggle, i.e. silently play
            # normal mode. This is the "unverifiable click" the delay exists for.
            time.sleep(self.click_settle)
        else:
            self._log(f"Hard Mode: skipped (hard_mode={hard_mode})")

        # `confirm` is the **Select Stage** button, and it is what makes Start exist — so
        # it is searched now, with the old coordinate as the fallback. Clicking it blind
        # was fine only as long as the panel never moved; it does, per stage.
        ok, message = self.click_select_stage(coords.get("confirm"))
        if not ok:
            return (False, f"select stage failed: {message}")
        trail.append("select stage")
        # No settle: Start does not exist until this click lands, so the search below has
        # nothing stale to hit and polls until the real button appears.

        # Start is searched, not clicked blind: its position depends on the stage panel's
        # height. `coords["start"]` is only the fallback for a missing template.
        # `fade_wait` for the same reason as the challenge path: Start appears as a result of
        # the click above and is matchable before it is clickable.
        ok, message = self.click_start_match(
            coords.get("start"), fade_wait=self.panel_fade_wait
        )
        if not ok:
            return (False, f"start click failed: {message}")
        trail.append("start")
        # No sleep here: the caller's next step is `wait_for_match_ready`, a 60s poll.
        return (True, f"clicked {'+'.join(trail)} ({message})")

    def result_screen_up(self) -> bool:
        """One look for the in-stage Play button: are we standing on a finished match?

        The lobby's own Play does not exist on a result screen, so a task switch has to leave
        the stage first (`leave_match`). Same single-look contract as `in_match`, and for the
        same reason: this answers "where are we", not "get there". False when the template is
        missing, so an uncaptured `match_play.png` costs the handover, not the run.
        """
        path = match_play_image()
        if not self._engine.template_exists(path):
            return False
        return self._find(path) is not None

    def in_match(self) -> bool:
        """One look for the in-match Start Game button: are we already inside a
        stage, with the wave not yet started?

        Used to decide whether a run needs the lobby chain at all — a player who
        joined the stage by hand is already past it. Deliberately a single look
        with no wait: this answers "where are we right now", not "get there".
        """
        return self._find(start_game_image()) is not None

    def click_start_game(self, timeout: float | None = None) -> tuple[bool, str]:
        """Find and click the in-match Start Game button, which begins the wave.

        Separate from wait_for_match_ready (which only looks): the same button
        starts the first match and every match after a win, so the match loop
        comes back through here.
        """
        budget = self.search_timeout if timeout is None else float(timeout)
        return self._find_click(start_game_image(), "Start Game", timeout=budget)

    def click_repeat(self, timeout: float | None = None) -> tuple[bool, str]:
        """Click **Repeat** on the victory screen, which replays the stage.

        Needed because `game_won.png` is now a crop of the victory screen's *text*: finding
        it proves the match ended, but that screen stays up until something dismisses it.
        Repeat is what dismisses it, and only after that does `start_game.png` come back —
        so the win path is game_won -> repeat -> start_game, in that order.

        A missing template is **not** a failure: it reports success with a note and leaves
        the cycle to poll for Start Game as it did before. There is no fallback coordinate
        for this one (nobody has measured it), and failing the run over an uncaptured file
        would break every gamemode the moment this shipped.
        """
        path = repeat_image()
        if not self._engine.template_exists(path):
            return (True, f"skipped Repeat — {path} is missing, waiting for Start Game instead")
        budget = self.search_timeout if timeout is None else float(timeout)
        return self._find_click(path, "Repeat", timeout=budget)

    def click_button(
        self, path: str, label: str, timeout: float = 0.0, fade_wait: float = 0.0
    ) -> tuple[bool, str]:
        """Find a control and click it once, with no check that it went away.

        For a button that stays on screen after being clicked — an Expedition node's first
        Continue does, and `click_until_gone` reads that as a click that never landed and
        fires two more into it. Something else has to be the proof; see
        `MacroController._exp_click_pair`.
        """
        return self._find_click(path, label, timeout=timeout, fade_wait=fade_wait)

    def sighted(self, path: str) -> bool:
        """One look: is this template on screen right now?

        Same contract as `in_match` and `result_screen_up` — this answers "what is up", not
        "get there". False when the file is missing, so a template nobody has captured yet
        leaves its feature inert instead of taking the run down.
        """
        if not self._engine.template_exists(path):
            return False
        return self._find(path) is not None

    def click_until_gone(
        self,
        path: str,
        label: str,
        timeout: float = 0.0,
        fade_wait: float = 0.0,
        attempts: int = 3,
    ) -> tuple[bool, str]:
        """Click a control until it stops being found.

        `_find_click` clicks once, which is right for a lobby button whose disappearance the
        next step proves anyway. It is not enough for a control the caller will look for
        again: a laggy client swallows a click without the button going anywhere, and the
        next poll then re-finds the *same* screen and reads it as a new one. For a counted
        screen that is not a slow retry, it is a wrong count.

        Not found on the first look is a miss; not found after a click is the success.
        """
        budget = max(0.0, float(timeout))
        trail = ""
        for attempt in range(1, max(1, int(attempts)) + 1):
            match = self._find(path, budget if attempt == 1 else 0.0)
            if match is None:
                if attempt == 1:
                    return (False, self._miss(path, label))
                return (True, f"{label} cleared after {attempt - 1} click(s){trail}")
            if attempt == 1 and fade_wait > 0:
                # Same reason as `_find_click`: found is not clickable, and the panel slides
                # while it fades, so the first centre goes stale.
                time.sleep(fade_wait)
                settled = self._find(path, timeout=0.0)
                if settled is not None:
                    match = settled
            ok, message = self._click(match)
            if not ok:
                return (False, f"{label} click failed: {message}")
            trail = f" ({match.score:.2f})"
            time.sleep(self.click_settle)
        return (False, f"{label} still on screen after {attempts} clicks{trail}")

    def wait_for_match_ready(self, timeout: float | None = None) -> tuple[bool, str]:
        """Block until the in-match Start Game button appears, i.e. the stage has
        finished loading and the player has control.

        This is the handover from the lobby macro to the match macro. It exists
        because `join_wait` is a fixed guess: a cold load can take much longer,
        and anything that acts before the stage is interactive (camera setup, unit
        placement) is acting on a screen that isn't there yet.
        """
        budget = self.match_ready_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + max(0.0, budget)
        path = start_game_image()
        checks = 0
        while True:
            if self._should_stop():
                return (False, f"stopped by user after {checks} checks")
            checks += 1
            match = self._find(path)
            if match is not None:
                return (True, f"stage loaded ({match.score:.2f}) after {checks} checks")
            if time.monotonic() >= deadline:
                return (
                    False,
                    f"Start Game not found within {budget:.1f}s ({checks} checks) — "
                    "still loading, or the template needs updating",
                )
            # Slept in slices so a stop is noticed within `search_poll`, not up to a whole
            # second later. This loop is the 60s one, so it dominates how slow F1 feels.
            waited = 0.0
            while waited < self.match_ready_poll:
                if self._should_stop():
                    break
                time.sleep(min(self.search_poll, self.match_ready_poll - waited))
                waited += self.search_poll

    def run_and_start(
        self,
        gamemode: str,
        stage: str,
        act: str,
        hard_mode: bool,
        difficulty: int | None = None,
    ) -> tuple[bool, str]:
        ok, message = self.run_to_act(gamemode, stage, act)
        if not ok:
            return (False, message)
        time.sleep(self.click_settle)
        # Difficulty first: it's part of choosing what to run, so it has to be set
        # before the confirm/start clicks commit the run.
        if difficulty is not None and difficulty_coord(gamemode) is not None:
            ok, difficulty_message = self.set_difficulty(gamemode, difficulty)
            if not ok:
                return (False, difficulty_message)
            time.sleep(self.click_settle)
        return self.start_stage(gamemode, hard_mode)

    def run_to_stage_and_start(
        self, gamemode: str, stage: str, hard_mode: bool, difficulty: int | None = None
    ) -> tuple[bool, str]:
        """For a gamemode with no act dimension (Expedition): stage, then start."""
        ok, message = self.run_to_stage(gamemode, stage)
        if not ok:
            return (False, message)
        time.sleep(self.click_settle)
        if difficulty is not None and difficulty_coord(gamemode) is not None:
            ok, difficulty_message = self.set_difficulty(gamemode, difficulty)
            if not ok:
                return (False, difficulty_message)
            time.sleep(self.click_settle)
        return self.start_stage(gamemode, hard_mode)

    # # Events routes
    def click_events(self) -> tuple[bool, str]:
        """Open the events list. The Events gamemode's equivalent of Play.

        The events list is its own lobby section, not a card in the gamemode menu,
        so this replaces both `click_play` and `open_gamemode` for that mode.
        """
        return self._find_click(events_image(), "Events", timeout=self.search_timeout)

    def enter_portal(self, name: str) -> tuple[bool, str]:
        """Lobby → bag → Portals tab → search the portal → Activate → Start.

        Portals has no card in the intermission menu, so none of the `click_play` chain
        applies: this is the whole route in, and it is why the mode is `own_entry`.

        The Portals tab arrives from the bag click and Activate from the picker, so both get
        `fade_wait` — found is not clickable while a panel is still fading.

        **Start is required, and it is the same button as every other mode's** — confirmed in
        game: activating a portal reveals `lobby/start_match.png`, and pressing it is what
        loads the stage. So a miss here fails the step rather than being reported and passed
        over. Letting it through would hand the caller a 60s `wait_for_match_ready` that
        cannot succeed, and the log would blame the stage for not loading instead of naming
        the button that was never found.
        """
        trail: list[str] = []
        ok, message = self._find_click(
            portal_bag_image(), "Bag", timeout=self.search_timeout
        )
        if not ok:
            return (False, f"bag: {message}")
        trail.append(message)

        ok, message = self._find_click(
            portals_tab_image(),
            "Portals tab",
            timeout=self.search_timeout,
            fade_wait=self.panel_fade_wait,
        )
        if not ok:
            return (False, f"portals tab: {message}")
        trail.append(message)

        ok, message = self.pick_portal(name, portal_activate_image(), "Activate Portal")
        if not ok:
            return (False, f"pick: {message}")
        trail.append(message)

        ok, message = self.click_start_match(fade_wait=self.panel_fade_wait)
        if not ok:
            return (False, f"start: {message}")
        trail.append(message)
        return (True, " \u2192 ".join(trail))

    def click_select_portal(self) -> tuple[bool, str]:
        """Click **Select Portal** on the victory screen, which reopens the portal picker.

        Only a won Portals match offers it — a loss consumes nothing and ends on the defeat
        screen — so a miss here is information, not a fault: it tells the caller to leave
        through the lobby instead of queueing another run.
        """
        return self._find_click(
            portal_select_portal_image(), "Select Portal", timeout=self.search_timeout
        )

    def pick_portal(
        self, name: str, confirm_path: str, confirm_label: str
    ) -> tuple[bool, str]:
        """Type a portal's name into the picker's search field and confirm it.

        The shared half of both portal chains: the bag reaches this picker through the
        inventory and confirms with **Activate Portal**, the victory screen reaches it
        through **Select Portal** and confirms with **Select**. Same field, same grid, so
        only `confirm_path` differs.

        Ordering is find-field, click, type, confirm — and the confirm is looked for
        **before** the grid is touched. That is not an optimisation: nobody has confirmed
        whether this panel needs the filtered tile clicked before its button lights up, and
        this way both layouts work. If the button is already there the tile click never
        happens; if it is not, the tile is clicked and the button is given the fade wait it
        needs as an arriving control.

        The name is sanitised **here** rather than trusted from the caller, because this is
        the one method that hands it to `SendText`. A name that doesn't survive fails the
        step: typing a repaired string could filter the grid to a different portal, and
        confirming spends it.
        """
        wanted = sanitize_search_text(name)
        if not wanted:
            return (
                False,
                f"'{name}' is not a usable portal name — letters, digits, spaces, "
                "apostrophes and hyphens only, up to 40 characters",
            )

        ok, message = self._find_click(
            portal_search_image(), "Portal search", timeout=self.search_timeout
        )
        if not ok:
            return (False, f"search field: {message}")
        if not self._ahk.available():
            return (False, "AutoHotkey v2 not found")
        # The click above parked the cursor at the corner, which does not take focus off a
        # text field — focus follows the click, not the pointer.
        # The timeout has to cover the script's own sleeps: it types one character at a time
        # with a gap between, so a long name legitimately takes longer than a short one.
        ok, message = self._ahk.run(
            type_text_script(wanted), wait=True, timeout=10.0 + len(wanted) * 0.1
        )
        if not ok:
            return (False, f"typing '{wanted}' failed: {message}")
        trail = f"typed '{wanted}'"

        # The grid filters as the name is typed, so give the confirm one look before
        # assuming a tile has to be selected.
        match = self._find(confirm_path, timeout=self.panel_fade_wait)
        if match is None:
            coord = slot_coord(1)
            if coord is None:
                return (
                    False,
                    f"{trail}, but {confirm_label} did not appear and the result slot has "
                    "no click point — set Portals · Bag grid in Settings > Debug > Click Points",
                )
            rect = self._rect()
            if rect is None:
                return (False, f"{trail}, then Roblox went away")
            ok, message = self._click_client(rect, coord)
            if not ok:
                return (False, f"{trail}, but the result slot click failed: {message}")
            trail += f", clicked slot 1 at {coord[0]},{coord[1]}"

        ok, message = self._find_click(
            confirm_path,
            confirm_label,
            timeout=self.search_timeout,
            fade_wait=self.panel_fade_wait,
        )
        if not ok:
            return (False, f"{trail}, but {message}")
        return (True, f"{trail} → {message}")

    def route_step_budget(self, step: NavStep) -> float:
        """Wall-clock a route step can legitimately need, for the runner's timeout.

        A find with scrolls is the expensive case: its first look owns the full
        search timeout and every scroll costs a wheel script plus a settle. Without
        this a long-but-healthy step gets killed by a fixed step timeout.
        """
        timeout = step.timeout or self.search_timeout
        if step.kind == KIND_FIND:
            return timeout + step.max_scrolls * (self.scroll_settle + 8.0) + 10.0
        if step.kind == KIND_EXPECT:
            return timeout + 10.0
        if step.kind == KIND_WAIT:
            return step.wait_ms / 1000.0 + 10.0
        return 20.0

    def run_route_step(self, step: NavStep) -> tuple[bool, str]:
        """Run one user-authored route step. Returns (ok, message).

        Deliberately no fallbacks: a route step that can't do its job fails the
        run. Half-navigating an event menu and then clicking a coordinate that now
        means something else is worse than stopping.
        """
        ok, why = step.is_actionable()
        if not ok:
            return (False, why)

        if step.kind == KIND_WAIT:
            time.sleep(step.wait_ms / 1000.0)
            return (True, f"waited {step.wait_ms}ms")

        if step.kind == KIND_SCROLL:
            return self._scroll_at(step.scroll_point(), step.notches)

        if step.kind == KIND_CLICK:
            rect = self._rect()
            if rect is None:
                return (False, "Roblox not found")
            ok, message = self._click_client(
                rect, (step.x, step.y), button=step.button, count=step.count
            )
            if not ok:
                return (False, f"click ({step.x},{step.y}) failed: {message}")
            return (True, f"clicked {step.x},{step.y}")

        timeout = step.timeout or self.search_timeout
        region = step.region()

        if step.kind == KIND_EXPECT:
            match = self._find(step.image, timeout=timeout, region=region)
            if match is None:
                return (False, f"{step.image} not on screen within {timeout:.1f}s")
            return (True, f"saw {step.image} ({match.score:.2f})")

        # KIND_FIND: the select_stage pattern, generalised. The first look owns the
        # whole timeout so a screen still animating in gets time to arrive; later
        # looks are single-shot because by then we're only scrolling it into view.
        self._park()
        for attempt in range(step.max_scrolls + 1):
            match = self._find(
                step.image, timeout=timeout if attempt == 0 else 0.0, region=region
            )
            if match is not None:
                ok, message = self._click(match)
                if not ok:
                    return (False, f"found {step.image} but click failed: {message}")
                return (True, f"clicked {step.image} ({match.score:.2f})")
            if attempt < step.max_scrolls:
                ok, message = self._scroll_at(step.scroll_point(), step.notches)
                if not ok:
                    return (False, f"scroll failed: {message}")
                time.sleep(self.scroll_settle)
        scrolled = f" after {step.max_scrolls} scrolls" if step.max_scrolls else ""
        return (False, f"{step.image} not found{scrolled}")

    # # Helpers
    def _find_report(self, path: str, label: str) -> tuple[bool, str]:
        match = self._find(path)
        if match is None:
            return (False, self._miss(path, label))
        return (True, f"{label} at {match.center_x},{match.center_y} ({match.score:.2f})")

    def _find_click(
        self, path: str, label: str, timeout: float = 0.0, fade_wait: float = 0.0
    ) -> tuple[bool, str]:
        """Search for a control and click it. `fade_wait` is for a control that appears as
        part of a transition we just triggered.

        **Finding a template does not prove the element is interactive.**
        `cv2.matchTemplate`'s normalized correlation is invariant to a uniform brightness
        scale, so an element at 40% opacity part-way through a fade-in still scores ~0.93.
        A click fired then is swallowed by Roblox and the failure surfaces one step later,
        as the *next* search reporting a screen that isn't there (`best 0.42 < 0.70`).
        No score threshold can tell the two apart — only time can, hence a real wait.

        Pass `fade_wait` only where the element is *arriving*; a control on a screen that
        was already up needs none, and paying it everywhere would add seconds per run.
        The re-find afterwards is because a panel usually slides while it fades, which
        makes the first centre stale; a single look, and the first match stands if it misses.
        """
        match = self._find(path, timeout)
        if match is None:
            return (False, self._miss(path, label))
        waited = ""
        if fade_wait > 0:
            time.sleep(fade_wait)
            settled = self._find(path, timeout=0.0)
            if settled is not None:
                match = settled
            waited = f", after {fade_wait:.1f}s fade wait"
        ok, message = self._click(match)
        if not ok:
            return (False, f"{label} click failed: {message}")
        if waited:
            return (
                True,
                f"clicked {label} at {match.center_x},{match.center_y} "
                f"({match.score:.2f}{waited})",
            )
        # The score goes in the message because these templates are small text crops
        # (`challenge.png` is 67x12) searched over the whole client, so a weak
        # hit is a plausible false positive — and a click reported without its score
        # can't be told apart from a good one after the fact.
        return (
            True,
            f"clicked {label} at {match.center_x},{match.center_y} ({match.score:.2f})",
        )
