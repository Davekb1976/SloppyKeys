"""Which recorded walk path a target walks on Auto.

A walk path is a recording (`paths/<name>.json`, WASD transitions). Some targets drop the
character away from where the placement coordinates were measured, so the run has to walk
before it places anything — Raid's Spirit City is the case that forced it, since its acts are
separate areas of one map.

This table is the *mapping*, not the movement: it says which recording a target uses. The
recordings themselves ship in `paths/defaults/` and are listed alongside the user's own, so
a fresh install walks correctly with nothing to record first. A user recording under the same
name shadows the shipped one (`recording.walk_path_file`).

An entry whose recording is missing from disk is a real state, not an error: the Auto button
says which target it belongs to so it can be recorded under that name.
"""

from __future__ import annotations

# target key -> the walk path recorded for it. Act-level first, then the whole map: only the
# acts that need their own walk get their own row.
DEFAULT_WALK_PATHS: dict[str, str] = {
    # Act 2's playfield sits away from the spawn: back, right, back again.
    "Raid/Spirit City/Act 2": "Spirit City Act 2",
    # Act 3 is straight to the right of the spawn.
    "Raid/Spirit City/Act 3": "Spirit City Act 3",
    # Villian Invasion drops you short of the placement points: forward for 2s. Only stable
    # while the event is in rotation — when it rotates out the key stops matching and costs
    # nothing.
    "Events/Villian Invasion/Act 1": "Villian Invasion Act 1",
}


def target_key(gamemode: str, map_name: str, act: str) -> str:
    """The table key for one target, or "" when the target is incomplete.

    Gamemode and map are both required rather than "any two parts": dropping the map would
    turn (Raid, "", Act 2) into "Raid/Act 2", which reads exactly like a complete two-part
    key for a map called "Act 2".
    """
    mode, stage, target = (str(part or "").strip() for part in (gamemode, map_name, act))
    if not mode or not stage:
        return ""
    return "/".join(part for part in (mode, stage, target) if part)


def default_walk_path(gamemode: str, map_name: str, act: str) -> str:
    """The walk path this target uses on Auto, or "".

    Act first, then the map: acts of the same map share one walk unless one of them says
    otherwise.
    """
    act_key = target_key(gamemode, map_name, act)
    map_key = target_key(gamemode, map_name, "")
    for key in (act_key, map_key):
        if key and key in DEFAULT_WALK_PATHS:
            return DEFAULT_WALK_PATHS[key]
    return ""
