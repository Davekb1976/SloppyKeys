"""Render the GitHub release notes for a tag.

    python .github/release_notes.py 0.1.0 v0.1.0 owner/repo > notes.md

**Python, not PowerShell, on purpose.** These notes are markdown full of backticks, and a
backtick is PowerShell's escape character: the first version of this lived inline in
`release.yml` and the build died at the first ``` with "Unexpected token". A triple-quoted
Python string needs no escaping at all, and this can be run locally to read the notes before
a tag goes out.

Reads `SHA256SUMS.txt` from the working directory — the checksums step writes it, and the
in-app updater refuses to install anything it can't check against it.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

TEMPLATE = """\
### Requirements

- Windows 10 or 11, x64
- [AutoHotkey v2](https://www.autohotkey.com/) — every click and keypress goes through it,
  so the macro can't drive the game without it
- Display scaling at 100%. At 125% the templates score as different images and matching
  fails.

### Install

`SloppyKeys-Setup-{version}.exe` installs per-user to `%LOCALAPPDATA%\\Programs\\SloppyKeys`
— no admin, and the folder stays writable so your captures and settings save. Your
`images`, `configs`, `routes.json` and `settings.json` are never overwritten by an upgrade,
and never removed unless you say yes when uninstalling.

The portable zip is the same build with no installer: unzip anywhere writable and run
`SloppyKeys.exe`.

### Updating

If you installed a previous version with the installer, SloppyKeys can update itself:
**Settings > Main > Updates**. It asks GitHub once per launch, downloads only when you
click, checks the download against the `SHA256SUMS.txt` below, and never touches an update
while the macro is running. One toggle turns the whole thing off.

Neither download is code-signed, so SmartScreen will warn about an unknown publisher.

```
{sums}
```

{changes}
"""


def previous_tag(tag: str) -> str:
    """The tag before this one, or "" for the first release."""
    result = subprocess.run(
        ("git", "describe", "--tags", "--abbrev=0", f"--exclude={tag}"),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(f"usage: {sys.argv[0]} <version> <tag> <owner/repo>")
    version, tag, repo = sys.argv[1:4]
    sums = pathlib.Path("SHA256SUMS.txt").read_text(encoding="utf-8").strip()
    previous = previous_tag(tag)
    changes = (
        f"**Changes:** https://github.com/{repo}/compare/{previous}...{tag}"
        if previous
        else "First tagged release."
    )
    sys.stdout.write(TEMPLATE.format(version=version, sums=sums, changes=changes))


if __name__ == "__main__":
    main()
