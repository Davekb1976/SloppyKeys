"""OCR boxes read for the Unit Teams dialog.

Editable in Settings > Vision (OCR tab), stored in `settings.json` under
`vision_regions` with the `teams_` prefix.

Read through `unit_teams_region()`, never the default directly.
"""

from __future__ import annotations

# Default region for the Unit Teams modal on 1152x756 viewport:
# (x, y, w, h) in client space. Centered modal ~690x415.
UNIT_TEAMS_DEFAULT_REGION = (230, 170, 695, 415)

_OVERRIDES: dict[str, tuple[int, int, int, int]] = {}

KEY_PREFIX = "teams_"


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


def unit_teams_region() -> tuple[int, int, int, int]:
    """The box scanned for Unit Teams (Team #1 - Team #8). Honours the user's override."""
    return _OVERRIDES.get(region_key("panel"), UNIT_TEAMS_DEFAULT_REGION)


def region_specs() -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """(key, label, default) for everything the OCR tab can edit here."""
    return [
        (region_key("panel"), "Unit Teams panel", UNIT_TEAMS_DEFAULT_REGION),
    ]
