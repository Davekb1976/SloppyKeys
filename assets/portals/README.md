# assets/portals

The chain into a Portals run. Portals is entered from the **inventory bag**, not the
intermission menu, so none of these belong in `lobby/` and there is no card in
`gamemodes/`.

Capture all of them from the **Image Manager** (F6), Portals tab: it grabs the exact pixels
the matcher reads at the pinned client size and writes them to the right filename. Cropping
from Roblox's own screenshot gives the wrong pixel size and the template can never match —
see `assets/README.md`.

The chain is `LobbyNavigator.enter_portal`: bag → Portals tab → search field → type the
portal's name → Activate Portal → Start. The **search field is not a template** — it is a
measured click point, for the reason below. In the order a run meets them:

- `bag.png` — the lobby's inventory button. This is the run's entry point, the way
  `lobby/play.png` is for Story and `lobby/events.png` is for Events. Nothing in the Play
  chain applies to Portals, which is what `own_entry` on its gamemode row means.
- `portals_tab.png` — the Portals section inside the bag.
- `activate.png` — **Activate Portal**, on the selected portal's detail panel. Also the *gate*
  on typing: see below.

And two more for queueing the next run without leaving the match:

- `select_portal.png` — **Select Portal**, on the **result screen, after either outcome**. It
  reopens the same picker, so only the confirm button differs from the bag chain.
- `select.png` — **Select**, that picker's confirm. `activate.png`'s counterpart.

**Crop `select_portal.png` from the button itself, not from anything that implies a win.**
This file used to carry a second job — telling a win from a loss, on the reasoning that only a
won screen shows Select Portal while a lost one shows Repeat. A run measured otherwise: it
logged `Loss. (defeat screen 0.96)` and then matched Select Portal at `1.00`. A win offers
Select Portal, a loss offers Select Portal *and* Repeat, so its presence says nothing about the
outcome and there is no reason to want it to. The win/loss banners are matched separately
(`match/game_won.png`, `match/game_lost.png`) and that is the only outcome signal.

What follows is simpler than the asymmetry it replaced: one path takes Select Portal after
every match, and `match/repeat.png` is the fallback for not finding it.

The Start button that appears after Activate has no file here, and does not need one:
**it is the same button as every other mode's**, `lobby/start_match.png` — confirmed in game.
That template is already a search rather than a coordinate, because the button moves with the
panel it sits on, which is exactly why one file serves Story, Raid, Expedition, Challenge and
now Portals. Pressing it is what loads the stage, so a miss fails the run rather than being
passed over.

## There is no `search.png` — two panels, two identical fields

The search field was a template for one release, and the reasoning was sound: it is the one
click in this project whose failure sends *characters into the game world*, because the portal
name is typed straight after it and `r`, `t` and `x` are priority, upgrade and sell. So the
typing was gated on finding it.

It could not do that job. **The in-match picker holds a second field pixel-identical to the
bag's**, and the template matched the wrong one at a full `1.00` — measured, from the log:

```
clicked Portal search at 544,324 (1.00) → typed 'summ', clicked slot 1 at 294,253
```

A perfect score on the wrong box. Nothing fixes that: identical pictures are not separable by
a threshold, a recapture, or a search region. And it only failed on one of the two panels, so
the bag chain worked throughout, which is what made it hard to see.

So the field is a **measured point per panel** now — `content/portals.py::SEARCH_COORDS` and
`MATCH_SEARCH_COORDS`, set in Settings → Debug → Click Points as *Bag search field* and
*In-match search field*. Both ship unset and the run refuses rather than guessing, because a
guess focuses nothing and the name goes into the world.

The gate moved to the panel's **own confirm button** — `activate.png` for the bag, `select.png`
in-match. That is unique per panel, so finding it proves *which* picker is open rather than
that some field exists somewhere. It is already on screen when the picker opens, which is what
the two releases of skipped tile clicks accidentally demonstrated.

## The name is typed one character at a time

Sent as one string it arrived as "summr", "smmer", even "smr". `SendText` is delivered
through SendInput, which puts no gap between characters and ignores `SetKeyDelay`, so the
field received the whole name inside a single rendered frame and kept whichever characters it
happened to read — the same class of failure as a click landing on a stale cursor position.

`input_scripts.TYPE_GAP_FRAMES` is the gap, in **frames** rather than milliseconds, because
that is what the game is counting: two frames is 33ms at 60Hz and 8ms at 240Hz. If letters
still go missing, raise that number — it is the one knob, and it is the first thing to try
before suspecting the field or the template.

## There is no chooser template

A chooser of three portals appears at the end of a run, and **the game selects one itself**
when nothing is clicked. So there is nothing here for it: a template, a result click point and
a mid-match handler would have existed to do what already happens on its own. The run waits
for the victory screen and takes Select Portal from there.
