# assets/stages/raid

- `spirit_city.png`

Crop the Spirit City label from the stage carousel at the pinned **1152×756** client size,
the same way the Story templates were made — through the Image Manager (F6), which captures
at that size by construction.

**There is no search region.** `STAGE_SEARCH_REGIONS["Raid"]` used to scope this search to a
28px strip around the label; it was removed because it had to be hand-measured per gamemode,
it went stale the moment the viewport size changed, and a band shorter than the template
makes the match impossible rather than merely slow. `select_stage` searches the whole client
now, which costs about 17ms a look, so the crop can sit anywhere.
