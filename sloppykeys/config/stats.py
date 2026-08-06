"""Run counters: this session's, and all-time.

Session numbers live in memory and reset when the app restarts. All-time numbers
persist in settings.json under "stats", so a long-running farm survives a restart
and the Run panel can show both.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
STATS_KEY = "stats"
WINS_KEY = "wins"
LOSSES_KEY = "losses"


def _rate(wins: int, total: int) -> str:
    """Win % as text. No runs yet is "-", not 0% — nothing has been won or lost."""
    if total <= 0:
        return "-"
    return f"{round(wins * 100 / total)}%"


def format_duration(seconds: float) -> str:
    """H:MM:SS, the shape the Discord embeds and the Run panel both want."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


@dataclass
class RunStats:
    """A snapshot for the UI and the webhook — plain values, no live clocks."""

    wins: int = 0
    losses: int = 0
    all_wins: int = 0
    all_losses: int = 0
    macro_seconds: float = 0.0
    stage_seconds: float = 0.0
    # How long the match that just finished took. Separate from `stage_seconds`, which is
    # the clock on the match *in progress* and reads 0 between matches: anything reporting
    # a duration after a result — every win/loss embed — wants this one.
    last_stage_seconds: float = 0.0
    last_run: str = "-"

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def all_total(self) -> int:
        return self.all_wins + self.all_losses

    @property
    def win_rate(self) -> str:
        return _rate(self.wins, self.total)

    @property
    def all_win_rate(self) -> str:
        return _rate(self.all_wins, self.all_total)

    @property
    def macro_time(self) -> str:
        """How long the app has been open. Not how long the current run has lasted:
        uptime means since it started, and a clock that read `0:00:00` until F1 and
        went back to it on F2 was the one number on the panel nobody could use."""
        return format_duration(self.macro_seconds)

    @property
    def stage_time(self) -> str:
        """The match in progress, or `-` when there isn't one — the lobby chain, a
        placement pass and the result screen are all outside a match."""
        if self.stage_seconds <= 0:
            return "-"
        return format_duration(self.stage_seconds)

    @property
    def last_stage_time(self) -> str:
        """Duration of the last finished match, or `-` before there is one. Not
        `0:00:00`, which is what made this look broken rather than empty."""
        if self.last_stage_seconds <= 0:
            return "-"
        return format_duration(self.last_stage_seconds)


class StatsTracker:
    """Owns the counters and the two clocks.

    Written from the macro worker thread and read from the UI thread. Both are
    plain int/float attributes guarded by the GIL, and a torn read would only
    misdraw one frame of a label, so no lock — `ponytail:` if a future reader
    needs a consistent multi-field view, snapshot under a lock instead.
    """

    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)
        stored = self._read()
        self._all_wins = stored[0]
        self._all_losses = stored[1]
        self.wins = 0
        self.losses = 0
        # Uptime, and it runs from here — the tracker is built with the window. Nothing
        # starts or stops it: F1 and F2 are runs, and the session is the app's lifetime,
        # which is the same span the win/loss counters cover.
        self._launched = time.monotonic()
        self._stage_start: float | None = None
        self._last_stage = 0.0
        self._last_run = "-"

    # # Persistence
    def _read(self) -> tuple[int, int]:
        raw = read_json(self._path).get(STATS_KEY, {})
        if not isinstance(raw, dict):
            return (0, 0)

        def count(key: str) -> int:
            try:
                return max(0, int(raw.get(key, 0)))
            except (TypeError, ValueError):
                return 0

        return (count(WINS_KEY), count(LOSSES_KEY))

    def _write(self) -> None:
        # Called from the **macro worker** on every result, while the UI thread is free to
        # be saving the task queue or a delay into the same file. Read-then-write here was
        # reverting those edits; `update_json` holds the lock across both halves.
        counts = {WINS_KEY: self._all_wins, LOSSES_KEY: self._all_losses}

        def mutate(payload: dict) -> None:
            payload[STATS_KEY] = counts

        update_json(self._path, mutate)

    # # Clocks
    def abandon_stage(self) -> None:
        """The run ended without a result — F2, or a step that failed.

        Drops the match clock without recording a duration: a match nobody saw the end of
        has no length worth reporting, and freezing one would put it under `last match` as
        if it had finished.
        """
        self._stage_start = None

    def start_stage(self) -> None:
        """A match has begun. Called when the in-match Start Game click lands, which is
        the moment the waves start — the only event that means "the match is running"."""
        self._stage_start = time.monotonic()

    def end_stage(self) -> None:
        """A match has finished: freeze its duration and stop the clock.

        Called the moment the win or defeat screen is matched, not when the result is
        recorded — the result screenshot waits out the reward animation in between, and
        that second belongs to neither match.

        Idempotent: a second call keeps the frozen duration, so `record()` can call it
        without knowing whether the caller already did.
        """
        if self._stage_start is None:
            return
        self._last_stage = max(0.0, time.monotonic() - self._stage_start)
        self._stage_start = None

    # # Outcomes
    def record(self, won: bool) -> None:
        # A no-op when the outcome step already ended the match, which is the normal path.
        # Kept as a backstop so a result counted from anywhere else still freezes the clock
        # rather than leaving it running into the next match.
        self.end_stage()
        if won:
            self.wins += 1
            self._all_wins += 1
            self._last_run = "Win"
        else:
            self.losses += 1
            self._all_losses += 1
            self._last_run = "Loss"
        self._write()

    def snapshot(self) -> RunStats:
        now = time.monotonic()
        return RunStats(
            wins=self.wins,
            losses=self.losses,
            all_wins=self._all_wins,
            all_losses=self._all_losses,
            macro_seconds=now - self._launched,
            stage_seconds=0.0 if self._stage_start is None else now - self._stage_start,
            last_stage_seconds=self._last_stage,
            last_run=self._last_run,
        )
