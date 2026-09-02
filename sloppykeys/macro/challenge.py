"""Reading the challenge panel, and tracking which rows are worth attempting.

Challenge is not a farm target. It is a side task the macro reaches from inside a
match: while any of the three offered challenges has runs left, they come first;
otherwise the queue falls through to its target slots.

Two halves, deliberately separate:

- `ChallengeScanner` **reads** the panel — OCR for the limit and the map, saturation for
  the star, no templates, no clicking, no sleeping. The Dashboard's Scan button
  (`bridge.scan_challenge`) runs it on its own, so the coordinates can be proven before
  anything drives the game.
- `ChallengeTracker` **remembers** across reads: which rows this rotation has already
  been lost on, and when that memory stops applying.

Phase 2 is these two plus their report. Nothing here is wired into a run yet.

Replaces an earlier Regular/Daily/Weekly tier model that did not match the game's
present layout (three rows, each with its own map and its own `n/10`).
"""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

import cv2  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]

from sloppykeys.content.challenge import (
    SLOTS,
    STAR_SATURATION_MIN,
    limit_region,
    map_region,
    star_region,
    challenge_maps,
    expected_templates,
    interval_key,
)
from sloppykeys.core.image_search import ImageSearchEngine
from sloppykeys.core.ocr import OcrReader

# What a read concluded about one row.
STATE_RUNNABLE = "runnable"
STATE_EXHAUSTED = "exhausted"
STATE_UNKNOWN = "unknown"

# Where a read came from, so a report can say why it believes what it believes. OCR is
# the only sensor left — the two template shortcuts (the `0/10` crop and the greyed star)
# are both gone.
SOURCE_OCR = "ocr"
SOURCE_NONE = ""

# How close an OCR'd map name has to be to a real one. Measured on deliberately
# noisy strings: genuine reads scored 0.88-1.00 with the runner-up at ~0.55, and
# nonsense topped out at 0.38. 0.60 sits in that gap with room either side.
MAP_MATCH_MIN = 0.60

RectProvider = Callable[[], "tuple[int, int, int, int] | None"]

# OCR reads small stylised text approximately, so digits get the usual confusions
# folded back before parsing. Only characters that cannot appear in "9 / 10".
# Public because the wave counter needs the same fold — one table, so a confusion fixed
# for one reader is fixed for both.
DIGIT_FIXES = str.maketrans({"o": "0", "O": "0", "D": "0", "l": "1", "I": "1", "|": "1"})


def parse_limit(text: str) -> tuple[int | None, int | None]:
    """`"9/10"` -> `(9, 10)`. `(None, None)` when it can't be read confidently.

    Refuses rather than guesses: this decides whether the macro spends a run. A bare
    number with no separator is exactly the ambiguous case ("910" could be 9/10 or
    10 of something), so it is rejected.
    """
    compact = re.sub(r"\s+", "", text or "")
    # Separators first, digit confusions second, and in that order on purpose: "|" is
    # both a plausible misread of the slash and of the digit 1, so folding digits first
    # would turn "9|10" into "9110" and lose the split.
    for separator in ("/", "\\", ":", "|"):
        if compact.count(separator) != 1:
            continue
        left, right = compact.split(separator)
        match = re.search(r"(\d{1,3})\s*$", left.translate(DIGIT_FIXES))
        total_match = re.match(r"^\s*(\d{1,3})", right.translate(DIGIT_FIXES))
        if not match or not total_match:
            continue
        remaining, total = int(match.group(1)), int(total_match.group(1))
        if total <= 0 or remaining > total:
            return (None, None)
        return (remaining, total)
    return (None, None)


def match_map_name(text: str, candidates: list[str]) -> tuple[str, float]:
    """Best of a closed set for an OCR'd map name, with its similarity.

    The row reads like `Rose Kingdom Act 3` and OCR may mangle a character, so this
    strips the act and fuzzy-matches the rest. A closed set is what makes that safe:
    the answer can only ever be one of the maps a challenge can land on, or nothing.
    """
    target = _normalize_map(text)
    if not target:
        return ("", 0.0)
    best_name, best_score = "", 0.0
    for name in candidates:
        score = difflib.SequenceMatcher(None, target, _normalize_map(name)).ratio()
        if score > best_score:
            best_name, best_score = name, score
    if best_score < MAP_MATCH_MIN:
        return ("", best_score)
    return (best_name, best_score)


def _normalize_map(text: str) -> str:
    """Lowercase letters and spaces only, with any trailing act dropped."""
    lowered = re.sub(r"[^a-z ]+", " ", (text or "").lower())
    lowered = re.sub(r"\bact\b.*$", "", lowered)
    return " ".join(lowered.split())


@dataclass
class ChallengeRead:
    """One row as last seen. `map_name` is empty when no candidate matched."""

    slot: int
    state: str = STATE_UNKNOWN
    map_name: str = ""
    map_score: float = 0.0
    runs_remaining: int | None = None
    runs_total: int | None = None
    # Colour in the star box, which is what decides "already completed". Reported on every
    # row, not just the ones it rejects, because the threshold is the kind of number that
    # has to be checkable against a real panel rather than argued about.
    star_saturation: float | None = None
    source: str = SOURCE_NONE
    raw_limit: str = ""
    raw_map: str = ""
    note: str = ""
    # Has the macro already played this row this rotation? Set by `ChallengeTracker`, not by
    # the scanner — it is memory, not something visible in the panel's pixels. It lives on
    # the read so the stats panel can say "Done": that panel is handed the reads and nothing
    # else, so without this a finished challenge kept showing "Ready".
    played: bool = False

    @property
    def is_candidate(self) -> bool:
        """Worth attempting? An unknown read counts: better to try it and let the
        game refuse than to skip a runnable challenge because a read was poor."""
        return self.state != STATE_EXHAUSTED

    @property
    def limit_text(self) -> str:
        if self.runs_remaining is None or self.runs_total is None:
            return "?/?"
        return f"{self.runs_remaining}/{self.runs_total}"

    def summary(self) -> str:
        where = self.map_name or "map unknown"
        detail = f" ({self.map_score:.2f})" if self.map_name else ""
        via = f" via {self.source}" if self.source else ""
        raw = f' read "{self.raw_map}" / "{self.raw_limit}"' if (self.raw_map or self.raw_limit) else ""
        star = "" if self.star_saturation is None else f", star sat {self.star_saturation:.0f}"
        suffix = f" — {self.note}" if self.note else ""
        return (
            f"slot {self.slot}: {self.state} {self.limit_text}{star}, "
            f"{where}{detail}{via}{raw}{suffix}"
        )


class ChallengeScanner:
    """Reads the three rows. No input, no waiting: one read per box.

    OCR for the two strings, because neither is knowable ahead of time — the limit counts
    down and the map rotates with an act appended. Saturation for the star, because an
    active star and a greyed one differ only in colour. No templates at all.

    The panel has to be open already — this answers "what is on screen now", which
    is what makes it safe as a report and usable mid-run once navigation exists.
    """

    def __init__(
        self,
        engine: ImageSearchEngine,
        rect_provider: RectProvider,
        log: Callable[[str], None] | None = None,
        ocr: OcrReader | None = None,
    ) -> None:
        self._engine = engine
        self._rect = rect_provider
        self._log = log or (lambda _m: None)
        self._ocr = ocr or OcrReader()

    @property
    def ocr(self) -> OcrReader:
        return self._ocr

    def scan(self) -> list[ChallengeRead]:
        return [self.read_slot(slot) for slot in SLOTS]

    def scan_if_open(self) -> tuple[list[ChallengeRead], bool]:
        """(reads, panel_was_open). Only trust the reads when the flag is True.

        Read off the wrong screen, the limit boxes OCR to junk, `parse_limit` refuses it
        and every row comes back `unknown` — which `is_candidate` counts as "worth
        attempting", so a scan taken in a stage would tell the queue there are three
        challenges waiting. The proof that the panel is really up is that at least one
        row parsed a proper `n/10`: nothing else on screen produces that in these exact
        boxes.
        """
        reads = self.scan()
        parsed = any(read.runs_total is not None for read in reads)
        return (reads, parsed)

    def read_slot(self, slot: int) -> ChallengeRead:
        limit_box = limit_region(slot)
        map_box = map_region(slot)
        if limit_box is None or map_box is None:
            return ChallengeRead(slot=slot, note="no coordinates for this slot")
        if self._rect() is None:
            return ChallengeRead(slot=slot, note="Roblox not found")

        read = ChallengeRead(slot=slot)

        # Limit: OCR the digits. There is no template fallback by design (see the note in
        # content/challenge.py).
        limit_text = self._read_text(limit_box)
        read.raw_limit = limit_text
        remaining, total = parse_limit(limit_text)
        if remaining is not None:
            read.runs_remaining, read.runs_total = remaining, total
            read.state = STATE_EXHAUSTED if remaining <= 0 else STATE_RUNNABLE
            read.source = SOURCE_OCR
        else:
            # OCR is the only sensor for the count, by the user's call: a `0/10` crop
            # could confirm the exhausted state but never tell 7 from 8, so it only ever
            # covered the case of the engine failing to start. An unreadable limit stays
            # unknown, which `is_candidate` treats as worth attempting.
            read.state = STATE_UNKNOWN
            read.source = SOURCE_NONE
            read.note = self._ocr_note() or "limit text unreadable"

        # Map: OCR, then nearest of the closed set. No templates involved — the act in
        # the text makes a crop-per-map-and-act impractical, and fuzzy matching a read
        # against five known names absorbs the character errors OCR makes at this size.
        map_text = self._read_text(map_box)
        read.raw_map = map_text
        read.map_name, read.map_score = match_map_name(map_text, challenge_maps())
        if not read.map_name and map_text:
            read.note = (read.note + "; " if read.note else "") + "map text matched nothing"

        # The greyed star, last and as an **override**. It is the game's own "not this
        # one" and it beats the limit text — a row finished this rotation still shows runs
        # left, because the limit counts the *day's* ten. It also beats anything the macro
        # remembers, since that memory dies with the process.
        #
        # Deliberately after the limit read, not before it: `scan_if_open` proves the
        # panel is up by some row parsing an `n/10`, so a row-state shortcut that returned
        # early left the panel looking absent while it was wide open. That cost several
        # runs. Whatever else is added here, the limit read stays unconditional.
        star_box = star_region(slot)
        read.star_saturation = self._star_saturation(star_box) if star_box else None
        if read.star_saturation is not None and read.star_saturation < STAR_SATURATION_MIN:
            read.state = STATE_EXHAUSTED
            read.note = (read.note + "; " if read.note else "") + (
                f"star greyed out (saturation {read.star_saturation:.0f} "
                f"< {STAR_SATURATION_MIN})"
            )
        return read

    # # Internals
    def _read_text(self, region: tuple[int, int, int, int]) -> str:
        """OCR one client-space box. Empty string when it can't be read at all."""
        rect = self._rect()
        if rect is None:
            return ""
        x, y, width, height = region
        image = self._engine.capture_bgr((rect[0] + x, rect[1] + y, width, height))
        result = self._ocr.read_line(image)
        return result.text if result.ok else ""

    def _ocr_note(self) -> str:
        ready, message = self._ocr.available()
        return "" if ready else message

    def _star_saturation(self, region: tuple[int, int, int, int]) -> float | None:
        """How coloured is this row's star? 90th percentile of HSV saturation, or None if
        the capture failed.

        This is the greyed-star check, done by the one measurement that can answer it.
        Matching the `star_used.png` crop was tried and cannot work: an active star and a
        greyed one are the same shape, matching in this project is grayscale, and the crop
        scored **0.999 on all three active stars** — no separation at all. Matching the same
        crop *in colour* does separate (0.999 greyed vs 0.828 active) but leaves a 0.17
        margin, needs a hand-tuned threshold sitting right on the engine's default, and
        needs a colour path the engine doesn't have. Saturation reads 6 on the user's real
        greyed crop against 242-243 on live active stars, so it is the same question asked
        in the one way that isn't marginal.

        Percentile rather than mean so the answer doesn't shift with how much of the box is
        star and how much is background. None on a failed capture, and the caller treats
        that as "don't reject the row" — refusing to play on a missing frame is worse than
        attempting it and letting the game refuse.
        """
        rect = self._rect()
        if rect is None:
            return None
        x, y, width, height = region
        image = self._engine.capture_bgr((rect[0] + x, rect[1] + y, width, height))
        if image is None or image.size == 0:
            return None
        saturation = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)[:, :, 1]
        return float(np.percentile(saturation, 90))

    def _exists(self, rel_path: str) -> bool:
        return os.path.isfile(self._engine.to_absolute_path(rel_path))

    def missing_templates(self) -> list[str]:
        """Which crops the scan still needs — the answer to "why is everything
        unknown"."""
        return [path for path in expected_templates() if not self._exists(path)]


@dataclass
class ChallengeTracker:
    """What the macro remembers between reads.

    There is deliberately no `enabled` flag here: whether challenges run is decided by one
    thing only, a Challenge task being in the queue. `MacroController._challenge_wants_in`
    asks this tracker before every match, so position does not decide when one is taken.

    A row that has been **played** is done for the rest of the rotation, win or lose — one
    run of each of the three per rotation. When the clock crosses :00 or :30 the maps
    re-roll and those marks stop applying.
    """

    reads: dict[int, ChallengeRead] = field(default_factory=dict)
    _skipped: set[int] = field(default_factory=set)
    _interval: tuple[int, int, int, int, int] | None = None
    # Which rotation the panel was last *looked at* in, whether or not the look worked.
    # Keyed by interval so it expires on its own, and it is what stops a panel that can't
    # be read from sending the macro out of a match once per match cycle for ever.
    _attempted: tuple[int, int, int, int, int] | None = None

    def note_time(self, now: datetime | None = None) -> bool:
        """Call before deciding anything. Returns True when the rotation changed,
        which is also when the skip list was cleared."""
        key = interval_key(now)
        if key == self._interval:
            return False
        rolled = self._interval is not None
        self._interval = key
        self._skipped.clear()
        if rolled:
            self.reads.clear()
        return rolled

    def note_reads(self, reads: list[ChallengeRead]) -> None:
        self.reads = {read.slot: read for read in reads}

    def note_scan_attempt(self, now: datetime | None = None) -> None:
        """The panel was looked at in this rotation — successfully or not."""
        self._attempted = interval_key(now)

    def needs_rescan(self, now: datetime | None = None) -> bool:
        """Is there no usable read for the current rotation yet?

        True right after a re-roll, because `note_time` throws the old rotation's reads
        away — and that is the case a running macro cannot otherwise notice. Without this
        the queue falls through to its targets and never looks at the challenge panel
        again, which is what the user hit: the maps reset mid-match and the run carried on
        with targets for the rest of the session.

        False once a scan has been attempted in this rotation, even a failed one, so an
        unreadable panel costs one detour rather than one per match.
        """
        return not self.reads and self._attempted != interval_key(now)

    # There is no `note_run_used`. It decremented a row's `n/10` between scans so a win
    # notification could carry the new number, and its only caller was
    # `window.py::_record_outcome`, deleted with the Qt front end. Nothing needs it now: the
    # game's counter is the source of truth, every rotation re-scans it, and a played row is
    # retired by `mark_done` regardless of the count.

    def mark_done(self, slot: int) -> None:
        """This row has been played this rotation — don't offer it again until the re-roll.

        Both outcomes count. A **loss** would lose again on the same map and spend another
        of the day's ten. A **win** has taken what that row was worth: the design is one
        run of each of the three per rotation, so replaying it instead of moving to the
        next row is a wasted run either way. Cleared by `note_time` when the maps change.

        Also flags the stored read, which is the *only* thing the stats panel sees — the
        skip list is private to this tracker, so a played row kept reading "Ready" there.
        `_skipped` stays the authority for decisions; the flag is for display.
        """
        self._skipped.add(int(slot))
        read = self.reads.get(int(slot))
        if read is not None:
            read.played = True

    def is_skipped(self, slot: int) -> bool:
        return slot in self._skipped

    def candidates(self) -> list[ChallengeRead]:
        """Rows worth attempting, top to bottom: not exhausted, not lost this
        rotation. Empty means fall through to the target slots."""
        return [
            read
            for slot in SLOTS
            if (read := self.reads.get(slot)) is not None
            and read.is_candidate
            and not self.is_skipped(slot)
        ]

    def has_work(self) -> bool:
        return bool(self.candidates())

    def summary(self) -> str:
        if not self.reads:
            return "challenge panel not read yet"
        parts = []
        for slot in SLOTS:
            read = self.reads.get(slot)
            if read is None:
                continue
            state = "skipped" if self.is_skipped(slot) else read.state
            parts.append(f"{slot}: {state} {read.map_name or '?'}")
        return ", ".join(parts)
