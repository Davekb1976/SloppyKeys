"""Check GitHub for a newer release, and install it.

stdlib only (`urllib.request` + `json` + `hashlib`), same reasoning as `core/webhook.py`:
this is two GETs.

**Nothing here touches Roblox.** It is an HTTPS request to GitHub and, if the user asks
for it, launching our own installer. That keeps it well clear of the ban surface
(`.kiro/steering/coding-standards.md`).

**Courtesy feature rules apply.** The check runs on a worker, never blocks the UI, never
runs during a macro run, and a failure is a status line — not an error dialog and never a
stalled run. GitHub allows 60 unauthenticated API calls an hour per IP; one per launch.

# Why no token
The releases API is public, so no credential is needed. That is deliberate: a token
shipped inside an exe is a published token.

# What "install" does
Downloads `SloppyKeys-Setup-<version>.exe`, checks it against the `SHA256SUMS.txt`
published beside it, then runs it with `/SILENT` and quits the app so the running exe can
be replaced. Offered **only** when this copy was installed by that installer
(`installed_by_setup`) — a portable-zip user running it would end up with a second copy in
`%LOCALAPPDATA%`, so they get the release page instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from ..version import VERSION

REPO = "Davekb1976/SloppyKeys"
REPO_URL = f"https://github.com/{REPO}"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"{REPO_URL}/releases/latest"

# Every URL taken from the API response is checked against this before it is fetched. The
# response is untrusted input like any other JSON off the network; without the check, a
# compromised or mistaken `browser_download_url` would be downloaded and executed.
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    # Where a release asset download redirects.
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

TIMEOUT_SECONDS = 15.0
USER_AGENT = f"SloppyKeys/{VERSION} (+https://github.com/{REPO})"
# The API response is a few KB of JSON. A response orders of magnitude bigger than that is
# not something to parse.
MAX_JSON_BYTES = 1024 * 1024
# The onedir installer is ~110MB. Twice that is room to grow; a download that keeps going
# past it is not the installer.
MAX_DOWNLOAD_BYTES = 400 * 1024 * 1024
SUMS_NAME = "SHA256SUMS.txt"

# Uninstall key Inno Setup writes for this AppId (see installer.iss). `_is1` is Inno's
# suffix.
UNINSTALL_KEY = (
    r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    r"\{8E5C6E2A-4B7D-4C1E-9A3F-51099AC5E401}_is1"
)

_VERSION_PATTERN = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class Release:
    version: str
    page_url: str
    setup_url: str
    setup_name: str
    sums_url: str


def parse_version(text: object) -> tuple[int, int, int] | None:
    match = _VERSION_PATTERN.fullmatch(str(text or "").strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def is_newer(candidate: object, current: object = VERSION) -> bool:
    """True only when both parse and candidate sorts above current.

    An unparseable version is *not* newer: better to miss an update than to offer a
    download because a tag was named something unexpected.
    """
    left, right = (parse_version(candidate), parse_version(current))
    if left is None or right is None:
        return False
    return left > right


def _safe_url(url: object) -> str:
    """The URL if it is https and points at a host we expect, else ""."""
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        return ""
    return text


def _get(url: str, limit: int) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return (response.read(limit + 1)[:limit], "")
    except urllib.error.HTTPError as exc:
        # Both of these are ordinary answers rather than faults, and "HTTP 404 Not Found"
        # in the Settings panel reads like a broken app.
        if exc.code == 404:
            return (b"", "no releases published yet")
        if exc.code == 403:
            return (b"", "GitHub is rate-limiting this address; try again later")
        return (b"", f"HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        return (b"", f"could not reach GitHub: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return (b"", f"network error: {exc}")


def latest_release() -> tuple[Release | None, str]:
    """The newest published release, or (None, reason).

    (None, "") means the request worked and there is nothing newer than this build.
    """
    body, error = _get(LATEST_URL, MAX_JSON_BYTES)
    if error:
        return (None, error)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return (None, f"GitHub sent something unreadable: {exc}")
    return release_from(payload)


def release_from(payload: object) -> tuple[Release | None, str]:
    """The pure half of `latest_release`: an API response in, a Release out.

    Split out so the parsing — which is a trust boundary, since every field here came off
    the network — is testable without a network. Nothing is trusted to be the right type.
    """
    if not isinstance(payload, dict):
        return (None, "GitHub sent an unexpected response.")

    tag = str(payload.get("tag_name", ""))
    version = parse_version(tag)
    if version is None:
        return (None, f"latest release is tagged {tag!r}, which isn't a version")
    if not is_newer(tag):
        return (None, "")

    number = ".".join(str(part) for part in version)
    assets = payload.get("assets")
    assets = assets if isinstance(assets, list) else []
    setup_name = f"SloppyKeys-Setup-{number}.exe"
    urls = {
        str(asset.get("name", "")): _safe_url(asset.get("browser_download_url"))
        for asset in assets
        if isinstance(asset, dict)
    }
    return (
        Release(
            version=number,
            page_url=_safe_url(payload.get("html_url")) or RELEASES_URL,
            setup_url=urls.get(setup_name, ""),
            setup_name=setup_name,
            sums_url=urls.get(SUMS_NAME, ""),
        ),
        "",
    )


def sha256_for(sums: str, filename: str) -> str:
    """Pull one hash out of a `sha256sum`-format listing, or "" if it isn't there."""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            digest = parts[0].strip().lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
    return ""


def update_dir() -> str:
    """Where a downloaded installer goes: a folder of ours inside %TEMP%.

    Its own folder rather than %TEMP% itself so `clear_downloads` can empty it without ever
    reasoning about whose file it is looking at.
    """
    return os.path.join(tempfile.gettempdir(), "SloppyKeys-update")


def clear_downloads() -> None:
    """Delete anything left from a previous update.

    The app quits the moment it hands over to the installer, so it can't clean up after
    itself — it cleans up on the way *in* instead. A 110MB installer nobody deletes is how
    a tool quietly eats someone's disk. A file the running installer still holds open just
    fails to delete and goes next launch.
    """
    folder = update_dir()
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def expected_sha(release: Release) -> tuple[str, str]:
    """The published SHA-256 for this release's installer, or ("", reason).

    A release without one doesn't get installed automatically — see `download`.
    """
    if not release.sums_url:
        return ("", f"the release publishes no {SUMS_NAME}")
    body, error = _get(release.sums_url, MAX_JSON_BYTES)
    if error:
        return ("", error)
    digest = sha256_for(body.decode("utf-8", errors="replace"), release.setup_name)
    if not digest:
        return ("", f"{SUMS_NAME} lists no hash for {release.setup_name}")
    return (digest, "")


def download(
    url: str, dest: str, expected_sha: str = "", progress: Callable[[int], None] | None = None
) -> tuple[bool, str]:
    """Fetch `url` to `dest`, refusing anything that doesn't match `expected_sha`.

    The hash comes from the same release as the file, so it proves the download arrived
    intact — not that GitHub is honest. HTTPS and `ALLOWED_HOSTS` are what do that.
    A mismatch deletes the file: a half-downloaded installer left on disk is something a
    user will double-click.
    """
    if not _safe_url(url):
        return (False, "That download URL isn't a GitHub release asset.")
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    except OSError as exc:
        return (False, f"Failed to make a folder for the download: {exc}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            with open(dest, "wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise OSError(f"download passed {MAX_DOWNLOAD_BYTES} bytes")
                    digest.update(chunk)
                    handle.write(chunk)
                    if progress:
                        progress(total)
    except urllib.error.HTTPError as exc:
        return (False, f"HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        return (False, f"could not reach GitHub: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return (False, f"Failed to download the update: {exc}")

    if expected_sha and digest.hexdigest() != expected_sha:
        try:
            os.remove(dest)
        except OSError:
            pass
        return (False, "The download didn't match its published SHA-256, so it was deleted.")
    return (True, f"{round(total / (1024 * 1024))}MB")


def installed_by_setup(app_root: str) -> bool:
    """True when `app_root` is the folder our installer installed into.

    A portable-zip copy or a dev checkout returns False, and is offered the release page
    instead of an in-place update — running the installer from there would leave a second
    copy in `%LOCALAPPDATA%` and keep launching the old one.
    """
    if not getattr(sys, "frozen", False):
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
            location = str(winreg.QueryValueEx(key, "InstallLocation")[0])
    except (OSError, ValueError, IndexError):
        return False
    if not location:
        return False
    return os.path.normcase(os.path.normpath(location.rstrip("\\"))) == os.path.normcase(
        os.path.normpath(app_root)
    )


def launch_installer(path: str) -> tuple[bool, str]:
    """Start the downloaded installer and return; the caller then quits the app.

    `/SILENT` shows progress but no wizard, and Inno's restart manager closes this exe so
    it can be replaced. The caller quitting immediately is what makes that clean.
    """
    if not os.path.isfile(path):
        return (False, "The downloaded installer went missing.")
    try:
        # Detached: the installer must outlive us, since it is replacing our exe.
        subprocess.Popen(
            [path, "/SILENT"],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
    except OSError as exc:
        return (False, f"Failed to start the installer: {exc}")
    return (True, "installer started")
