# Design vocabulary

All of this is our own implementation. External products were studied for general UX
patterns only — never reference a tool, product or inspiration source in a commit, a code
comment or documentation.

## Stack

pywebview + HTML/CSS/JS front end, Python back end, talking over `js_api`. WebView2
(Chromium) renders, so modern CSS is available: grid, custom properties, `color-mix()`,
`backdrop-filter`, transitions. The window is frameless; the titlebar is a DOM element
with `-webkit-app-region: drag`. File pickers go through
`webview.create_file_dialog()` on the Python side.

Macro logic, the AHK bridge, image search and OCR stay Python-only.

## Layout

```
┌───────────────────────────────────────────────────────────────────┐
│  TITLEBAR (44px)   [logo] SloppyKeys │ nav icons │ uptime │ – ×   │
├──────────────────────────────────────────┬────────────────────────┤
│        GAME VIEWPORT (1152×756)          │  RIGHT PANEL (380px)   │
│        (native HWND over the WebView)    │  swaps per nav button  │
├──────────────────────────────────────────┤                        │
│  PROCESS LOG (fills height below game)   │                        │
└──────────────────────────────────────────┴────────────────────────┘
```

- The viewport is the game's own window, floated over the slot by Python at exact pixel
  coordinates. The DOM reserves a placeholder `<div>` and reports its
  `getBoundingClientRect()`; that is where the position comes from.
- Window size is set from Win32 after the frame comes off, clamped to the work area.
  pywebview sizes the form while it still has a frame, so the client area lands short.
- Navigation is 30×30px icon buttons in the titlebar, not a sidebar rail.
- Screens: Run · Units · Tasks · Route · Settings.
- The process log sits below the viewport with a capped line count.

## Colour

Seven semantic custom properties, each used at three tiers (bg ~14%, border ~45%,
glow ~55%):

| Variable | Role |
|---|---|
| `--brand` / `--accent` | Primary accent, selected state |
| `--teal` | Go / win / success |
| `--amber` | Pause / warning |
| `--rose` | Stop / loss / error / destructive |
| `--lilac` | Status / session |
| `--slate` | Neutral accent |
| `--sky` | Informational |

Backgrounds `--bg-deep` `--bg-card` `--bg-surface`; text `--text` `--text-dim`
`--text-muted`; `--border`. Every derived colour goes through these so a theme change
propagates. No raw hex in a feature block.

## Typography and density

- Body: system-ui / Segoe UI, 500, 11–13px. Headings 600–700.
- Micro-labels: 8–9px, uppercase, letter-spacing 0.06–0.12em, `--text-muted`.
- Mono (log, keybinds): Consolas / ui-monospace, 11px.
- Panel padding 8px · row gaps 6–8px · section gaps 10–12px · control heights 28–32px ·
  icon buttons 30×30px.

## The panel component

Every section with its own identity is a `.panel`: a bordered card with

1. **Header** — a coloured tag pill (8–9px uppercase: `MACRO`, `SETUP`, `COMBAT`,
   `SYSTEM`) + title (12–13px semibold) + optional count on the right.
2. **Toolbar** (optional) — action buttons inside the panel, below the header.
3. **Body** — the content. Only the body scrolls (`overflow-y: auto`).

Panels are separated by an 8px gap, never edge-to-edge. The selected item in a list gets
`border-left: 3px solid var(--accent)` and a soft accent background.

A section title may carry **one** action on the right (Challenge → Scan).

## Setting rows

Two columns in a panel body: left label + description, right control. Full-width rows put
the control below. Label 12px semibold, description 10px `--text-faint`, micro-label above
a control 9px uppercase `--text-muted`.

## Booleans: `.check`, and nothing else

One square box that fills with a square dot when checked. Used for every on/off value.

```html
<label class="check"><input type="checkbox" data-field="sprint"><span class="check-box"></span>Sprint</label>
<label class="check check--lg"><input type="checkbox" data-key="hard_mode"><span class="check-box"></span></label>
```

- The native input stays in the DOM, visually hidden (`opacity: 0`, **not**
  `display: none`), so `el.checked`, `change`, labels and focus keep working.
- Trailing text goes inside the same `<label>` so it is part of the hit target.
- `.check--lg` (20px) for a settings row; default 16px in block rows.
- **No sliding switch**, no bare native checkbox, no glyph tick. A sliding `.toggle`
  existed and was deleted — don't reintroduce it.
- A grouped or multi-state choice is not a checkbox: use chunky `.slot-toggle` buttons or
  a `.blk-select` dropdown.

## Tooltips: `data-tip`, never `title`

```html
<button class="btn btn--sm tip-left" data-tip="Delete this walk path">✕</button>
<button data-tip="Grab the game now.&#10;The Challenge panel must be open">Preview</button>
```

A dark pill with an accent bar down its leading edge, appearing below the trigger after a
0.25s hover. `white-space: pre-line`, so `&#10;` in the attribute (or `\n` from JS) breaks a
line — keep it to three short lines.

- **The native `title` attribute is not used anywhere.** WebView2 renders it late, in the
  OS font, and not at all on some frameless paths. `[data-tip]` in `style.css` is the only
  tooltip.
- `.tip-left` for anything inside a block row or a dense list: a tooltip below lands on the
  next row and reads as part of it. `.tip-above` for a bottom strip.
- **Titlebar tooltips are automatic and sideways.** The game window sits directly below the
  bar and paints over any DOM it overlaps, so a tooltip dropped downward renders inside
  Roblox. `#titlebar [data-tip]` puts it beside the trigger; the right-hand group flips.
- Hover is not discoverable: a tooltip explains an icon or adds a precondition. Anything the
  user must read is a `.setting-desc` or a visible note.
- Setting it from JS is `el.setAttribute("data-tip", …)`.

## Block rows

A row in the Macro Manager: `.block-row` with a coloured left border per type
(`--blk-color`), a `.block-type` name, `.block-fields`, and `.block-actions` (once /
clone / remove) pushed right.

- Fields carry captions: `blkField("X", …)` renders a 8px uppercase label above the
  control. Never a bare input whose meaning is only its placeholder.
- Place Unit shows a `.unit-ord` `#N` pill; unit actions select a placed unit by `#N`
  through a dropdown rather than carrying their own coordinates.

## Alignment and full height

The gutter is **8px** everywhere. The viewport sits flush inside `.dash-left`; the process
log matches its width; the right panel has 8px on all four sides. The last section uses
`flex: 1` so both columns end flush — a new card above it takes space from it
automatically.

Any screen with two or more columns has a structural `border-right` on the left container
that must run unbroken from titlebar to window bottom. That needs `height: 100%` on every
container in the chain, and panels inside using `flex: 1` so they never shrink-wrap.

## Interactions

Hover: border tint toward accent, `translateY(-1px)`. Press: `scale(0.96)`. Focus: accent
border + soft glow. Disabled: `opacity: 0.4`, `cursor: default`. Honour
`prefers-reduced-motion` by collapsing animations to instant.

Icons: rail icons vector-drawn; other glyphs from **Segoe Fluent Icons** (ships with
Windows). No emoji as an interactive affordance.

Coordinates are **picked, not typed** — the region overlay is translucent so the user
clicks through to the live window and it returns client-space numbers. Reuse it.

## File layout

```
sloppykeys/ui_web/
  index.html   shells for every screen and modal
  style.css    tokens + one named block per feature
  app.js       screen switching, render functions, js_api calls
  bridge.py    the js_api surface; owns data and identity
```
