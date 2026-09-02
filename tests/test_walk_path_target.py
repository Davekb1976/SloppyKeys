"""Runnable checks that Auto resolves the walk path of the target actually being played.

Two bugs met here. A challenge preempts a task now, and `_run_challenge_task` did not set
`_current_task`, so the whole detour ran while that still described the *interrupted* task —
a Story challenge walked the Portals playfield's route because the interrupted task was
Portals/Summer. And a challenge that did carry its own map found no route at all, because
the routes are keyed under Story.

No framework, no capture, no input.

`.venv\\Scripts\\python.exe tests\\test_walk_path_target.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.walk_paths import (  # noqa: E402
    BORROWED_ROUTES,
    DEFAULT_WALK_PATHS,
    default_walk_path,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402


# # A mode's own rows still win
assert default_walk_path("Story", "East Town", "Act 1") == "East Town"
assert default_walk_path("Raid", "Spirit City", "Act 2") == "Spirit City Act 2"
assert default_walk_path("Raid", "Spirit City", "Act 1") == "", "no row, no walk"
assert default_walk_path("Portals", "Summer", "") == "Summer"

# # A side task borrows the routes of the mode whose maps it plays
# Challenge rotates through Story's maps on the same playfields, so it spawns where Story
# spawns — the same reason it reads Story's placement backdrops.
assert BORROWED_ROUTES == {"Challenge": "Story"}, BORROWED_ROUTES
assert default_walk_path("Challenge", "East Town", "") == "East Town"
assert default_walk_path("Challenge", "East Town", "Act 3") == "East Town"
# A Story map with no route of its own still has none as a challenge.
assert default_walk_path("Challenge", "School Grounds", "") == ""
# The borrowing is one hop and one direction: Story does not pick up Challenge's rows, and
# nothing else borrows.
assert default_walk_path("Story", "Summer", "") == ""
assert default_walk_path("Expedition", "East Town", "") == "", "Expedition's spawn differs"

# # No cross-mode collision: a route belongs to the mode that keys it
for key in DEFAULT_WALK_PATHS:
    assert key.count("/") in (1, 2), key


# # The detour runs with the challenge as the current task, and restores the caller's
class Recorder(MacroController):
    def __init__(self) -> None:  # noqa: D107 - test double
        self._current_task = None
        self.seen: list[dict | None] = []

    def _run_challenge_task_inner(self, task):
        # What every downstream reader would see mid-detour.
        self.seen.append(self._current_task)


ctrl = Recorder()
interrupted = {"mode": "Portals", "map": "Summer", "stage": ""}
ctrl._current_task = interrupted
challenge = {"mode": "Challenge", "challenge_slots": [True, True, True]}
ctrl._run_challenge_task(challenge)

assert ctrl.seen == [challenge], ctrl.seen
assert ctrl.seen[0]["mode"] == "Challenge", "the detour must not look like the interrupted task"
assert ctrl._current_task is interrupted, "the interrupted task has to come back"

# Restored even when the detour raises, or one bad scan would leave the queue mistaken about
# what it is playing for the rest of the run.
class Exploder(Recorder):
    def _run_challenge_task_inner(self, task):
        raise RuntimeError("scan blew up")


ctrl = Exploder()
ctrl._current_task = interrupted
try:
    ctrl._run_challenge_task(challenge)
except RuntimeError:
    pass
assert ctrl._current_task is interrupted, "restored on the exception path too"

print("walk path target: OK")
