"""Story Golden Hour act coordinates, template registration, and selection tests."""

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.content.acts import (  # noqa: E402
    ACT_COORDS,
    act_coord,
    apply_point_overrides,
    golden_hour_act_coord,
    GOLDEN_HOUR_ACT_COORDS,
)
from sloppykeys.content.nav_images import (  # noqa: E402
    expected_paths,
    golden_hour_act_image,
    golden_hour_image,
    GOLDEN_HOUR_ACT_IMAGE,
    GOLDEN_HOUR_IMAGE,
)
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402
from sloppykeys.core.image_search import ImageMatch  # noqa: E402


# 1. Template registration
assert GOLDEN_HOUR_IMAGE == "golden_hour.png"
assert GOLDEN_HOUR_ACT_IMAGE == "golden_hour_act.png"
gh_path = golden_hour_image()
gh_act_path = golden_hour_act_image()
assert gh_path.endswith(os.path.join("assets", "lobby", "golden_hour.png"))
assert gh_act_path.endswith(os.path.join("assets", "lobby", "golden_hour_act.png"))
assert gh_path in expected_paths(), "golden_hour_image must be registered in expected_paths"
assert gh_act_path in expected_paths(), "golden_hour_act_image must be registered in expected_paths"

# 2. Coordinates
# Normal Story acts
assert act_coord("Story", "Act 1") == (249, 233)
assert act_coord("Story", "Act 2") == (250, 287)
assert act_coord("Story", "Mastery") == (249, 567)

# Golden Hour coordinates
assert golden_hour_act_coord("Story", "Golden Hour") == (249, 233)
assert golden_hour_act_coord("Story", "Act 1") == (250, 287)
assert golden_hour_act_coord("Story", "Act 2") == (246, 341)
assert golden_hour_act_coord("Story", "Act 3") == (248, 397)
assert golden_hour_act_coord("Story", "Act 4") == (246, 451)
assert golden_hour_act_coord("Story", "Act 5") == (245, 513)
assert golden_hour_act_coord("Story", "Infinite") == (249, 567)
assert golden_hour_act_coord("Story", "Mastery") == (249, 567)

# Override test
apply_point_overrides({"act.Story.Golden Hour": (260, 240)})
assert golden_hour_act_coord("Story", "Golden Hour") == (260, 240)
apply_point_overrides({})
assert golden_hour_act_coord("Story", "Golden Hour") == (249, 233)

# 3. LobbyNavigator.select_act mock tests
nav = LobbyNavigator.__new__(LobbyNavigator)
nav._rect = lambda: (100, 100, 1152, 756)
nav.park_client = (10, 10)
nav.scroll_settle = 0.0
nav.click_settle = 0.0
nav._ahk = MagicMock()
nav._ahk.available.return_value = True
nav._ahk.run.return_value = (True, "")

# Case A: Story with Golden Hour present, prefer_golden=True -> clicks matched image directly
mock_match = ImageMatch("golden_hour_act", 0.95, 349, 333, 300, 300, 50, 50)
nav._find = lambda path, **kwargs: mock_match  # Golden Hour found
nav._click = MagicMock(return_value=(True, ""))
orig_isfile = os.path.isfile
os.path.isfile = lambda p: True if "golden_hour" in p else orig_isfile(p)

try:
    ok, msg = nav.select_act("Story", "Act 1", prefer_golden=True)
    assert ok is True
    assert "clicked Golden Hour" in msg
    assert nav._click.called, "Must click matched image directly"

    # Case B: Story with Golden Hour present, prefer_golden=False -> scrolls down, then clicks Act 1 (NO pre-click on Golden Hour)
    nav._ahk.run.reset_mock()
    nav._scroll_at = MagicMock(return_value=(True, ""))
    ok, msg = nav.select_act("Story", "Act 1", prefer_golden=False)
    assert ok is True
    assert msg == "clicked Act 1"
    assert nav._scroll_at.called, "Must scroll down when Golden Hour is present to expose normal acts"
    assert nav._ahk.run.call_count == 1, "Must NOT click top slot, only click target act after scrolling"
    call_args = nav._ahk.run.call_args[0][0]
    assert "349" in call_args and "333" in call_args

    # Case C: Story with Golden Hour present, selecting Mastery -> scrolls down, then clicks Mastery at (249, 567)
    nav._scroll_at.reset_mock()
    nav._ahk.run.reset_mock()
    ok, msg = nav.select_act("Story", "Mastery", prefer_golden=False)
    assert ok is True
    assert msg == "clicked Mastery"
    assert nav._scroll_at.called, "Must scroll down for Mastery"
    assert nav._ahk.run.call_count == 1
    call_args = nav._ahk.run.call_args[0][0]
    assert "349" in call_args and "667" in call_args

    # Case D: Story without Golden Hour (not found on screen), prefer_golden=True -> falls back to Act 1
    nav._find = lambda path, **kwargs: None  # Golden Hour not found
    ok, msg = nav.select_act("Story", "Act 1", prefer_golden=True)
    assert ok is True
    assert "Golden Hour inactive" in msg
    call_args = nav._ahk.run.call_args[0][0]
    # Normal Act 1 coordinate: 100 + 249 = 349, 100 + 233 = 333
    assert "349" in call_args and "333" in call_args
finally:
    os.path.isfile = orig_isfile

print("All Golden Hour act tests passed.")
