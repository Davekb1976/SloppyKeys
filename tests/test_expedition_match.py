"""Runnable check for Expedition's mid-match decisions.

No framework: `.venv\\Scripts\\python.exe tests\\test_expedition_match.py`.

Three silent failures live here. Checking Continue before Extract declines an offer without
ever counting it, so a task asking for the third checkpoint plays forever. Counting a
checkpoint that is merely *still on screen* as a new sighting extracts a run early, which
cannot be undone. And acting on anything found behind the upgrade card clicks the card
instead, which looks in the log exactly like a click that worked.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.expedition import (  # noqa: E402
    ACCEPT_EXTRACT,
    CARD,
    CONTINUE,
    CONTINUE_WAVE,
    DECLINE_EXTRACT,
    DISMISS_CARD,
    EXTRACT,
    EXTRACT_ATTEMPTS_BEFORE_PLAYING_ON,
    NOTHING,
    RESTART_ROUND,
    SIGHTING_DEBOUNCE,
    START_GAME,
    ExpeditionMatch,
    extract_after_from_task,
)


def test_priority() -> None:
    match = ExpeditionMatch(extract_after=1)
    # The card covers the buttons, so it is handled before anything found behind it.
    assert match.decide({CARD, CONTINUE, EXTRACT, START_GAME}, 100.0)[0] == DISMISS_CARD
    # Nothing was counted while the card was up.
    assert match.sightings == 0
    # A mid-match Start Game outranks a checkpoint: the board has been reset.
    assert match.decide({START_GAME, CONTINUE}, 101.0)[0] == RESTART_ROUND
    # Extract outranks the Continue sitting beside it.
    assert match.decide({EXTRACT, CONTINUE}, 102.0)[0] == ACCEPT_EXTRACT
    assert match.decide(set(), 103.0) == (NOTHING, "")


def test_offer_counting() -> None:
    match = ExpeditionMatch(extract_after=3)
    # One offer, still on screen across four looks a second apart: one sighting.
    for tick in range(4):
        action, _ = match.decide({EXTRACT}, 200.0 + tick)
        assert action == DECLINE_EXTRACT
    assert match.sightings == 1
    # A later checkpoint, past the debounce, is a new offer.
    match.decide({EXTRACT}, 200.0 + SIGHTING_DEBOUNCE + 10)
    assert match.sightings == 2
    action, note = match.decide({EXTRACT}, 200.0 + 2 * (SIGHTING_DEBOUNCE + 10))
    assert match.sightings == 3
    assert action == ACCEPT_EXTRACT, note
    # Waves between checkpoints are just Continues.
    assert match.decide({CONTINUE}, 400.0)[0] == CONTINUE_WAVE


def test_playing_on() -> None:
    match = ExpeditionMatch(extract_after=1)
    assert match.decide({EXTRACT}, 300.0)[0] == ACCEPT_EXTRACT
    for _ in range(EXTRACT_ATTEMPTS_BEFORE_PLAYING_ON):
        match.note_extract_failed()
    assert match.playing_on
    # Extraction is a party decision: once it will not take, stop asking and play on.
    action, note = match.decide({EXTRACT}, 400.0)
    assert action == DECLINE_EXTRACT, note


def test_restage_once() -> None:
    match = ExpeditionMatch()
    assert match.note_restage() is True
    # A chatty popup must not rewind the phase over and over.
    assert match.note_restage() is False


def test_task_field() -> None:
    assert extract_after_from_task(None) == 1
    assert extract_after_from_task("") == 1
    assert extract_after_from_task("junk") == 1
    assert extract_after_from_task(0) == 1
    assert extract_after_from_task(-4) == 1
    assert extract_after_from_task("3") == 3


class _StubNav:
    """Just enough navigator to prove the wiring: what is on screen, and what got clicked."""

    search_timeout = 6.0
    search_poll = 0.01
    panel_fade_wait = 0.0
    click_settle = 0.0

    def __init__(self, on_screen: set[str]) -> None:
        self.on_screen = on_screen
        self.clicked: list[str] = []

    def sighted(self, path: str) -> bool:
        return os.path.basename(path) in self.on_screen

    def click_until_gone(self, path, label, timeout=0.0, fade_wait=0.0, attempts=3):
        name = os.path.basename(path)
        self.clicked.append(name)
        self.on_screen.discard(name)
        return (True, f"{label} cleared")

    def click_start_game(self, timeout=None):
        self.clicked.append("start_game.png")
        self.on_screen.discard("start_game.png")
        return (True, "clicked")


def _controller(on_screen: set[str], task: dict | None = None) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    ctrl._log = lambda _m: None
    ctrl._paused = False
    ctrl._stop_requested = False
    ctrl._current_task = task if task is not None else {"mode": "Expedition"}
    ctrl._nav = _StubNav(on_screen)
    ctrl._exp_next_check = 0.0
    ctrl._exp = ctrl._expedition_state()
    return ctrl


def test_only_expedition_gets_a_state() -> None:
    # Every other gamemode must come out None, or Story pays four searches a second.
    for mode in ("Story", "Raid", "Challenge", "Events", ""):
        assert _controller(set(), {"mode": mode})._exp is None
    ctrl = _controller(set(), {"mode": "Expedition", "extract_after": "2"})
    assert ctrl._exp is not None and ctrl._exp.extract_after == 2


def test_wave_dispatch() -> None:
    ctrl = _controller({"exp_continue.png", "exp_continue_2.png"})
    assert ctrl._expedition_tick() is None
    # The wave Continue, then the second Continue on the panel it opens.
    assert ctrl._nav.clicked == ["exp_continue.png", "exp_continue_2.png"]


def test_extract_dispatch() -> None:
    ctrl = _controller({
        "exp_extract.png", "exp_extract_confirm.png", "exp_extract_final.png",
    })
    # The whole chain, and only then a win — the last look proves Extract is gone.
    assert ctrl._expedition_tick() == "win"
    assert ctrl._nav.clicked == [
        "exp_extract.png", "exp_extract_confirm.png", "exp_extract_final.png",
    ]


def test_extract_that_never_registers() -> None:
    class _StickyNav(_StubNav):
        def click_until_gone(self, path, label, timeout=0.0, fade_wait=0.0, attempts=3):
            name = os.path.basename(path)
            self.clicked.append(name)
            # Extract stays up: the click landed but the game never took it.
            if name != "exp_extract.png":
                self.on_screen.discard(name)
            return (True, f"{label} cleared")

    ctrl = _controller(set())
    ctrl._nav = _StickyNav({
        "exp_extract.png", "exp_extract_confirm.png", "exp_extract_continue.png",
    })
    # Not a win, and not a stall either: it declines so the run keeps moving.
    assert ctrl._expedition_tick() is None
    assert ctrl._exp.failed_extracts == 1
    assert "exp_extract_continue.png" in ctrl._nav.clicked


def test_restage_dispatch() -> None:
    ctrl = _controller({"start_game.png"})
    assert ctrl._expedition_tick() == "restage"
    assert ctrl._nav.clicked == ["start_game.png"]
    # Second time: handled, but the phase is not rewound again.
    ctrl._exp_next_check = 0.0
    ctrl._nav.on_screen.add("start_game.png")
    assert ctrl._expedition_tick() is None


def test_reset_battle_state() -> None:
    ctrl = MacroController.__new__(MacroController)
    ctrl._upgrade_state = {123: {"remaining": 0}}
    ctrl._wave_check_time = 999.0
    ctrl._reset_battle_state()
    # A replay must find no spent upgrade blocks, or it places units it never upgrades.
    assert ctrl._upgrade_state == {}
    assert ctrl._wave_check_time == 0.0


def main() -> None:
    test_priority()
    test_offer_counting()
    test_playing_on()
    test_restage_once()
    test_task_field()
    test_only_expedition_gets_a_state()
    test_wave_dispatch()
    test_extract_dispatch()
    test_extract_that_never_registers()
    test_restage_dispatch()
    test_reset_battle_state()
    print("OK: Expedition decisions and dispatch")


if __name__ == "__main__":
    main()
