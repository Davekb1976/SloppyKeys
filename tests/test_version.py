"""The version scheme and the release changelog.

    .venv\\Scripts\\python.exe tests\\test_version.py

Guards three things a person or a tool gets wrong by hand: writing `0.1.10` (every
versioning tool's default), letting a second copy of the number appear somewhere it can go
stale, and padding a release note with work nobody downloading the build can see.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bump_version import group_subjects  # noqa: E402
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

# The release body is a changelog for the build: grouped, prefix stripped, and everything a
# user of the exe cannot observe left out.
notes = group_subjects(
    [
        "feat(ui): add a hidden window on Ctrl + /",
        "fix(lobby): wait for the panel to fade before clicking Start",
        "perf(vision): search the challenge panel once per scan",
        "docs(steering): add rules for writing a commit subject",
        "chore: bump a comment",
        "refactor(runner): split the run loop",
        "fix(build): render release notes in python",
        "fix(ci): let the pages workflow enable Pages itself",
        "not a conventional subject at all",
    ]
)
assert notes.startswith("New:\n- add a hidden window on Ctrl + /"), notes
assert "Fixed:\n- wait for the panel to fade before clicking Start" in notes, notes
assert "Changed:\n- search the challenge panel once per scan" in notes, notes
for invisible in ("steering", "bump a comment", "split the run loop", "notes in python", "Pages"):
    assert invisible not in notes, f"{invisible!r} is not a user-visible change"
assert "not a conventional subject" not in notes, "an unparseable subject is skipped"
assert "feat(" not in notes and "fix(" not in notes, "the type(scope) prefix is stripped"

assert group_subjects([]) == "Maintenance only: nothing user-facing."
assert group_subjects(["docs: tidy the readme"]) == "Maintenance only: nothing user-facing."

print("test_version: ok")
