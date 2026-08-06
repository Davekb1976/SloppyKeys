"""Runnable check for parse_private_server_link.

No framework: `.venv\\Scripts\\python.exe tests\\test_private_server_link.py`.
Fails loudly if the link parsing or the trust-boundary rejection breaks.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.settings import parse_private_server_link  # noqa: E402

CODE = "0a212a4eae3c8b459ea0dcfa43d40d7a"
SHARE_URI = f"roblox://navigation/share_links?code={CODE}&type=Server"


def ok(link: str, expected: str) -> None:
    uri, error = parse_private_server_link(link)
    assert not error, f"{link!r} unexpectedly rejected: {error}"
    assert uri == expected, f"{link!r} -> {uri!r}, expected {expected!r}"


def rejected(link: str) -> None:
    uri, error = parse_private_server_link(link)
    assert error, f"{link!r} should have been rejected, got {uri!r}"
    assert uri == "", f"{link!r} rejected but still returned {uri!r}"


# Current share format, the one users actually copy out of Roblox.
ok(f"https://www.roblox.com/share?code={CODE}&type=Server", SHARE_URI)
ok(f"  https://www.roblox.com/share?code={CODE}&type=server  ", SHARE_URI)
ok(CODE, SHARE_URI)
ok(SHARE_URI, SHARE_URI)

# Legacy /games/ link: no share code exists, so the deprecated deep link is used.
ok(
    f"https://www.roblox.com/games/123456?privateServerLinkCode={CODE}",
    f"roblox://placeId=123456&linkCode={CODE}",
)

# Trust boundary: nothing but plain alphanumerics reaches the shell URI.
rejected("")
rejected("   ")
rejected("https://www.roblox.com/share?code=abc&type=Server")  # too short
rejected(f"https://www.roblox.com/share?code={CODE}%22&type=Server")
rejected(f'https://www.roblox.com/share?code={CODE}"&type=Server')
rejected(f"https://www.roblox.com/share?code={CODE}&type=Profile")
rejected(f"file:///c:/windows?code={CODE}")
rejected("https://www.roblox.com/games/123456")
rejected("roblox://navigation/share_links?type=Server")

print("private server link parsing: OK")
