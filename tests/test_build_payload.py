"""What a shipped build carries, and what it must not.

Both failures this guards are silent and land on someone else's machine: a folder of *this*
machine's crops copied into the payload, or a secret carried out of the developer's
`settings.json`. `installer.iss` ships `assets\\*` with `onlyifdoesntexist`, so a file that
gets in once is never replaced afterwards.

    .venv\\Scripts\\python.exe tests\\test_build_payload.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_exe import (  # noqa: E402
    DATA_DIRS,
    SHIPPED_SETTINGS_KEYS,
    SKIP_DIRS,
    _ignore,
    shipped_settings,
)


def test_local_only_folders_are_skipped() -> None:
    """`assets/regions` and `assets/detect` hold crops of whatever was on one user's screen.

    Both are gitignored, so a clean-runner build never saw them, but a build from a working
    tree copied them straight into the payload.
    """
    for folder in ("debug", "__pycache__", "regions", "detect"):
        assert folder in SKIP_DIRS, f"{folder} must not be copied into a build"

    names = ["match", "lobby", "gamemodes", "regions", "detect", "debug", "images.json"]
    dropped = _ignore("assets", names)
    assert dropped == {"regions", "detect", "debug"}, dropped
    # The template folders the app cannot run without must survive the same filter.
    for keep in ("match", "lobby", "gamemodes", "images.json"):
        assert keep not in dropped, f"{keep} is shipped data and was dropped"


def test_shipped_settings_never_carries_a_secret() -> None:
    """The allowlist is the mechanism; this is the assertion that it held.

    Secrets are *set* blank rather than merely omitted, so a key that sneaks into the
    allowlist later still cannot leak.
    """
    source = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(
                {
                    "private_server_link": "https://www.roblox.com/share?code=leak&type=Server",
                    "discord_webhook": "https://discord.com/api/webhooks/leak",
                    "discord_user_id": "286825732000000000",
                    "stats": {"wins": 412, "losses": 7},
                    "tasks": [{"mode": "Expedition"}],
                    "regions": {"wait_wave": [1, 2, 3, 4]},
                    "points": {"act_1": [10, 20]},
                    "hard_mode": True,
                    "delays": {"click_settle": 0.4},
                },
                handle,
            )
            source = handle.name
        payload, carried = shipped_settings(source)
    finally:
        if source:
            os.unlink(source)

    assert payload["private_server_link"] == "", "the private server link shipped"
    assert payload["discord_webhook"] == "", "the Discord webhook shipped"
    # Not a secret, but it names a person: blanked rather than merely left out.
    assert payload["discord_user_id"] == "", "the Discord user ID shipped"
    assert payload["stats"] == {"wins": 0, "losses": 0}, "the developer's counters shipped"

    # This machine's measurements and the developer's own queue are not shipped: an override
    # present on a fresh install turns the UI's Reset button into a no-op.
    for key in ("regions", "points", "tasks"):
        assert key not in payload, f"{key} must not ship"

    # The tuning that *is* meant to carry forward still does.
    assert payload["hard_mode"] is True
    assert payload["delays"] == {"click_settle": 0.4}
    assert set(carried) <= set(SHIPPED_SETTINGS_KEYS), carried


def test_missing_source_settings_is_not_an_error() -> None:
    """A clean runner has no `settings.json` at all — it is gitignored."""
    payload, carried = shipped_settings(os.path.join(tempfile.gettempdir(), "nope.json"))
    assert carried == []
    assert payload["private_server_link"] == ""
    assert payload["discord_webhook"] == ""


def test_user_work_folders_are_not_copied() -> None:
    """`operations/`, `recordings/` and `paths/` (bar `defaults/`) are created on first save."""
    flat = {part for entry in DATA_DIRS for part in entry.replace("\\", "/").split("/")}
    for folder in ("operations", "recordings", "presets"):
        assert folder not in flat, f"{folder} is the user's own work and must not ship"
    assert os.path.join("paths", "defaults") in DATA_DIRS, "shipped walk paths must ship"
    assert "paths" not in DATA_DIRS, "shipping all of paths/ would carry user recordings"


for name, case in sorted(list(globals().items())):
    if name.startswith("test_") and callable(case):
        case()
        print(f"  {name} ok")

print("build payload ok")
