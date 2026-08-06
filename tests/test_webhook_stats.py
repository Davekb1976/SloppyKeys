"""Runnable checks for the Discord webhook URL guard and the run counters.

No network, no framework:
`.venv\\Scripts\\python.exe tests\\test_webhook_stats.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.stats import StatsTracker, format_duration  # noqa: E402
from sloppykeys.core.webhook import (  # noqa: E402
    IMAGE_FILENAME,
    MAX_IMAGE_BYTES,
    USERNAME_MAX,
    DiscordWebhook,
    encode_multipart,
    validate_webhook_url,
)

GOOD = "https://discord.com/api/webhooks/123456789/abcDEF-token_123"

# # URL guard: this value decides where run data gets POSTed, so it's a boundary.
clean, error = validate_webhook_url(GOOD)
assert clean == GOOD and not error, (clean, error)
assert validate_webhook_url("  " + GOOD + "  ")[0] == GOOD

# Empty means "notifications off", which is not an error.
assert validate_webhook_url("") == ("", "")
assert validate_webhook_url("   ") == ("", "")

for bad in (
    "http://discord.com/api/webhooks/1/t",          # not https
    "https://evil.example.com/api/webhooks/1/t",    # not Discord
    "https://discord.com/channels/1/2",             # not a webhook path
    "https://discord.com/api/webhooks/",            # no id/token
    "ftp://discord.com/api/webhooks/1/t",
    "not a url",
):
    url, error = validate_webhook_url(bad)
    assert not url and error, bad

# discord.com alternates are fine.
assert validate_webhook_url("https://discordapp.com/api/webhooks/1/tok")[0]

# # A webhook with no URL is disabled and refuses to send rather than raising.
off = DiscordWebhook(lambda: "")
assert off.enabled is False
ok, message = off.send("nope", [("a", "b")])
assert not ok and "No webhook" in message, message

bad_hook = DiscordWebhook(lambda: "https://evil.example.com/api/webhooks/1/t")
assert bad_hook.enabled is False
assert bad_hook.send("nope", [])[0] is False

# # Screenshot attachment (body building only — nothing is posted)
PNG = b"\x89PNG\r\n\x1a\n fake pixels"
content_type, body = encode_multipart({"embeds": [{"title": "Stage Won"}]}, PNG)
boundary = content_type.split("boundary=")[1]
assert content_type.startswith("multipart/form-data; boundary=----SloppyKeys")
assert boundary.encode() not in PNG  # a random boundary can't collide with the payload
assert body.startswith(f"--{boundary}\r\n".encode())
assert body.endswith(f"--{boundary}--\r\n".encode())
assert b'name="payload_json"' in body and b'name="files[0]"' in body
assert f'filename="{IMAGE_FILENAME}"'.encode() in body
assert b"Content-Type: image/png" in body
assert PNG in body, "the image bytes must survive encoding unchanged"
assert body.count(f"--{boundary}".encode()) == 3  # two parts + the closing marker

# The embed points at the upload, and only when there is one.
captured: list[dict] = []
hook = DiscordWebhook(lambda: GOOD)
hook._post = lambda url, payload, image=None: (  # type: ignore[method-assign]
    captured.append({"payload": payload, "image": image}),
    (True, "HTTP 200"),
)[1]

hook.send("Stage Won", [("Map", "Story")], blocking=True, image_png=PNG)
embed = captured[-1]["payload"]["embeds"][0]
assert embed["image"] == {"url": f"attachment://{IMAGE_FILENAME}"}, embed
assert captured[-1]["image"] == PNG

hook.send("Macro Started", [("Map", "Story")], blocking=True)
embed = captured[-1]["payload"]["embeds"][0]
assert "image" not in embed, "start/end embeds must stay text-only"
assert captured[-1]["image"] is None

# Oversized screenshots are dropped, not sent, and don't fail the embed.
ok, _message = hook.send(
    "Stage Won", [], blocking=True, image_png=b"x" * (MAX_IMAGE_BYTES + 1)
)
assert ok and captured[-1]["image"] is None
assert "image" not in captured[-1]["payload"]["embeds"][0]

# # Every embed carries its own clock, and each event posts under its own author
# name so Discord can't stack a run's messages under one header and one time.
hook.send("Stage Won", [("Map", "Story")], blocking=True)
won = captured[-1]["payload"]
hook.send("Macro Ended", [("Map", "Story")], blocking=True)
ended = captured[-1]["payload"]

stamp = won["embeds"][0]["timestamp"]
assert datetime.fromisoformat(stamp).tzinfo is not None, stamp  # offset-aware for Discord
assert won["username"] == "SloppyKeys \u00b7 Stage Won", won["username"]
assert ended["username"] != won["username"]
assert len(DiscordWebhook(lambda: GOOD)._message_username("x" * 200)) <= USERNAME_MAX
# No title still names the app rather than posting as a blank author.
assert DiscordWebhook(lambda: GOOD)._message_username("") == "SloppyKeys"

# # Durations
assert format_duration(0) == "0:00:00"
assert format_duration(59) == "0:00:59"
assert format_duration(3661) == "1:01:01"
assert format_duration(-5) == "0:00:00"

# # Counters, session vs all time, persisted across instances
with tempfile.TemporaryDirectory() as root:
    tracker = StatsTracker(root)
    snap = tracker.snapshot()
    assert (snap.wins, snap.losses, snap.all_wins) == (0, 0, 0)
    # Nothing played yet reads as "-", not 0%.
    assert snap.win_rate == "-" and snap.all_win_rate == "-"

    tracker.start_macro()
    # A run starts in the lobby, so starting it must not start the match clock: `-`, not a
    # duration that would go on to count the navigation and the join as match time.
    assert tracker.snapshot().stage_time == "-", tracker.snapshot().stage_time

    tracker.record(True)
    tracker.record(True)
    tracker.record(False)
    snap = tracker.snapshot()
    assert (snap.wins, snap.losses, snap.total) == (2, 1, 3)
    assert snap.win_rate == "67%", snap.win_rate
    assert snap.last_run == "Loss"

    # All-time survives a restart; the session resets.
    again = StatsTracker(root)
    snap = again.snapshot()
    assert (snap.wins, snap.losses) == (0, 0)
    assert (snap.all_wins, snap.all_losses) == (2, 1), snap
    assert snap.all_win_rate == "67%"

    # Written into settings.json without disturbing other keys.
    with open(os.path.join(root, "settings.json"), encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["stats"] == {"wins": 2, "losses": 1}, saved

# # The match clock: Start Game to the result screen, and nothing either side of it.
with tempfile.TemporaryDirectory() as root:
    clock = StatsTracker(root)
    clock.start_macro()
    clock.start_stage()
    assert clock.snapshot().stage_time != "-"
    clock.end_stage()
    frozen = clock.snapshot().last_stage_seconds
    assert frozen > 0, frozen
    assert clock.snapshot().stage_time == "-", "the clock stops at the result screen"
    # `record` runs after the result screenshot's delay: it must neither extend the match
    # nor start a clock for a match that hasn't begun.
    clock.record(True)
    assert clock.snapshot().last_stage_seconds == frozen
    assert clock.snapshot().stage_time == "-"

print("webhook + stats: OK")
