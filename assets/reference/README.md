# Reference screenshots

Backgrounds for the unit placement picker. Two layouts, and the picker checks them
in this order:

```
images/reference/<Gamemode>/<Map>/<Act>.png     per act
images/reference/<Gamemode>/<Map>.png           per map
```

e.g. `images/reference/Story/Flower Forest.png` (Story's acts share one playfield)
and `images/reference/Raid/Spirit City/Act 2.png` (Raid's acts are separate areas of
the same map, so each needs its own).

Use the per-map file when every act looks the same, the per-act files when they
don't. A missing per-act file falls back to the per-map one, then to a live capture.

**Don't mix the two for one map.** The per-act file wins, and only Raid and Events get
per-act rows in Settings > Vision (`image_manager.PER_ACT_MAPS`) — so a per-act file
under a per-map gamemode like Story is used by the picker and shown nowhere in the UI,
which reads as the app having picked a backdrop out of nowhere. `Story/School
Grounds/Act 1.png` sat next to `Story/School Grounds.png` and shadowed it that way.

Drop the files in by hand. Capture them at the pinned **800x599** client size, from
inside the stage, with the macro's camera already set: a stored coordinate only
points at the same ground while the camera angle matches. A file at another size
still loads, but it won't line up with the coordinates the picker writes.

These are not search templates; nothing image-matches against them. They exist so
the picker can show the map even when Roblox is sitting in the lobby, and so a map
looks the same between sessions. Replacing one moves nothing: saved coordinates are
plain client-space numbers.

Sequence-step coordinate picking ignores these and always uses a live capture, on
purpose — an ability target depends on where the unit actually is.
