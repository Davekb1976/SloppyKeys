# assets/portals

The chain into a Portals run. Portals is entered from the **inventory bag**, not the
intermission menu, so none of these belong in `lobby/` and there is no card in
`gamemodes/`.

Capture all of them from the **Image Manager** (F6), Portals tab: it grabs the exact pixels
the matcher reads at the pinned client size and writes them to the right filename. Cropping
from Roblox's own screenshot gives the wrong pixel size and the template can never match —
see `assets/README.md`.

In the order a run meets them:

- `bag.png` — the lobby's inventory button. This is the run's entry point, the way
  `lobby/play.png` is for Story and `lobby/events.png` is for Events.
- `portals_tab.png` — the Portals section inside the bag.
- `search.png` — the search field. Clicked to focus it, then the portal name is typed.
- `activate.png` — **Activate Portal**, on the selected portal's detail panel.

And two more for queueing the next run without leaving the match:

- `select_portal.png` — **Select Portal**, on the **victory screen**. It reopens the same
  picker, so only the confirm button differs from the bag chain.
- `select.png` — **Select**, that picker's confirm. `activate.png`'s counterpart.

`select_portal.png` carries a second job: **it is how the run tells a win from a loss**, with
no banner template involved.

Portals is the only mode whose victory screen has no Repeat. Winning consumes the portal and
hands out a new one, so that screen offers Select Portal instead. A loss consumes nothing, so
its screen keeps Repeat. The two outcomes therefore have completely disjoint controls, which
is a stronger signal than matching the banner would be — so the run looks for Select Portal,
and falling back to `match/repeat.png` *is* the loss path. Both consequences follow from that:

- crop `select_portal.png` from something only the **won** screen shows, or a loss will be
  read as a win and the chain will type into a picker that never opened;
- a loss replays the same portal through Repeat, with no bag trip and nothing retyped, because
  the portal is still owned.

The Start button that appears after Activate has no file here on purpose:
`lobby/start_match.png` is already a search rather than a coordinate, because that button
moves with the panel it sits on. If a capture ever shows the two are different art, this is
where the second one goes.

## `search.png` carries more weight than it looks

Every other template in this project fails safely: the search misses, the step reports it,
the task is skipped. This one is different, because **the portal name is typed immediately
after it**, and if the field never took focus those characters land in the game world where
`r`, `t` and `x` are priority, upgrade and sell.

A focused field is not something a template can prove — the field itself is. So the typing
is gated on this match, and if it stops matching after a game update the right fix is to
recapture it, not to lower its threshold.

## The end-of-match chooser is not here

`assets/match/portal_choice.png` — three portals appear before the victory screen and one
must be picked. It lives with the match templates because that is where it is seen. Crop the
**header**, not a card: the three faces are different portals every match, so no card face
is a stable crop. Same reasoning as `match/exp_upgrade_card.png`.
