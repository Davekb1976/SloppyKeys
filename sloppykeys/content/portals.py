"""Portals: the one click in the bag chain that nothing can verify.

Every other step into a Portals run is a template in `assets/portals/` — the bag, the Portals
tab, the search field, Activate Portal. Those either match or fail loudly.

The portal tile is different. After the portal's name is typed the grid filters down to it,
so the tile is at a known *place* rather than being a known *picture* — which is the whole
reason for typing: a template per portal would need recapturing every time the devs add a
tier, and there is no crop that means "the portal you asked for".

Slot 1 now ships a **measured** default, like `ACT_COORDS` and `START_COORDS` do. What this
module refuses to ship is a *guessed* one: activating a portal consumes it, so a click 40px
out spends the wrong item and the log still reads like a working run. That is why `UNSET` and
`slot_coord`'s `None` stay — a slot nobody has measured still refuses, and the run step is
expected to stop and say so rather than click a placeholder.
"""

from __future__ import annotations

# Client-space centre of each result slot in the filtered Portals grid, keyed by position.
# One entry, because a search specific enough to name a portal leaves one result — slot 2
# exists as a row the moment anyone needs it, not before.
#
# (0, 0) means "not measured". It is a real coordinate the picker could store, so `slot_coord`
# treats it as unset rather than trusting it: the client's top-left corner is empty ground,
# which is exactly the click that would look harmless and do nothing.
UNSET = (0, 0)
SLOT_COORDS: dict[int, tuple[int, int]] = {
    # Measured by the user at the pinned 1152x756 viewport, on a search filtered to one
    # result. Shipped rather than left unset because the alternative is that every other
    # install refuses the moment the grid needs a tile click — and only the account that
    # measured it would have a working Portals run. A user whose grid sits elsewhere still
    # overrides it in Settings > Debug > Click Points.
    1: (394, 253),
}

# The mode these points belong to, for the editor's grouping.
GAMEMODE = "Portals"

_OVERRIDES: dict[str, tuple[int, int]] = {}


def slot_key(slot: int) -> str:
    """The `points` storage key for one result slot."""
    return f"portal.slot.{int(slot)}"


def apply_point_overrides(overrides: dict[str, tuple[int, int]]) -> None:
    """Replace the override set with the whole `points` dict; foreign keys never match."""
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def slot_coord(slot: int = 1) -> tuple[int, int] | None:
    """The measured centre of a result slot, or None while it is unset.

    None is the answer a caller has to handle: it means "the user has not calibrated this
    yet", and the only correct response is to stop and say so.
    """
    default = SLOT_COORDS.get(int(slot))
    if default is None:
        return None
    coord = _OVERRIDES.get(slot_key(slot), default)
    return None if tuple(coord) == UNSET else (int(coord[0]), int(coord[1]))


def point_specs() -> list[tuple[str, str, str, tuple[int, int]]]:
    """(key, gamemode, label, default) for the portal grid's blind clicks."""
    return [
        (slot_key(slot), GAMEMODE, f"Result slot {slot}", coord)
        for slot, coord in SLOT_COORDS.items()
    ]
