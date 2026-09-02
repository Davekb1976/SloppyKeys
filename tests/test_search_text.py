"""Runnable checks for the typed-search trust boundary: what `sanitize_search_text`
accepts, and that nothing it accepts can break out of the `SendText()` it lands in.

The portal search field is the only place this project types a *string* into the game, and
a portal is consumed when it is activated — so a string that filters the list to the wrong
item spends the wrong one. These assert the rejection, not the tidying.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_search_text.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.keybinds import (  # noqa: E402
    SEARCH_TEXT_MAX,
    sanitize_search_text,
)
from sloppykeys.macro.input_scripts import type_text_script  # noqa: E402


# # Accepted: anything a game item name plausibly is
for good in (
    "Rose Kingdom Portal",
    "King's Tomb",
    "Tier-3",
    "portal 12",
    "A",
):
    assert sanitize_search_text(good) == good, good

# Surrounding whitespace is not part of the name, and trimming it can't change which item
# matches — so this one is a repair on purpose.
assert sanitize_search_text("  Rose Kingdom  ") == "Rose Kingdom"


# # Rejected outright, never escaped or stripped
# Every one of these would either end the AHK string literal, escape inside it, or split
# the script into a second line of code.
for bad in (
    'Rose" MsgBox("pwned',      # ends the literal
    "Rose`nMsgBox",             # backtick stays special even in text mode
    "Rose\nMsgBox",             # a real newline is a second statement
    "Rose%Var%",                # deref in a legacy context
    "{Enter}",                  # would be a key name to Send, though not to SendText
    "Rose;comment",
    "C:/Windows",
    "Rosé",                     # non-ASCII: outside the whitelist, so no guessing
    "",
    "   ",
    None,
    [],
):
    assert sanitize_search_text(bad) == "", repr(bad)

# Coerced, like `sanitize_game_key` does: a JSON number is a name made of digits, and the
# whitelist still has the final say on what those characters are.
assert sanitize_search_text(123) == "123"

# Bounded: a pasted paragraph is a rejection, not a truncation — a truncated name is still
# a name, and it would search for the wrong thing.
assert sanitize_search_text("a" * SEARCH_TEXT_MAX) == "a" * SEARCH_TEXT_MAX
assert sanitize_search_text("a" * (SEARCH_TEXT_MAX + 1)) == ""


# # The script the accepted text lands in
script = type_text_script(sanitize_search_text("King's Tomb"))
assert 'SendText("King\'s Tomb")' in script, script
# One statement on the SendText line, and the line count is fixed: if a name could carry a
# newline this is the assertion that would fail.
send_lines = [line for line in script.splitlines() if "SendText" in line]
assert len(send_lines) == 1, send_lines
assert send_lines[0].strip().endswith('")'), send_lines[0]
# Activates Roblox first, and exits 0 — the same contract every other builder has, so
# `AhkBridge.run(wait=True)` reads success the same way.
assert "WinActivate" in script and "ExitApp(0)" in script
# No mouse: typing must not move the cursor off the field that was just clicked.
assert "MouseMove" not in script and "Click(" not in script

print("search text: OK")
