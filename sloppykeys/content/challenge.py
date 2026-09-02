"""Challenge panel: where things are on screen, and when the game refills them.

Data only — no capture, no clicking. `macro/challenge.py` reads this to decide what
to look at; nothing here knows about cv2 or the Roblox window.

The panel shows **three** challenge rows at a time. Each has a star (its own colour per
row), a `Daily Limit n/10`, a map name with the act appended (`Rose Kingdom - Act 3`)
and a `Hard Mode` tag underneath. Positions are fixed, so every read is a small crop at
a known place rather than a search over the whole client.

Observed on the real panel, and **not yet accounted for**: the left column carries
section headers — Regular, Daily and Weekly — each with its own "Resets in" countdown,
and the row titles read `Regular Challenge#1` / `#3`. So the three rows these
coordinates read are the **Regular** ones, and Daily and Weekly are separate sections
that may have rows of their own. Everything here is scoped to what is on screen; if the
other two sections need running, that is a further set of coordinates.

Two reads decide everything, and both are **OCR** (`core/ocr.py`), because neither
string is knowable in advance — the limit counts down and the map rotates with an act
appended, so there is nothing stable to crop a template from:

- **Runnable** — `n/10` parsed from the row's limit box; `0` means used up. Read from
  the text rather than the star, because each star is a different colour, so going by
  the star would need three greyed templates and would break on a palette change.
- **Which map** — the map name box read and then fuzzy-matched to the five maps a
  challenge can land on. The row says `Rose Kingdom Act 3`, so the act is stripped and
  the rest compared; a closed set is what makes an approximate read safe.

Coordinates are client space at the pinned 1152x756 viewport, in the project's
`(x, y, w, h)` form. Measured by the user as corner pairs and converted here.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from .gamemodes import CHALLENGE, maps_for
from .nav_images import CHALLENGE_DIR, IMAGES_DIR

SLOT_COUNT = 3
SLOTS = (1, 2, 3)

# The game shows "Daily Limit 10 / 10" and counts down to 0 / 10.
RUNS_PER_DAY = 10

# Where the countdown to the next rotation is drawn. Read by nothing: the clock
# below is cheaper and can't misread. Kept because the box is measured and a future
# display of "next reset in 4:12" would want it.
RESET_TIMER_REGION = (279, 273, 33, 19)

# Per slot, top to bottom.
STAR_REGIONS: dict[int, tuple[int, int, int, int]] = {
    1: (515, 248, 24, 25),
    2: (516, 375, 24, 23),
    3: (518, 498, 21, 24),
}
# A box that clips its text reads plausible nonsense instead of failing — the limit boxes
# once cut the digits off "Daily Limit 9/10" and read "K", and the map boxes sat low
# enough to read the "Hard Mode" tag underneath three times. So cover the whole phrase
# with a few pixels of pad; over-wide is safe, because `parse_limit` finds the n/10 inside
# "Daily Limit 9/10" and `match_map_name` strips the trailing act.
LIMIT_REGIONS: dict[int, tuple[int, int, int, int]] = {
    1: (469, 325, 35, 15),
    2: (469, 454, 33, 14),
    3: (469, 580, 35, 14),
}
MAP_REGIONS: dict[int, tuple[int, int, int, int]] = {
    1: (549, 251, 200, 19),
    2: (549, 377, 180, 20),
    3: (549, 500, 191, 21),
}

# Inside the matchmaking UI, after a loss: replays the same challenge. A fixed
# coordinate because it is a button on a screen the macro has already confirmed.
LOSS_RETRY_CLICK = (512, 394)

# # User overrides
# The boxes above are defaults measured on one machine. The panel's text can sit
# elsewhere for someone else, and an OCR crop that is a few pixels off reads plausible
# nonsense rather than failing — so these are editable in Settings > Vision, stored in
# `settings.json` under `regions`, and applied here through `apply_region_overrides`.
#
# Deliberately a module-level override rather than a constructor argument on
# `ChallengeScanner`: `debug_boxes()` and `row_click()` read the same boxes, and threading
# the overrides through the scanner alone would leave those two on the defaults — the panel
# dump would show boxes the scan isn't using, which is exactly the kind of inconsistency
# that cost days here before.
#
# Read through the accessors (`star_region`, `limit_region`, `map_region`,
# `reset_timer_region`, `row_click`), never the tables directly, or an override is ignored.
_OVERRIDES: dict[str, tuple[int, int, int, int]] = {}


def region_key(kind: str, slot: int | None = None) -> str:
    """The storage key for a box. Matches `debug_boxes()`' names, so a dumped PNG's
    filename is also the key you edit."""
    return kind if slot is None else f"slot{slot}_{kind}"


def apply_region_overrides(overrides: dict[str, tuple[int, int, int, int]]) -> None:
    """Replace the override set. Called at startup and after every edit.

    Whole-set replacement rather than a merge so clearing one in the UI actually clears it.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def _region(kind: str, default, slot: int | None = None):
    return _OVERRIDES.get(region_key(kind, slot), default)


def reset_timer_region() -> tuple[int, int, int, int]:
    return _region("reset_timer", RESET_TIMER_REGION)


def star_region(slot: int) -> tuple[int, int, int, int] | None:
    return _region("star", STAR_REGIONS.get(slot), slot)


def limit_region(slot: int) -> tuple[int, int, int, int] | None:
    return _region("limit", LIMIT_REGIONS.get(slot), slot)


def map_region(slot: int) -> tuple[int, int, int, int] | None:
    return _region("map", MAP_REGIONS.get(slot), slot)


def region_specs() -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """(key, label, default) for everything the Vision tab can edit, in panel order."""
    specs: list[tuple[str, str, tuple[int, int, int, int]]] = [
        (region_key("reset_timer"), "Reset timer", RESET_TIMER_REGION),
    ]
    for slot in SLOTS:
        specs.append((region_key("star", slot), f"Row {slot} star", STAR_REGIONS[slot]))
        specs.append((region_key("limit", slot), f"Row {slot} limit text", LIMIT_REGIONS[slot]))
        specs.append((region_key("map", slot), f"Row {slot} map name", MAP_REGIONS[slot]))
    return specs


# # Running a challenge — two points still to be measured
# Where to click to *select* a row: the middle of its map-name box, so it follows a map
# region the user re-measures. **An assumption, not a measurement** — the whole card looks
# clickable; verify with the "Challenge leg: dry run" tester row before trusting it.
def row_click(slot: int) -> tuple[int, int] | None:
    region = map_region(slot)
    if region is None:
        return None
    return (region[0] + region[2] // 2, region[1] + region[3] // 2)
# Starting one is **three** clicks, all in the lobby, measured by the user:
#   1. the challenge row on the list      -> ROW_CLICK[slot], opens that challenge's UI
#   2. SELECT_STAGE_CLICK                 -> selects the stage, which reveals Start
#   3. START_CLICK                        -> begins the run
# Step 2 was the missing one, and it is why Start "wasn't there": the button does not
# exist until the stage is selected. These are fixed points on screens the macro has
# already confirmed, same as `START_COORDS` for the other gamemodes.
SELECT_STAGE_CLICK = (431, 449)
START_CLICK = (508, 410)

# The challenge list's own close button (measured by the user). Getting *out* of the list
# is not the same as changing gamemode: this screen is a panel over the gamemode menu, and
# closing it is what puts the gamemode cards back within reach. Clicking
# `CHANGE_GAMEMODE_CLICK` here instead is what made "Open Story: Story card not found"
# happen every time the queue had finished its challenges and moved on to a target.
CLOSE_LIST_CLICK = (672, 175)

# Leaving a finished match lands on the gamemode panel, showing the mode just played.
# This is its "change gamemode" control — a coordinate rather than `win_change.png`
# because the template search for it failed in game, and the panel is one the macro has
# already confirmed by getting here. From here the Challenge card is clickable again.
CHANGE_GAMEMODE_CLICK = (676, 391)

# # Templates
# Only one, and only as a fallback. The limit and the map are both read by OCR
# (`core/ocr.py`) because neither string is knowable in advance — the count moves and
# the map rotates with an act appended. This crop lets the *runnable* decision, the
# only read that changes what the macro does, still work on a machine where the OCR
# engine won't start.
DEBUG_SUBDIR = "debug"
# # The greyed star: read by colour, with no template at all
# A row already completed this rotation draws its star grey. That is the only on-screen
# statement of "not this one" — the `n/10` daily limit keeps counting runs left, so a
# finished row still reads 8/10 — and the macro's own memory of what it has played dies
# with the process.
#
# A template was tried and failed badly: template matching here is grayscale, and colour
# is the *only* difference between an active star and a greyed one, so a greyed crop
# matched active stars at 0.999. Saturation is the discriminator, and it is not close.
# Measured (`debug/panel_miss.png` star boxes vs the user's greyed crop), as the 90th
# percentile of HSV saturation over the box:
#
#   greyed star    6            (mean over the whole box: 1.7)
#   active stars   242-243      (means 163-182)
#
# So the threshold sits in a 40x gap and needs no tuning. No file to capture, name or
# keep in sync — which is the other reason this beats a template.
STAR_SATURATION_MIN = 60
# There is deliberately no `0/10` crop. It was an optional fallback for the runnable
# decision when the OCR engine wouldn't start, and it could never report the count
# itself — 7 and 8 look nothing alike to a reader but identical to a "not zero" crop.
# The user's call: the limit is read by OCR or not at all.





def challenge_maps() -> list[str]:
    """Maps a challenge can land on, i.e. which map-name templates are needed and
    which `configs/Challenge/<Map>.json` plans have to exist."""
    return maps_for(CHALLENGE)


def expected_templates() -> list[str]:
    """Nothing. The scan is pure OCR now — both template shortcuts were removed (the
    `0/10` crop by the user's call, the greyed star because it matched active stars). Kept
    so the tester row and `missing_templates()` keep their shape if a crop ever returns."""
    return []


def debug_boxes() -> list[tuple[str, tuple[int, int, int, int]]]:
    """Every measured box, named, for dumping what is actually inside each one.

    The coordinates came off screenshots, and nobody has yet seen what the macro
    sees through them. Writing each box out as a PNG is how that gets checked before
    any template is cropped from a guess — the boxes are proven first, then the crops
    come out of them.

    Reads through the accessors, so a dump always shows the boxes the scan is really
    using — including the user's overrides. A dump of the defaults while the scan used
    something else would be worse than no dump at all.
    """
    boxes: list[tuple[str, tuple[int, int, int, int]]] = [
        (region_key("reset_timer"), reset_timer_region())
    ]
    for slot in SLOTS:
        boxes.append((region_key("star", slot), star_region(slot)))
        boxes.append((region_key("limit", slot), limit_region(slot)))
        boxes.append((region_key("map", slot), map_region(slot)))
    return boxes


def debug_path(name: str) -> str:
    """Where a dumped box lands. Not a template — nothing searches this folder."""
    return os.path.join(IMAGES_DIR, CHALLENGE_DIR, DEBUG_SUBDIR, f"{name}.png")


# # Reset schedule
# The three offered challenges re-roll on every half-hour clock boundary (:00 and
# :30) — wall clock, not 30 minutes from launch. Daily limits refill at 20:00 local.
#
# None of this is treated as the source of truth: whether a row is runnable is always
# re-read from the screen. The clock only decides *when it is worth looking again*,
# and when a per-interval skip stops applying because the maps have changed.
INTERVAL_MINUTES = 30
DAILY_RESET_HOUR = 20


def interval_key(now: datetime | None = None) -> tuple[int, int, int, int, int]:
    """Identifies the current rotation window. Two reads in the same window share a
    key; crossing :00 or :30 changes it, which is what clears skipped rows."""
    moment = now or datetime.now()
    return (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute // INTERVAL_MINUTES,
    )


def next_interval_at(now: datetime | None = None) -> datetime:
    """The next :00 or :30 boundary after `now`."""
    moment = now or datetime.now()
    floor = moment.replace(
        minute=(moment.minute // INTERVAL_MINUTES) * INTERVAL_MINUTES,
        second=0,
        microsecond=0,
    )
    return floor + timedelta(minutes=INTERVAL_MINUTES)


def next_daily_reset_at(now: datetime | None = None) -> datetime:
    """The next 20:00 local time after `now`."""
    moment = now or datetime.now()
    today = moment.replace(hour=DAILY_RESET_HOUR, minute=0, second=0, microsecond=0)
    return today if today > moment else today + timedelta(days=1)


def daily_quota_spent(reads: dict) -> bool:
    """Is the day's allowance of challenge runs gone?

    True only when all three rows were read and every one of them says `0 left`. The
    `n/10` is a **daily** limit, so that state does not clear at the next re-roll: fresh
    maps arrive with nothing left to spend on them, and the next runnable challenge is
    after `next_daily_reset_at`.

    False on a partial read on purpose — a row that couldn't be OCR'd is unknown, not
    zero, and calling the day finished on a missed crop would stop the macro looking.

    Takes the tracker's `reads` mapping so this stays a fact about the numbers on screen,
    with no view of what has been played or skipped.
    """
    return all(
        (read := reads.get(slot)) is not None and read.runs_remaining == 0
        for slot in SLOTS
    )
