# images/stages/raid

- `spirit_city.png`

Crop the Spirit City label from the stage carousel at the pinned **800x599** client
size, the same way the Story templates were made. The search is scoped to
`STAGE_SEARCH_REGIONS["Raid"] = (1, 426, 812, 28)`, so the crop must sit inside that
28px-tall strip — a template taller than its region never matches.
