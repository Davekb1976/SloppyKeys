"""Portals: the one click in the bag chain that nothing can verify.

Every other step into a Portals run is a template in `assets/portals/` — the bag, the Portals
tab, the search field, Activate Portal. Those either match or fail loudly.

The portal tile is different. After the portal's name is typed the grid filters down to it,
so the tile is at a known *place* rather than being a known *picture* — which is the whole
reason for typing: a template per portal would need recapturing every time the devs add a
tier, and there is no crop that means "the portal you asked for".

**There are two grids, not one.** The same picker is reached from two places and the panel
holding it does not sit in the same spot: the **bag**, opened from the lobby, and the
**in-match** picker that Select Portal opens on the result screen. So each has its own table
and its own stored point. Sharing one coordinate across both clicks the wrong tile in
whichever context was not measured — and the log still reads like a working run, which is the
failure this module is built around.

The bag's slot 1 ships a **measured** default, like `ACT_COORDS` and `START_COORDS` do. What
this module refuses to ship is a *guessed* one: activating a portal consumes it, so a click
40px out spends the wrong item. That is why `UNSET` and `slot_coord`'s `None` stay — the
in-match grid is unmeasured, so it refuses, and the run step is expected to stop and say so
rather than click the bag's coordinate and hope.
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
# The **in-match** grid: the picker Select Portal opens on the result screen. A separate
# table because the panel is not the bag's — measured on a different screen entirely, so the
# bag's (394, 253) points at the wrong tile here. Unset until someone measures it: a wrong
# click spends a portal, and this path is only reached when the confirm button does not light
# up on its own, so it has never been exercised in game.
MATCH_SLOT_COORDS: dict[int, tuple[int, int]] = {
    1: UNSET,
}

# The mode these points belong to, for the editor's grouping.
GAMEMODE = "Portals"

_OVERRIDES: dict[str, tuple[int, int]] = {}


def slot_key(slot: int, in_match: bool = False) -> str:
    """The `points` storage key for one result slot, per grid.

    The bag's key is unchanged (`portal.slot.1`) on purpose, so a user who already measured it
    keeps their value when the in-match grid arrives beside it.
    """
    return f"portal.{'match.' if in_match else ''}slot.{int(slot)}"


def apply_point_overrides(overrides: dict[str, tuple[int, int]]) -> None:
    """Replace the override set with the whole `points` dict; foreign keys never match."""
    _OVERRIDES.clear()
    _OVERRIDES.update(overrides)


def slot_coord(slot: int = 1, in_match: bool = False) -> tuple[int, int] | None:
    """The measured centre of a result slot in one of the two grids, or None while unset.

    `in_match` picks the grid: False is the bag, True is the picker Select Portal opens. They
    are different screens with different geometry, so the caller has to say which it is on.

    None is the answer a caller has to handle: it means "the user has not calibrated this
    grid yet", and the only correct response is to stop and say so.
    """
    table = MATCH_SLOT_COORDS if in_match else SLOT_COORDS
    default = table.get(int(slot))
    if default is None:
        return None
    coord = _OVERRIDES.get(slot_key(slot, in_match), default)
    return None if tuple(coord) == UNSET else (int(coord[0]), int(coord[1]))


def point_specs() -> list[tuple[str, str, str, tuple[int, int]]]:
    """(key, gamemode, label, default) for both portal grids' blind clicks.

    Both grids are listed, which is also what whitelists them for the editor — a grid with no
    row here cannot be measured, so the run step would refuse forever with no way to fix it.
    """
    specs = [
        (slot_key(slot), GAMEMODE, f"Bag result slot {slot}", coord)
        for slot, coord in SLOT_COORDS.items()
    ]
    specs += [
        (slot_key(slot, True), GAMEMODE, f"In-match result slot {slot}", coord)
        for slot, coord in MATCH_SLOT_COORDS.items()
    ]
    return specs
