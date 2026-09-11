"""Tests for Eclipse Card Priority List settings, bridge APIs, and nav images."""

import os
import sys
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.config.unified import DEFAULTS, UnifiedSettings
from sloppykeys.content.nav_images import card_image, card_image_paths, CARDS_DIR
from sloppykeys.ui_web.bridge import Api

# 1. Check DEFAULTS
assert "eclipse_cards" in DEFAULTS
assert DEFAULTS["eclipse_cards"] == [
    {"name": "Redemption", "enabled": True},
    {"name": "Sacrifice", "enabled": True},
]
assert "eclipse_card_fallback" in DEFAULTS
assert DEFAULTS["eclipse_card_fallback"] == "skip"

# 2. Check path helpers
assert card_image("Divine Regeneration").replace("\\", "/") == "assets/cards/divine_regeneration.png"
assert card_image("Trait Purge").replace("\\", "/") == "assets/cards/trait_purge.png"
assert card_image("King's Wrath").replace("\\", "/") == "assets/cards/kings_wrath.png"

# 3. Test UnifiedSettings and Bridge APIs with a temporary directory
tmp_dir = tempfile.mkdtemp()
try:
    settings = UnifiedSettings(tmp_dir)

    # Defaults on clean directory
    assert settings.get_eclipse_cards() == [
        {"name": "Redemption", "enabled": True},
        {"name": "Sacrifice", "enabled": True},
    ]
    assert settings.get_eclipse_card_fallback() == "skip"

    # Set cards with order and enabled flags
    test_cards = [
        {"name": "Divine Regeneration", "enabled": True},
        {"name": "Trait Purge", "enabled": False},
        {"name": "Shadow Surge", "enabled": True},
    ]
    assert settings.set_eclipse_cards(test_cards) is True
    loaded = settings.get_eclipse_cards()
    assert len(loaded) == 3
    assert loaded[0] == {"name": "Divine Regeneration", "enabled": True}
    assert loaded[1] == {"name": "Trait Purge", "enabled": False}
    assert loaded[2] == {"name": "Shadow Surge", "enabled": True}

    # Reorder cards
    reordered = [loaded[2], loaded[0], loaded[1]]
    settings.set_eclipse_cards(reordered)
    loaded_reordered = settings.get_eclipse_cards()
    assert loaded_reordered[0]["name"] == "Shadow Surge"
    assert loaded_reordered[1]["name"] == "Divine Regeneration"
    assert loaded_reordered[2]["name"] == "Trait Purge"

    # Fallback setting
    assert settings.set_eclipse_card_fallback("first") is True
    assert settings.get_eclipse_card_fallback() == "first"
    assert settings.set_eclipse_card_fallback("invalid") is True
    assert settings.get_eclipse_card_fallback() == "skip"

    # Test Bridge Api methods
    os.makedirs(os.path.join(tmp_dir, "assets", "cards"), exist_ok=True)
    api = Api.__new__(Api)
    api._app_root = tmp_dir
    api._window = None
    api._ctrl = None

    # Bridge get_eclipse_cards
    cards_res = api.get_eclipse_cards()
    assert cards_res["ok"] is True
    assert cards_res["fallback"] == "skip"
    assert len(cards_res["cards"]) == 3
    assert cards_res["cards"][0]["name"] == "Shadow Surge"
    assert cards_res["cards"][0]["missing"] is True  # no file on disk yet

    # Bridge add_eclipse_card
    add_res = api.add_eclipse_card("Solar Burst")
    assert add_res["ok"] is True
    assert len(add_res["cards"]) == 4
    assert add_res["cards"][3]["name"] == "Solar Burst"
    assert add_res["cards"][3]["enabled"] is True

    # Duplicate rejection
    dup_res = api.add_eclipse_card("solar burst")
    assert dup_res["ok"] is False
    assert "already in the pool" in dup_res["reason"]

    # Empty name rejection
    empty_res = api.add_eclipse_card("   ")
    assert empty_res["ok"] is False

    # Bridge remove_eclipse_card
    rem_res = api.remove_eclipse_card("Trait Purge")
    assert rem_res["ok"] is True
    assert len(rem_res["cards"]) == 3
    assert not any(c["name"] == "Trait Purge" for c in rem_res["cards"])

    # Fallback bridge
    api.set_eclipse_card_fallback("first")
    assert api.get_eclipse_card_fallback() == "first"

    # Test Image Manager category and expected cards listing
    templates_res = api.list_vision_templates()
    assert templates_res["ok"] is True
    cards_cat = next((c for c in templates_res["categories"] if c["key"] == "cards"), None)
    assert cards_cat is not None
    assert cards_cat["label"] == "Cards"
    assert cards_cat["kind"] == "template"
    # Configured cards should be listed as missing templates in Image Manager
    missing_names = {item["name"] for item in cards_cat["names"]}
    assert "shadow_surge" in missing_names
    assert "divine_regeneration" in missing_names
    assert "solar_burst" in missing_names

finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

print("Eclipse cards test: OK")
