"""Runnable checks for the run loop's mutable state, the class of bug that has bitten most.

Every one of these pins a flag that is set on one path and has to be cleared on another. The
failure mode is always the same and always quiet: a later step reads a stale value and silently
skips or repeats work, and the log reads like a healthy run.

Three are covered:

- **`_kept_position` must not survive a rep that aborted.** It means "Repeat Stage put the
  character back where it stood, so do not walk again". `_run` clears it after the phase that
  reads it, so the two `break`s that skip that clear — Roblox gone, lobby chain failed — had to
  clear it themselves, or the *next* task's walk is suppressed on a character that respawned.
- **`_phases` must be restored after a challenge detour.** `_current_task` already was; its
  sibling was not, so the pair disagreed in the window after a detour — one naming the
  interrupted task, the other the challenge's operation.
- **The stage clock must stop when a match ends with no result.** `abandon_stage` had no caller
  at all, so a stopped or timed-out match left the clock running and the next match could report
  a duration measured from the previous one.

Nothing captures or clicks: the controller is built with `__new__` and its primitives replaced.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_run_state.py`
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.stats import StatsTracker  # noqa: E402
from sloppykeys.macro.controller import MacroController  # noqa: E402


# # `_kept_position` is consumed by the walk block, and only by it
def walk_ran(kept: bool) -> bool:
    """True when the walk_path block actually replayed a recording."""
    ctrl = MacroController.__new__(MacroController)
    fired: list[str] = []
    ctrl._ahk = type("Ahk", (), {"run": staticmethod(lambda *a, **k: fired.append("ran") or (True, "ok"))})()
    ctrl._log = lambda _m: None
    ctrl._app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ctrl._current_task = {"mode": "Portals", "map": "Summer", "stage": ""}
    ctrl._kept_position = kept
    ctrl._execute_block({"type": "walk_path", "mode": "auto"})
    return bool(fired)


assert walk_ran(kept=False), "a respawned rep must walk"
assert not walk_ran(kept=True), "a rep that kept its position must not"


# # The two aborting `break`s in `_run` clear it. Driven through the real loop with a queue of
# # one task, so the statement order is the shipped one rather than a restatement of it.
def rep_abort(fail: str) -> bool:
    """Run one task whose rep aborts, and report `_kept_position` afterwards.

    `fail` picks which guard trips: "roblox" is `_try_reopen_roblox` returning False,
    "lobby" is `_navigate_lobby` returning False.
    """
    ctrl = MacroController.__new__(MacroController)
    ctrl._log = lambda _m: None
    ctrl._stop_requested = False
    ctrl._paused = False
    ctrl._cycle = 0
    ctrl._current_task = None
    ctrl._camera_set = True
    # As if the previous rep had just taken Repeat Stage.
    ctrl._kept_position = True
    ctrl._app_root = "."
    ctrl._try_reopen_roblox = lambda: fail != "roblox"
    ctrl._navigate_lobby = lambda *a: fail != "lobby"
    ctrl._challenge_task = staticmethod(lambda _tasks: None)
    ctrl._challenge_wants_in = lambda *a, **k: False

    task = {"mode": "Story", "map": "Flower Forest", "stage": "Act 1", "repeat": 3}
    passes = {"n": 0}

    class Settings:
        def __init__(self, _root):
            pass

        def get_tasks(self):
            # One pass, then an empty queue so `_run`'s outer `while` exits.
            passes["n"] += 1
            return [task] if passes["n"] == 1 else []

    import sloppykeys.macro.controller as mod

    original = mod.UnifiedSettings
    mod.UnifiedSettings = Settings
    try:
        ctrl._run()
    finally:
        mod.UnifiedSettings = original
    return ctrl._kept_position


assert rep_abort("roblox") is False, "Roblox relaunching respawns — the next task must walk"
assert rep_abort("lobby") is False, "a half-finished lobby chain proves nothing about position"


# # The challenge detour restores `_phases` alongside `_current_task`
ctrl = MacroController.__new__(MacroController)
ctrl._log = lambda _m: None
ctrl._current_task = {"mode": "Portals", "map": "Summer"}
ctrl._phases = {"battle": ["the interrupted task's blocks"]}
before_task, before_phases = ctrl._current_task, ctrl._phases


def fake_inner(_task):
    # What the real detour does to both before returning.
    ctrl._current_task = {"mode": "Challenge", "map": "East Town"}
    ctrl._phases = {"battle": ["the challenge's blocks"]}


ctrl._run_challenge_task_inner = fake_inner
ctrl._run_challenge_task({"mode": "Challenge"})
assert ctrl._current_task is before_task, ctrl._current_task
assert ctrl._phases is before_phases, "the detour must not leave its own phases behind"


# # A detour that raises still restores both — that is what the `finally` is for
def raising_inner(_task):
    ctrl._current_task = {"mode": "Challenge"}
    ctrl._phases = {"battle": []}
    raise RuntimeError("the panel vanished")


ctrl._run_challenge_task_inner = raising_inner
try:
    ctrl._run_challenge_task({"mode": "Challenge"})
except RuntimeError:
    pass
assert ctrl._current_task is before_task
assert ctrl._phases is before_phases


# # The stage clock: abandoned, not carried into the next match
import tempfile  # noqa: E402

root = tempfile.mkdtemp(prefix="sk_state_")
tracker = StatsTracker(root)

# A match that is timed and recorded reports a duration.
tracker.start_stage()
time.sleep(0.01)
tracker.record(won=True, target="timed")
assert tracker.history()[0]["duration"] != "-"

# A match that started but was abandoned, then a *later* match that was never clocked: the
# second must not inherit the first's elapsed time. Without `abandon_stage` the clock kept
# running and `record` measured from the abandoned match's start.
tracker.start_stage()
time.sleep(0.01)
tracker.abandon_stage()
tracker.record(won=False, target="never clocked")
assert tracker.history()[0]["duration"] == "-", tracker.history()[0]
assert tracker.snapshot().stage_seconds == 0.0, "an abandoned clock must read zero, not keep ticking"

for name in os.listdir(root):
    os.remove(os.path.join(root, name))
os.rmdir(root)

print("run state: OK")
