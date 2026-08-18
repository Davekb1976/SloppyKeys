"""Runnable checks for the challenge panel model: reset schedule, per-rotation
skips, and the coordinate table.

No framework, no capture, no input fired:
`.venv\\Scripts\\python.exe tests\\test_challenge_scan.py`
"""

from __future__ import annotations

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

assert tracker.note_time(datetime(2026, 7, 30, 12, 30)) is True, "crossed :30"
assert not tracker.is_skipped(1), "new maps, so old losses stop applying"
assert tracker.reads == {}, "and the old reads are stale"
assert tracker.candidates() == [], "nothing until it is read again"



# # TaskDirector: challenges preempt, a loss skips, targets take turns by limit
from sloppykeys.config.tasks import KIND_TARGET, TaskSlot  # noqa: E402
from sloppykeys.macro.tasks import (  # noqa: E402
    DO_CHALLENGE,
    DO_NOTHING,
    DO_TARGET,
    TaskDecision,
    TaskDirector,
)

story = TaskSlot(kind=KIND_TARGET, gamemode="Story", map_name="King's Tomb", act="Act 3", limit=2)
raid = TaskSlot(kind=KIND_TARGET, gamemode="Raid", map_name="Spirit City", act="Act 1", limit=3)

# Nothing queued: F1 must behave as it did before the feature existed.
assert not TaskDirector().is_configured()
assert TaskDirector().decide().kind == DO_NOTHING

# Two targets, no challenges: each runs its limit, then the queue loops.
director = TaskDirector(slots=[story, raid])
assert director.is_configured()
seen = []
for _match in range(6):
    decision = director.decide()
    seen.append(decision.slot.gamemode)
    director.note_match(decision, won=True)
assert seen == ["Story", "Story", "Raid", "Raid", "Raid", "Story"], seen

# A lost target run still counts: the queue keeps moving rather than stalling.
director = TaskDirector(slots=[story, raid])
first = director.decide()
director.note_match(first, won=False)
second = director.decide()
director.note_match(second, won=False)
assert director.decide().slot.gamemode == "Raid", "a loss spends a run like a win"

# Challenges preempt while the tracker has candidates, then it falls through.
live = ChallengeTracker()
live.note_reads(
    [
        ChallengeRead(slot=1, state=STATE_RUNNABLE, map_name="Rose Kingdom"),
        ChallengeRead(slot=2, state=STATE_RUNNABLE, map_name="Flower Forest"),
        ChallengeRead(slot=3, state=STATE_EXHAUSTED),
    ]
)
director = TaskDirector(slots=[story], tracker=live, challenges=True)
first = director.decide()
assert first.kind == DO_CHALLENGE and first.challenge.slot == 1, first
# **Winning** it also consumes the row: one run of each per rotation, so the next
# decision is the next challenge and not the same one again.
director.note_match(first, won=True)
assert live.is_skipped(1), "a won row is done for this rotation too"
second = director.decide()
assert second.kind == DO_CHALLENGE and second.challenge.slot == 2, second
# A loss consumes it just the same — the same map would only lose again.
director.note_match(second, won=False)
# Both lost, third exhausted -> the target fills the gap until the maps re-roll.
third = director.decide()
assert third.kind == DO_TARGET and third.slot.gamemode == "Story", third
# Re-reading inside the same rotation does not un-skip a lost row: the map is the
# same one that was just lost, so the skip has to outlive the read.
live.note_reads([ChallengeRead(slot=1, state=STATE_RUNNABLE, map_name="Rose Kingdom")])
assert director.decide().kind == DO_TARGET, "a skip lasts the whole rotation"

# Crossing the boundary clears the skips *and* the stale reads, so the first decision
# after a rotation falls to a target and challenges resume once the panel is re-read.
later = datetime.now() + timedelta(hours=1)
assert director.decide(later).kind == DO_TARGET, "stale reads dropped with the rotation"
assert not live.is_skipped(1), "new maps, so the old losses stop applying"
live.note_reads([ChallengeRead(slot=1, state=STATE_RUNNABLE, map_name="Rose Kingdom")])
assert director.decide(later).kind == DO_CHALLENGE, "a fresh scan puts challenges first again"

# Challenges off means they never run, whatever the panel says. The toggle is the only
# switch — a challenge is no longer one of the three queue slots, so there is no queued
# slot that can disagree with it.
read_but_unqueued = ChallengeTracker()
read_but_unqueued.note_reads([ChallengeRead(slot=1, state=STATE_RUNNABLE, map_name="Rose Kingdom")])
targets_only = TaskDirector(slots=[story], tracker=read_but_unqueued)
assert not targets_only.wants_challenges
assert targets_only.decide().kind == DO_TARGET

# current_target ignores challenges, so a caller that can't run one yet still gets on
# with the queue instead of refusing to start.
both = TaskDirector(slots=[story, raid], tracker=live, challenges=True)
assert both.current_target() is story
both.note_match(TaskDecision(kind=DO_TARGET, slot=story), won=True)
both.note_match(TaskDecision(kind=DO_TARGET, slot=story), won=True)
assert both.current_target() is raid, "the limit moved it along"
assert TaskDirector(challenges=True).current_target() is None

# Challenges on but nothing read yet, with no target: nothing to do rather than a guess at
# what the panel might hold.
empty = TaskDirector(tracker=ChallengeTracker(), challenges=True)
assert empty.decide().kind == DO_NOTHING

print("challenge scan: OK")
