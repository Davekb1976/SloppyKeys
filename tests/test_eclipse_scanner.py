"""Tests for LobbyNavigator.find_and_select_eclipse_stage and select_act with prefer_eclipse."""

import os
import sys
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.core.image_search import ImageMatch


nav = LobbyNavigator.__new__(LobbyNavigator)
nav._rect = lambda: (100, 100, 1152, 756)
nav.park_client = (10, 10)
nav.search_timeout = 1.0
nav.scroll_settle = 0.0
nav.panel_fade_wait = 0.0
nav._park = MagicMock()
nav._ahk = MagicMock()
nav._ahk.available.return_value = True
nav._ahk.run.return_value = (True, "")

# 1. Template missing on disk
orig_isfile = os.path.isfile
os.path.isfile = lambda p: False if ("eclipse" in p or "golden_hour" in p) else orig_isfile(p)
try:
    ok, msg = nav.find_and_select_eclipse_stage(max_scrolls=3, notches=4)
    assert ok is False
    assert "not found" in msg
finally:
    os.path.isfile = orig_isfile

# 2. Template present, found immediately on attempt 0
os.path.isfile = lambda p: True if "eclipse.png" in p else orig_isfile(p)
try:
    mock_match = ImageMatch(
        profile_name="eclipse", score=0.94, center_x=300, center_y=400, left=275, top=390, width=50, height=20
    )
    nav._find = MagicMock(return_value=mock_match)
    nav._click = MagicMock(return_value=(True, ""))
    nav._scroll = MagicMock(return_value=(True, ""))

    ok, msg = nav.find_and_select_eclipse_stage(max_scrolls=3, notches=4)
    assert ok is True
    assert "selected Eclipse stage" in msg
    assert nav._find.call_count == 1
    assert nav._click.call_count == 1
    assert nav._scroll.call_count == 0

    # 3. Found on attempt 2 (after 2 scrolls)
    find_results = [None, None, mock_match]
    nav._find = MagicMock(side_effect=lambda *args, **kwargs: find_results.pop(0))
    nav._click = MagicMock(return_value=(True, ""))
    nav._scroll = MagicMock(return_value=(True, ""))

    ok, msg = nav.find_and_select_eclipse_stage(max_scrolls=3, notches=4)
    assert ok is True
    assert "selected Eclipse stage" in msg
    assert nav._find.call_count == 3
    assert nav._scroll.call_count == 2
    assert nav._click.call_count == 1

    # 4. Not found after max scrolls
    nav._find = MagicMock(return_value=None)
    nav._click.reset_mock()
    nav._scroll = MagicMock(return_value=(True, ""))

    ok, msg = nav.find_and_select_eclipse_stage(max_scrolls=3, notches=4)
    assert ok is False
    assert "not found after 3 scrolls" in msg
    assert nav._find.call_count == 4
    assert nav._scroll.call_count == 3
    assert nav._click.call_count == 0

finally:
    os.path.isfile = orig_isfile

# 5. select_act with prefer_eclipse=True
os.path.isfile = lambda p: True if "eclipse_act.png" in p else orig_isfile(p)
try:
    mock_act_match = ImageMatch(
        profile_name="eclipse_act", score=0.95, center_x=249, center_y=230, left=200, top=200, width=98, height=60
    )
    nav._find = MagicMock(return_value=mock_act_match)
    nav._click = MagicMock(return_value=(True, ""))

    ok, msg = nav.select_act("Story", "Eclipse", prefer_eclipse=True)
    assert ok is True
    assert "clicked Eclipse" in msg
    assert nav._click.called
finally:
    os.path.isfile = orig_isfile

print("Eclipse scanner test: OK")
