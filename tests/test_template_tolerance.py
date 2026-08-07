"""Runnable check: a per-template tolerance reaches the search that uses it.

Settings > Vision offers a threshold spin per template, and the number is worthless if a
search resolves it in some places and takes the 0.70 default in others — the tester then
reports one thing and the run does another. `find_until` resolves it for every lobby and
placement search; the end-of-match outcome builds its profiles by hand, and that is the one
that silently ignored it.

No framework, no Qt, no capture, no input:
`.venv\\Scripts\\python.exe tests\\test_template_tolerance.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import game_lost_image, game_won_image  # noqa: E402
from sloppykeys.config.regions import clean_confidence  # noqa: E402
from sloppykeys.core.image_search import (  # noqa: E402
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    CONFIDENCE_USER_MIN,
    DEFAULT_CONFIDENCE,
    ImageMatch,
    apply_confidence_overrides,
    best_match,
    best_score,
    confidence_for,
    confidence_key,
)
from sloppykeys.macro.placement import UnitPlacer  # noqa: E402

WON, LOST = game_won_image(), game_lost_image()


class _Engine:
    """Enough of `ImageSearchEngine` for the profile builder and `best_match`: it resolves
    paths and hands back one canned hit, so nothing is captured or matched."""

    hit: ImageMatch | None = None

    def to_absolute_path(self, rel_path: str) -> str:
        return os.path.join("C:\\images", rel_path)

    def find_all(self, profiles, _rect, confidence=None):
        # `best_match` must ask for everything, or a bad score is reported as "no capture".
        assert confidence == 0.0, confidence
        self.asked = [(p.name, p.confidence) for p in profiles]
        return [] if self.hit is None else [self.hit]


def thresholds() -> dict[str, float]:
    placer = UnitPlacer(_Engine(), ahk=None, roblox_rect=lambda: None, game_keys=lambda: {})
    return {profile.name: profile.confidence for profile in placer._outcome_profiles()}


# # No overrides: both outcome templates sit at the default
apply_confidence_overrides({})
assert thresholds() == {WON: DEFAULT_CONFIDENCE, LOST: DEFAULT_CONFIDENCE}, thresholds()

# # One tuned, the other untouched — this is what the Vision spin writes
apply_confidence_overrides({WON: 0.85})
tuned = thresholds()
assert tuned[WON] == 0.85, tuned
assert tuned[LOST] == DEFAULT_CONFIDENCE, "tuning one template must not move the other"

# # Path spelling: a value stored with backslashes must still be found
apply_confidence_overrides({WON.replace("/", "\\"): 0.55})
assert thresholds()[WON] == 0.55, thresholds()
assert confidence_key("images\\match\\game_won.png") == confidence_key("images/match/game_won.png")

# # Out-of-range values are clamped, not trusted: this reaches a matcher
apply_confidence_overrides({WON: 5.0, LOST: -1.0})
clamped = thresholds()
assert clamped[WON] == CONFIDENCE_MAX, clamped
assert clamped[LOST] == CONFIDENCE_MIN, clamped

# # The range a user may set. The engine floor must stay *below* it: `best_score` pins
# `CONFIDENCE_MIN` to accept anything, and it cannot be a value a search might demand.
assert CONFIDENCE_MIN < CONFIDENCE_USER_MIN < DEFAULT_CONFIDENCE < CONFIDENCE_MAX < 1.0
assert CONFIDENCE_USER_MIN == 0.51, CONFIDENCE_USER_MIN
# A stored value is *rejected*, not clamped, so the file never disagrees with what is in
# force — and the bounds it enforces are the same ones the spin offers.
for good in (CONFIDENCE_USER_MIN, DEFAULT_CONFIDENCE, CONFIDENCE_MAX):
    assert clean_confidence(good) == good, good
for bad in (CONFIDENCE_MIN, 0.0, 1.0, 5.0, -1.0, "0.8", True, None):
    assert clean_confidence(bad) is None, bad

# # Clearing an override returns the template to the default rather than pinning the old value
apply_confidence_overrides({})
assert thresholds() == {WON: DEFAULT_CONFIDENCE, LOST: DEFAULT_CONFIDENCE}
assert confidence_for("images/lobby/play.png") == DEFAULT_CONFIDENCE

# # The diagnostic reports *where*, not only how well
# Settings > Vision moves the cursor to this point, which is the only thing that separates a
# marginal hit on the right button from a confident hit on the wrong one.
engine = _Engine()
rect = lambda: (0, 0, 1152, 756)  # noqa: E731 - a stub provider, not logic

engine.hit = ImageMatch(
    profile_name=WON, score=0.63, center_x=576, center_y=809, left=556, top=801,
    width=40, height=16,
)
found = best_match(engine, rect, WON)
assert (found.center_x, found.center_y) == (576, 809), found
# A failing score still comes back with its position rather than as "nothing captured".
assert found.score == 0.63 and found.score < DEFAULT_CONFIDENCE
# `best_score` is now derived from it and must not have changed its answer.
assert best_score(engine, rect, WON) == 0.63

engine.hit = None
assert best_match(engine, rect, WON) is None
assert best_score(engine, rect, WON) is None
# No rect (Roblox closed) is "nothing captured", not a zero score.
assert best_match(engine, lambda: None, WON) is None

print("template tolerance: OK")
