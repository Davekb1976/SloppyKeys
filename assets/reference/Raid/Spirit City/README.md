# Spirit City reference images — one per act

Spirit City's three acts are different areas of the same map, so each act gets its
own placement-picker background. Drop these in by hand:

```
assets/reference/Raid/Spirit City/Act 1.png
assets/reference/Raid/Spirit City/Act 2.png
assets/reference/Raid/Spirit City/Act 3.png
```

Capture each at the pinned **1152×756** client size, from inside that act, with the macro's
camera already set — Image Manager (F6) → Set Camera, then the card's **+**, which saves the
whole client frame rather than a crop. For an act whose macro starts with a walk path,
capture *after* the walk has run. A stored coordinate only points at the same ground while
the camera and the character position match.

Until a file exists the picker falls back to a live capture, so picking still works;
it just can't be planned from the lobby.
