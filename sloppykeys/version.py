"""The version, in one place.

Everything else derives from this string: the titlebar pill (`ui/window.py`), the
installer's `AppVersion` (passed as `ISCC /DAppVersion=...`, which *refuses* to compile
without it), the release tag, and the release asset names. A second copy of a version
number is a stale version number.

# The scheme

`MAJOR.MINOR.PATCH`, where **PATCH is one digit**. `0.1.9` is followed by `0.2.0`, not
`0.1.10` — so a "release number" reads left to right with no ambiguity about whether 10
comes after 9. `bump_version.py` does the carry; `tests/test_version.py` fails on a
two-digit patch, because every tool in the world will happily write one.

MAJOR is a human decision (a break in the on-disk formats, or the day this stops being
pre-1.0).
"""

from __future__ import annotations

VERSION = "1.0.6"


def bump(version: str) -> str:
    """The next version after `version`, carrying at 10.

    Kept here rather than in `bump_version.py` so the test can reach it without importing
    a script that talks to git.
    """
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"not a MAJOR.MINOR.PATCH version: {version!r}")
    major, minor, patch = (int(part) for part in parts)
    # Reject `0.1.10` rather than carrying it to `0.2.0`: something already broke the
    # scheme upstream, and quietly producing a plausible next number hides it.
    if patch > 9 or minor > 9:
        raise ValueError(f"minor and patch are single digits in this scheme: {version!r}")
    if patch < 9:
        return f"{major}.{minor}.{patch + 1}"
    if minor < 9:
        return f"{major}.{minor + 1}.0"
    return f"{major + 1}.0.0"
