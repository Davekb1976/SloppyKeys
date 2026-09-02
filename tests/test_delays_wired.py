"""Every delay the Delays tab offers must actually change behaviour.

The tab builds itself from `DELAY_SPEC`, so a row appears, adjusts and saves with nothing behind
it. Two entries sat like that — `result_screenshot_delay` and `lobby_rejoin_wait` had no reader
anywhere, so those two sliders did nothing at all. A setting that silently changes nothing is
worse than a missing one, because the user tunes it and then trusts the result.

**Each delay is given a distinctive value and traced to where it is consumed.** An earlier version
of this file only checked the key name appeared somewhere in the tree, which a *comment* mentioning
the key satisfies — and the commit that wired these added exactly such comments. So the grep would
have passed on a broken wire. These assertions read the value back instead.

Nothing captures or clicks: the navigator, placer and controller are built with `__new__` and their
primitives replaced, and `time.sleep` is swapped for a recorder.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_delays_wired.py`
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sloppykeys.config.delays import DEFAULTS, DELAY_SPEC, DelaysStore  # noqa: E402
from sloppykeys.macro.controller import MacroController  # noqa: E402
from sloppykeys.macro.lobby import LobbyNavigator  # noqa: E402
from sloppykeys.macro.placement import UnitPlacer  # noqa: E402

# One recognisable number per key, none of them a default, so a value that landed in the wrong
# place is visible rather than coincidentally right.
PROBE = {
    "image_search_cooldown": 0.11,
    "panel_fade_wait": 0.22,
    "search_timeout": 33.0,
    "camera_zoom": 4.4,
    "placement_settle": 0.55,
    "result_screenshot_delay": 0.66,
    "lobby_rejoin_wait": 77.0,
}
assert set(PROBE) == set(DELAY_SPEC), "a delay was added or removed without tracing it here"

root = tempfile.mkdtemp(prefix="sk_delays_")
path = os.path.join(root, "settings.json")
store = DelaysStore(root)
for key, value in PROBE.items():
    store.set(key, value)

# # The store round-trips through settings.json, which is what startup reads
loaded = DelaysStore(root).all()
assert loaded == PROBE, loaded
with open(path, encoding="utf-8") as handle:
    assert json.load(handle)["delays"]["search_timeout"] == 33.0

# # LobbyNavigator: three keys, and `image_search_cooldown` feeds two attributes
nav = LobbyNavigator.__new__(LobbyNavigator)
nav.click_settle = nav.scroll_settle = nav.search_timeout = nav.panel_fade_wait = -1.0
nav.apply_delays(loaded)
assert nav.click_settle == 0.11, nav.click_settle
assert nav.scroll_settle == 0.11, "the unverifiable-click wait covers scrolls too"
assert nav.search_timeout == 33.0, nav.search_timeout
assert nav.panel_fade_wait == 0.22, nav.panel_fade_wait

# # UnitPlacer: its own two
placer = UnitPlacer.__new__(UnitPlacer)
placer.search_timeout = placer.settle = -1.0
placer.apply_delays(loaded)
assert placer.search_timeout == 33.0, placer.search_timeout
assert placer.settle == 0.55, placer.settle


# # camera_zoom reaches the AHK script as milliseconds, not seconds
def camera_script() -> str:
    ctrl = MacroController.__new__(MacroController)
    captured: list[str] = []
    ctrl._log = lambda _m: None
    ctrl._rect = lambda: (0, 0, 1152, 756)
    ctrl._delays = loaded
    ctrl._camera_set = False
    ctrl._ahk = type(
        "Ahk", (), {"run": staticmethod(lambda script, **k: (captured.append(script), (True, "ok"))[1])}
    )()
    ctrl.run_camera()
    return captured[0]


script = camera_script()
# 4.4s -> 4400ms. A value read but not converted would appear as `4` and hold the zoom for 4ms.
assert "4400" in script, script


# # result_screenshot_delay is the sleep in front of the capture
def screenshot_sleep() -> float:
    import sloppykeys.macro.controller as mod

    slept: list[float] = []
    original = mod.time.sleep
    mod.time.sleep = slept.append
    ctrl = MacroController.__new__(MacroController)
    ctrl._delays = loaded
    # No rect, so the capture bails straight after the sleep — the sleep is what is under test.
    ctrl._rect = lambda: None
    try:
        assert ctrl._capture_screenshot() is None
    finally:
        mod.time.sleep = original
    return slept[0] if slept else -1.0


assert screenshot_sleep() == 0.66, screenshot_sleep()


# # lobby_rejoin_wait is the deadline on the relaunch poll, and it reaches the log too
def rejoin_timeout_message() -> str:
    import sloppykeys.macro.controller as mod

    logs: list[str] = []
    ctrl = MacroController.__new__(MacroController)
    ctrl._log = logs.append
    ctrl._delays = loaded
    ctrl._app_root = root
    ctrl._stop_requested = False
    # Far enough back to clear `REOPEN_COOLDOWN`. The fake clock below starts at zero, so the
    # shipped default of 0.0 reads as "relaunched a moment ago" and the throttle returns before
    # the poll this is testing. In production `time.time()` is ~1.7e9 against that 0.0.
    ctrl._last_reopen_time = -1000.0

    class Settings:
        def __init__(self, _root):
            pass

        def get(self, key, default=None):
            # Auto-reopen on, and a **bare share code** rather than a URL: `parse_private_server_link`
            # accepts 8-64 alphanumerics on its own, so this reaches the poll without a real
            # private-server link ever appearing in the tree.
            if key == "private_server_link":
                return "aaaabbbbcccc"
            return True if key == "auto_reopen_roblox" else default

    # No window, ever — so the poll runs to its deadline and reports it.
    originals = (mod.UnifiedSettings, mod.rbx.find_roblox_window, mod.time.time, mod.time.sleep)
    mod.UnifiedSettings = Settings
    mod.rbx.find_roblox_window = staticmethod(lambda: None)
    clock = {"t": 0.0}

    def fake_time():
        return clock["t"]

    def fake_sleep(seconds):
        clock["t"] += max(0.01, float(seconds))

    mod.time.time = fake_time
    mod.time.sleep = fake_sleep
    try:
        import unittest.mock

        with unittest.mock.patch("os.startfile", create=True):
            assert ctrl._try_reopen_roblox() is False
    finally:
        (mod.UnifiedSettings, mod.rbx.find_roblox_window, mod.time.time, mod.time.sleep) = originals
    return "\n".join(logs)


message = rejoin_timeout_message()
# The number in the give-up line is the setting, not the hardcoded 60 it replaced.
assert "77s" in message, message
assert "60s" not in message, message


# # The reverse direction: a control on the page bound to a key the store does not know saves
# # into a slot nothing reads back. `action_delay_ms` was exactly that, so it is gone.
from sloppykeys.config.unified import DEFAULTS as UNIFIED_DEFAULTS  # noqa: E402

assert "action_delay_ms" not in UNIFIED_DEFAULTS, "a setting nothing reads must not be offered"
with open(os.path.join(ROOT, "sloppykeys", "ui_web", "index.html"), encoding="utf-8") as handle:
    html = handle.read()
assert 'data-key="action_delay_ms"' not in html, "the control outlived the setting"
for key in sorted(set(re.findall(r'data-key="([a-z_0-9]+)"', html))):
    assert key in UNIFIED_DEFAULTS, f"{key} is bound on the page but absent from DEFAULTS"

# Labels and defaults are what the tab draws, so both have to be usable.
for key, (label, default) in DELAY_SPEC.items():
    assert label and label.strip(), key
    assert isinstance(default, (int, float)) and default >= 0, (key, default)
    assert DEFAULTS[key] == default, key

for name in os.listdir(root):
    os.remove(os.path.join(root, name))
os.rmdir(root)

print(f"delays wired: OK ({len(DELAY_SPEC)} delays, each traced to its consumer)")
