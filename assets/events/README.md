# assets/events

Templates a user-authored Events route searches for. One folder per event, so binning an
event is binning a folder:

```
assets/events/<Event>/<Act>_<n>.png
assets/events/Villian Invasion/Main_1.png
```

That layout is `nav_routes.step_image(map, act, index)`, and both name segments go through
`clean_name` — they become path segments, so a typed event name can never escape this folder.

## There is no route editor yet

The Capture / Test / duplicate-a-step flow this file used to describe belonged to the PySide6
route editor, which was deleted with Qt. The Routes screen in the current UI is a placeholder,
so today a route is either **hand-edited in `routes.json`** or shipped in `routes.default.json`
and merged on first run. `RouteStore` reads and writes the JSON; nothing in `ui_web/` calls its
`set_steps`.

Two consequences worth knowing while that is true:

- **Put the PNGs here yourself**, at the path above, and point the step's `Image` at it. The
  Image Manager's **Events** section lists whatever is already on disk, so it can recapture a
  file but not create one for a step that has none.
- **Deleting an event or act leaves its templates behind.** The old editor moved and deleted
  files alongside the JSON; that half was not rebuilt. Stale folders here are harmless —
  nothing searches for a template no step names — but they are yours to clear out.

## Crop it right

The scale rule is the whole of `assets/README.md`: capture through the app's own path, at
100% display scaling. A template cropped from a full-desktop screenshot or an image editor
can land at a different scale than the client capture, and a mis-scaled template never
matches at any confidence.

Crop tight to something that only appears on the screen you mean — an event card cropped to
include the "Ends Update 1" line will match several other cards. Each template carries its own
threshold (0.80 by default), tunable on its Image Manager card.
