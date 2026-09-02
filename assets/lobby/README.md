# assets/lobby

- `play.png` — the Play button that opens the intermission menu.
- `events.png` — the Events button. Used instead of `play.png` for the Events
  gamemode, which enters through the events list rather than the gamemode cards.
- `select_stage.png` — **the Select Stage button**, clicked one step before Start.
- `start_match.png` — **the lobby Start button**, the last click before a stage loads.
- `close.png` — the **X** that dismisses any panel in the gamemode UI, the challenge list
  included. One file, not one per panel.
- `close_gamemode.png` — the intermission menu's own **Back** control, which puts the
  **lobby proper** back on screen. See below.

Capture all of these from the **Image Manager** (F6): it grabs the exact pixels the matcher
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
`start_match.png` with `assets/match/start_game.png`, the *in-match* button that begins the
wave.

Until a file exists the macro falls back to the old fixed coordinate and says so in the log
(`clicked Select Stage at x,y (fixed coordinate — add assets/lobby/select_stage.png ...)`),
so nothing breaks in the meantime — but the fallback is the bug these files fix.

## `close.png` and `close_gamemode.png` — two closes, in that order

They are different controls, which is why they are two files: `close.png` is the small red X
in a panel's corner, `close_gamemode.png` is the Back button on the chooser. Dismissing a
panel takes the X; getting off the chooser afterwards takes Back.

`close.png` lives here rather than under `challenge/` because nothing about it is
challenge-specific — it is the same X, in the same place, on every panel the gamemode UI
opens. One file matches all of them, and a per-panel crop would be the same pixels stored
again under another name.

## The Back one is what uncovers the inventory bag

The intermission menu is a panel *over* the lobby, and **the bag Portals is entered from is
on the lobby**. So a queue that leaves that panel open cannot start a Portals task: the bag
search runs against the panel covering it and reports `Bag not found (best 0.52 < 0.80)`.

That number is the trap. A covered template scores like a badly cropped one, so the miss
reads as "recapture `portals/bag.png`" when the template was fine and the screen was wrong.
If a search misses at a plausible-looking score, check what is on top of it before recapturing.

Story and Raid never needed this, which is why one close looked correct for a long time —
the cards they click are on the panel itself. Only a chain that starts on the lobby cares.

Used by `LobbyNavigator.close_gamemode_menu`, and the only caller so far is the second half
of leaving a challenge detour that started no match
(`MacroController._close_challenge_ui`).

**No fallback coordinate, deliberately.** Every other button here degrades to a measured
point while its template is uncaptured; this one does not, because a blind click aimed at the
lobby lands in the game world if the panel has already closed. Until the file exists the log
says `assets/lobby/close_gamemode.png is missing — capture it in the Image Manager` and the
panel stays open, which is the survivable failure of the two.
