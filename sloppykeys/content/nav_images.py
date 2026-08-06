"""Where the lobby-navigation template images live.

Paths are derived from the gamemode/stage schema so the folder layout can't
drift from `gamemodes.py`. All paths are relative to the app root; feed them
through `ImageSearchEngine.to_absolute_path`.

Layout (under images/):
    images/lobby/play.png                       the Play button
    images/gamemodes/<gamemode>.png             one per gamemode card
    images/stages/<gamemode>/<stage>.png        one per stage/map
    images/match/start_game.png                 in-match, proves the stage loaded

Filenames are slugs: lowercase, non-alphanumerics collapsed to "_".
  "King's Tomb"        -> kings_tomb.png
  "Fairy King Forest"  -> fairy_king_forest.png
"""

from __future__ import annotations

import os
import re

from .gamemodes import GAMEMODES

IMAGES_DIR = "images"
LOBBY_DIR = "lobby"
GAMEMODES_DIR = "gamemodes"
STAGES_DIR = "stages"
MATCH_DIR = "match"
# Where route templates live: the event cards in the sidebar, the act cards, and
# anything else a user-authored Events route needs to confirm.
EVENTS_DIR = "events"

PLAY_IMAGE = "play.png"
# The lobby's Start button — the last click before the stage loads, on the panel that
# appears once a stage/act is selected. **Its position moves with the stage**, because
# each stage's panel is a different height, which is why it cannot be a coordinate the way
# `hard_mode` and `confirm` are. One template covers every gamemode: it is the same button
# on the same panel, only somewhere else on screen.
START_MATCH_IMAGE = "start_match.png"
# The lobby's **Select Stage** button, clicked one step before Start. It is what opens the
# panel Start lives on, so Start does not exist until this is clicked — the two cannot be
# reordered. Searched rather than clicked blind for the same reason as Start: it sits on the
# stage/act panel, whose height differs per stage, so its position moves.
SELECT_STAGE_IMAGE = "select_stage.png"
# The lobby's Events button. Clicked instead of Play for the Events gamemode,
# because the events list is a different UI section from the gamemode cards.
EVENTS_IMAGE = "events.png"
# Only exists once a stage is loaded and the player has control, so finding it is
# how the macro tells "in the match" from "still on the loading screen". It comes
# back after a win, which is also how the next match is started.
START_GAME_IMAGE = "start_game.png"
# The unit panel that opens when a placed unit is clicked. Every action on a
# placed unit (priority, upgrade, sell) waits for this first, so a missed click
# can't send keypresses into the game world.
UNIT_UI_IMAGE = "unit_ui.png"
# The win screen. Ends a match cycle. Crop it to something only a *win* shows —
# anything shared with the loss screen would restart the loop after a defeat.
GAME_WON_IMAGE = "game_won.png"
# The defeat screen. Optional: without this file a loss is simply never
# recognised, so the cycle waits out its timeout instead of counting the loss.
GAME_LOST_IMAGE = "game_lost.png"
# The victory screen's **Repeat** button. `game_won.png` is now a crop of the victory
# screen's own text, and that screen does not clear itself — Repeat is the click that
# replays the stage, after which `start_game.png` appears again. So the win path is:
# game_won -> repeat -> start_game.
REPEAT_IMAGE = "repeat.png"

# # In-match menu buttons
# Captured and registered, not used by the macro yet: nothing in the run chain
# leaves a stage by hand today (a win returns to the lobby on its own). They are
# here so the path is defined in one place when it is needed — leaving a stuck
# match, or restarting the game after a crash.
#
# The two chains they form, in order:
#   back_lobby -> return_lobby_confirm   (the confirmation dialog it opens)
#   settings   -> restart_game           (the settings panel it opens)
# and `match_play` opens the Play panel, where the gamemode selection lives — the
# same screen the lobby chain's `play.png` leads to, reached from inside a stage.
BACK_LOBBY_IMAGE = "back_lobby.png"
RETURN_LOBBY_CONFIRM_IMAGE = "return_lobby_confirm.png"
SETTINGS_IMAGE = "settings.png"
RESTART_GAME_IMAGE = "restart_game.png"
MATCH_PLAY_IMAGE = "match_play.png"

# # The post-match panel's "change gamemode" control
# Leaving a finished match lands on a panel showing the mode just played; this is the
# control that reopens the gamemode chooser. It used to be a blind coordinate only
# (`challenge.CHANGE_GAMEMODE_CLICK`) because an earlier crop of this never matched — which
# is expected, it was cropped at the old client size. Wired up as a real template again so
# it can be recaptured in Settings > Vision and the click can be *verified* instead of fired
# at a screen nothing has confirmed. The coordinate stays as the missing-template fallback.
WIN_CHANGE_IMAGE = "win_change.png"


def slug(name: str) -> str:
    # Drop apostrophes so "King's Tomb" -> kings_tomb, not king_s_tomb.
    cleaned = name.lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")


# There is deliberately no stage search region. `STAGE_SEARCH_REGIONS` used to hold a
# per-gamemode band around the stage labels so `select_stage` scanned only that strip. It
# was removed: it had to be hand-measured per gamemode, it silently went stale whenever the
# viewport size changed, and a band shorter than the template makes the match impossible
# rather than merely slow. `select_stage` searches the whole client now (~17ms a look).


def play_image() -> str:
    return os.path.join(IMAGES_DIR, LOBBY_DIR, PLAY_IMAGE)


def start_match_image() -> str:
    """The lobby Start button, searched rather than clicked blind — it moves per stage.

    Not `start_game_image()`, which is the *in-match* button that begins the wave. This one
    is the last click in the lobby, and finding it is what makes one chain work for Story,
    Raid, Expedition and Challenge alike.
    """
    return os.path.join(IMAGES_DIR, LOBBY_DIR, START_MATCH_IMAGE)


def select_stage_image() -> str:
    """The lobby Select Stage button — the click that makes Start appear.

    Not to be confused with `LobbyNavigator.select_stage`, which picks the *map card* from
    the stage list. This is the confirm button on the panel that follows it.
    """
    return os.path.join(IMAGES_DIR, LOBBY_DIR, SELECT_STAGE_IMAGE)


def events_image() -> str:
    """The lobby Events button — the Events gamemode's entry point."""
    return os.path.join(IMAGES_DIR, LOBBY_DIR, EVENTS_IMAGE)


def events_templates_dir() -> str:
    """Default folder for route templates, offered by the route editor's picker."""
    return os.path.join(IMAGES_DIR, EVENTS_DIR)


def gamemode_image(gamemode: str) -> str:
    return os.path.join(IMAGES_DIR, GAMEMODES_DIR, f"{slug(gamemode)}.png")


def stage_image(gamemode: str, stage: str) -> str:
    return os.path.join(IMAGES_DIR, STAGES_DIR, slug(gamemode), f"{slug(stage)}.png")


def start_game_image() -> str:
    """The in-match Start Game button — the match-loaded signal."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, START_GAME_IMAGE)


def unit_ui_image() -> str:
    """The placed-unit panel — proves a unit click actually selected something."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, UNIT_UI_IMAGE)


def game_won_image() -> str:
    """The win screen — ends a match cycle."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, GAME_WON_IMAGE)


def game_lost_image() -> str:
    """The defeat screen — also ends a match cycle, counted as a loss."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, GAME_LOST_IMAGE)


def repeat_image() -> str:
    """The victory screen's Repeat button — replays the stage after a win."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, REPEAT_IMAGE)


def back_lobby_image() -> str:
    """In-match Back to Lobby — opens `return_lobby_confirm_image`, doesn't leave."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, BACK_LOBBY_IMAGE)


def return_lobby_confirm_image() -> str:
    """The confirmation that `back_lobby_image` opens. This is the click that leaves."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, RETURN_LOBBY_CONFIRM_IMAGE)


def settings_image() -> str:
    """In-match settings button — opens the panel holding `restart_game_image`."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, SETTINGS_IMAGE)


def restart_game_image() -> str:
    """Restart Game, inside the in-match settings panel."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, RESTART_GAME_IMAGE)


def match_play_image() -> str:
    """In-match Play button — opens the gamemode selection from inside a stage."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, MATCH_PLAY_IMAGE)


def win_change_image() -> str:
    """The post-match panel's change-gamemode control — reopens the gamemode chooser."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, WIN_CHANGE_IMAGE)





def expected_paths() -> list[str]:
    """Every template the navigation flow will look for."""
    paths = [
        play_image(),
        events_image(),
        select_stage_image(),
        start_match_image(),
        start_game_image(),
        repeat_image(),
        win_change_image(),
    ]
    for name, gamemode in GAMEMODES.items():
        # A custom gamemode has no card in the gamemode menu and no fixed stage
        # list — it enters through the Events button and its templates are
        # whatever the user's route references.
        if gamemode.custom:
            continue
        paths.append(gamemode_image(name))
        # A side task (Challenge) *does* have a card in the gamemode menu — that is how
        # the macro reaches it — but no stage cards: which map each challenge is on is
        # read off the challenge panel, not picked from a list.
        if gamemode.side_task:
            continue
        for stage in gamemode.maps:
            paths.append(stage_image(name, stage))
    return paths
