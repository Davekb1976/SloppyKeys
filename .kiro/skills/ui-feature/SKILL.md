---
name: ui-feature
description: Build or change a screen, panel, modal or block row in the pywebview UI. Covers the four-layer split (shell / appearance / render / data), the component checklist, the design tokens, and the traps specific to having a live game window on top of the page. Use when adding a UI surface, restyling one, or wiring a control to the Python bridge.
---

# Building a UI feature

The reference implementation is the **Image Manager** (`#im-modal`, `.im-*`,
`renderImGrid`, `list_vision_templates`). Read those four places before starting; this
file is the generalisation, not a substitute for looking at the working example.

Design vocabulary — colours, density, typography, the panel component, the `.check`
box — is in `references/design-vocabulary.md`. Read it before writing any CSS.

## The four layers

Every surface splits the same way. The value is that each layer has exactly one reason
to change, and three of them never need to know the game exists.

| Layer | Lives in | Owns | Must never |
|---|---|---|---|
| **Shell** | `index.html` | One empty container with an `id`, plus static chrome (title, close button) | Contain the rows, cards or items themselves |
| **Appearance** | `style.css` | A named block of prefixed classes | Decide what data is shown; hold `style=` attributes |
| **Render + state** | `app.js` | `render<Thing>()` that rebuilds from one state object, and re-wires after | Build paths, read the filesystem, know where files live |
| **Data + identity** | `bridge.py` | Enumerating, validating, and returning plain JSON | Return HTML or pre-formatted strings |

Concretely, for the Image Manager: `index.html` has `<div id="im-grid" class="im-grid"></div>`
and nothing else; `style.css` has one `/* ---- Image Manager ---- */` block of `.im-*`
rules; `app.js` holds `imData` + `renderImGrid()`; `bridge.py::list_vision_templates`
walks `assets/`, base64s the thumbnails, and returns a dict.

### Why the shell stays empty

Because the render function replaces it wholesale. That is also what let the crop view
reuse the same modal by swapping `.modal-body` — a shell with cards hard-coded in it
could not have been reused.

## The rules that came from real bugs

Each of these cost a debugging session. They are the reason the pattern is worth
following rather than a style preference.

1. **The server owns identity; the label is only for reading.** A list the user edits
   must carry a stable identity from the backend and send *that* back. The Image Manager
   keyed templates by filename while the search engine keyed by relative path, so the
   threshold slider silently did nothing and a recapture wrote to the wrong folder.
   Send `path`, show `name`.

2. **Render from state; never patch the DOM in place.** One `render<Thing>()` that
   rebuilds from one state object. No surgical `textContent` updates scattered through
   handlers — they drift out of step with the data.

3. **Re-wire after every render.** `innerHTML =` throws away every listener. Attach
   handlers at the end of the render function, not once at startup.

4. **Cross the bridge as JSON, never as an interpolated string.** Use `json.dumps` when
   calling into the page. An f-string put Python's `False` into JS and crashed the run
   loop with `False is not defined`.

5. **Anything slow goes to a thread and pushes back through a `window.on*` callback.**
   Capture, OCR and AHK block. Return from the `js_api` call as soon as the *ordering*
   is safe, then push the result. The OCR scan returned early and the screen switched
   back before the frame was grabbed, so half the regions read empty.

6. **A missing thing is a state, not an absence.** Show it — the Image Manager's
   `MISSING` badge, the detect dropdown's `(missing)` option. Silently dropping a
   dangling reference reads as "configured and fine" and fails at run time.

7. **Reject invalid input at the bridge, don't repair it.** A name that sanitises to
   nothing is an error, not a file called `-.png`. Everything from the page is untrusted:
   validate anything that becomes a path (`_template_path`) or an AHK string.

## The game window sits on top of the page

Not a detail — it dictates modal behaviour. Roblox is its own top-level window in the
topmost band over the viewport slot; it paints over all DOM content. `SetWindowRgn`
cannot cut a hole in it because WebView2 composites through DirectComposition.

- A modal that opens over the Dashboard **must** hide the game first
  (`set_game_visible(false)`) and restore it on close.
- The game is *covered* by z-order, never `SW_HIDE` — hiding it drops its taskbar button.
- **Never reveal the game from the caller for a capture.** The backend does it inside
  `_game_revealed()`, so every capture path gets it right once. Callers that did their
  own show/hide each got it wrong differently.
- `window.prompt` / `window.confirm` do not exist in WebView2. Every dialog is an HTML
  modal.

## Checklist for a new component

**Required.**

- A named CSS block, classes prefixed per feature (`im-`, `chal-`, `detect-`), colours
  only from the semantic custom properties.
- Empty shell in `index.html` with an `id`.
- One `render<Thing>()` rebuilding from one state object, re-wiring at the end.
- Bridge methods returning plain JSON, with the identity the backend uses.
- Empty state. Every list has one — "No runs yet", "Not scanned".
- Keyboard reachable: a real `<input>`/`<button>` under the hood, focus visible. If a
  control is a styled `<label>` wrapping a hidden input, the input stays in the DOM
  (`opacity: 0`, not `display: none`).
- Disabled and in-flight states for anything that calls the backend — button reads
  `...`, re-enabled by the callback, including on failure.

**Optional — add when the surface actually needs it.**

- Zoom/pan (only for images: reuse `showCropView`, don't write a second one).
- Filter/search (only past ~15 items).
- Tabs (only with a real second grouping).
- Live polling (only if the value changes without user action, and then clock-derived
  where possible — the challenge re-roll needs no capture).

## When to follow this pattern, and when not to

**Follow it** for anything that lists, edits or previews data the user owns: a settings
category, a picker, a manager, a block row, a dashboard card.

**Don't force it** on:

- *Static chrome* — the titlebar, a nav button. No state, no render function; put it in
  the shell and style it.
- *A one-shot action button* — Start, Scan. It needs a disabled/in-flight state, not a
  render pipeline.
- *A canvas interaction* — cropping, region picking. These are imperative by nature.
  Reuse the existing one (`showCropView` takes `onBack`/`onRetake`/`onSave`) rather than
  writing a parallel implementation.
- *Anything whose data lives in `content/`* — gamemodes, acts, delays. Those are tables;
  the UI derives from them and the change belongs in the table, not the UI. Adding a map
  is one line in `content/gamemodes.py`, and the selector, config paths and expected
  templates all follow.

## Before saying it works

`python -m compileall sloppykeys`, then a probe that constructs the bridge method you
added and asserts on its return shape. You cannot see the rendered window — the user is
the sensor. State plainly what you verified and what needs eyeballing, and never assert
a cause for pixels nobody has looked at.
