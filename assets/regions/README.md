# OCR box previews

One PNG per OCR region, named for its region key (`slot1_map.png`, `match_wave.png`, ...).
Shown beside that box's coordinates in **Settings → OCR → Text Regions**, so you can see what
the macro is actually reading without putting the screen up first.

These **ship with the build**. They are crops taken at the pinned 1152×756 viewport at 100%
display scaling, so they describe the game's own UI rather than one machine — the same reason
`assets/reference/` ships. A fresh install would otherwise show an empty preview column until
the user managed to get the Challenge panel on screen.

## They are reference, not calibration

The shipped crops were taken at *tuned* boxes, not at the defaults in `content/challenge.py`
and `config/regions.py`. Most are within a few pixels of the default; `match_wave` and
`slot3_map` are further off. So treat a shipped preview as "this is the wave counter", not as
"this is exactly what the numbers beside it cut out".

Nothing reads these files but the Settings panel — no matching, no OCR, no macro step. A wrong
one is cosmetic.

## Replacing them

Press **Preview** on a section with that section's screen up in Roblox. Each box's crop is
rewritten in place under the same filename (`bridge._write_region_preview`), so your own
capture replaces the shipped one and nothing needs deleting. **Reset to Defaults** deletes
them instead, because they would then be pictures of coordinates that no longer apply.

To make them match the defaults exactly: Reset to Defaults, put the Challenge panel up, press
Preview, then do the same for the In Match section with a stage running, and commit the result.
