# assets/match

Templates seen from **inside** a stage. Capture them from the **Image Manager** (F6), which
grabs the exact pixels the matcher reads at the pinned client size.

## The match cycle

- `start_game.png` — the in-match Start Game button, which begins the wave. Finding it is
  also how the macro knows a stage has loaded and the player has control.
- `unit_ui.png` — the panel that opens when a placed unit is clicked. Every action on a
  placed unit waits for this first, so a missed click can't send keypresses into the world.
- `game_won.png` — the **victory screen's text**. Ends a match cycle.
- `repeat.png` — the victory screen's **Repeat** button.
- `game_lost.png` — the defeat screen. Optional: without it a loss simply isn't recognised
  and the cycle waits out its timeout instead of counting the loss.

**The win order is `game_won` → `repeat` → `start_game`.** The victory screen does not clear
itself, so finding `game_won.png` proves the match ended but nothing more; Repeat is the
click that replays the stage, and only after it does Start Game come back. Crop `repeat.png`
tightly around the button.

Repeat never fails a run: if the file is missing or the button isn't found, the macro logs it
and falls through to Start Game, which polls on a deadline. So a missing `repeat.png` costs
one wasted search per win, not a broken cycle.

Keep `game_won.png` and `game_lost.png` visually distinct. An earlier pair both contained the
word `Game` and a win was scored as a defeat; the current pair cross-matches at 0.41, which is
safe. The outcome check scores **both** against one capture and takes the better, and refuses
to decide when the two are within a hair of each other — a win once scored `won 0.57,
lost 0.71`, which is why that guard exists.

## In-match menu — captured, not yet used by any run

Nothing in the run chain leaves a stage by hand today (a win returns to the lobby on its own).
These are here so the paths are defined for leaving a stuck match or restarting after a crash.
Each first click only *opens a panel*, so anything built on them must wait for the second
template rather than clicking a fixed coordinate after a sleep:

- `back_lobby.png` → `return_lobby_confirm.png` (the second click is the one that leaves)
- `settings.png` → `restart_game.png`
- `match_play.png` — opens the gamemode selection from inside a stage. A *different*, smaller
  Play than the lobby's `assets/lobby/play.png`.
- `win_change.png` — the post-match panel's change-gamemode control. Never matched in game, so
  `change_gamemode` clicks `CHANGE_GAMEMODE_CLICK` instead and waits `panel_fade_wait` first.

## Mid-match modals

- `exp_upgrade_card.png` — Expedition's "Select an upgrade!" modal. Cropped from the
  **header**, never a card face: it hands out three choices and the three faces differ every
  time. It renders over the buttons underneath, so anything found behind it is drawn but
  unclickable.

There is deliberately **no Portals equivalent.** A chooser of three portals does appear at the
end of a portal run, but the game selects one itself when nothing is clicked — so a template
for it, a click point, and a mid-match handler would all have existed to do what already
happens. A Portals run waits for the victory screen.

## Auto Play — a pair, and they must not cross-match

The `autoplay` block searches both:

- `autoplay.png` — the button in its **off** state, the one it clicks.
- `autoplay_active.png` — the **on** state, which is the only proof the click landed.

Crop them from the same area so only the state differs, and crop the part that actually
changes — the lit border, the fill, the label. An icon that looks the same either way makes
the two templates score alike, and then the block reports success the moment it finds the
*off* state and places nothing all match.

Both optional. A missing `autoplay.png` makes the block skip itself and say so; the plan's
other blocks run as normal.
