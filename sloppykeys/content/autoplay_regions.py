"""OCR boxes read for the Auto Play Settings dialog.

Editable in Settings > Vision (OCR tab), stored in `settings.json` under
`vision_regions` with the `autoplay_` prefix.

Read through `autoplay_presets_region()`, never the default directly.
"""

from __future__ import annotations

# Default region for the Autoplay presets area on 1152x756 viewport:
# (x, y, w, h) in client space. Centered area ~430x320.
AUTOPLAY_PRESETS_DEFAULT_REGION = (360, 220, 430, 320)

_OVERRIDES: dict[str, tuple[int, int, int, int]] = {}

KEY_PREFIX = "autoplay_"


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


def autoplay_presets_region() -> tuple[int, int, int, int]:
    """The box scanned for Auto Play presets. Honours the user's override."""
    return _OVERRIDES.get(region_key("presets"), AUTOPLAY_PRESETS_DEFAULT_REGION)


def region_specs() -> list[tuple[str, str, tuple[int, int, int, int]]]:
    """(key, label, default) for everything the OCR tab can edit here."""
    return [
        (region_key("presets"), "Autoplay presets", AUTOPLAY_PRESETS_DEFAULT_REGION),
    ]
