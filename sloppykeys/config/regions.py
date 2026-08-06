"""User overrides for measured screen geometry: OCR boxes and click points.

Why this exists: every coordinate in `content/` was measured on one machine, and being a
few pixels off doesn't fail cleanly. An OCR crop reads *plausible nonsense* (three rows all
confidently reporting "Herd Mode" is a real example from this project); an act click lands
on the neighbouring act and the macro plays the wrong thing. Anyone whose game sits
differently has to re-measure, and asking them to edit Python is not an option.

Three keys in `settings.json`:

- `regions` — `[x, y, w, h]` boxes, keyed by `content/challenge.py::region_key`. Those are
  also the filenames the panel dump writes, so the PNG you look at names the box you fix.
- `points` — `[x, y]` click points, keyed by `content/acts.py::act_key` and
  `content/start_stage.py::start_key` / `difficulty_key`.
- `confidence` — a per-template match threshold as a plain float, keyed by the template's
  relative path (`image_search.confidence_key`). Applied through
  `image_search.apply_confidence_overrides`; the default is `DEFAULT_CONFIDENCE` and only a
  deviation is stored.

Everything read from disk goes through a cleaner: JSON is untrusted input, and these values
become numpy slices and AHK click coordinates.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from sloppykeys.core.image_search import CONFIDENCE_MAX, CONFIDENCE_USER_MIN

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
KEY = "regions"
POINTS_KEY = "points"
CONFIDENCE_KEY = "confidence"

# A box smaller than this can hold no readable glyph, and a zero/negative one would slice
# an empty array. Also the guard against a stray click being saved as a region.
MIN_SIDE = 4
# Nothing legitimate is this far out; the client is ~1152x756. A generous ceiling rather
# than the exact viewport so a box stays valid if the viewport is retuned slightly.
MAX_COORD = 4096


def clean_box(value: Any) -> tuple[int, int, int, int] | None:
    """A 4-tuple of sane ints, or None. Rejects rather than repairs.

    Rejection, not clamping: a box the app silently reshaped would read the wrong pixels
    and look like an OCR fault, which is the exact failure this feature exists to fix.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, width, height = (int(part) for part in value)
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or width < MIN_SIDE or height < MIN_SIDE:
        return None
    if x + width > MAX_COORD or y + height > MAX_COORD:
        return None
    return (x, y, width, height)


def clean_point(value: Any) -> tuple[int, int] | None:
    """A click point as two sane ints, or None. Rejects rather than repairs.

    (0, 0) is allowed — it is a real client pixel — but a negative one is not: it would
    click outside the game window.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        x, y = (int(part) for part in value)
    except (TypeError, ValueError):
        return None
    if x < 0 or y < 0 or x > MAX_COORD or y > MAX_COORD:
        return None
    return (x, y)


class _OverrideStore:
    """One `settings.json` key holding `{name: [ints]}`. Absent means "use the default".

    Shared by regions and points so the read/clean/write-under-one-lock logic exists once.
    """

    def __init__(
        self,
        app_root: str,
        key: str,
        clean: Callable[[Any], Any],
        encode: Callable[[Any], Any] = list,
    ) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)
        self._key = key
        self._clean = clean
        # How a cleaned value is written. `list` for the coordinate stores; a scalar store
        # (confidence) passes `float`, because `[0.62]` would be a lie about the shape.
        self._encode = encode

    def all(self) -> dict[str, Any]:
        """Every valid override on disk. Invalid entries are dropped, not raised on — a
        hand-edited file shouldn't stop the app from starting."""
        payload = read_json(self._path) or {}
        stored = payload.get(self._key)
        if not isinstance(stored, dict):
            return {}
        cleaned: dict[str, Any] = {}
        for key, value in stored.items():
            value = self._clean(value)
            if isinstance(key, str) and value is not None:
                cleaned[key] = value
        return cleaned

    def set(self, key: str, value) -> bool:
        """Save one override. False when the value is rejected."""
        cleaned = self._clean(value)
        if cleaned is None or not key:
            return False

        def mutate(payload: dict) -> dict:
            entries = dict(payload.get(self._key) or {})
            entries[key] = self._encode(cleaned)
            payload[self._key] = entries
            return payload

        # `update_json` holds one lock across the read and the write: several stores share
        # this file and the macro worker writes stats to it every match.
        update_json(self._path, mutate)
        return True

    def clear(self, key: str) -> None:
        """Drop one override, so the code default applies again."""

        def mutate(payload: dict) -> dict:
            entries = dict(payload.get(self._key) or {})
            entries.pop(key, None)
            payload[self._key] = entries
            return payload

        update_json(self._path, mutate)


def clean_confidence(value: Any) -> float | None:
    """A per-template match threshold, or None. Rejects rather than clamps.

    The floor is `CONFIDENCE_USER_MIN` (0.60), not the engine's 0.50: this project already
    removed a global tolerance setting after it drifted to 0.57 and started matching the
    wrong screens. Rejecting a hand-edited 0.2 rather than clamping it keeps the file honest
    about what is in force — a silently raised value would look like the macro ignoring the
    setting.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    threshold = float(value)
    if threshold < CONFIDENCE_USER_MIN or threshold > CONFIDENCE_MAX:
        return None
    return threshold


class RegionStore(_OverrideStore):
    """The `regions` key: OCR crop boxes for the challenge panel."""

    def __init__(self, app_root: str) -> None:
        super().__init__(app_root, KEY, clean_box)


class PointStore(_OverrideStore):
    """The `points` key: act / start-sequence / difficulty click points."""

    def __init__(self, app_root: str) -> None:
        super().__init__(app_root, POINTS_KEY, clean_point)


class ConfidenceStore(_OverrideStore):
    """The `confidence` key: per-template match thresholds, keyed by template path.

    Scalar values, so it passes `float` as the encoder instead of the default `list`.
    Applied through `image_search.apply_confidence_overrides`, which is what every search
    reads — this store only persists.
    """

    def __init__(self, app_root: str) -> None:
        super().__init__(app_root, CONFIDENCE_KEY, clean_confidence, encode=float)
