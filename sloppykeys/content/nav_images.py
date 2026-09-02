"""Where the lobby-navigation template images live.

Paths are derived from the gamemode/stage schema so the folder layout can't
drift from `gamemodes.py`. All paths are relative to the app root; feed them
through `ImageSearchEngine.to_absolute_path`.

Layout (under assets/):
    assets/lobby/play.png                       the Play button
    assets/gamemodes/<gamemode>.png             one per gamemode card
    assets/stages/<gamemode>/<stage>.png        one per stage/map
    assets/match/start_game.png                 in-match, proves the stage loaded
    assets/portals/bag.png                      the inventory bag Portals is entered through
    assets/reference/<gamemode>/<map>.png       placement backdrop, not a template

Filenames are slugs: lowercase, non-alphanumerics collapsed to "_".
  "King's Tomb"        -> kings_tomb.png
  "Fairy King Forest"  -> fairy_king_forest.png
"""

from __future__ import annotations

import os
import re

from ..config.unit_configs import safe_component
from .gamemodes import GAMEMODES

IMAGES_DIR = "assets"
LOBBY_DIR = "lobby"
GAMEMODES_DIR = "gamemodes"
STAGES_DIR = "stages"
MATCH_DIR = "match"
# Where route templates live: the event cards in the sidebar, the act cards, and
# anything else a user-authored Events route needs to confirm.
EVENTS_DIR = "events"
# Portals is entered from the inventory bag rather than the gamemode cards, so its chain
# has no `play.png` and no card in `gamemodes/`. Its own folder for that reason: none of
# these four belong to the lobby's intermission menu.
PORTALS_DIR = "portals"
# Placement backdrops, not search templates: whole client-area screenshots the position
# picker draws coordinates on. See assets/reference/README.md.
REFERENCE_DIR = "reference"

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

# # Expedition's in-match screens
# Observed in game, which is what these follow rather than any guess about waves:
#
#   join         Start Game, then a Continue, then a second Continue
#   defense/wave only Start Game — the same button, once per wave
#   encounter    a Continue, then a second Continue
#   checkpoint   Extract then a second Extract (the "end this run?" panel), *or* a
#                Continue then a second Continue to keep playing
#   boss         cleared, then the checkpoint's own Extract/Continue again
#
# So the whole vocabulary is one button pair repeated. There is no separate crop for the
# Continue beside Extract: it is the same Continue the encounter shows.
#
#   exp_continue        the first Continue at a node
#   exp_continue_2      the second Continue, on the panel the first one opens
#   exp_extract         Extract at a checkpoint
#   exp_extract_confirm the second Extract, on the "end this run?" panel
#   exp_upgrade_card    the "Select an upgrade!" header
#
# All optional: a missing crop never matches, which leaves that step inert rather than
# failing a run, and nothing outside an Expedition match searches for them.
#
# There is no Expedition Repeat: its victory screen is left through Back to Lobby and its
# confirmation (`back_lobby` + `return_lobby_confirm`, already captured), after which the
# next run enters from the lobby's Play like a fresh one.
#
# `exp_upgrade_card` is the level-up modal that hands out three cards. Cropped from the
# *header*, not a card face, because the three faces differ every time. It matters more than
# it looks: it renders over whatever is underneath, so an Extract or Continue behind it is
# drawn but unclickable.
EXP_CONTINUE_IMAGE = "exp_continue.png"
EXP_CONTINUE_2_IMAGE = "exp_continue_2.png"
EXP_EXTRACT_IMAGE = "exp_extract.png"
EXP_EXTRACT_CONFIRM_IMAGE = "exp_extract_confirm.png"
EXP_UPGRADE_CARD_IMAGE = "exp_upgrade_card.png"

# # The game's own Auto Play
# A pair, because the whole point is telling the two states apart: `autoplay` is the button
# to click, `autoplay_active` is what proves the click took. One template could not do it —
# a toggle that is found is not a toggle that is on.
#
# Crop them from the **same** area so only the state differs, and crop something that
# actually changes (the lit border, the label, the fill) rather than an icon that looks
# identical either way. If the two crops cross-match, the block will report success the
# instant it finds the off state and place nothing all match.
AUTOPLAY_IMAGE = "autoplay.png"
AUTOPLAY_ACTIVE_IMAGE = "autoplay_active.png"

# # The post-match panel's "change gamemode" control
# Leaving a finished match lands on a panel showing the mode just played; this is the
# control that reopens the gamemode chooser. It used to be a blind coordinate only
# (`challenge.CHANGE_GAMEMODE_CLICK`) because an earlier crop of this never matched — which
# is expected, it was cropped at the old client size. Wired up as a real template again so
# it can be recaptured in Settings > Vision and the click can be *verified* instead of fired
# at a screen nothing has confirmed. The coordinate stays as the missing-template fallback.
WIN_CHANGE_IMAGE = "win_change.png"

# # Portals
# The chain, in the order a run meets it:
#
#   bag          the lobby's inventory button
#   portals_tab  the Portals section inside the bag
#   search       the search field, clicked to focus it before the name is typed
#   activate     Activate Portal, on the selected portal's detail panel
#
# `search` earns a template rather than a coordinate because it is the one click in this
# project whose failure sends *characters into the game world*: the portal name is typed
# next, and `r`, `t` and `x` are the priority, upgrade and sell keys. A focused field is
# not matchable, but the field itself is, so this is the closest thing to proof available
# and the typing is gated on it.
#
# There is no `start.png` yet. The Start that appears after Activate may be the same art as
# `lobby/start_match.png`, which is already searched rather than clicked blind precisely
# because it moves per panel — so it is reused until a capture proves the two differ.
PORTAL_BAG_IMAGE = "bag.png"
PORTALS_TAB_IMAGE = "portals_tab.png"
PORTAL_SEARCH_IMAGE = "search.png"
PORTAL_ACTIVATE_IMAGE = "activate.png"

# # Queueing the next portal from the victory screen
# A won Portals match ends on the victory screen with a **Select Portal** button, which opens
# the same picker the bag does — same search field, same grid — but confirms with **Select**
# instead of **Activate**. So it is two more crops, not a second chain: `pick_portal` serves
# both and only the confirm template changes.
#
# `select_portal` is also the signal that this path is even available. A lost match consumes
# nothing and ends on the defeat screen, which has no such button, so the search failing is
# how the run knows to leave through the lobby instead.
PORTAL_SELECT_PORTAL_IMAGE = "select_portal.png"
PORTAL_SELECT_IMAGE = "select.png"

# The end-of-match chooser: three portals, one of which must be picked before the victory
# screen appears. Lives with the match templates because that is where it is seen, and
# cropped from its **header** for the same reason as `exp_upgrade_card` — the three faces
# are different portals every time, so no card is a stable crop.
PORTAL_CHOICE_IMAGE = "portal_choice.png"


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


def exp_continue_image() -> str:
    """Expedition's wave Continue — the large one that ends a wave."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, EXP_CONTINUE_IMAGE)


def exp_continue_2_image() -> str:
    """The smaller Continue on the panel the wave Continue opens."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, EXP_CONTINUE_2_IMAGE)


def exp_extract_image() -> str:
    """Extract at a checkpoint. Accepting it ends the run on the victory screen."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, EXP_EXTRACT_IMAGE)


def exp_extract_confirm_image() -> str:
    """The second Extract, on the "are you sure you'd like to end this run?" panel."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, EXP_EXTRACT_CONFIRM_IMAGE)


def exp_upgrade_card_image() -> str:
    """The "Select an upgrade!" header — the level-up modal that blocks everything behind it."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, EXP_UPGRADE_CARD_IMAGE)


def expedition_match_paths() -> list[str]:
    """Every template an Expedition match looks for, in the order the run meets them."""
    return [
        exp_continue_image(),
        exp_continue_2_image(),
        exp_extract_image(),
        exp_extract_confirm_image(),
        exp_upgrade_card_image(),
    ]


def autoplay_image() -> str:
    """The game's Auto Play button, **off** — the one the block clicks."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, AUTOPLAY_IMAGE)


def autoplay_active_image() -> str:
    """Auto Play in its **on** state — the only proof the click landed."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, AUTOPLAY_ACTIVE_IMAGE)


def portal_bag_image() -> str:
    """The lobby's inventory bag — how a Portals run enters, instead of Play."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTAL_BAG_IMAGE)


def portals_tab_image() -> str:
    """The Portals section inside the bag."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTALS_TAB_IMAGE)


def portal_search_image() -> str:
    """The portal search field. Clicked to focus it before the name is typed."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTAL_SEARCH_IMAGE)


def portal_activate_image() -> str:
    """Activate Portal, on the selected portal's detail panel."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTAL_ACTIVATE_IMAGE)


def portal_select_portal_image() -> str:
    """The victory screen's **Select Portal** button — opens the picker for the next run."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTAL_SELECT_PORTAL_IMAGE)


def portal_select_image() -> str:
    """**Select**, the victory-screen picker's confirm. `activate.png`'s counterpart."""
    return os.path.join(IMAGES_DIR, PORTALS_DIR, PORTAL_SELECT_IMAGE)


def portal_choice_image() -> str:
    """The end-of-match "pick one of three portals" header, before the victory screen."""
    return os.path.join(IMAGES_DIR, MATCH_DIR, PORTAL_CHOICE_IMAGE)


def portal_paths() -> list[str]:
    """Every template a Portals run looks for, in the order it meets them."""
    return [
        portal_bag_image(),
        portals_tab_image(),
        portal_search_image(),
        portal_activate_image(),
        portal_choice_image(),
        portal_select_portal_image(),
        portal_select_image(),
    ]





def map_reference_image(gamemode: str, map_name: str, act: str = "") -> str:
    """Placement backdrop for a map — or for one act, where the acts are separate areas.

    Display names, not slugs: these are hand-dropped files and the tree already holds
    `assets/reference/Story/King's Tomb.png`. Each name goes through `safe_component`
    anyway — an event's map and act names are typed by the user, and one path segment
    containing `..` would put a capture anywhere on disk.
    """
    parts = [IMAGES_DIR, REFERENCE_DIR, safe_component(gamemode), safe_component(map_name)]
    if act:
        parts.append(safe_component(act))
    return os.path.join(*parts) + ".png"


def map_reference_paths() -> list[str]:
    """Every placement backdrop the schema implies, captured or not.

    Nothing matches against these, so a missing one only means the picker falls back to a
    live capture — but the Image Manager lists them from here, and a mode absent from this
    list has no card to capture into. That is why Expedition had no maps.
    """
    paths = []
    for name, gamemode in GAMEMODES.items():
        # Events' maps are the user's own events, known only to routes.json.
        if gamemode.custom:
            continue
        # A side task plays another mode's maps — Challenge rotates through Story's five, on
        # the same playfields — so it reads Story's backdrops. Its own folder would be six
        # duplicate captures of the same ground.
        if gamemode.side_task:
            continue
        for map_name in gamemode.maps:
            if gamemode.per_act_reference:
                paths.extend(map_reference_image(name, map_name, act) for act in gamemode.targets)
            else:
                paths.append(map_reference_image(name, map_name))
    return paths


def expected_paths() -> list[str]:
    """Every template the run will look for, captured or not.

    Drives the Image Manager's "expected but missing" cards, so a template absent from here
    has nowhere to be captured into. Expedition's in-match screens are listed even though
    each is individually optional — a run cannot advance past a checkpoint without them, and
    an uncapturable template is indistinguishable from a broken macro.
    """
    paths = [
        play_image(),
        events_image(),
        select_stage_image(),
        start_match_image(),
        start_game_image(),
        repeat_image(),
        win_change_image(),
        # Only the `autoplay` block searches for these, and a plan without one never looks —
        # but an uncaptured template is indistinguishable from a broken block, so both get a
        # card. `sighted` returns False for a missing file, which leaves the block inert.
        autoplay_image(),
        autoplay_active_image(),
    ]
    paths += expedition_match_paths()
    # Listed before the gamemode loop because Portals' chain is not derived from the
    # schema: it enters through the bag, so it has neither a card in `gamemodes/` nor
    # stage cards, and the loop below would produce nothing for it.
    paths += portal_paths()
    for name, gamemode in GAMEMODES.items():
        # A custom gamemode has no card in the gamemode menu and no fixed stage
        # list — it enters through the Events button and its templates are
        # whatever the user's route references.
        if gamemode.custom:
            continue
        # An `own_entry` mode has neither: Portals is reached from the inventory bag, and
        # its portal is found by a typed search, so there is no card in the intermission
        # menu and no stage list. Listing either would put a permanent MISSING card in the
        # Image Manager for a screen that does not exist.
        if gamemode.own_entry:
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
