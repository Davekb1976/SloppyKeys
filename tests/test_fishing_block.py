r"""Runnable checks for the Fishing block in Macro Manager.

    .venv\Scripts\python.exe tests\test_fishing_block.py

Verifies:
1. fishing_icon_image and fishing_rank_image accessors resolve under assets/fishing/.
2. Both templates are registered in expected_paths() and the "fishing" category exists in Image Manager.
3. If fishing_rank is already sighted, _tick_fishing returns True immediately without clicking.
4. If fishing_rank is not sighted, _tick_fishing clicks fishing_icon and parks the cursor.
5. Linear execution (_execute_block) and tick execution (_execute_battle_block) both handle type="fishing".
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import (
    expected_paths,
    fishing_icon_image,
    fishing_rank_image,
)
from sloppykeys.macro.controller import MacroController
from sloppykeys.ui_web.bridge import Api

# 1. Path & Image Manager checks
icon_path = fishing_icon_image()
rank_path = fishing_rank_image()
assert icon_path.replace("\\", "/").endswith("assets/fishing/fishing_icon.png"), icon_path
assert rank_path.replace("\\", "/").endswith("assets/fishing/fishing_rank.png"), rank_path

exp = [p.replace("\\", "/") for p in expected_paths()]
assert icon_path.replace("\\", "/") in exp, "fishing_icon must be in expected_paths"
assert rank_path.replace("\\", "/") in exp, "fishing_rank must be in expected_paths"

api = Api.__new__(Api)
api._app_root = ""
# Verify IMAGE_CATEGORIES has "fishing"
categories_dict = {}
# Verify list_vision_templates declares "fishing"
import inspect
bridge_src = inspect.getsource(Api.list_vision_templates)
assert '"fishing": ("Fishing", "template")' in bridge_src, "Fishing must be in IMAGE_CATEGORIES"


# 2. Controller execution checks
class MockEngine:
    def template_exists(self, _path: str) -> bool:
        return True


class MockNav:
    def __init__(self, rank_sighted: bool):
        self.rank_sighted = rank_sighted
        self.clicks: list[str] = []
        self.panel_fade_wait = 0.0

    def sighted(self, path: str) -> bool:
        return self.rank_sighted

    def click_button(self, path: str, label: str, fade_wait: float = 0.0):
        self.clicks.append(label)
        return (True, f"clicked {label}")


class MockPlacer:
    def __init__(self):
        self.parks = 0

    def park(self):
        self.parks += 1


ctrl = MacroController.__new__(MacroController)
ctrl._engine = MockEngine()
ctrl._placer = MockPlacer()
ctrl._log = lambda _msg: None

block = {"type": "fishing", "params": {}}

# Case A: Fishing rank is ALREADY sighted -> 0 clicks, returns True
ctrl._nav = MockNav(rank_sighted=True)
ctrl._fishing_state = {}
done = ctrl._tick_fishing(block)
assert done is True, "must return True when rank is already sighted"
assert len(ctrl._nav.clicks) == 0, f"must not click when already equipped, got: {ctrl._nav.clicks}"
assert ctrl._placer.parks == 0, "no park needed when skipping click"

# Case B: Fishing rank is NOT sighted -> clicks icon, parks cursor, returns False to await verification
ctrl._nav = MockNav(rank_sighted=False)
ctrl._fishing_state = {}
ctrl._placer = MockPlacer()
done = ctrl._tick_fishing(block)
assert done is False, "must return False while waiting for next tick to verify"
assert ctrl._nav.clicks == ["Fishing Icon"], f"must click Fishing Icon, got {ctrl._nav.clicks}"
assert ctrl._placer.parks == 1, "must park cursor after clicking icon"

# Next tick: rank becomes sighted -> returns True
ctrl._nav.rank_sighted = True
ctrl._fishing_state[id(block)]['next_look'] = 0.0
done = ctrl._tick_fishing(block)
assert done is True, "must return True once rank is verified"

# Case C: Battle block routing
ctrl._nav = MockNav(rank_sighted=True)
ctrl._fishing_state = {}
done = ctrl._execute_battle_block(block)
assert done is True, "_execute_battle_block must handle fishing"

# Case D: Linear block routing
ctrl._checkpoint = lambda: False
ctrl._nav = MockNav(rank_sighted=True)
ctrl._fishing_state = {}
ctrl._execute_block(block)  # Completes cleanly without error

print("fishing block: OK")
