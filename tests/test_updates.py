"""Update check: version comparison, and the trust boundary around a GitHub response.

    .venv\\Scripts\\python.exe tests\\test_updates.py

No network. `release_from` is the pure half of `latest_release`, which is where every
field off the wire gets checked — a bad `browser_download_url` here would be downloaded
and executed, so the interesting cases are the hostile ones.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.core.updates import (  # noqa: E402
    SUMS_NAME,
    clear_downloads,
    is_newer,
    parse_version,
    release_from,
    sha256_for,
    update_dir,
)

assert parse_version("v0.1.2") == (0, 1, 2)
assert parse_version("0.1.2") == (0, 1, 2)
for bad in ("", "beta", "v0.1", "0.1.2-rc1", "latest", None, 3):
    assert parse_version(bad) is None, bad

assert is_newer("v0.2.0", "0.1.9")
assert is_newer("v1.0.0", "0.9.9")
assert not is_newer("v0.1.0", "0.1.0")
assert not is_newer("v0.1.0", "0.1.1")
# An unparseable tag is never "newer" — missing an update beats offering a download
# because someone tagged a release `nightly`.
assert not is_newer("nightly", "0.1.0")
assert not is_newer("v0.1.1", "beta")


def payload(tag: str, url: str, sums: str = "https://github.com/o/r/x/SHA256SUMS.txt") -> dict:
    return {
        "tag_name": tag,
        "html_url": "https://github.com/o/r/releases/tag/" + tag,
        "assets": [
            {"name": "SloppyKeys-Setup-9.9.9.exe", "browser_download_url": url},
            {"name": SUMS_NAME, "browser_download_url": sums},
        ],
    }


release, error = release_from(payload("v9.9.9", "https://github.com/o/r/x/SloppyKeys-Setup-9.9.9.exe"))
assert error == "" and release is not None
assert release.version == "9.9.9"
assert release.setup_name == "SloppyKeys-Setup-9.9.9.exe"
assert release.setup_url.startswith("https://github.com/")
assert release.sums_url.endswith(SUMS_NAME)

# A download URL off a host we don't expect is dropped, not followed. The release still
# reports itself as available — the UI then offers the release page instead of an install.
release, error = release_from(payload("v9.9.9", "https://evil.example/pwn.exe"))
assert error == "" and release is not None and release.setup_url == "", release
# http, even on the right host, is not good enough.
release, _ = release_from(payload("v9.9.9", "http://github.com/o/r/x/SloppyKeys-Setup-9.9.9.exe"))
assert release is not None and release.setup_url == ""

# An asset named something other than the expected installer is not picked up as one.
release, _ = release_from(
    {"tag_name": "v9.9.9", "assets": [{"name": "notes.txt", "browser_download_url": "https://github.com/a"}]}
)
assert release is not None and release.setup_url == "" and release.page_url.startswith("https://")

# Junk in the response: no crash, no release.
for bad in ({}, {"tag_name": "nightly"}, {"tag_name": 7}, [], "", None, {"tag_name": "v9.9.9", "assets": "no"}):
    result, message = release_from(bad)
    if bad == {"tag_name": "v9.9.9", "assets": "no"}:
        assert result is not None and result.setup_url == ""
    else:
        assert result is None and message, bad

# The download folder is ours alone, so clearing it can't reach anyone else's temp files,
# and clearing an absent one is not an error.
assert os.path.basename(update_dir()) == "SloppyKeys-update"
assert os.path.dirname(update_dir()) == tempfile.gettempdir()
clear_downloads()
os.makedirs(update_dir(), exist_ok=True)
litter = os.path.join(update_dir(), "SloppyKeys-Setup-9.9.9.exe")
with open(litter, "wb") as handle:
    handle.write(b"not really an installer")
clear_downloads()
assert not os.path.exists(litter), "a leftover download is deleted on the next check"

digest = "0" * 63 + "1"
listing = f"{digest}  SloppyKeys-Setup-9.9.9.exe\ndeadbeef  short.exe\n"
assert sha256_for(listing, "SloppyKeys-Setup-9.9.9.exe") == digest
assert sha256_for(listing, "short.exe") == "", "a malformed hash is not a hash"
assert sha256_for(listing, "missing.exe") == ""
# `sha256sum -b` writes a `*` before the name.
assert sha256_for(f"{digest} *SloppyKeys-Setup-9.9.9.exe", "SloppyKeys-Setup-9.9.9.exe") == digest

print("test_updates: ok")
