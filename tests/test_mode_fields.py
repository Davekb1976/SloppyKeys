"""Runnable checks that a gamemode only offers the Task Builder rows it can operate.

A control that does nothing is worse than a missing one — it reads as a setting that was
applied. These assert the two predicates the page hides rows by, per mode, plus the one
number every threshold surface has to agree on.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_mode_fields.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.gamemodes import (  # noqa: E402
    FARM_GAMEMODE_NAMES,
    has_targets,
    maps_for,
    search_label,
)
from sloppykeys.content.start_stage import has_difficulty  # noqa: E402
from sloppykeys.core.image_search import DEFAULT_CONFIDENCE, confidence_for  # noqa: E402
from sloppykeys.ui_web.bridge import Api  # noqa: E402

api = Api.__new__(Api)
api._app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
api._ctrl = None
api._window = None


# # Stage: only where there is an act dimension
# Expedition's difficulty is not an act, and Portals has no act at all — both dropdowns could
# only ever have shown "—".
assert has_targets("Story") is True
assert has_targets("Raid") is True
assert has_targets("Expedition") is False
assert has_targets("Events") is True  # custom: acts come from routes.json
assert has_targets("Portals") is False

# # Difficulty: only where a control exists for the macro to click
# Story has the Hard Mode toggle, Expedition the 1-3 cycle. Raid, Events and Portals have
# neither, and all three were offering Easy/Hard that nothing acted on.
assert has_difficulty("Story") is True
assert has_difficulty("Expedition") is True
assert has_difficulty("Raid") is False
assert has_difficulty("Events") is False
assert has_difficulty("Portals") is False

# # The free-text row: Portals only
for mode in FARM_GAMEMODE_NAMES:
    expected = "Portal" if mode == "Portals" else ""
    assert search_label(mode) == expected, (mode, search_label(mode))

# # Portals' map is the playfield, not the portal
assert maps_for("Portals") == ["Summer"], maps_for("Portals")

# # What the page actually receives
fields = api.get_mode_fields("Portals")
assert fields == {
    "map_label": "Portal Map",
    "target_label": "Act",
    "stage": False,
    "difficulty": False,
    "extract": False,
    "search_label": "Portal",
}, fields

fields = api.get_mode_fields("Expedition")
assert fields["stage"] is False and fields["difficulty"] is True and fields["extract"] is True
assert fields["target_label"] == "Difficulty", fields

fields = api.get_mode_fields("Story")
assert fields["stage"] is True and fields["difficulty"] is True and fields["extract"] is False

fields = api.get_mode_fields("Events")
assert fields["stage"] is True and fields["difficulty"] is False
assert fields["map_label"] == "Event", fields

# An unknown mode must answer with something the page can render, not blow up.
fields = api.get_mode_fields("NoSuchMode")
assert fields["stage"] is False and fields["difficulty"] is False and fields["search_label"] == ""


# # One default tolerance, agreed everywhere
# It was hardcoded in three more places in the bridge, so raising the engine's default left
# every slider and the Test button reporting against the old number.
assert DEFAULT_CONFIDENCE == 0.80, DEFAULT_CONFIDENCE
assert confidence_for("assets/lobby/play.png") == DEFAULT_CONFIDENCE
payload = api.list_vision_templates()
assert payload["default_threshold"] == DEFAULT_CONFIDENCE, payload["default_threshold"]
for cat in payload["categories"]:
    for card in cat["names"]:
        # Untouched templates report the default; this repo ships one tuned override.
        assert 0.50 <= card["threshold"] <= 1.0, card

print("mode fields: OK")
