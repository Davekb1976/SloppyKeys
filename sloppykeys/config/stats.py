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
# One record per finished match, newest last, for the Dashboard's Run History card. Separate
# from `stats` because that key is two counters that get overwritten — a list needs its own.
HISTORY_KEY = "run_history"
# **Bounded on write.** A farm left running overnight finishes hundreds of matches, and this
# file is read whole on every settings edit, so an unbounded list would grow the parse cost of
# every unrelated save. Fifty is more rows than the card can show without scrolling for a while.
HISTORY_LIMIT = 50

# When a run finished. `%I:%M %p` rather than `%H:%M`, and dated, because a card capped at 50
# rows spans more than one day on a long farm and a bare `18:42` cannot say which.
STAMP_FORMAT = "%Y-%m-%d %I:%M %p"
# Rows written before the format changed hold a bare 24-hour `HH:MM`. The time converts exactly;
# the date does not exist, so it is not invented — a legacy row shows the hour it has and no
# more. Normalised on read rather than rewritten on disk: the file is the user's, and a
# migration that touched every row to restyle it would risk more than it fixes.
LEGACY_STAMP_FORMAT = "%H:%M"
LEGACY_STAMP_DISPLAY = "%I:%M %p"


def clean_target(raw: object) -> str:
    """A run's target with empty parts dropped: `Portals / Summer /` -> `Portals / Summer`.

    The label is stored **at write time**, so rows recorded before `_task_label` learned to
    filter keep their dangling separator for as long as they stay on the card — fixing the
    producer could not reach them. Splitting on the separator also catches the doubled ` /  / `
    a task with an empty map left behind, and a part that is nothing but whitespace, which
    passes a truthiness filter.
    """
    parts = (part.strip() for part in str(raw or "").split("/"))
    return " / ".join(part for part in parts if part) or "—"


def clean_stamp(raw: object) -> str:
    """A run's timestamp in the current format, converting a legacy 24-hour one on the way.

    Anything that is not a bare `HH:MM` passes through: it is either already the current shape
    or something hand-edited, and neither is worth guessing at.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = time.strptime(text, LEGACY_STAMP_FORMAT)
    except ValueError:
        return text
    return time.strftime(LEGACY_STAMP_DISPLAY, parsed)


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
        # Does `_last_stage` belong to the match about to be recorded, or the one before it?
        # `end_stage` deliberately no-ops when no clock is running, so `_last_stage` survives
        # across matches — which is right for the webhook reading it straight after a result,
        # and wrong for a history row on a match that was never clocked: it would inherit the
        # previous match's length and print a duration nobody measured.
        self._stage_timed = False
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

    def _write(self, entry: dict | None = None) -> None:
        # Called from the **macro worker** on every result, while the UI thread is free to
        # be saving the task queue or a delay into the same file. Read-then-write here was
        # reverting those edits; `update_json` holds the lock across both halves.
        #
        # The counters and the history row go in **one** mutate for the same reason: two
        # `update_json` calls would take the lock twice and could interleave with a UI save
        # between them, leaving a result counted but unlisted.
        counts = {WINS_KEY: self._all_wins, LOSSES_KEY: self._all_losses}

        def mutate(payload: dict) -> None:
            payload[STATS_KEY] = counts
            if entry is None:
                return
            # Whatever is on disk is untrusted — a hand-edited file, or an older shape — so a
            # non-list is replaced rather than appended to, which would raise and lose the run.
            existing = payload.get(HISTORY_KEY)
            rows = [r for r in existing if isinstance(r, dict)] if isinstance(existing, list) else []
            rows.append(entry)
            payload[HISTORY_KEY] = rows[-HISTORY_LIMIT:]

        update_json(self._path, mutate)

    def history(self) -> list[dict]:
        """Finished matches, **newest first**, as the card wants them.

        Read from disk rather than memory so the card is populated on a fresh launch, before
        this session has finished anything. A row with no result is **dropped, not repaired**:
        that is not a run, and inventing one would put a fake match on the card.

        `target` and `at` are a different case and are normalised rather than dropped. Both are
        *display* strings written by an older build — a dangling separator, a 24-hour clock — so
        there is nothing to validate and nothing to invent, and a row is still the run it always
        was. See `clean_target` and `clean_stamp`.
        """
        raw = read_json(self._path).get(HISTORY_KEY)
        if not isinstance(raw, list):
            return []
        rows = []
        for row in raw:
            if not isinstance(row, dict) or row.get("result") not in ("Win", "Loss"):
                continue
            rows.append(
                {
                    "result": row["result"],
                    "target": clean_target(row.get("target")),
                    "duration": str(row.get("duration") or "-"),
                    "at": clean_stamp(row.get("at")),
                }
            )
        rows.reverse()
        return rows

    # # Clocks
    def abandon_stage(self) -> None:
        """The run ended without a result — F2, or a step that failed.

        Drops the match clock without recording a duration: a match nobody saw the end of
        has no length worth reporting, and freezing one would put it under `last match` as
        if it had finished.
        """
        self._stage_start = None
        self._stage_timed = False

    def start_stage(self) -> None:
        """A match has begun. Called when the in-match Start Game click lands, which is
        the moment the waves start — the only event that means "the match is running"."""
        self._stage_start = time.monotonic()
        # A fresh match owns no duration yet, so the previous one's cannot be reported as its.
        self._stage_timed = False

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
        self._stage_timed = True

    # # Outcomes
    def record(self, won: bool, target: str = "") -> None:
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
        # Only a clock that ran for *this* match gives a duration — see `_stage_timed`. Spent
        # here so the next result cannot inherit it. `target` comes from the caller because the
        # tracker has no view of the queue.
        duration = format_duration(self._last_stage) if self._stage_timed else "-"
        self._stage_timed = False
        self._write(
            {
                "result": self._last_run,
                "target": clean_target(target),
                "duration": duration,
                "at": time.strftime(STAMP_FORMAT),
            }
        )

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
