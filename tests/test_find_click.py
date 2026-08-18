"""Runnable checks for Find + Click and the During match schedule.

Two new pieces. `find_instances` answers "every place this one template appears", which
`find_all` cannot — it takes `minMaxLoc`, the single best pixel, so two copies of an icon
come back as one. And `_MatchSchedule` is what lets an ability repeat during a match: the
run loop advances one step at a time and waits for it, so a repeating step in the chain
would hold the run and stop anything looking for the result screen.

A third section used to cover the PySide6 step editor (`DetailEditor`, its During-match
toggle and its default interval). That editor was deleted with `sloppykeys/ui/` — steps are
block dicts edited in `ui_web/app.js` now, with no seconds conversion and no toggle — so
those asserts went with it rather than being re-pointed at something equivalent.

No framework, no capture, no input — the engine's capture is replaced with a synthetic
frame: `.venv\\Scripts\\python.exe tests\\test_find_click.py`
"""

from __future__ import annotations

import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.units import (  # noqa: E402
    ACTION_FIND_CLICK,
    StepAction,
    UnitPlan,
    UnitStep,
)
from sloppykeys.core.image_search import (  # noqa: E402
    ImageProfile,
    ImageSearchEngine,
    SearchRegion,
)
from sloppykeys.macro.placement import (  # noqa: E402
    _MatchSchedule,
    parse_wave,
    split_steps,
)

RECT = (0, 0, 400, 300)
ICON = 20


def build_engine(root: str, spots: list[tuple[int, int]]) -> ImageSearchEngine:
    """An engine whose capture is a flat frame with the same icon at each spot."""
    rng = np.random.default_rng(7)
    icon = rng.integers(0, 255, size=(ICON, ICON), dtype=np.uint8)
    os.makedirs(os.path.join(root, "images"), exist_ok=True)
    cv2.imwrite(os.path.join(root, "images", "icon.png"), icon)

    frame = np.full((RECT[3], RECT[2]), 40, dtype=np.uint8)
    for x, y in spots:
        frame[y : y + ICON, x : x + ICON] = icon

    engine = ImageSearchEngine(root)
    engine._capture_gray = lambda _rect: frame  # type: ignore[method-assign]
    return engine


def profile(region: tuple[int, int, int, int] | None = None) -> ImageProfile:
    return ImageProfile(
        name="images/icon.png",
        image_path="images/icon.png",
        region=SearchRegion(*region) if region else None,
        confidence=0.9,
    )


# # Three copies of one icon are three matches, not one
with tempfile.TemporaryDirectory() as root:
    spots = [(30, 40), (150, 40), (300, 200)]
    engine = build_engine(root, spots)

    found = engine.find_instances(profile(), RECT)
    assert len(found) == 3, [(m.left, m.top, round(m.score, 3)) for m in found]
    corners = sorted((match.left, match.top) for match in found)
    assert corners == sorted(spots), corners
    # Centres are what the click uses.
    for match in found:
        assert match.center_x == match.left + ICON // 2
        assert match.center_y == match.top + ICON // 2

    # `find_all` is the contrast, and the reason this function exists.
    single = engine.find_all([profile()], RECT)
    assert len(single) == 1, single

    # # The limit bounds clicks, not just work
    assert len(engine.find_instances(profile(), RECT, limit=2)) == 2
    assert len(engine.find_instances(profile(), RECT, limit=1)) == 1

    # # A region confines the search
    inside = engine.find_instances(profile((0, 0, 200, 100)), RECT)
    assert sorted((m.left, m.top) for m in inside) == [(30, 40), (150, 40)], inside

    # # A region smaller than the template can never match, and must not raise
    assert engine.find_instances(profile((0, 0, 5, 5)), RECT) == []

    # # Nothing above the threshold is an empty list, not a bad match
    strict = profile()
    strict.confidence = 0.999
    hits = engine.find_instances(strict, RECT)
    assert all(match.score >= 0.999 for match in hits), [m.score for m in hits]

# # Two icons touching are still two, one overlapping is one
with tempfile.TemporaryDirectory() as root:
    engine = build_engine(root, [(100, 100), (100 + ICON, 100)])
    assert len(engine.find_instances(profile(), RECT)) == 2

# # A Find + Click action survives a save/load round trip
action = StepAction(
    type=ACTION_FIND_CLICK,
    image="images/match/ability.png",
    region_x=10,
    region_y=20,
    region_w=100,
    region_h=50,
    button="right",
    click_all=True,
)
back = StepAction.from_payload(action.as_payload())
assert back.type == ACTION_FIND_CLICK
assert back.image == "images/match/ability.png", back.image
assert back.region() == (10, 20, 100, 50), back.region()
assert back.button == "right" and back.click_all, back

# An unset region means "whole client", never a zero-sized one a template can't fit in.
assert StepAction(type=ACTION_FIND_CLICK).region() is None

# The path becomes a file path, so it goes through the route steps' validator.
assert StepAction.from_payload({"Type": "findclick", "Image": "../../etc/passwd"}).image == ""
assert StepAction.from_payload({"Type": "findclick", "ClickAll": "yes"}).click_all

# A type this build doesn't know falls back rather than running something unintended.
assert StepAction.from_payload({"Type": "teleport"}).type == "click"

# # During match steps are scheduled, never chained
plan = UnitPlan.empty()
plan.steps[0] = UnitStep(step=1, x="10", y="20", slot="1", preplacement=True)
plan.steps[1] = UnitStep(step=2, x="30", y="40", slot="2")
plan.steps[2] = UnitStep(
    step=3, kind="sequence", during_match=True, wait="2000",
    actions=[StepAction(type=ACTION_FIND_CLICK, image="images/a.png")],
)

assert [step.step for step in plan.match_steps()] == [3]
assert [step.step for step in plan.chain_steps()] == [1, 2]
pre, during = split_steps(plan.enabled_steps())
assert [step.step for step in pre] == [1], pre
assert [step.step for step in during] == [2], during

# A sequence step's interval and flag have to survive the round trip, or the step silently
# becomes a one-shot chain step again.
loaded = UnitStep.from_payload(plan.steps[2].as_payload(), fallback_step=3)
assert loaded.during_match and loaded.wait == "2000", (loaded.during_match, loaded.wait)


# # The schedule: one step per pass, own clock each, dropped on failure
def step_at(number: int, interval_ms: int) -> UnitStep:
    return UnitStep(
        step=number,
        kind="sequence",
        during_match=True,
        wait=str(interval_ms),
        actions=[StepAction(type=ACTION_FIND_CLICK, image="images/a.png")],
    )


ran: list[int] = []
schedule = _MatchSchedule([step_at(1, 1000), step_at(2, 5000)])

# Both are due immediately, but only one runs per pass — a burst of clicks with no look at
# the screen between them is how a result gets missed.
assert schedule.run_due(0.0, lambda s: (ran.append(s.step), True)[1])
assert ran == [1], ran
assert schedule.run_due(0.0, lambda s: (ran.append(s.step), True)[1])
assert ran == [1, 2], ran
# Neither is due again yet.
assert not schedule.run_due(0.5, lambda s: (ran.append(s.step), True)[1])
# The 1s step comes back on its own clock; the 5s one does not.
assert schedule.run_due(1.1, lambda s: (ran.append(s.step), True)[1])
assert ran == [1, 2, 1], ran
assert not schedule.run_due(1.2, lambda s: (ran.append(s.step), True)[1])
# With both overdue, step order decides — and the loser is not starved, it takes the next
# pass, which is one OUTCOME_POLL later.
assert schedule.run_due(5.2, lambda s: (ran.append(s.step), True)[1])
assert ran == [1, 2, 1, 1], ran
assert schedule.run_due(5.25, lambda s: (ran.append(s.step), True)[1])
assert ran == [1, 2, 1, 1, 2], ran
assert "step 1 x3" in schedule.trail() and "step 2 x2" in schedule.trail(), schedule.trail()

# A step that fails stops being scheduled: the match is still winnable without an ability,
# and repeating a broken template every poll would fill the log for the rest of the match.
failing = _MatchSchedule([step_at(1, 0)])
assert failing.run_due(0.0, lambda _s: False)
assert not failing.run_due(100.0, lambda _s: False), "a failed step must not be retried"

# No during-match steps means no trail and nothing to run.
empty = _MatchSchedule([])
assert not empty.run_due(0.0, lambda _s: True)
assert empty.trail() == ""

# An interval of 0 is floored, so there is always a look between two presses.
floored = _MatchSchedule([step_at(1, 0)])
assert floored.run_due(0.0, lambda _s: True)
assert not floored.run_due(0.05, lambda _s: True), "0ms must not mean back-to-back"

# # Reading the wave counter — refuse rather than guess, it decides when an ability fires
assert parse_wave("12/25", 25) == 12
assert parse_wave("12 / 25", 25) == 12
# Digit confusions folded, separator misreads included: "|" is both a plausible slash and
# a plausible 1, which is why the separator is resolved first.
assert parse_wave("l2/25", 25) == 12
assert parse_wave("9|10", 10) == 9
# A total that disagrees with the stage is a misread of the whole thing, not a new map.
assert parse_wave("12/26", 25) is None
assert parse_wave("12/25", 0) == 12, "no max set still reads a well-formed counter"

# A bare number is only safe because max_wave bounds it.
assert parse_wave("12", 25) == 12
assert parse_wave("Wave 12", 25) == 12
assert parse_wave("125", 25) is None, "a 25-wave stage cannot be on wave 125"
assert parse_wave("125", 0) is None, "above WAVE_MAX with no stage total to trust"
assert parse_wave("26", 25) is None
assert parse_wave("0", 25) is None, "wave 0 does not exist"
assert parse_wave("", 25) is None
assert parse_wave("~~~", 25) is None
assert parse_wave("12 of 3 things 25", 25) is None, "two numbers is ambiguous"

# A Wait for Wave action survives the round trip, and its ceiling is enforced on read.
gate = StepAction(
    type="wave", wave=12, max_wave=25,
    region_x=500, region_y=10, region_w=90, region_h=24,
)
gate_back = StepAction.from_payload(gate.as_payload())
assert (gate_back.wave, gate_back.max_wave) == (12, 25), gate_back
assert gate_back.region() == (500, 10, 90, 24), gate_back.region()
assert StepAction.from_payload({"Type": "wave", "Wave": 10**6}).wave == 99
assert StepAction.from_payload({"Type": "wave", "Wave": -5}).wave == 0

# The gate has **no** timing field of its own: it takes one look, and repeating it is the
# step's During match interval. A poll here would hold the loop watching for the result.
assert not StepAction(type="wave").uses("wait_ms")
assert "Ms" not in gate.as_payload(), gate.as_payload()
# An unboxed gate says so in the list, since it can only ever fault at run time.
assert "no region" in StepAction(type="wave", wave=3).summary()
assert "no region" not in gate.summary(), gate.summary()

print("find click: OK")
