"""Runnable checks for the challenge panel model: reset schedule, per-rotation
skips, and the coordinate table.

No framework, no capture, no input fired:
`.venv\\Scripts\\python.exe tests\\test_challenge_scan.py`
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.challenge import (  # noqa: E402
    LIMIT_REGIONS,
    MAP_REGIONS,
    SLOTS,
    STAR_REGIONS,
    STAR_SATURATION_MIN,
    challenge_maps,
    daily_quota_spent,
    expected_templates,
    interval_key,
    next_daily_reset_at,
    next_interval_at,
)
from sloppykeys.content.gamemodes import STORY_MAPS  # noqa: E402
from sloppykeys.macro.challenge import (  # noqa: E402
    MAP_MATCH_MIN,
    STATE_EXHAUSTED,
    STATE_RUNNABLE,
    STATE_UNKNOWN,
    ChallengeRead,
    ChallengeTracker,
    match_map_name,
    parse_limit,
)

# Read from the app rather than hardcoded: the viewport size has changed twice (816x638 ->
# 800x599 -> 1152x756) and a hardcoded copy here would have kept passing while every box was
# out of bounds. It lives in the bridge now; `sloppykeys.ui.theme` was the PySide6 front end.
from sloppykeys.ui_web.bridge import VIEWPORT_H, VIEWPORT_W  # noqa: E402

VIEWPORT = (VIEWPORT_W, VIEWPORT_H)

# # Coordinates stay inside the pinned viewport, or they'd read someone else's pixels
for name, table in (("star", STAR_REGIONS), ("limit", LIMIT_REGIONS), ("map", MAP_REGIONS)):
    assert sorted(table) == list(SLOTS), (name, sorted(table))
    for slot, (x, y, width, height) in table.items():
        assert width > 0 and height > 0, (name, slot)
        assert x + width <= VIEWPORT[0], (name, slot, x + width)
        assert y + height <= VIEWPORT[1], (name, slot, y + height)

# Rows are top to bottom, so each slot's boxes sit below the previous slot's.
for table in (STAR_REGIONS, LIMIT_REGIONS, MAP_REGIONS):
    tops = [table[slot][1] for slot in SLOTS]
    assert tops == sorted(tops), tops

# # No templates at all: the scan is pure OCR, and no per-map crops were ever wanted.
# Compared against the table rather than a copy of it: Challenge draws from Story's maps, so
# a map added to Story has to appear here too. The copy went stale when East Town landed.
assert challenge_maps() == STORY_MAPS, challenge_maps()
assert expected_templates() == [], expected_templates()
# The greyed-star threshold sits in the measured gap: greyed reads 6, active reads 242.
assert 20 < STAR_SATURATION_MIN < 150, STAR_SATURATION_MIN

# # Limit parsing: OCR reads small digits approximately, so fold the confusions in
assert parse_limit("9/10") == (9, 10)
assert parse_limit("10 / 10") == (10, 10)
assert parse_limit("O/1O") == (0, 10), "O read for zero"
assert parse_limit("9|10") == (9, 10), "slash read as a pipe"
assert parse_limit("l/10") == (1, 10), "lowercase L read for one"
assert parse_limit("") == (None, None)
assert parse_limit("910") == (None, None), "no separator is ambiguous, so refuse"
assert parse_limit("11/10") == (None, None), "more left than the total can't be right"
assert parse_limit("garbage") == (None, None)

# # Map names: fuzzy match to the closed set, with the act stripped
for noisy, expected in (
    ("Rose Kingdom Act 3", "Rose Kingdom"),
    ("Rose Kingdorn Act 3", "Rose Kingdom"),
    ("R0se Kingdom Act 5", "Rose Kingdom"),
    ("Faity KingForest Act1", "Fairy King Forest"),
    ("Kings Tomb Act 2", "King's Tomb"),
    ("Schoo1 Grounds Act 4", "School Grounds"),
):
    name, score = match_map_name(noisy, challenge_maps())
    assert name == expected, (noisy, name, score)
    assert score >= MAP_MATCH_MIN, (noisy, score)

for nothing in ("", "utter nonsense here", "   ", "Act 3"):
    name, _score = match_map_name(nothing, challenge_maps())
    assert name == "", (nothing, name)

# # Reset schedule: half-hour wall-clock boundaries, daily refill at 20:00
same = (
    interval_key(datetime(2026, 7, 30, 14, 0)),
    interval_key(datetime(2026, 7, 30, 14, 29, 59)),
)
assert same[0] == same[1], same
assert interval_key(datetime(2026, 7, 30, 14, 30)) != same[0], "crossing :30 re-rolls"
assert next_interval_at(datetime(2026, 7, 30, 14, 5)) == datetime(2026, 7, 30, 14, 30)
assert next_interval_at(datetime(2026, 7, 30, 14, 42)) == datetime(2026, 7, 30, 15, 0)
assert next_daily_reset_at(datetime(2026, 7, 30, 9, 0)) == datetime(2026, 7, 30, 20, 0)
assert next_daily_reset_at(datetime(2026, 7, 30, 21, 0)) == datetime(2026, 7, 31, 20, 0)
# 20:00 is a :00 boundary, so the rotation rolls with it and the tracker drops its reads —
# which is what sends the macro back to the panel to find the refilled counts.
assert interval_key(datetime(2026, 7, 30, 19, 55)) != interval_key(datetime(2026, 7, 30, 20, 0))

# # The day's quota: all three rows at 0, and only on a complete read
def _spent(*remaining: int | None) -> bool:
    return daily_quota_spent(
        {
            slot: ChallengeRead(slot=slot, state=STATE_UNKNOWN, runs_remaining=left)
            for slot, left in zip(SLOTS, remaining)
        }
    )


assert _spent(0, 0, 0), "every row at 0 is the day's runs gone"
assert not _spent(0, 1, 0), "one row with a run left is not the day"
assert not _spent(0, 0, None), "an unreadable row is unknown, not zero"
assert not daily_quota_spent({}), "nothing read yet says nothing about the day"

# # A read decides whether a row is worth attempting
assert ChallengeRead(slot=1, state=STATE_RUNNABLE).is_candidate
assert not ChallengeRead(slot=1, state=STATE_EXHAUSTED).is_candidate
assert ChallengeRead(slot=1, state=STATE_UNKNOWN).is_candidate, "try it, let the game refuse"

# # Tracker: a loss skips that row for the rotation, and a rotation clears the skips
tracker = ChallengeTracker()
noon = datetime(2026, 7, 30, 12, 0)
assert tracker.note_time(noon) is False, "first read is not a rotation change"
tracker.note_reads(
    [
        ChallengeRead(slot=1, state=STATE_RUNNABLE, map_name="Rose Kingdom"),
        ChallengeRead(slot=2, state=STATE_EXHAUSTED, map_name="Flower Forest"),
        ChallengeRead(slot=3, state=STATE_UNKNOWN),
    ]
)
assert [read.slot for read in tracker.candidates()] == [1, 3], tracker.summary()

tracker.mark_done(1)
assert tracker.is_skipped(1)
assert [read.slot for read in tracker.candidates()] == [3], "a played row moves to the next"
tracker.mark_done(3)
assert tracker.candidates() == [], "all lost or exhausted: fall through to the targets"
assert not tracker.has_work()
assert tracker.has_work() == bool(tracker.candidates()), "has_work is the readable form"

assert tracker.note_time(datetime(2026, 7, 30, 12, 30)) is True, "crossed :30"
assert not tracker.is_skipped(1), "new maps, so old losses stop applying"
assert tracker.reads == {}, "and the old reads are stale"
assert tracker.candidates() == [], "nothing until it is read again"



# There was a `TaskDirector` section here. It tested a decision layer that preempted a
# three-slot queue from a `run_challenges` toggle, and it had no production caller — the web
# UI made challenges a queue task instead. Both modules are deleted;
# `tests/test_challenge_priority.py` covers the rules that survived, against the controller
# that actually runs them.


# # `is_candidate` is a property, and no caller may call it
# It was called as `read.is_candidate()` in the run loop, which raises
# `TypeError: 'bool' object is not callable` on the first row. Nothing catches it there, so
# the exception unwound the whole run and surfaced only as "stopped unexpectedly" — every
# Challenge task failed that way, silently, for as long as the code existed. A property read
# as a call is invisible to `compileall` and to any test that doesn't reach the line, so this
# guards the shape instead of the behaviour.
assert isinstance(
    ChallengeRead.__dict__["is_candidate"], property
), "is_candidate is expected to stay a property"

# Parsed, not grepped: the comment explaining this bug names the call form, and so will any
# future note about it, so a text scan would flag its own documentation.
_source_root = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sloppykeys"
)
for folder, _dirs, files in os.walk(_source_root):
    for name in sorted(files):
        if not name.endswith(".py"):
            continue
        path = os.path.join(folder, name)
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            assert not (
                isinstance(func, ast.Attribute) and func.attr == "is_candidate"
            ), f"{path}:{node.lineno} calls is_candidate, which is a property"

print("challenge scan: OK")
