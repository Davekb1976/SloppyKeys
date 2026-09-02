"""Anime Expedition content schema.

The selector UI is generated from this table, so adding a map or gamemode is a
data edit here rather than a UI change.

Terminology follows the game itself:
  Gamemode  - Story / Raid / Expedition (lobby cards say "Gamemode")
  Map       - lobby cards say "Current Map"
  Act       - lobby cards say "3/5 Acts Cleared"
  Difficulty- Expedition's 1-3 selector

Challenge is here as a **side task**: never an F1 target of its own (it is reached
from inside a match, not from the lobby), but it needs the same per-map unit plan,
placement reference and start-position walk as anything else the macro plays. So it
is a gamemode with `side_task=True`, which keeps it off the Selector page while the
config surfaces treat it like any other mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Story acts run 1-5 plus two special acts shown as icons in game.
STORY_ACTS = ["Act 1", "Act 2", "Act 3", "Act 4", "Act 5", "Infinite", "Mastery"]
# In in-game order. Named because Challenge draws from the same five maps in this
# patch, and two copies of the list would drift apart.
STORY_MAPS = [
    "School Grounds",
    "Flower Forest",
    "Rose Kingdom",
    "Fairy King Forest",
    "King's Tomb",
    "East Town",
]
RAID_ACTS = ["Act 1", "Act 2", "Act 3"]
# Expedition has no third dimension: its difficulty is a toggle for how hard the
# same map gets, like Story's Hard Mode, not a separate farm target. So it saves
# one config per map and the difficulty lives in Settings.
EXPEDITION_TARGETS: list[str] = []


@dataclass(frozen=True)
class Gamemode:
    """One selectable farm target family.

    target_label names the third dropdown, which differs per gamemode
    (Act for Story/Raid, Difficulty for Expedition).
    """

    name: str
    map_label: str
    target_label: str
    maps: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    # True when the maps and acts are user-authored rather than listed here, so
    # this table can't know them (Events — see content/nav_route.py). The Run
    # strip fills both dropdowns from the route store instead, and `has_targets`
    # stays True so the config path keeps its <Map>/<Act> shape.
    custom: bool = False
    # True when each act of a map is its own playfield, so the placement backdrop has to
    # be captured per act (`assets/reference/<Mode>/<Map>/<Act>.png`) instead of once per
    # map. Raid's three acts are separate areas of Spirit City; Story's five share one.
    per_act_reference: bool = False
    # True for a mode the macro plays but the user never selects as the run target:
    # Challenge, which is entered from inside a match. It is kept out of the
    # Selector page, the full-run tester dialog and the lobby template expectations,
    # while configs / reference images / start positions treat it normally.
    side_task: bool = False
    # True when the mode is reached through its **own** chain of templates rather than the
    # intermission menu, so neither a card in `assets/gamemodes/` nor stage cards in
    # `assets/stages/<mode>/` exist to be captured — Portals is entered from the inventory
    # bag and its portal is found by a typed search, not picked off a stage list.
    #
    # Not `custom`: that also means the maps are unknown to this table, and it drops the
    # placement backdrop with them. An `own_entry` mode still plays on a real playfield, so
    # it still needs `assets/reference/<Mode>/<Map>.png` — leaving it out is what left
    # Expedition with no maps to capture.
    own_entry: bool = False

    def targets_for_map(self, _map_name: str) -> list[str]:
        # Every map in a gamemode currently exposes the same target set.
        return list(self.targets)


GAMEMODES: dict[str, Gamemode] = {
    "Story": Gamemode(
        name="Story",
        map_label="Map",
        target_label="Act",
        maps=STORY_MAPS,
        targets=STORY_ACTS,
    ),
    "Raid": Gamemode(
        name="Raid",
        map_label="Map",
        target_label="Act",
        maps=["Spirit City"],
        targets=RAID_ACTS,
        per_act_reference=True,
    ),
    "Expedition": Gamemode(
        name="Expedition",
        map_label="Map",
        target_label="Difficulty",
        # Not `STORY_MAPS`: Expedition offers its own subset, and its stage cards are
        # separate crops under `assets/stages/expedition/` because they look different
        # on screen from Story's.
        maps=[
            "School Grounds",
            "Flower Forest",
            "Rose Kingdom",
            "East Town",
        ],
        targets=EXPEDITION_TARGETS,
    ),
    # Events rotate with every update, so its maps (the events themselves) and
    # acts are built by the user in Run > Route and read from routes.json.
    "Events": Gamemode(
        name="Events",
        map_label="Event",
        target_label="Act",
        maps=[],
        targets=[],
        custom=True,
    ),
    # Entered from the inventory bag, not the gamemode cards, so `own_entry` — its chain
    # lives in `assets/portals/` (bag, Portals tab, search field, Activate Portal).
    #
    # **One map, and its name is the mode's.** Every portal drops into the same playfield,
    # so the map dimension carries no information; the single entry exists so the per-map
    # machinery has a key — one placement backdrop at `assets/reference/Portals/Portals.png`
    # and one config path. What actually varies is *which portal* is activated, and that is
    # a typed search string on the task, not a map. Rename this the moment the playfield's
    # in-game name is known: it costs this string plus the backdrop's filename.
    "Portals": Gamemode(
        name="Portals",
        map_label="Map",
        target_label="Act",
        maps=["Portals"],
        targets=[],
        own_entry=True,
    ),
    # A side task, not a farm target: the macro reaches it from inside a match and
    # the game rotates which map each of the three offered challenges is on. No act
    # dimension, so a plan is per map — `configs/Challenge/<Map>.json`. Every
    # challenge is Hard regardless of the Hard Mode setting.
    "Challenge": Gamemode(
        name="Challenge",
        map_label="Map",
        target_label="Act",
        maps=STORY_MAPS,
        targets=[],
        side_task=True,
    ),
}

# The gamemode whose navigation is a user-authored route instead of a table.
EVENTS = "Events"
# Picked on the Selector like a gamemode, but deliberately **not** in `GAMEMODES`: it
# means "run the task queue" rather than one target, and it has no maps, acts or
# `configs/` path of its own. Keeping it out of the table is what stops it leaking into
# `maps_for`, config paths and the template expectations.
TASK_SELECTION = "Task"
# The side task the Tasks tab can queue.
CHALLENGE = "Challenge"

GAMEMODE_NAMES = list(GAMEMODES.keys())
# What the user can pick as a run target: everything the macro can enter from the
# lobby. Side tasks are played, never selected.
FARM_GAMEMODE_NAMES = [
    name for name, gamemode in GAMEMODES.items() if not gamemode.side_task
]


def get_gamemode(name: str) -> Gamemode | None:
    return GAMEMODES.get(name.strip())


def maps_for(gamemode_name: str) -> list[str]:
    gamemode = get_gamemode(gamemode_name)
    return list(gamemode.maps) if gamemode else []


def targets_for(gamemode_name: str, map_name: str) -> list[str]:
    gamemode = get_gamemode(gamemode_name)
    return gamemode.targets_for_map(map_name) if gamemode else []


def has_targets(gamemode_name: str) -> bool:
    """False when a gamemode saves one config per map (no third selector).

    True for a custom gamemode even though `targets` is empty here: its acts are
    stored per map in routes.json, and the config path must stay <Map>/<Act>.
    """
    gamemode = get_gamemode(gamemode_name)
    return bool(gamemode and (gamemode.targets or gamemode.custom))


def is_custom(gamemode_name: str) -> bool:
    """Does this gamemode get its maps and acts from the route store?"""
    gamemode = get_gamemode(gamemode_name)
    return bool(gamemode and gamemode.custom)


def is_side_task(gamemode_name: str) -> bool:
    """Is this played by the macro but never chosen as the run target?"""
    gamemode = get_gamemode(gamemode_name)
    return bool(gamemode and gamemode.side_task)


def selection_complete(gamemode: str, map_name: str, target: str) -> bool:
    """Is this a fully chosen farm target? A gamemode without a target dimension
    is complete at Map, so callers must not demand all three."""
    if not gamemode or not map_name:
        return False
    return bool(target) or not has_targets(gamemode)


def labels_for(gamemode_name: str) -> tuple[str, str]:
    """Return (map_label, target_label) for driving the dropdown captions."""
    gamemode = get_gamemode(gamemode_name)
    if gamemode is None:
        return ("Map", "Act")
    return (gamemode.map_label, gamemode.target_label)
