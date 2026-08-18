"""OCR boxes read while a match is running.

Separate from `content/challenge.py` because they are read on a different screen: the
challenge boxes only exist on the challenge panel, these only exist in a live stage. The
two share the `settings.json["vision_regions"]` store and the Settings > OCR editor, so a
key here must not collide with one there — hence the `match_` prefix.

Same contract as every other table of measured numbers: **read the accessor, never the
table.** A box measured on one machine at one viewport size is wrong elsewhere, and an OCR
crop a few pixels off reads plausible nonsense rather than failing, so the user can correct
it and the override is what the runner must see.

Measured at the pinned 1152x756 client size.
"""

from __future__ import annotations

# Where the wave counter is drawn in the match HUD, as (x, y, w, h) in client space.
#
# **Not yet confirmed against a real stage.** It came from an approximation in the runner
# rather than a measurement, which is exactly why it is editable: `wait_wave` reads whatever
# is in this box and compares the first run of digits, so a box over the wrong HUD element
# gates on the wrong number and looks like a hung block.
WAVE_REGION = (420, 15, 160, 40)


_OVERRIDES: dict[str, tuple[int, int, int, int]] = {}

# The key prefix that marks a region as belonging to this table. The OCR editor groups by
# it, and it is what keeps `wave` from colliding with a challenge box of the same name.
KEY_PREFIX = "match_"


def region_key(kind: str) -> str:
    """The `vision_regions` storage key for one box."""
    return f"{KEY_PREFIX}{kind}"


def apply_region_overrides(overrides: dict[str, tuple[int, int, int, int]]) -> None:
    """Replace the override set. Called at startup and after every edit.

    Takes the whole `vision_regions` dict; keys belonging to other tables simply never
    match. Whole-set replacement rather than a merge, so clearing one really clears it.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def wave_region() -> tuple[int, int, int, int]:
    """The box `wait_wave` OCRs. Honours the user's measurement."""
    return _OVERRIDES.get(region_key("wave"), WAVE_REGION)


def region_specs() -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """(key, label, default) for everything the OCR tab can edit here."""
    return [
        (region_key("wave"), "Wave counter", WAVE_REGION),
    ]
