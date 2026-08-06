"""The version scheme: single-digit patch, carry at 10.

    .venv\\Scripts\\python.exe tests\\test_version.py

Guards two things a person or a tool gets wrong by hand: writing `0.1.10` (every
versioning tool's default), and letting a second copy of the number appear somewhere it
can go stale.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.version import VERSION, bump  # noqa: E402

FORMAT = re.compile(r"\d+\.\d+\.\d")

assert FORMAT.fullmatch(VERSION), f"VERSION {VERSION!r} must be MAJOR.MINOR.PATCH, patch 0-9"

assert bump("0.1.0") == "0.1.1"
assert bump("0.1.8") == "0.1.9"
assert bump("0.1.9") == "0.2.0", "patch carries into minor at 10, never 0.1.10"
assert bump("0.9.9") == "1.0.0", "and minor carries into major the same way"
assert bump("1.0.0") == "1.0.1"

# Every reachable version stays in the format, so the installer name and tag always parse.
version = "0.0.0"
for _ in range(250):
    version = bump(version)
    assert FORMAT.fullmatch(version), version

for bad in ("0.1", "0.1.10", "v0.1.0", "0.1.x", "", "0.1.0.1"):
    try:
        bump(bad)
    except ValueError:
        continue
    raise AssertionError(f"bump({bad!r}) should have been rejected")

# The titlebar and the Discord footer read this constant; the installer takes it on the
# command line (`installer.iss` errors without /DAppVersion). Nothing else may hard-code a
# version, or one of them goes stale — that is the whole point of `version.py`.
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "installer.iss"), encoding="utf-8") as handle:
    iss = handle.read()
assert '#define AppVersion "' not in iss, "installer.iss must take the version via /DAppVersion"

print("test_version: ok")
