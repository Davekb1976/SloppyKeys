"""Render the GitHub release notes for a tag.

    python .github/release_notes.py 0.1.1 v0.1.1 owner/repo > notes.md

**The changelog is the release description.** Setup instructions belong in the README, which
is one link away and stays current; repeating them in every release means a reader scrolls
past the same three paragraphs to find the one thing they came for — what changed. Only the
facts that are specific to *this* build stay: what's new, which file to download, and its
checksums.

The changelog itself is read back off the tagged commit, where `bump_version.py` wrote it, so
the notes and the `Release <version>` commit cannot disagree.

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
{changelog}

**[`SloppyKeys-Setup-{version}.exe`]({repo_url}/releases/download/{tag}/SloppyKeys-Setup-{version}.exe)**
— installs per-user, no admin, keeps your `images`, `configs` and settings. The portable zip
is the same build without the installer.

Needs [AutoHotkey v2](https://www.autohotkey.com/) and Windows display scaling at 100% —
[setup notes]({repo_url}#readme). Unsigned, so SmartScreen will warn.

<details><summary>SHA-256</summary>

```
{sums}
```

</details>

{changes}
"""


def changelog(tag: str) -> str:
    """The tagged commit's own body, which is the changelog `bump_version.py` wrote."""
    result = subprocess.run(
        ("git", "show", "-s", "--format=%b", f"{tag}^{{commit}}"),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    body = result.stdout.strip() if result.returncode == 0 else ""
    return body or "No recorded changes."


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
    repo_url = f"https://github.com/{repo}"
    sums = pathlib.Path("SHA256SUMS.txt").read_text(encoding="utf-8").strip()
    previous = previous_tag(tag)
    changes = (
        f"[Every commit since {previous}]({repo_url}/compare/{previous}...{tag})"
        if previous
        else "First tagged release."
    )
    sys.stdout.write(
        TEMPLATE.format(
            changelog=changelog(tag),
            version=version,
            tag=tag,
            repo_url=repo_url,
            sums=sums,
            changes=changes,
        )
    )


if __name__ == "__main__":
    main()
