"""Start-stage sequence coordinates (after an act is selected).

Client-space points, clicked with the hover-wiggle. The `hard_mode` point is
only clicked when Hard Mode is enabled (Story only). `confirm` and `start` are
always clicked. After `start`, the macro waits the join delay for the game to load.

Only gamemodes present here have a coordinate-based start sequence.
"""

from __future__ import annotations

# `confirm` (Select Stage) and `start` are **fallbacks only**: both are searched as templates
# at runtime and these coordinates are used solely when the PNG is missing from disk. They are
# not editable in Settings > Vision for that reason. `hard_mode` is the one real blind click.
START_COORDS: dict[str, dict[str, tuple[int, int]]] = {
    "Story": {
        "hard_mode": (366, 322),  # optional; only when Hard Mode is on
        "confirm": (274, 450),
        "start": (490, 408),
    },
    # Raid has no Hard Mode toggle: Select Stage, then Start.
    "Raid": {
        "confirm": (275, 451),
        "start": (485, 432),
    },
}


# # User overrides
# Editable in Settings > Vision > Points, stored in `settings.json` under `points`, applied
# through `apply_point_overrides`. Only the keys already in the tables above are editable, so
# a gamemode without a Hard Mode toggle can't grow one. Read the accessors, never the tables.
_OVERRIDES: dict[str, tuple[int, int]] = {}


def start_key(gamemode: str, step: str) -> str:
    """The `points` storage key for one start-sequence click."""
    return f"start.{gamemode}.{step}"


def difficulty_key(gamemode: str) -> str:
    return f"difficulty.{gamemode}"


def apply_point_overrides(overrides: dict[str, tuple[int, int]]) -> None:
    """Replace the override set with the whole `points` dict; foreign keys never match."""
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def start_coords(gamemode: str) -> dict[str, tuple[int, int]] | None:
    """The gamemode's sequence with any overrides merged in, or None if it has none."""
    defaults = START_COORDS.get(gamemode)
    if defaults is None:
        return None
    return {
        step: _OVERRIDES.get(start_key(gamemode, step), coord)
        for step, coord in defaults.items()
    }


# # Difficulty (Expedition)
# One button that cycles rather than three separate buttons: it reads 1 when the
# menu opens and each click advances 1 -> 2 -> 3 -> 1. So selecting a difficulty
# means clicking (target - 1) times, and nothing at all for difficulty 1.
DIFFICULTY_COORDS: dict[str, tuple[int, int]] = {
    "Expedition": (312, 473),
}
DIFFICULTY_MIN = 1
DIFFICULTY_MAX = 3
DIFFICULTY_ON_OPEN = 1


def difficulty_coord(gamemode: str) -> tuple[int, int] | None:
    """The cycling difficulty button, or None for a gamemode without one."""
    default = DIFFICULTY_COORDS.get(gamemode)
    return _OVERRIDES.get(difficulty_key(gamemode), default)


# The only start-sequence step that is clicked without verifying anything, so the only one
# worth an editor row. `confirm` and `start` below are template searches at runtime and keep
# their coordinate only as a missing-template fallback — see `point_specs`.
BLIND_STEPS = ("hard_mode",)

# What each start-sequence key is called in the editor.
STEP_LABELS = {
    "hard_mode": "Hard Mode toggle",
}


def point_specs() -> list[tuple[str, str, tuple[int, int]]]:
    """(key, label, default) for the start-sequence points that are actually clicked blind.

    `confirm` and `start` are **excluded on purpose.** `LobbyNavigator.click_select_stage`
    and `click_start_match` search `select_stage.png` / `start_match.png` and only touch
    these coordinates when the template is missing from disk — so with the PNGs captured, a
    point picked here would change nothing, and an editable row that does nothing is worse
    than no row. Fix a missed Select Stage or Start by recapturing its template instead.
    """
    specs = [
        (start_key(gamemode, step), f"{gamemode} · {STEP_LABELS.get(step, step)}", coord)
        for gamemode, steps in START_COORDS.items()
        for step, coord in steps.items()
        if step in BLIND_STEPS
    ]
    specs += [
        (difficulty_key(gamemode), f"{gamemode} · difficulty cycle", coord)
        for gamemode, coord in DIFFICULTY_COORDS.items()
    ]
    return specs


def difficulty_clicks(target: int) -> int:
    """How many clicks to get from the menu's default to `target`."""
    span = DIFFICULTY_MAX - DIFFICULTY_MIN + 1
    wanted = max(DIFFICULTY_MIN, min(DIFFICULTY_MAX, int(target)))
    return (wanted - DIFFICULTY_ON_OPEN) % span


def difficulty_options(gamemode: str) -> list[str]:
    """What a task's Difficulty field offers for this gamemode.

    A gamemode with a cycling button counts 1..3; the rest get the Normal/Hard toggle. One
    field, two meanings, because the game itself has two different controls there.
    """
    if difficulty_coord(gamemode) is None:
        return ["Normal", "Hard"]
    return [str(n) for n in range(DIFFICULTY_MIN, DIFFICULTY_MAX + 1)]


def difficulty_from_task(raw: object) -> int:
    """The cycling difficulty a task asks for, clamped.

    The stored field is a string because the same control shows Normal/Hard for the modes
    without a cycle, so anything non-numeric — including a task authored before this moved
    out of Settings — means the default.
    """
    try:
        return max(DIFFICULTY_MIN, min(DIFFICULTY_MAX, int(str(raw).strip())))
    except (TypeError, ValueError):
        return DIFFICULTY_ON_OPEN
