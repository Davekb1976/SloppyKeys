# Reference screenshots

Backgrounds for the unit placement picker. Two layouts:

```
assets/reference/<Gamemode>/<Map>/<Act>.png     per act
assets/reference/<Gamemode>/<Map>.png           per map
```

e.g. `assets/reference/Story/Flower Forest.png` (Story's acts share one playfield)
and `assets/reference/Raid/Spirit City/Act 2.png` (Raid's acts are separate areas of
the same map, so each needs its own).

Which layout a gamemode uses is `per_act_reference` in `content/gamemodes.py`, and
`nav_images.map_reference_paths()` derives the whole list from that table — so the
Image Manager's **Maps** section offers a card per expected file, captured or not.
Hit `+` on one to save the current Roblox screen into it; there is no crop step,
because a reference is the full client area or the coordinates read off it land
somewhere else in the stage. Events is the exception: its maps are the user's own
events in `routes.json`, so only files already on disk show up.

**Don't mix the two layouts for one map.** The per-act file wins, so a per-act file
under a per-map gamemode is used by the picker and shown nowhere, which reads as the
app having picked a backdrop out of nowhere. `Story/School Grounds/Act 1.png` sat
next to `Story/School Grounds.png` and shadowed it that way.

Capture from inside the stage, with the macro's camera already set (Set Camera in the
Image Manager runs the same step the macro does) at the pinned **1152x756** client
size: a stored coordinate only points at the same ground while the camera angle
matches. A file at another size still loads, but it won't line up.

These are not search templates; nothing image-matches against them. They exist so
the picker can show the map even when Roblox is sitting in the lobby, and so a map
looks the same between sessions. A missing one is not an error — the picker falls
back to a live capture. Replacing one moves nothing: saved coordinates are plain
client-space numbers.

Sequence-step coordinate picking ignores these and always uses a live capture, on
purpose — an ability target depends on where the unit actually is.
