"""Every delay the Delays tab offers must actually change something.

The tab builds itself from `DELAY_SPEC`, so adding a row there is enough to make it appear,
adjustable and saved — with nothing behind it. Two entries sat like that: `result_screenshot_delay`
and `lobby_rejoin_wait` had no reader anywhere in the tree, so moving those sliders did nothing at
all. A setting that silently changes nothing is worse than a missing one, because the user tunes it
and then trusts the result.

This is a source check, not a behaviour check: it asserts each key is *read* somewhere outside
`config/delays.py`, which is the property that broke. It cannot tell whether the value is used
sensibly — only that the wire exists.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_delays_wired.py`
"""

from __future__ import annotations

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sloppykeys.config.delays import DEFAULTS, DELAY_SPEC  # noqa: E402

# Everything except the module that declares them — a key appearing only there is the bug.
sources = {}
for path in glob.glob(os.path.join(ROOT, "sloppykeys", "**", "*.py"), recursive=True):
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    if rel == "sloppykeys/config/delays.py":
        continue
    with open(path, encoding="utf-8") as handle:
        sources[rel] = handle.read()

unread = []
for key in DELAY_SPEC:
    readers = [rel for rel, src in sources.items() if key in src]
    if not readers:
        unread.append(key)

assert not unread, (
    "these delays are offered in Settings > Delays and read by nothing: " + ", ".join(unread)
)

# The label and default are what the tab draws, so both have to be usable.
for key, (label, default) in DELAY_SPEC.items():
    assert label and label.strip(), key
    assert isinstance(default, (int, float)) and default >= 0, (key, default)
    assert DEFAULTS[key] == default, key

# # And the reverse: a General-tab setting that nothing reads is the same bug wearing a
# # different tab. `action_delay_ms` was exactly that — a number box promising a pause after
# # every click, with no reader — so it is gone from the defaults and from the page.
from sloppykeys.config.unified import DEFAULTS as UNIFIED_DEFAULTS  # noqa: E402

assert "action_delay_ms" not in UNIFIED_DEFAULTS, "a setting nothing reads must not be offered"
with open(os.path.join(ROOT, "sloppykeys", "ui_web", "index.html"), encoding="utf-8") as handle:
    html = handle.read()
assert 'data-key="action_delay_ms"' not in html, "the control outlived the setting"

# Every `[data-key]` the settings page binds must be a key the store actually knows, or the
# control saves into a slot nothing will ever read back.
import re  # noqa: E402

for key in set(re.findall(r'data-key="([a-z_0-9]+)"', html)):
    assert key in UNIFIED_DEFAULTS, f"{key} is bound on the page but absent from DEFAULTS"

print(f"delays wired: OK ({len(DELAY_SPEC)} delays, all read)")
