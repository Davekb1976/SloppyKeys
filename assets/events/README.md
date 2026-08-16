# images/events

Templates for user-authored Events routes (Run panel > Route tab).

One folder per event, so binning an event is binning a folder:

```
images/events/<Event>/<Act>_<n>.png
images/events/Villian Invasion/Main_1.png
```

Normally you don't put files here by hand. Select a `find` or `expect` step and
press **Capture**: drag a box on the Roblox window and exactly that box is
screenshotted from the Roblox window — the same pixels the search reads — and saved
under that event's folder. The step's search region is set to the same box.

Re-capturing a step that already has a template overwrites its own file, wherever
that file lives, so a step keeps its image across reorders. A step with no template
takes the next free number. The numbering is not a step position — moving steps
around doesn't rename anything. A duplicated step shares its path, so re-capturing
one of the pair takes a fresh name rather than changing the other.

Deleting a step, resetting a route, or deleting an act or event deletes the
templates that go with it — but never one another route still uses, and never a
file outside this folder.

That path matters. A template cropped from a full-desktop screenshot or an image
editor can end up at a different scale than the client capture, and a mis-scaled
template never matches at any confidence.

**Test** next to it does one look for that template on the live screen and reports
the match score (0.70 is the threshold), so you can confirm a capture works before
running the route. To reuse a template on another act, duplicate the step — its
image path comes with it.

Crop tight to something that only appears on the screen you mean — an event card
cropped to include the "Ends Update 1" line will match several other cards.
