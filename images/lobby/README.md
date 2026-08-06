# images/lobby

- `play.png` — the Play button that opens the intermission menu.
- `events.png` — the Events button. Used instead of `play.png` for the Events
  gamemode, which enters through the events list rather than the gamemode cards.
- `select_stage.png` — **the Select Stage button**, clicked one step before Start.
- `start_match.png` — **the lobby Start button**, the last click before a stage loads.

Capture all of these from **Settings > Images**: it grabs the exact pixels the matcher
reads, at the pinned client size, and writes them to the right filename. Cropping from
Roblox's own screenshot gives the wrong pixel size and the template will never match.

## `select_stage.png` and `start_match.png` — the order matters

Select Stage is what **opens the panel Start sits on**, so Start does not exist until it is
clicked. That is what "Start wasn't there" always meant. `LobbyNavigator.start_stage` and
`start_challenge` both do Select Stage, then Start.

Both are searched rather than clicked blind because **each stage's panel is a different
height, so both buttons land somewhere different every time**. `hard_mode` (in
`content/start_stage.py`) is still a coordinate: it sits on the fixed part of the panel.

Crop each tightly around the button, from a stage whose panel is a *typical* height — the
art is the same everywhere, so any stage will do.

One pair of files covers **every** selector: Story, Raid, Expedition and Challenge all go
through `click_select_stage` then `click_start_match`. An Events route can reference the
same files in FIND steps, since routes are authored rather than tabled.

Don't confuse `click_select_stage` (this button) with `LobbyNavigator.select_stage`, which
picks the *map card* out of the stage list — an earlier step. And don't confuse
`start_match.png` with `images/match/start_game.png`, the *in-match* button that begins the
wave.

Until a file exists the macro falls back to the old fixed coordinate and says so in the log
(`clicked Select Stage at x,y (fixed coordinate — add images/lobby/select_stage.png ...)`),
so nothing breaks in the meantime — but the fallback is the bug these files fix.
