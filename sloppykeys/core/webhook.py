"""Discord webhook notifications.

stdlib only (`urllib.request` + `json`): Discord webhooks are one HTTPS POST, so
pulling in `requests` would buy nothing.

Sends are fire-and-forget on a daemon thread. A webhook is a courtesy message, not
part of the macro: Discord being slow, rate-limiting, or unreachable must never
stall a run or freeze the UI. Failures are reported through the log callback and
otherwise ignored.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlparse

# Discord's own hosts. Anything else is rejected rather than posted to: the URL
# comes from a text field and this process would happily POST run data anywhere.
ALLOWED_HOSTS = {"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"}
WEBHOOK_PATH_PREFIX = "/api/webhooks/"

TIMEOUT_SECONDS = 10.0
USER_AGENT = "SloppyKeys (https://github.com/, macro notifier)"

# A Discord snowflake: 17-20 digits. "Copy User ID" (Developer Mode on) gives the bare
# digits; the `<@123>` and `<@!123>` forms are what you get from copying a mention out of a
# message, so both are read. Anything else is rejected rather than cleaned up — an ID the app
# quietly reshaped would silently ping nobody, which is indistinguishable from a broken field.
_USER_ID_PATTERN = re.compile(r"^<@!?(\d{17,20})>$|^(\d{17,20})$")

# Discord rejects an upload over its per-request limit (8 MiB on a free server) with
# a 413, which would drop the whole embed. A 1152x756 PNG is ~1 MB, so this only
# trips if something unexpected gets handed in — better a text-only embed than none.
MAX_IMAGE_BYTES = 7 * 1024 * 1024
IMAGE_FILENAME = "screenshot.png"

# Discord's cap on a per-message username override.
USERNAME_MAX = 80

# Embed colours, left as ints because that's what Discord takes.
COLOR_START = 0x8B5CF6   # violet
COLOR_WIN = 0x22C55E     # green
COLOR_LOSS = 0xEF4444    # red
COLOR_END = 0x64748B     # slate


def validate_webhook_url(url: str) -> tuple[str, str]:
    """Return (clean_url, error). Empty url is not an error — it means "off"."""
    cleaned = (url or "").strip()
    if not cleaned:
        return ("", "")

    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        return ("", "Webhook URL must start with https.")
    if parsed.hostname not in ALLOWED_HOSTS:
        return ("", "That isn't a Discord webhook host.")
    if not parsed.path.startswith(WEBHOOK_PATH_PREFIX) or len(parsed.path) <= len(
        WEBHOOK_PATH_PREFIX
    ):
        return ("", "Webhook URL should look like /api/webhooks/<id>/<token>.")
    return (cleaned, "")


def validate_user_id(text: str) -> tuple[str, str]:
    """Return (snowflake, error). Empty is not an error — it means "don't ping"."""
    cleaned = (text or "").strip()
    if not cleaned:
        return ("", "")
    match = _USER_ID_PATTERN.match(cleaned)
    if match is None:
        return ("", "That isn't a Discord user ID. Turn on Developer Mode, then Copy User ID.")
    return (match.group(1) or match.group(2), "")


def encode_multipart(payload: dict, image: bytes) -> tuple[str, bytes]:
    """Build a multipart/form-data body: the embed as `payload_json`, the PNG as
    `files[0]`. That pairing is how Discord attaches a file to an embed.

    Hand-rolled because the stdlib has no multipart encoder and this is two parts.
    The boundary is random, so it cannot collide with the payload; the filename is
    the module constant, never anything caller-supplied, so nothing user-controlled
    reaches a header.
    """
    boundary = f"----SloppyKeys{uuid.uuid4().hex}"
    marker = f"--{boundary}\r\n".encode("utf-8")
    parts = [
        marker,
        b'Content-Disposition: form-data; name="payload_json"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(payload).encode("utf-8"),
        b"\r\n",
        marker,
        f'Content-Disposition: form-data; name="files[0]"; filename="{IMAGE_FILENAME}"\r\n'.encode(
            "utf-8"
        ),
        b"Content-Type: image/png\r\n\r\n",
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    return (f"multipart/form-data; boundary={boundary}", b"".join(parts))


class DiscordWebhook:
    """Posts embeds to one webhook URL, which can change at runtime."""

    def __init__(
        self,
        url_provider: Callable[[], str],
        log: Callable[[str], None] | None = None,
        username: str = "SloppyKeys",
        user_id_provider: Callable[[], str] | None = None,
    ) -> None:
        self._url_provider = url_provider
        self._log = log or (lambda _m: None)
        self._username = username
        # Read through a provider like the URL, so editing the field in Settings takes effect
        # on the next send without rebuilding the hook.
        self._user_id_provider = user_id_provider or (lambda: "")

    @property
    def enabled(self) -> bool:
        url, error = validate_webhook_url(self._url_provider())
        return bool(url) and not error

    def send(
        self,
        title: str,
        fields: list[tuple[str, str]],
        color: int = COLOR_START,
        footer: str = "",
        blocking: bool = False,
        image_png: bytes | None = None,
        ping: bool = False,
    ) -> tuple[bool, str]:
        """Queue one embed. `blocking` is for the Settings test button, which wants
        a real answer; the macro never blocks on this.

        `image_png` attaches a screenshot shown inside the embed. Oversized or empty
        bytes are dropped rather than failing the send — the figures matter more
        than the picture.

        `ping` mentions the configured user. It has to go in `content`: a mention inside an
        embed renders as a mention but notifies nobody, which is the trap that makes this look
        implemented when it isn't. No ID configured means no ping and no error — the field is
        optional and a missing one is not a failed send.
        """
        url, error = validate_webhook_url(self._url_provider())
        if error:
            return (False, error)
        if not url:
            return (False, "No webhook URL set.")

        image = image_png if image_png and len(image_png) <= MAX_IMAGE_BYTES else None
        if image_png and image is None:
            self._log(
                f"Discord webhook: screenshot dropped ({len(image_png)} bytes over the limit)."
            )

        user_id, id_error = validate_user_id(self._user_id_provider())
        if id_error:
            # Say it once, on the send that wanted it, and post anyway: a mistyped ID must not
            # cost the notification itself.
            self._log(f"Discord webhook: {id_error}")

        payload = {
            # Per-message username, not the bare bot name. Each send is already its
            # own Discord message, but Discord *stacks* consecutive messages from the
            # same author under one header, which is what makes a run's embeds look
            # like one message with the times run together. A different author name
            # breaks the stack, so Start / Stage Won / Stage Lost / Macro Ended each
            # get their own header and time. Two identical events in a row can still
            # stack — the embed timestamp below is what keeps those readable.
            "username": self._message_username(title),
            "embeds": [
                {
                    "title": title,
                    "color": int(color),
                    # The clock on the embed: Discord renders this in the footer, in
                    # the reader's own timezone, per embed. UTC with an offset so it
                    # is unambiguous regardless of where the machine is set.
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    # inline=False: one fact per line reads better than a grid of
                    # two-word columns in a phone notification.
                    "fields": [
                        {"name": name, "value": value or "-", "inline": False}
                        for name, value in fields
                    ],
                    **({"footer": {"text": footer}} if footer else {}),
                    # attachment:// points the embed at the file uploaded alongside
                    # it in the same request.
                    **(
                        {"image": {"url": f"attachment://{IMAGE_FILENAME}"}}
                        if image
                        else {}
                    ),
                }
            ],
            # Always sent, whether or not this message pings. `parse: []` switches off
            # @everyone, @here and role mentions outright, so the only mention that can ever
            # notify from this app is the one ID the user typed into their own settings.
            "allowed_mentions": {
                "parse": [],
                **({"users": [user_id]} if ping and user_id else {}),
            },
        }
        if ping and user_id:
            payload["content"] = f"<@{user_id}>"

        if blocking:
            return self._post(url, payload, image)

        thread = threading.Thread(
            target=self._post_and_log, args=(url, payload, image), daemon=True
        )
        thread.start()
        return (True, "queued")

    # # Internals
    def _message_username(self, title: str) -> str:
        """`SloppyKeys · <event>`, clamped to Discord's 80-character limit.

        Titles come from this app, not from user input, but the clamp stays: Discord
        rejects the whole message on an over-long username, and losing a run's
        notification to a long title would be a silly way to fail.
        """
        event = " ".join((title or "").split())
        if not event:
            return self._username[:USERNAME_MAX]
        return f"{self._username} \u00b7 {event}"[:USERNAME_MAX]

    def _post_and_log(self, url: str, payload: dict, image: bytes | None = None) -> None:
        ok, message = self._post(url, payload, image)
        if not ok:
            self._log(f"Discord webhook failed: {message}")

    def _post(
        self, url: str, payload: dict, image: bytes | None = None
    ) -> tuple[bool, str]:
        if image:
            content_type, body = encode_multipart(payload, image)
        else:
            content_type, body = ("application/json", json.dumps(payload).encode("utf-8"))
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type, "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return (True, f"HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            # 401/404 means the URL is wrong or the webhook was deleted; 429 is
            # rate limiting. Either way the run carries on.
            return (False, f"HTTP {exc.code} {exc.reason}")
        except urllib.error.URLError as exc:
            return (False, f"could not reach Discord: {exc.reason}")
        except (TimeoutError, OSError) as exc:
            return (False, f"network error: {exc}")
