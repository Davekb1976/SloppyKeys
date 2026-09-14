r"""Runnable checks for disconnect detection and private server rejoin.

No framework, no input fired:
`.venv\Scripts\python.exe tests\test_disconnect_rejoin.py`
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.nav_images import reconnect_image, expected_paths
from sloppykeys.core.image_search import ImageMatch
from sloppykeys.core.win32 import roblox_window as rbx
from sloppykeys.macro.lobby import LobbyNavigator
from sloppykeys.macro.controller import MacroController

# 1. nav_images registration
p = reconnect_image().replace("\\", "/")
assert p == "assets/lobby/reconnect.png", f"Unexpected reconnect_image: {p}"
all_expected = [x.replace("\\", "/") for x in expected_paths()]
assert p in all_expected, f"{p} not in expected_paths()"
print("OK: reconnect_image is correctly defined and in expected_paths")

# 2. LobbyNavigator.is_disconnected() logic
class MockEngine:
    def __init__(self, exists: bool = False, match: ImageMatch | None = None):
        self._exists = exists
        self._match = match

    def template_exists(self, path: str) -> bool:
        return self._exists

    def to_absolute_path(self, path: str) -> str:
        return path


class MockAhk:
    def available(self) -> bool:
        return True

    def run(self, script, wait=True, timeout=5):
        return (True, "mocked")


mock_rect = lambda: (0, 0, 1152, 756)

# Case A: template does not exist on disk -> is_disconnected() must return False
nav_no_template = LobbyNavigator(MockEngine(exists=False), MockAhk(), mock_rect)
assert nav_no_template.is_disconnected() is False, "Should be False when template missing"

# Case B: template exists but not found on screen -> False
nav_not_found = LobbyNavigator(MockEngine(exists=True), MockAhk(), mock_rect)
nav_not_found._find = lambda path, timeout=0.0, region=None: None
assert nav_not_found.is_disconnected() is False, "Should be False when not on screen"

# Case C: template exists and found on screen -> True
nav_found = LobbyNavigator(MockEngine(exists=True), MockAhk(), mock_rect)
dummy_match = ImageMatch("reconnect", 0.95, 100, 200, 90, 190, 20, 20)
nav_found._find = lambda path, timeout=0.0, region=None: dummy_match
assert nav_found.is_disconnected() is True, "Should be True when Reconnect is found"
print("OK: LobbyNavigator.is_disconnected behaves correctly across template and match states")

# 3. wait_for_match_ready & wait_for_lobby abort early on disconnect
nav_abort = LobbyNavigator(MockEngine(exists=True), MockAhk(), mock_rect)
nav_abort._find = lambda path, timeout=0.0, region=None: dummy_match

ok, msg = nav_abort.wait_for_match_ready(timeout=5.0)
assert ok is False, "wait_for_match_ready should fail on disconnect"
assert "disconnected" in msg, f"Expected disconnect in message, got: {msg}"

ok, msg = nav_abort.wait_for_lobby(timeout=5.0)
assert ok is False, "wait_for_lobby should fail on disconnect"
assert "disconnected" in msg, f"Expected disconnect in message, got: {msg}"
print("OK: wait_for_match_ready and wait_for_lobby abort promptly on disconnect")

# 4. close_roblox_process exists and callable
assert hasattr(rbx, "close_roblox_process"), "close_roblox_process must be exported"
rbx.close_roblox_process()
print("OK: close_roblox_process callable and safe")

# 5. Controller disconnect check & handler
with tempfile.TemporaryDirectory() as tmpdir:
    logs: list[str] = []
    ctrl = MacroController(tmpdir, log=lambda m: logs.append(m))
    
    ctrl._nav.is_disconnected = lambda: True
    assert ctrl._check_disconnected() is True
    
    relaunch_called = []
    ctrl._relaunch_private_server = lambda reason="": relaunch_called.append(reason) or True
    
    handled = ctrl._handle_disconnect()
    assert handled is True
    assert len(relaunch_called) == 1
    assert relaunch_called[0] == "Roblox disconnected"
    assert ctrl._camera_set is False
    assert ctrl._kept_position is False
    assert any("Reconnect button detected" in l for l in logs)

    relaunch_called.clear()
    recovered = ctrl._try_reopen_roblox()
    assert recovered is True
    assert len(relaunch_called) == 1

print("OK: MacroController disconnect detection and rejoin handling works as expected")

# 6. Test _run_match aborts on disconnect
with tempfile.TemporaryDirectory() as tmpdir:
    logs = []
    ctrl = MacroController(tmpdir, log=lambda m: logs.append(m))
    ctrl._placer.park = lambda: None
    ctrl._placer.poll_outcome = lambda: None
    
    ctrl._nav.is_disconnected = lambda: True
    ctrl._handle_disconnect = lambda: True
    
    ctrl._run_match([], [], [])
    assert ctrl._left_early is True, "_left_early must be True when match exits due to disconnect"

print("OK: _run_match exits cleanly on disconnect and flags _left_early")
print("\nALL DISCONNECT REJOIN CHECKS PASSED.")
