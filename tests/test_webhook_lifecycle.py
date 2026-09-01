"""The run-lifecycle notifications: started, paused, resumed, ended.

These existed only in the webhook module's docstring for months -- the match result was the
one event with a caller. What this pins down is *which* events fire, that they fire once, and
which of them pings, because a notifier that cries wolf gets muted and then the one message
worth having is silent too.

Nothing is posted: `_post` is replaced, so no network and no Discord.

    .venv\\Scripts\\python.exe tests\\test_webhook_lifecycle.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.core.webhook import (  # noqa: E402
    COLOR_END,
    COLOR_PAUSE,
    COLOR_START,
    DiscordWebhook,
)
from sloppykeys.macro.controller import MacroController  # noqa: E402

GOOD = "https://discord.com/api/webhooks/123456789/abcDEF-token_123"
USER = "286825732000000000"


def build(root: str) -> tuple[MacroController, list[dict]]:
    """A controller wired to a temp app root, with every send captured instead of posted."""
    with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
        json.dump(
            {
                "discord_webhook": GOOD,
                "discord_user_id": USER,
                "tasks": [
                    {"mode": "Expedition", "map": "School Grounds", "stage": "1", "repeat": 1},
                    {"mode": "Expedition", "map": "East Town", "stage": "1", "repeat": 1},
                ],
            },
            handle,
        )

    sent: list[dict] = []
    ctrl = MacroController(root, log=lambda _m: None)

    original = MacroController._webhook

    def patched(self):
        hook = original(self)
        if hook is not None:
            hook._post = lambda url, payload, image=None: (
                sent.append(payload),
                (True, "HTTP 200"),
            )[1]
        return hook

    ctrl._webhook = patched.__get__(ctrl, MacroController)
    return (ctrl, sent)


def titles(sent: list[dict]) -> list[str]:
    return [payload["embeds"][0]["title"] for payload in sent]


def test_start_announces_the_queue() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)
        assert ctrl.start() is None, "a queue of two tasks must start"
        assert titles(sent) == ["Macro Started"], titles(sent)
        embed = sent[0]["embeds"][0]
        assert embed["color"] == COLOR_START
        values = {f["name"]: f["value"] for f in embed["fields"]}
        assert values["Queue"] == "2 task(s)", values
        assert "School Grounds" in values["Up first"], values
        # Starting is not worth a phone buzz: the user just pressed the button.
        assert "content" not in sent[0], sent[0]


def test_start_refused_on_an_empty_queue_says_nothing() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)
        with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"discord_webhook": GOOD, "tasks": []}, handle)
        assert ctrl.start() == "task queue is empty"
        assert sent == [], "a refused start must not notify"


def test_pause_and_resume_fire_once_each_and_never_ping() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)
        ctrl.start()
        sent.clear()

        ctrl.pause()
        ctrl.pause()  # already paused: not a second message
        ctrl.resume()
        ctrl.resume()  # already running
        assert titles(sent) == ["Macro Paused", "Macro Resumed"], titles(sent)
        assert sent[0]["embeds"][0]["color"] == COLOR_PAUSE
        assert sent[1]["embeds"][0]["color"] == COLOR_START
        # Both are keyboard-initiated, so the user is present either way.
        for payload in sent:
            assert "content" not in payload, payload


def test_end_pings_only_when_the_run_stopped_on_its_own() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)

        # A run that ended by itself -- an empty queue here -- is the case worth a ping.
        ctrl._run = lambda: (True, "queue empty")  # type: ignore[method-assign]
        ctrl.run_loop()
        assert titles(sent)[-1] == "Macro Ended", titles(sent)
        ended = sent[-1]
        assert ended["embeds"][0]["color"] == COLOR_END
        assert ended["content"] == f"<@{USER}>", ended.get("content")
        values = {f["name"]: f["value"] for f in ended["embeds"][0]["fields"]}
        assert values["Reason"] == "queue empty", values
        assert "Uptime" in values and "Session" in values, values

        # The user pressing Stop is already at the machine, so that ending stays quiet.
        ctrl2, sent2 = build(root)
        ctrl2._run = lambda: (True, "stopped after 3 cycles")  # type: ignore[method-assign]
        ctrl2.stop()
        ctrl2.run_loop()
        assert titles(sent2)[-1] == "Macro Ended"
        assert "content" not in sent2[-1], sent2[-1]


def test_a_crash_still_reports_an_ending() -> None:
    """The ending nobody is watching for is the one that matters most."""
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)

        def boom():
            raise RuntimeError("template cache exploded")

        ctrl._run = boom  # type: ignore[method-assign]
        try:
            ctrl.run_loop()
        except RuntimeError:
            pass  # must propagate, not be swallowed by the notifier
        else:
            raise AssertionError("run_loop swallowed the exception")

        assert titles(sent)[-1] == "Macro Ended", titles(sent)
        values = {f["name"]: f["value"] for f in sent[-1]["embeds"][0]["fields"]}
        assert values["Reason"] == "stopped unexpectedly", values
        assert sent[-1]["content"] == f"<@{USER}>", "a crash must ping"


def test_no_webhook_url_means_silence_not_an_error() -> None:
    with tempfile.TemporaryDirectory() as root:
        ctrl, sent = build(root)
        with open(os.path.join(root, "settings.json"), "w", encoding="utf-8") as handle:
            json.dump({"tasks": [{"mode": "Story", "map": "East Town"}]}, handle)
        assert ctrl.start() is None
        ctrl.pause()
        ctrl.resume()
        assert sent == [], "notifications are off, so nothing is sent and nothing raises"


# A disabled hook must also never be built, so an invalid URL cannot post.
assert DiscordWebhook(lambda: "https://evil.example.com/api/webhooks/1/t").enabled is False

for name, case in sorted(list(globals().items())):
    if name.startswith("test_") and callable(case):
        case()
        print(f"  {name} ok")

print("webhook lifecycle ok")
