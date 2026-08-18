"""Runnable checks for the click-point editor.

    .venv\\Scripts\\python.exe tests\\test_vision_points.py

These are the coordinates the macro clicks **blind** — an act row, Story's Hard Mode toggle,
Expedition's difficulty cycle. Nothing verifies them, so a point 20px out picks the act above
the one the task asked for and the macro farms the wrong stage looking perfectly healthy.

Two things have to hold. A saved point must reach the tables the navigator reads: `points`
had no editor in this UI and was never applied, so a corrected coordinate in settings.json
did nothing at all. And an unknown key must be refused rather than stored, because a key that
matches no accessor sits in settings.json looking like a calibration that was saved.

No window, no capture, no input: the bridge is built with `Api.__new__` against a temp root.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.acts import ACT_COORDS, act_coord, apply_point_overrides  # noqa: E402
from sloppykeys.content.gamemodes import RAID_ACTS, STORY_ACTS  # noqa: E402
from sloppykeys.content.start_stage import difficulty_coord, start_coords  # noqa: E402
from sloppykeys.ui_web.bridge import VIEWPORT_H, VIEWPORT_W, Api  # noqa: E402


def build(root: str) -> Api:
    api = Api.__new__(Api)
    api._app_root = root
    api._window = None
    api._ctrl = None
    return api


with tempfile.TemporaryDirectory() as root:
    api = build(root)

    # # Grouped by the screen they are picked on, one group per gamemode
    groups = {g["key"]: g for g in api.list_vision_points()["groups"]}
    assert set(groups) == {"acts.Story", "acts.Raid", "start.Story", "start.Expedition"}, groups
    # Every act in the table gets a chip, and the count differs per mode — that is what the
    # dot overlay is drawn from.
    assert len(groups["acts.Story"]["points"]) == len(ACT_COORDS["Story"])
    assert len(groups["acts.Raid"]["points"]) == len(ACT_COORDS["Raid"])
    assert [p["label"] for p in groups["acts.Story"]["points"]] == STORY_ACTS
    assert [p["label"] for p in groups["acts.Raid"]["points"]] == RAID_ACTS
    # Story's pair is the Hard Mode toggle; Expedition's is the cycling button.
    assert [p["label"] for p in groups["start.Story"]["points"]] == ["Hard Mode toggle"]
    assert [p["label"] for p in groups["start.Expedition"]["points"]] == ["Difficulty cycle"]
    for group in groups.values():
        assert group["where"], group["key"]  # the screen that must be up, shown on the row
        assert not any(p["edited"] for p in group["points"]), "nothing is measured yet"

    # # Refused, not repaired
    for bad_key in ("act.Story.Act 9", "act.Nonsense.Act 1", "", "../evil"):
        assert api.set_vision_point(bad_key, 10, 10)["ok"] is False, bad_key
    for bad_xy in ((-1, 10), (10, -1), (VIEWPORT_W, 10), (10, VIEWPORT_H), ("x", 10)):
        assert api.set_vision_point("act.Story.Act 1", *bad_xy)["ok"] is False, bad_xy
    assert api.get_vision_points() == {}, "a refusal must store nothing"

    # # A saved point reaches the table the navigator reads
    assert api.set_vision_point("act.Story.Act 1", 300, 400) == {"ok": True, "x": 300, "y": 400}
    assert act_coord("Story", "Act 1") == (300, 400), act_coord("Story", "Act 1")
    assert act_coord("Story", "Act 2") == ACT_COORDS["Story"]["Act 2"], "only the one point moved"
    assert api.set_vision_point("difficulty.Expedition", 111, 222)["ok"]
    assert difficulty_coord("Expedition") == (111, 222)
    assert api.set_vision_point("start.Story.hard_mode", 55, 66)["ok"]
    assert start_coords("Story")["hard_mode"] == (55, 66)
    assert api.list_vision_points()["groups"][0]["points"][0]["edited"] is True

    # # A fresh process reads them back through the same path startup uses
    reloaded = build(root)
    apply_point_overrides({})  # forget them, as if the app had just started
    assert act_coord("Story", "Act 1") == ACT_COORDS["Story"]["Act 1"]
    applied = reloaded.apply_stored_overrides()
    assert applied["points"] == 3, applied
    assert act_coord("Story", "Act 1") == (300, 400), "startup did not apply stored points"

    # # Reset takes one group back to the shipped numbers and leaves the others alone
    assert reloaded.reset_vision_points("acts.Story")["ok"]
    assert act_coord("Story", "Act 1") == ACT_COORDS["Story"]["Act 1"]
    assert difficulty_coord("Expedition") == (111, 222), "reset spilled into another group"
    assert reloaded.reset_vision_points()["ok"]
    assert difficulty_coord("Expedition") is not None  # back to the default, not gone
    assert reloaded.get_vision_points() == {}

print("vision points: OK")
