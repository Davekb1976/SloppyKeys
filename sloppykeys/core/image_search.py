"""Template matching against the embedded Roblox viewport.

Pure search: capture a region, match templates, return hits. No input side
effects, no game knowledge.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

import cv2  # type: ignore[import-not-found]
import mss  # type: ignore[import-not-found]
import numpy as np  # type: ignore[import-not-found]

DEFAULT_CONFIDENCE = 0.70
CONFIDENCE_MIN = 0.50
CONFIDENCE_MAX = 0.99
# The floor a *user* may set, still above `CONFIDENCE_MIN` (which exists for `best_score`'s
# accept-anything probe, and must stay below anything a search can demand).
#
# The trap this guards is real and measured: a **global** tolerance setting was removed from
# this project after drifting to 0.57 and matching the wrong screens. Per-template is a much
# narrower blast radius — one image, not every search — so the floor is the engine's, plus
# one, rather than a round number chosen out of caution. Where it matters is the *reason* a
# template scores low: wrong scale costs 0.253 correlation, so a stubborn 0.61 is a bad crop
# and dropping the threshold to meet it buys a match on the wrong element. Recapture through
# Settings > Vision before spending the last of this range.
CONFIDENCE_USER_MIN = 0.51

# Per-template thresholds from Settings > Vision, keyed by the template's relative path with
# forward slashes. Module-level and read through `confidence_for` for the same reason
# `content/challenge.py` holds its region overrides that way: several call sites resolve the
# same template, and a threshold that applied in one of them and not the others would be
# worse than none. **Read `confidence_for`, never this dict.**
_CONFIDENCE_OVERRIDES: dict[str, float] = {}


def confidence_key(rel_path: str) -> str:
    """Storage key for a template path: separators normalised, so a value saved on one path
    spelling still matches a lookup on the other."""
    return str(rel_path).replace("\\", "/").strip().lstrip("./")


def apply_confidence_overrides(values: dict[str, float]) -> None:
    """Replace the override set. Called once at startup and again on every edit."""
    _CONFIDENCE_OVERRIDES.clear()
    for key, value in (values or {}).items():
        _CONFIDENCE_OVERRIDES[confidence_key(key)] = clamp_confidence(value)


def confidence_for(rel_path: str) -> float:
    """The threshold this template must clear. `DEFAULT_CONFIDENCE` unless overridden."""
    return _CONFIDENCE_OVERRIDES.get(confidence_key(rel_path), DEFAULT_CONFIDENCE)




@dataclass
class SearchRegion:
    x: int
    y: int
    width: int
    height: int

    def normalized(self, max_width: int, max_height: int) -> "SearchRegion":
        if max_width <= 0 or max_height <= 0:
            return SearchRegion(0, 0, 0, 0)

        x = max(0, min(int(self.x), max_width - 1))
        y = max(0, min(int(self.y), max_height - 1))
        return SearchRegion(
            x=x,
            y=y,
            width=max(1, min(int(self.width), max_width - x)),
            height=max(1, min(int(self.height), max_height - y)),
        )

    def as_payload(self) -> dict[str, int]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
        }


@dataclass
class ImageProfile:
    name: str
    image_path: str
    region: SearchRegion | None = None
    enabled: bool = True
    confidence: float = DEFAULT_CONFIDENCE


@dataclass
class ImageMatch:
    profile_name: str
    score: float
    center_x: int
    center_y: int
    left: int
    top: int
    width: int
    height: int


def clamp_confidence(value: float | int | str | None) -> float:
    try:
        confidence = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_CONFIDENCE
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, confidence))


class ImageSearchEngine:
    def __init__(self, app_root: str, log: Callable[[str], None] | None = None) -> None:
        self._app_root = app_root
        self._log = log
        self._template_cache: dict[str, tuple[float, np.ndarray]] = {}
        # The last capture error already reported. A capture that fails inside
        # `LobbyNavigator._find`'s poll loop fails again every `search_poll` (0.12s), so
        # reporting every one would bury the run in identical lines. Deliberately not
        # locked: a race can only cost one duplicate line.
        self._last_capture_error: str | None = None

    # # Paths
    def to_absolute_path(self, image_path: str) -> str:
        if os.path.isabs(image_path):
            return os.path.normpath(image_path)
        return os.path.normpath(os.path.join(self._app_root, image_path))

    def to_storable_path(self, image_path: str) -> str:
        absolute_path = self.to_absolute_path(image_path)
        try:
            relative_path = os.path.relpath(absolute_path, self._app_root)
        except ValueError:
            return absolute_path
        return absolute_path if relative_path.startswith("..") else relative_path

    # # Search
    def find_first(
        self,
        profiles: Iterable[ImageProfile],
        viewport_rect: tuple[int, int, int, int],
        confidence: float | None = None,
    ) -> ImageMatch | None:
        matches = self.find_all(profiles, viewport_rect, confidence=confidence)
        return matches[0] if matches else None

    def find_all(
        self,
        profiles: Iterable[ImageProfile],
        viewport_rect: tuple[int, int, int, int],
        confidence: float | None = None,
    ) -> list[ImageMatch]:
        viewport_x, viewport_y, viewport_width, viewport_height = viewport_rect
        if viewport_width <= 0 or viewport_height <= 0:
            return []

        viewport_gray = self._capture_gray(viewport_rect)
        if viewport_gray is None:
            return []

        matches: list[ImageMatch] = []

        for profile in profiles:
            if not profile.enabled:
                continue

            template = self._load_template_gray(profile.image_path)
            if template is None:
                continue

            region = profile.region or SearchRegion(0, 0, viewport_width, viewport_height)
            region = region.normalized(viewport_width, viewport_height)
            if region.width <= 0 or region.height <= 0:
                continue

            region_gray = viewport_gray[
                region.y : region.y + region.height,
                region.x : region.x + region.width,
            ]

            template_height, template_width = template.shape[:2]
            if region_gray.shape[1] < template_width or region_gray.shape[0] < template_height:
                continue

            result = cv2.matchTemplate(region_gray, template, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)

            threshold = profile.confidence if confidence is None else confidence
            if float(max_val) < float(threshold):
                continue

            match_left = viewport_x + region.x + int(max_loc[0])
            match_top = viewport_y + region.y + int(max_loc[1])

            matches.append(
                ImageMatch(
                    profile_name=profile.name,
                    score=float(max_val),
                    center_x=match_left + (template_width // 2),
                    center_y=match_top + (template_height // 2),
                    left=match_left,
                    top=match_top,
                    width=template_width,
                    height=template_height,
                )
            )

        matches.sort(key=lambda match: match.score, reverse=True)
        return matches

    # # Capture
    def capture_png(self, viewport_rect: tuple[int, int, int, int]) -> bytes | None:
        """One colour screenshot of the region, PNG-encoded, or None if it failed.

        The rect is screen coordinates, so a caller wanting part of the Roblox
        client passes the client origin plus its offset — the pixels are the same
        ones `_capture_gray` would match against, which is what makes a template
        captured this way the right scale.

        Encoded in memory rather than written to disk. Safe to call off the UI
        thread — mss and cv2 are used per call and touch no Qt objects.
        """
        raw = self._capture_raw(viewport_rect)
        if raw is None:
            return None
        # Drop the alpha channel: mss hands back BGRA and some drivers leave alpha
        # at 0, which PNG-encodes to a fully transparent (blank-looking) image.
        image = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR) if raw.shape[2] == 4 else raw
        try:
            ok, buffer = cv2.imencode(".png", image)
        except cv2.error:
            return None
        return bytes(buffer) if ok else None

    def capture_bgr(self, viewport_rect: tuple[int, int, int, int]) -> np.ndarray | None:
        """The region as a 3-channel BGR array, or None if the grab failed.

        For OCR, which wants pixels rather than a PNG. Same capture path as matching,
        so the text read is the text a template would have been matched against.
        """
        raw = self._capture_raw(viewport_rect)
        if raw is None:
            return None
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR) if raw.shape[2] == 4 else raw

    # # Internals
    def _capture_raw(self, viewport_rect: tuple[int, int, int, int]) -> np.ndarray | None:
        left, top, width, height = viewport_rect
        monitor = {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}

        try:
            with mss.mss() as screenshotter:
                raw = np.array(screenshotter.grab(monitor))
        except Exception as exc:
            # Reported, not swallowed. A failed capture reaches the caller as "no match",
            # which reads as a template problem and sends you to the wrong half of the
            # system — the same wrong-diagnosis trap as a mis-scaled template.
            self._report_capture_error(f"Screen capture failed at {monitor}: {exc}")
            return None
        if raw.ndim != 3:
            self._report_capture_error(
                f"Screen capture at {monitor} returned {raw.ndim}D data, expected 3D."
            )
            return None
        self._last_capture_error = None
        return raw

    def _report_capture_error(self, message: str) -> None:
        if message == self._last_capture_error:
            return
        self._last_capture_error = message
        if self._log is not None:
            self._log(message)

    def _capture_gray(self, viewport_rect: tuple[int, int, int, int]) -> np.ndarray | None:
        raw = self._capture_raw(viewport_rect)
        if raw is None:
            return None
        if raw.shape[2] == 4:
            return cv2.cvtColor(raw, cv2.COLOR_BGRA2GRAY)
        return cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)

    def template_exists(self, image_path: str) -> bool:
        """Is this template on disk? For a caller that needs a fallback when it isn't,
        rather than a search that can only fail."""
        return os.path.isfile(self.to_absolute_path(image_path))

    def _load_template_gray(self, image_path: str) -> np.ndarray | None:
        absolute_path = self.to_absolute_path(image_path)

        try:
            mtime = os.path.getmtime(absolute_path)
        except OSError:
            return None

        cached = self._template_cache.get(absolute_path)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        template = cv2.imread(absolute_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None

        self._template_cache[absolute_path] = (mtime, template)
        return template


def find_until(
    engine: ImageSearchEngine,
    rect_provider: Callable[[], "tuple[int, int, int, int] | None"],
    rel_path: str,
    timeout: float = 0.0,
    poll: float = 0.25,
    region: tuple[int, int, int, int] | None = None,
    confidence: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ImageMatch | None:
    """Look for one template until `timeout` seconds have passed.

    A deadline rather than an attempt count: what matters is how long the UI gets
    to finish animating in, not how many times we looked. `timeout=0` is a single
    look, for a screen already known to be up. `region` is client-space
    (x, y, w, h). Shared by the lobby navigator and the unit placer.

    `confidence=None` — the normal case — resolves this template's own threshold via
    `confidence_for`, so a value set in Settings > Vision applies to every search of that
    image without being plumbed through each caller. Pass a number only to force one.

    `should_stop` makes the wait **cancellable**: it is checked before every look and after
    every sleep, and a True gives up immediately with None. This is what lets F1 stop a run
    inside a step instead of at the end of one — a poll holds no mouse button and no key, so
    abandoning it is safe, unlike killing an AHK script mid-press.
    """
    profile = ImageProfile(
        name=rel_path,
        image_path=engine.to_absolute_path(rel_path),
        region=SearchRegion(*region) if region else None,
        confidence=confidence_for(rel_path)
        if confidence is None
        else clamp_confidence(confidence),
    )
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if should_stop is not None and should_stop():
            return None
        rect = rect_provider()
        if rect is not None:
            match = engine.find_first([profile], rect)
            if match is not None:
                return match
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(0.01, poll))


def best_match(
    engine: ImageSearchEngine,
    rect_provider: Callable[[], "tuple[int, int, int, int] | None"],
    rel_path: str,
    region: tuple[int, int, int, int] | None = None,
) -> ImageMatch | None:
    """The best hit for this template right now, whatever the threshold — score *and* where.

    The position is half the diagnosis and a log line carrying only the number cannot show
    it: a passing score in the wrong place and a failing score on the right element read
    identically. Measured case — the Events button matched `1.00` at 307,585 and `0.63` at
    576,809 in the same session, and only the coordinates say which of those is the button.
    """
    rect = rect_provider()
    if rect is None:
        return None
    profile = ImageProfile(
        name=rel_path,
        image_path=engine.to_absolute_path(rel_path),
        region=SearchRegion(*region) if region else None,
        confidence=CONFIDENCE_MIN,
    )
    # confidence=0.0 accepts anything, so find_all returns the best hit rather than
    # filtering it away.
    matches = engine.find_all([profile], rect, confidence=0.0)
    return matches[0] if matches else None


def best_score(
    engine: ImageSearchEngine,
    rect_provider: Callable[[], "tuple[int, int, int, int] | None"],
    rel_path: str,
    region: tuple[int, int, int, int] | None = None,
) -> float | None:
    """The best correlation for this template right now, whatever the threshold.

    The instrument a failed search was missing. "Play not found" says nothing about
    *why*: 0.68 means the crop is right and the tolerance is too tight, 0.10 means the
    screen isn't the one anybody thought it was. Guessing between those two has cost
    this project several rounds. Costs one extra match, and only on failure.
    """
    match = best_match(engine, rect_provider, rel_path, region=region)
    return match.score if match is not None else None
