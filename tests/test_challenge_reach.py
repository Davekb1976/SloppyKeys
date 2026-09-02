"""Runnable checks that a due challenge is actually reachable between matches.

Two faults made the preempt unreachable in practice, and together they meant a challenge that
came due during a Portals or Story run was simply never played:

- **The detour only knew how to start from the lobby.** `Play → Challenge card`. But a detour is
  taken *between matches*, so the game is usually on a result screen, where the lobby's Play does
  not exist. It reported "couldn't reach the challenge panel" while that screen's own Play sat
  there. From a result screen the route is Match Play → Change gamemode → Challenge card, which
  lands on the same chooser.
- **The tail started the next match first.** Select Portal and Repeat Stage both put the game back
  into a stage, so by the time the preempt ran there was a match in flight and nothing to navigate.
  A rep now ends at the result screen or the lobby whenever a challenge is due.

Nothing captures or clicks: the navigator is a fake recording its trail.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_challenge_reach.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController  # noqa: E402


class Nav:
    """A navigator that is either on a result screen or in the lobby."""

    def __init__(self, on_result: bool) -> None:
        self.on_result = on_result
        self.trail: list[str] = []
        self.click_settle = 0.0

    def result_screen_up(self):
        return self.on_result

    def _step(self, name):
        self.trail.append(name)
        return (True, "ok")

    def leave_match(self):
        return self._step("leave_match")

    def change_gamemode(self):
        return self._step("change_gamemode")

    def click_play(self):
        return self._step("click_play")

    def open_gamemode(self, mode):
        return self._step(f"open:{mode}")


def route(on_result: bool) -> list[str]:
    ctrl = MacroController.__new__(MacroController)
    ctrl._nav = Nav(on_result)
    ctrl._log = lambda _m: None
    ctrl._checkpoint = lambda: False
    assert ctrl._navigate_to_challenge() is True
    return ctrl._nav.trail


# From the lobby, the Play button is the way in and there is no match to leave.
assert route(on_result=False) == ["click_play", "open:Challenge"], route(False)
# From a finished match, leave first — and **do not** search for the lobby's Play, which is not
# on that screen. Change gamemode opens the same chooser the card lives on.
assert route(on_result=True) == [
    "leave_match",
    "change_gamemode",
    "open:Challenge",
], route(True)
assert "click_play" not in route(on_result=True), "the lobby Play is not on a result screen"


# # The tail must not chain another match when a challenge is due
def tail_again(challenge_due: bool, repeat: int = 10, rep: int = 0) -> bool:
    """The `again`/`more_reps` decision the rep tail makes, driven through the real loop.

    Returns whether the next match was chained (Repeat clicked / Select Portal taken).
    """
    ctrl = MacroController.__new__(MacroController)
    chained: list[str] = []
    ctrl._log = lambda _m: None
    ctrl._stop_requested = False
    ctrl._paused = False
    ctrl._cycle = 0
    ctrl._current_task = None
    ctrl._camera_set = True
    ctrl._kept_position = False
    ctrl._app_root = "."
    ctrl._try_reopen_roblox = lambda: True
    ctrl._navigate_lobby = lambda *a: True
    ctrl._run_phase_linear = lambda _blocks: None
    ctrl._run_match = lambda *a: None
    ctrl._placer = type("P", (), {"park": staticmethod(lambda: None)})()
    ctrl._stats = type("S", (), {"start_stage": staticmethod(lambda: None)})()
    ctrl._phases = {}

    challenge = {"mode": "Challenge", "challenge_slots": [True, True, True]}
    target = {"mode": "Story", "map": "Flower Forest", "stage": "Act 1", "repeat": repeat}

    # Due only at the tail, never at the rep top — otherwise the detour runs instead and the
    # tail is never reached, which is a different path.
    seen_top = {"n": 0}

    def wants_in(_task, now=None):
        seen_top["n"] += 1
        # The first call each rep is the preempt at the top; the second is the tail's own ask.
        return challenge_due and seen_top["n"] % 2 == 0

    ctrl._challenge_task = staticmethod(lambda _tasks: challenge)
    ctrl._challenge_wants_in = wants_in
    ctrl._run_challenge_task = lambda _t: chained.append("detour")
    ctrl._nav = type(
        "N",
        (),
        {
            "click_start_game": staticmethod(lambda: (True, "ok")),
            "click_repeat": staticmethod(lambda: (chained.append("repeat"), (True, "ok"))[1]),
        },
    )()

    passes = {"n": 0}

    class Settings:
        def __init__(self, _root):
            pass

        def get_tasks(self):
            passes["n"] += 1
            return [target, challenge] if passes["n"] == 1 else []

    import sloppykeys.macro.controller as mod

    original = mod.UnifiedSettings
    mod.UnifiedSettings = Settings
    original_load = mod.load_operation
    mod.load_operation = lambda *a: {"phases": {}}
    try:
        ctrl._run()
    finally:
        mod.UnifiedSettings = original
        mod.load_operation = original_load
    return "repeat" in chained


# Nothing due: the rep chains into the next match through Repeat, as it always has.
assert tail_again(challenge_due=False) is True, "a normal rep must still take Repeat"
# Due: the rep ends on the result screen so the preempt has something it can navigate from.
assert tail_again(challenge_due=True) is False, "a due challenge must not be handed a live match"

print("challenge reach: OK")
