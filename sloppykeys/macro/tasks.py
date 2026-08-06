"""Deciding what the macro plays next.

Pure decision logic: no capture, no clicking, no Qt. Feed it the saved queue and a
`ChallengeTracker`, tell it how each match ended, and it says what to do next. That
separation is what makes the rules testable — the awkward parts of this feature are
the rules, not the clicking.

The rules, from the user's design:

- **Challenges preempt.** While the `challenges` toggle is on and any offered challenge is
  runnable and hasn't been played this rotation, challenges come first, top to bottom.
  They are not a queue slot: preemption ignores position, so a slot would have been three
  places to store a boolean.
- **A played challenge is done for the rotation, win or lose.** Move to the next one; when
  all three are played or exhausted, fall through to the targets until the maps re-roll.
  Marking only losses meant a won row read as runnable and got picked again immediately.
- **Targets run in order, each for its own limit,** then the queue loops.
- **A limit only matters with two targets.** One target plus challenges never needs
  one, because challenges always go first and the target just fills the gap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sloppykeys.config.tasks import KIND_TARGET, TaskSlot

from .challenge import ChallengeRead, ChallengeTracker

# What to do next.
DO_CHALLENGE = "challenge"
DO_TARGET = "target"
DO_NOTHING = "idle"


@dataclass
class TaskDecision:
    kind: str = DO_NOTHING
    slot: TaskSlot | None = None
    challenge: ChallengeRead | None = None
    reason: str = ""

    @property
    def is_challenge(self) -> bool:
        return self.kind == DO_CHALLENGE

    def label(self) -> str:
        if self.kind == DO_CHALLENGE and self.challenge is not None:
            where = self.challenge.map_name or "unknown map"
            return f"challenge {self.challenge.slot} ({where})"
        if self.kind == DO_TARGET and self.slot is not None:
            return self.slot.summary()
        return "nothing queued"


@dataclass
class TaskDirector:
    """Queue position plus per-target run counts. One instance per run."""

    slots: list[TaskSlot] = field(default_factory=list)
    tracker: ChallengeTracker | None = None
    # Challenges are a toggle, not a slot: `AppSettings.run_challenges`.
    challenges: bool = False
    _position: int = 0
    _done_in_slot: int = 0

    @property
    def targets(self) -> list[TaskSlot]:
        return [slot for slot in self.slots if slot.kind == KIND_TARGET and slot.is_runnable()]

    @property
    def wants_challenges(self) -> bool:
        """Whether challenges preempt. Now the `challenges` flag, set from
        `AppSettings.run_challenges`, rather than a scan for a challenge slot — a challenge
        never had a queue position to occupy, so storing it as one of three slots cost a
        target slot to hold a boolean."""
        return self.challenges

    def is_configured(self) -> bool:
        """False means F1 behaves exactly as it did before this feature: the Run
        strip's selection, looping, with nothing else involved."""
        return bool(self.targets) or self.wants_challenges

    def decide(self, now: datetime | None = None) -> TaskDecision:
        """What to do next. Reads the tracker's latest scan; never scans itself."""
        tracker = self.tracker
        if self.wants_challenges and tracker is not None:
            tracker.note_time(now)
            candidates = tracker.candidates()
            if candidates:
                return TaskDecision(
                    kind=DO_CHALLENGE,
                    challenge=candidates[0],
                    reason=f"{len(candidates)} challenge(s) left this rotation",
                )

        targets = self.targets
        if not targets:
            if self.wants_challenges:
                return TaskDecision(reason="challenges done and no target queued")
            return TaskDecision(reason="nothing queued")

        slot = self.current_target()
        if slot is None:  # pragma: no cover - guarded by the check above
            return TaskDecision(reason="nothing queued")
        remaining = max(0, slot.limit - self._done_in_slot)
        return TaskDecision(
            kind=DO_TARGET,
            slot=slot,
            reason=f"{remaining} of {slot.limit} run(s) left on this target",
        )

    def runs_left(self) -> int:
        """Runs still owed on the current target before the queue moves on.

        Read by the Discord embed. Derived from `_done_in_slot` rather than tracked
        separately, so it cannot drift from the thing `note_match` actually advances.
        """
        slot = self.current_target()
        if slot is None:
            return 0
        return max(0, max(1, slot.limit) - self._done_in_slot)

    def next_target_label(self) -> str:
        """The target after this one, or "" when there is only one (so it just repeats)."""
        targets = self.targets
        if len(targets) < 2:
            return ""
        return targets[(self._position + 1) % len(targets)].summary()

    def current_target(self) -> TaskSlot | None:
        """The target slot whose turn it is, ignoring challenges.

        Separate from `decide()` so a caller that can't run a challenge yet can still
        get on with the queue instead of refusing to start.
        """
        targets = self.targets
        if not targets:
            return None
        return targets[self._position % len(targets)]

    def note_match(self, decision: TaskDecision, won: bool) -> None:
        """Record how a match ended, which is what moves the queue along.

        A lost challenge is skipped for the rotation. A won one is simply re-read next
        time: the game's own counter is the source of truth, so nothing is decremented
        here. A target counts the match either way — a loss is a run spent, and
        stopping the queue on a loss would leave the macro idle.
        """
        if decision.is_challenge:
            # Played is played, win or lose: one run of each row per rotation. Marking
            # only losses meant a won challenge was immediately picked again, because the
            # row still read as runnable.
            if decision.challenge is not None and self.tracker is not None:
                self.tracker.mark_done(decision.challenge.slot)
            # The row's `n/10` is *not* decremented here. Only a win spends one of the
            # day's ten, and the caller does it the moment the result is read
            # (`window.py::_record_outcome`) so the win notification carries the new
            # count rather than the one from before the match.
            return
        if decision.kind != DO_TARGET or decision.slot is None:
            return
        self._done_in_slot += 1
        if self._done_in_slot >= max(1, decision.slot.limit):
            self._position += 1
            self._done_in_slot = 0

    def summary(self) -> str:
        targets = self.targets
        if not targets:
            return "challenges only" if self.wants_challenges else "no tasks"
            
        slot = targets[self._position % len(targets)]
        prefix = "challenges first, then " if self.wants_challenges else ""
        return (
            f"{prefix}target {(self._position % len(targets)) + 1}/{len(targets)}: "
            f"{slot.summary()} ({self._done_in_slot} done)"
        )
