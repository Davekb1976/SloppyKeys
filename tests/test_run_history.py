"""Runnable checks for the Dashboard's Run History card: what gets written, and what reads back.

The card was markup with nothing behind it — no renderer, no bridge method, no producer — so it
showed its hardcoded "No runs yet" from the day it was authored. These pin the two halves that
now exist: `StatsTracker.record` appending a row, and `history()` handing it back newest first.

Three properties matter more than the happy path:

- **Bounded.** A farm left overnight finishes hundreds of matches, and `settings.json` is read
  whole on every unrelated settings edit, so the list is trimmed on write.
- **One write.** The counters and the new row go into a single `update_json` mutate. Two calls
  would take the shared lock twice and a UI save landing between them would count a result
  without listing it.
- **Rows are untrusted.** The file is user-editable and older builds wrote no list at all, so a
  bad shape is dropped rather than repaired — an invented row is a match that never happened.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_run_history.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.stats import (  # noqa: E402
    HISTORY_KEY,
    HISTORY_LIMIT,
    STATS_KEY,
    StatsTracker,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402

root = tempfile.mkdtemp(prefix="sk_history_")
path = os.path.join(root, "settings.json")


def stored() -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# # A fresh tracker has nothing to show, and says so with an empty list rather than a fake row
tracker = StatsTracker(root)
assert tracker.history() == []

# # A win and a loss, newest first
tracker.start_stage()
tracker.record(won=True, target="Portals / Summer")
tracker.record(won=False, target="Story / Flower Forest / Act 1")

rows = tracker.history()
assert [r["result"] for r in rows] == ["Loss", "Win"], rows
assert rows[0]["target"] == "Story / Flower Forest / Act 1", rows[0]
assert rows[1]["target"] == "Portals / Summer", rows[1]
# The clocked match has a duration; the one that was never started reads "-". It must **not**
# inherit the previous match's length — `end_stage` no-ops with no clock running, so `_last_stage`
# survives across matches, and reading it unconditionally printed the earlier match's duration on
# a row nobody timed. That is a plausible-looking wrong number, the worst kind.
assert rows[1]["duration"] != "-", rows[1]
assert rows[0]["duration"] == "-", rows[0]

# # The counters landed in the same file, in the same write
payload = stored()
assert payload[STATS_KEY] == {"wins": 1, "losses": 1}, payload[STATS_KEY]
assert len(payload[HISTORY_KEY]) == 2, payload[HISTORY_KEY]

# # An unrelated key written by the UI survives a result — the shared-lock mutate must not
# # clobber the rest of settings.json, which holds the task queue and the private-server link.
from sloppykeys.config.store import update_json  # noqa: E402

update_json(path, lambda p: p.__setitem__("tasks", [{"mode": "Portals"}]))
tracker.record(won=True, target="Portals / Summer")
assert stored()["tasks"] == [{"mode": "Portals"}], "a result must not drop other settings"
assert len(tracker.history()) == 3

# # Bounded on write
for i in range(HISTORY_LIMIT + 10):
    tracker.record(won=True, target=f"run {i}")
assert len(stored()[HISTORY_KEY]) == HISTORY_LIMIT, len(stored()[HISTORY_KEY])
# Trimmed from the front, so the newest survive: the last one written is first out of history().
assert tracker.history()[0]["target"] == f"run {HISTORY_LIMIT + 9}", tracker.history()[0]

# # Rubbish on disk is dropped, not repaired, and never raises
for junk in (
    "not a list",
    {"nested": "dict"},
    [1, 2, 3],
    [{"result": "Maybe"}],
    [{"target": "no result key"}],
    [None, {"result": "Win", "target": "kept"}],
):
    update_json(path, lambda p, j=junk: p.__setitem__(HISTORY_KEY, j))
    rows = StatsTracker(root).history()
    assert isinstance(rows, list), junk
    assert all(r["result"] in ("Win", "Loss") for r in rows), (junk, rows)
# Only the one valid row out of that last mixed list came through.
assert [r["target"] for r in rows] == ["kept"], rows

# # A result written over a broken list repairs the file going forward rather than failing
tracker = StatsTracker(root)
update_json(path, lambda p: p.__setitem__(HISTORY_KEY, "not a list"))
tracker.record(won=False, target="after the mess")
assert [r["target"] for r in tracker.history()] == ["after the mess"], tracker.history()
assert stored()[STATS_KEY]["losses"] >= 1

# # The counters still read back after a restart, which is the reason they live in the file
reloaded = StatsTracker(root)
assert reloaded.wins == 0, "session counters start at zero"
assert reloaded.snapshot().all_losses >= 1, "all-time counters persist"

for name in os.listdir(root):
    os.remove(os.path.join(root, name))
os.rmdir(root)


# # The `target` these rows carry drops empty parts instead of spelling them
# `get(key, default)` only answers the default when the key is **missing**, and the queue always
# writes `stage` — as "" for any mode with no stage control, and "" outright on a challenge
# detour. So every Portals, Expedition and Challenge row ended in a dangling " / ", and so did
# the Stage field of every Discord embed, which shares this label.
def label(task) -> str:
    ctrl = MacroController.__new__(MacroController)
    ctrl._current_task = task
    return ctrl._task_label()


assert label({"mode": "Portals", "map": "Summer", "stage": ""}) == "Portals / Summer"
assert label({"mode": "Challenge", "map": "School Grounds", "stage": ""}) == (
    "Challenge / School Grounds"
)
# A full three-part target is unchanged — this must not start dropping real information.
assert label({"mode": "Story", "map": "Flower Forest", "stage": "Act 1"}) == (
    "Story / Flower Forest / Act 1"
)
# Nothing at all still reads as something, since `record` stores `target or "—"`.
assert label({"mode": "Raid", "map": "", "stage": ""}) == "Raid"
assert label({}) == "—"
assert label(None) == "—"
for text in (
    label({"mode": "Portals", "map": "Summer", "stage": ""}),
    label({"mode": "Raid", "map": "", "stage": ""}),
    label({}),
):
    assert not text.rstrip().endswith("/"), text
    assert " /  / " not in text, text

print("run history: OK")
