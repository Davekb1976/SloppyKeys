"""Runnable check for the per-task difficulty.

No framework: `.venv\\Scripts\\python.exe tests\\test_difficulty.py`.

One field carries two different game controls: a 1-3 cycling button on Expedition, and Story's
Easy/Hard pair everywhere else. A bad fallback here is silent — the run plays a difficulty
nobody chose and still looks like a working macro. Tasks written before this moved out of
Settings hold "Normal" in that field, which is why anything unrecognised has to land on the
default rather than raise.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.settings import AppSettings  # noqa: E402
from sloppykeys.content.start_stage import (  # noqa: E402
    DIFFICULTY_ON_OPEN,
    difficulty_clicks,
    difficulty_from_task,
    difficulty_options,
    hard_mode_from_task,
)


def main() -> None:
    assert difficulty_options("Expedition") == ["1", "2", "3"]
    assert difficulty_options("Story") == ["Easy", "Hard"]
    assert difficulty_options("") == ["Easy", "Hard"]

    assert difficulty_from_task("2") == 2
    assert difficulty_from_task(3) == 3
    assert difficulty_from_task(" 2 ") == 2
    # Out of range clamps; a legacy or non-numeric value is the default, not an error.
    assert difficulty_from_task("9") == 3
    assert difficulty_from_task("0") == DIFFICULTY_ON_OPEN
    for legacy in ("Normal", "Hard", "", None, {}):
        assert difficulty_from_task(legacy) == DIFFICULTY_ON_OPEN, legacy
    # The default costs no clicks, which is the point of it being the default.
    assert difficulty_clicks(difficulty_from_task("Normal")) == 0

    # # The same field read as Story's Easy/Hard, which drives the Hard Mode click
    assert hard_mode_from_task("Hard") is True
    assert hard_mode_from_task("hard") is True
    assert hard_mode_from_task("Easy") is False
    # The label the field used to carry still means Easy, not "unrecognised".
    assert hard_mode_from_task("Normal", True) is False
    # Anything else — a leftover Expedition "2", a task from before the field existed —
    # falls back to the Settings toggle rather than silently playing Easy.
    for unknown in ("2", "", None, {}):
        assert hard_mode_from_task(unknown, True) is True, unknown
        assert hard_mode_from_task(unknown, False) is False, unknown

    # The global setting it replaced is gone, not merely unused.
    assert "expedition_difficulty" not in AppSettings.defaults()
    assert not hasattr(AppSettings, "get_expedition_difficulty")

    print("OK: difficulty options per gamemode, task field parsed and clamped")


if __name__ == "__main__":
    main()
