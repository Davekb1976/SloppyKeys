"""Runnable check for Api.test_webhook bridge method.

No framework: `.venv\\Scripts\\python.exe tests\\test_bridge_webhook.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.ui_web.bridge import Api  # noqa: E402
from sloppykeys.core.webhook import DiscordWebhook  # noqa: E402


def test_test_webhook_validation() -> None:
    api = Api.__new__(Api)
    with tempfile.TemporaryDirectory() as tmp:
        api._app_root = tmp
        api._window = None

        # 1. Empty URL
        res = api.test_webhook(url="", user_id="")
        assert res["ok"] is False
        assert "No webhook URL" in res["error"]

        # 2. Non-https or non-discord URL
        res = api.test_webhook(url="http://discord.com/api/webhooks/1/2", user_id="")
        assert res["ok"] is False
        assert "https" in res["error"]

        res = api.test_webhook(url="https://attacker.com/api/webhooks/1/2", user_id="")
        assert res["ok"] is False
        assert "Discord webhook host" in res["error"]

        # 3. Invalid user ID
        res = api.test_webhook(
            url="https://discord.com/api/webhooks/123456789/validToken123",
            user_id="invalid_user_id",
        )
        assert res["ok"] is False
        assert "Discord user ID" in res["error"]


def test_test_webhook_success_flow() -> None:
    api = Api.__new__(Api)
    with tempfile.TemporaryDirectory() as tmp:
        api._app_root = tmp
        pushed: list[tuple[str, dict]] = []
        api._push_js = lambda handler, payload: pushed.append((handler, payload))
        api._log_to_ui = lambda msg: None

        original_post = DiscordWebhook._post
        try:
            # Mock _post to return successful HTTP 204
            DiscordWebhook._post = lambda self, url, payload, image=None: (True, "HTTP 204")

            res = api.test_webhook(
                url="https://discord.com/api/webhooks/123456789/validToken123",
                user_id="286825732000000000",
            )
            assert res["ok"] is True

            # Give worker thread up to 1 second to fire _push_js
            deadline = time.time() + 1.0
            while time.time() < deadline and not pushed:
                time.sleep(0.05)

            assert len(pushed) == 1
            handler, payload = pushed[0]
            assert handler == "window.onWebhookTestResult"
            assert payload["ok"] is True
            assert payload["message"] == "HTTP 204"
        finally:
            DiscordWebhook._post = original_post


def main() -> None:
    test_test_webhook_validation()
    test_test_webhook_success_flow()
    print("OK: test_webhook bridge method")


if __name__ == "__main__":
    main()
