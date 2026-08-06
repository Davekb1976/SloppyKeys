"""Bump the version, commit it, tag it, push it — which is what publishes a release.

    .venv\\Scripts\\python.exe bump_version.py            # 0.1.0 -> 0.1.1
    .venv\\Scripts\\python.exe bump_version.py --set 0.2.0
    .venv\\Scripts\\python.exe bump_version.py --dry-run

The push of tag `vX.Y.Z` is what `.github/workflows/release.yml` triggers on, so there is
no separate "make a release" step: bump, and the installer appears on the Releases page.

Patch carries at 10 (`version.py::bump`), which is the one rule a person gets wrong by
hand, and the only reason this script exists rather than an edit and two git commands.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(HERE, "sloppykeys", "version.py")

sys.path.insert(0, HERE)
from sloppykeys.version import VERSION, bump  # noqa: E402


def run(*command: str) -> str:
    result = subprocess.run(command, cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Failed to run {' '.join(command)}: {result.stderr.strip()}")
    return result.stdout.strip()


def write_version(new: str) -> None:
    """Rewrite the one assignment, leaving the module's docstring and `bump` alone."""
    with open(VERSION_FILE, encoding="utf-8") as handle:
        text = handle.read()
    patched, count = re.subn(
        r'^VERSION = "[^"]*"$', f'VERSION = "{new}"', text, count=1, flags=re.MULTILINE
    )
    if count != 1:
        raise SystemExit(f"Found no `VERSION = \"...\"` line to rewrite in {VERSION_FILE}")
    with open(VERSION_FILE, "w", encoding="utf-8") as handle:
        handle.write(patched)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="exact", help="use this version instead of the next one")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen, do none of it")
    args = parser.parse_args()

    new = args.exact or bump(VERSION)
    # Validate `--set` through the same rule the test enforces, so a hand-typed 0.1.10
    # can't get in the back door.
    if not re.fullmatch(r"\d+\.\d+\.\d", new):
        raise SystemExit(f"{new!r} is not MAJOR.MINOR.PATCH with a single-digit patch")
    tag = f"v{new}"

    if run("git", "tag", "--list", tag):
        raise SystemExit(f"Tag {tag} already exists — releases are not re-cut, bump again")
    dirty = run("git", "status", "--porcelain")
    if dirty and not args.dry_run:
        raise SystemExit(f"Working tree is not clean; commit or stash first:\n{dirty}")

    print(f"{VERSION} -> {new}, tag {tag}")
    if args.dry_run:
        return

    write_version(new)
    run("git", "add", "sloppykeys/version.py")
    run("git", "commit", "-m", f"chore(release): {new}")
    run("git", "tag", "-a", tag, "-m", f"SloppyKeys {new}")
    run("git", "push", "origin", "main")
    run("git", "push", "origin", tag)
    print(f"pushed {tag} — the release workflow is building the installer now")


if __name__ == "__main__":
    main()
