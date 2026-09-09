"""Act selection coordinates.

Some gamemodes list their acts at fixed positions in the stage screen, so we
click a known client-space coordinate rather than image-matching each act. These
are Roblox *client* coordinates (as read by the point picker in Settings > Debug >
Click Points);
the navigator adds the Roblox client origin to get a screen point for AHK.

Only gamemodes present here use coordinate-based act selection. Others will need
their own entry (or a different mechanism) once measured.

Measured at the pinned 1152x756 client size through Settings > Vision > Points.
"""

from __future__ import annotations

# gamemode -> { act name -> (client_x, client_y) }
ACT_COORDS: dict[str, dict[str, tuple[int, int]]] = {
    "Story": {
        "Act 1": (249, 233),
        "Act 2": (250, 287),
        "Act 3": (246, 341),
        "Act 4": (248, 397),
        "Act 5": (246, 451),
        "Infinite": (245, 513),
        "Mastery": (249, 567),
    },
    # Raid lists three acts, spaced further apart than Story's seven.
    "Raid": {
        "Act 1": (249, 231),
        "Act 2": (252, 290),
        "Act 3": (252, 343),
    },
}

# When Golden Hour is active on a Story stage, the Gift Box is inserted at Slot 0,
# shifting Acts 1-5 and Infinite down by one slot. Mastery is scrolled off the bottom
# and reached by scrolling the act column down.
GOLDEN_HOUR_ACT_COORDS: dict[str, dict[str, tuple[int, int]]] = {
    "Story": {
        "Golden Hour": (249, 233),  # Slot 0: Gift box
        "Act 1": (250, 287),        # Slot 1
        "Act 2": (246, 341),        # Slot 2
        "Act 3": (248, 397),        # Slot 3
        "Act 4": (246, 451),        # Slot 4
        "Act 5": (245, 513),        # Slot 5
        "Infinite": (249, 567),     # Slot 6
        "Mastery": (249, 567),      # Lands at bottom slot after scrolling down
    },
}

# # User overrides
# Same reasoning as the challenge OCR boxes: the points above were measured on one machine
# at one viewport size, and being 20px out doesn't fail — it clicks the act above the one
# you asked for and the macro farms the wrong stage. Editable in Settings > Vision > Points,
# stored in `settings.json` under `points`, applied through `apply_point_overrides`.
#
# Module-level rather than injected, so `LobbyNavigator.select_act` and the Run page's
# "no act coordinates" guard read the same value. Read `act_coord`, never `ACT_COORDS`.
_OVERRIDES: dict[str, tuple[int, int]] = {}


def act_key(gamemode: str, act: str) -> str:
    """The `points` storage key for one act's click."""
    return f"act.{gamemode}.{act}"


def apply_point_overrides(overrides: dict[str, tuple[int, int]]) -> None:
    """Replace the override set. Whole-set replacement so clearing one really clears it.

    Takes the entire `points` dict; keys belonging to other tables simply never match.
    """
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def act_coord(gamemode: str, act: str) -> tuple[int, int] | None:
    default = ACT_COORDS.get(gamemode, {}).get(act)
    return _OVERRIDES.get(act_key(gamemode, act), default)


def golden_hour_act_coord(gamemode: str, act: str) -> tuple[int, int] | None:
    """The act coordinate when Golden Hour is active on the stage."""
    return GOLDEN_HOUR_ACT_COORDS.get(gamemode, {}).get(act)


def act_specs() -> list[tuple[str, str, str, tuple[int, int]]]:
    """(key, gamemode, label, default) for every act point, for the Vision editor.

    The gamemode is its own field because the editor groups by it: all of Story's acts are
    set from one screenshot of Story's act list, and the number of rows differs per mode.
    """
    return [
        (act_key(gamemode, act), gamemode, act, coord)
        for gamemode, acts in ACT_COORDS.items()
        for act, coord in acts.items()
    ]
