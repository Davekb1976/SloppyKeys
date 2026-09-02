"""Runnable checks that a challenge is taken by availability, not by queue position.

Challenge stays a queue task so it can be configured — per-map macros, per-slot enables —
but its position must not decide *when* it runs: the maps re-roll every half hour, and a
target task with a high repeat count can hold the queue for hours.

The termination cases are the ones worth pinning. `_challenge_wants_in` runs before every
match, so anything that makes it answer yes forever would stop the queue advancing at all:
a row the panel offers but the task cannot play, a panel that will not read, a row already
played this rotation.

Every call takes an explicit clock. Against the wall clock the re-roll case cannot be
exercised at all — the code would re-read the real time and undo the boundary the test set.

No framework, no capture, no input: the controller is built with `__new__`.

`.venv\\Scripts\\python.exe tests\\test_challenge_priority.py`
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.challenge import (  # noqa: E402
    STATE_EXHAUSTED,
    STATE_RUNNABLE,
    ChallengeRead,
    ChallengeTracker,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402

TASK = {
    "mode": "Challenge",
    "challenge_slots": [True, True, True],
    "challenge_macros": {"School Grounds": "sg plan", "Flower Forest": "ff plan"},
}

# Both are rotation boundaries, so T1 is a different rotation from T0.
T0 = datetime(2026, 1, 1, 12, 0, 0)
T1 = datetime(2026, 1, 1, 12, 30, 0)


def controller(reads=None, attempted=False) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    ctrl._challenges = ChallengeTracker()
    ctrl._challenges.note_time(T0)
    if attempted:
        ctrl._challenges.note_scan_attempt(T0)
    if reads is not None:
        ctrl._challenges.note_reads(reads)
    # Captured rather than discarded: a silent decline is the fault this half of the file
    # covers, so the lines are part of the behaviour under test.
    ctrl.lines = []
    ctrl._log = ctrl.lines.append
    ctrl._challenge_decline = ""
    return ctrl


def read(slot: int, map_name: str, state: str = STATE_RUNNABLE) -> ChallengeRead:
    return ChallengeRead(slot=slot, map_name=map_name, state=state)


# # Which task is the challenge one
assert MacroController._challenge_task([{"mode": "Story"}, TASK]) is TASK
assert MacroController._challenge_task([{"mode": "Story"}]) is None
first = {"mode": "Challenge", "id": "a"}
assert MacroController._challenge_task([first, {"mode": "Challenge", "id": "b"}]) is first


# # Nothing looked at yet this rotation: worth one detour, wherever Challenge sits
ctrl = controller()
assert ctrl._challenge_wants_in(TASK, T0) is True

# # A failed look still counts as a look, so an unreadable panel costs one detour, not one
# per match — this is the case that would otherwise stall the queue completely.
ctrl = controller(attempted=True)
assert ctrl._challenge_wants_in(TASK, T0) is False


# # A row the panel offers but this task cannot play is not work
# Offered on a map with no macro assigned:
ctrl = controller(reads=[read(1, "King's Tomb")], attempted=True)
assert ctrl._challenge_playable(TASK) == []
assert ctrl._challenge_wants_in(TASK, T0) is False

# Offered, macro assigned, but the user switched that slot off:
off = dict(TASK, challenge_slots=[False, True, True])
ctrl = controller(reads=[read(1, "School Grounds")], attempted=True)
assert ctrl._challenge_playable(off) == []
assert ctrl._challenge_wants_in(off, T0) is False

# Offered, enabled, macro assigned: real work.
ctrl = controller(reads=[read(1, "School Grounds")], attempted=True)
assert [r.slot for r in ctrl._challenge_playable(TASK)] == [1]
assert ctrl._challenge_wants_in(TASK, T0) is True

# An exhausted row is not offered at all, so a spent daily limit stops the detours.
ctrl = controller(reads=[read(1, "School Grounds", STATE_EXHAUSTED)], attempted=True)
assert ctrl._challenge_wants_in(TASK, T0) is False


# # Played rows retire for the rotation, and the re-roll brings the panel back
ctrl = controller(reads=[read(1, "School Grounds"), read(2, "Flower Forest")], attempted=True)
assert [r.slot for r in ctrl._challenge_playable(TASK)] == [1, 2]
ctrl._challenges.mark_done(1)
assert [r.slot for r in ctrl._challenge_playable(TASK)] == [2]
ctrl._challenges.mark_done(2)
assert ctrl._challenge_playable(TASK) == []
assert ctrl._challenge_wants_in(TASK, T0) is False, "a spent rotation must let the queue run"

# Crossing a :00/:30 boundary clears the marks and the stale reads, so the panel is worth
# another look. This is "the maps reset mid-match", decided on the clock with no capture.
assert ctrl._challenge_wants_in(TASK, T1) is True


# # A decline says why, once per reason
# (The label the history card shares is checked in tests/test_run_history.py.)
# Silence here is what made "it didn't go to challenge" undiagnosable: a spent rotation, an
# unreadable panel and a missing macro assignment all logged nothing at all.

# Rows offered but none this task can play — the macro assignments are the fix.
ctrl = controller(reads=[read(1, "King's Tomb")], attempted=True)
assert ctrl._challenge_wants_in(TASK, T0) is False
assert len(ctrl.lines) == 1, ctrl.lines
assert "no enabled slot has a macro assigned" in ctrl.lines[0], ctrl.lines
assert "slot 1 King's Tomb" in ctrl.lines[0], ctrl.lines

# Asked again with nothing changed: no second line. Asked twice per match, so a line per ask
# would bury a long run.
assert ctrl._challenge_wants_in(TASK, T0) is False
assert len(ctrl.lines) == 1, ctrl.lines

# The rotation spent, with reads on hand — a different reason, so it is said.
ctrl = controller(reads=[read(1, "School Grounds")], attempted=True)
ctrl._challenges.mark_done(1)
assert ctrl._challenge_wants_in(TASK, T0) is False
assert len(ctrl.lines) == 1, ctrl.lines
assert "nothing playable this rotation" in ctrl.lines[0], ctrl.lines

# Visited and read nothing — the OCR boxes are the fix, not the assignments, so it must not
# report the same reason as the two above.
ctrl = controller(attempted=True)
assert ctrl._challenge_wants_in(TASK, T0) is False
assert len(ctrl.lines) == 1, ctrl.lines
assert "read nothing" in ctrl.lines[0], ctrl.lines

# # The re-roll is announced
# `note_time`'s return value was discarded, so the one event the whole preempt exists to catch
# left no trace. It is only a re-roll on the *second* rotation seen — the first sets the clock.
ctrl = controller(reads=[read(1, "School Grounds")], attempted=True)
ctrl._challenges.mark_done(1)
assert ctrl._challenge_wants_in(TASK, T0) is False
rolled = len(ctrl.lines)
assert ctrl._challenge_wants_in(TASK, T1) is True
assert any("re-rolled" in line for line in ctrl.lines[rolled:]), ctrl.lines
# A yes never reports a decline.
assert not any("not detouring" in line for line in ctrl.lines[rolled:]), ctrl.lines

print("challenge priority: OK")
