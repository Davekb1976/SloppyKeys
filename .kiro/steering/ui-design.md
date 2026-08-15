---
title: UI Design Conventions
inclusion: always
---
# UI Design Conventions

All UI work is our own original implementation. External products were studied for
general UX patterns (layout hierarchy, density, color vocabulary) but our code,
structure, naming, and visual identity are independent. No reference to external
tools or products appears in commits, code comments, or documentation.

## Stack

**pywebview + HTML/CSS/JS** for the interface, **Python** for the backend. The macro
logic, AHK bridge, image search, OCR, and every `core/` / `macro/` module stay
Python-only and communicate with the UI through pywebview's `js_api` bridge.

- pywebview renders via WebView2 (Chromium) on Windows — full modern CSS is
  available (grid, custom properties, `color-mix()`, `backdrop-filter`, transitions).
- The window is frameless; the titlebar is a DOM element with
  `-webkit-app-region: drag`.
- `window.prompt()` / `window.confirm()` are blocked in WebView2 — all dialogs are
  HTML modals.
- `js_api` calls are async (return Promises). Long operations (capture, AHK, OCR)
  dispatch to a Python thread and push results back via `window.evaluate_js()`.
- File pickers use `webview.create_file_dialog()` on the Python side.
- WebView2 ships with Windows 10/11; no runtime to bundle.

## Layout

```
┌───────────────────────────────────────────────────────────────────┐
│  TITLEBAR (44px)                                                  │
│  [logo] SloppyKeys  │  nav icons  │  uptime  │  [–] [×]          │
├──────────────────────────────────────────┬────────────────────────┤
│                                          │  RIGHT PANEL (380px)   │
│        GAME VIEWPORT (1152×756)          │  screen content swaps  │
│        (native HWND over the WebView)    │  here per nav button   │
├──────────────────────────────────────────┤                        │
│  PROCESS LOG (fills height below game)   │                        │
└──────────────────────────────────────────┴────────────────────────┘
```

- The viewport is the game's own top-level window, floated in the topmost band over the
  slot by Python at exact pixel coordinates — not a child, never reparented. The DOM
  reserves a `<div>` as a placeholder and reports its `getBoundingClientRect()` to the
  backend, which is where the position comes from. Because the game is *above* the page,
  anything that must appear over the slot — a modal, an overlay — has to demote the game
  out of the topmost band first. See `coding-standards.md` for why a cut-out hole cannot
  work here.
- Window size is set from Win32 after the frame comes off, clamped to the work area:
  pywebview sizes the Form while it still has a frame, so the client area lands short of
  what was asked for and the log gets clipped.
- Navigation is icon buttons (30×30px) in the titlebar, not a sidebar rail.
- Right panel content swaps per screen: Run, Units, Tasks, Route, Settings.
- The process log sits below the viewport (not in the right panel) and scrolls
  independently with a capped line count.

## Screens

| Screen | Purpose |
|---|---|
| Run | Status readout, Start/Stop/Pause, scoreboard, run history |
| Units | Chip grid + detail editor for the active plan |
| Tasks | Queue list + builder panel |
| Route | Events nav-step list + fields + capture |
| Settings | Category rail + scrollable setting rows |

## Color Vocabulary

Seven semantic custom properties, each used at three opacity tiers:

| Variable | Role | Tiers |
|---|---|---|
| `--brand` | Primary accent, selected state | bg 14%, border 45%, glow 55% |
| `--teal` | Go / win / success | same |
| `--amber` | Pause / warning | same |
| `--rose` | Stop / loss / error / destructive | same |
| `--lilac` | Status / session | same |
| `--slate` | Neutral accent | same |
| `--sky` | Informational | same |

Backgrounds: `--bg-deep`, `--bg-card`, `--bg-surface`. Text: `--text`, `--text-dim`,
`--text-muted`. Border: `--border`. All derived colors use these variables so a theme
change propagates everywhere.

## Panel Component

Every section is a `.panel` — rounded card (12px radius) with:
1. **Header**: colored tag pill (8px uppercase) + title (11px semibold) + gradient rule
2. **Body**: content pattern (hero row, ledger rows, grid, form fields, list)

## Typography

- Body: system-ui / Segoe UI, 500 weight, 11-13px
- Headings / brand: 600-700 weight
- Micro-labels: 8-9px, uppercase, letter-spacing 0.06-0.12em, `--text-muted`
- Mono (log, keybinds): Consolas / ui-monospace, 11px

## Density

- Panel padding: 8px (uniform gutter between all adjacent sections)
- Row gaps: 6-8px
- Section gaps: 10-12px
- Control heights: 28-32px
- Icon buttons: 30×30px

## Alignment Rule

Every element at the same nesting level shares the same inset from its container's edge —
the gutter is **8px** everywhere in the dashboard:

- The game viewport sits flush left/right inside `.dash-left` (zero inset from its parent).
- The process log matches the viewport width (zero horizontal margin), with 8px vertical
  margin above and below.
- The right panel uses 8px padding on all four sides.
- Bottom alignment: the process log's bottom border and the Run History's bottom border
  must end at the same distance from the window edge. The last section in `.dash-right`
  uses `flex: 1` to stretch and fill remaining height so both columns end flush.

## Interactions

- Hover: border tint toward accent + subtle lift (`translateY(-1px)`)
- Press: `transform: scale(0.96)`
- Focus: accent border + soft glow shadow
- Disabled: `opacity: 0.4`, `cursor: default`
- Respect `prefers-reduced-motion`: collapse animations to instant

## File Layout

```
sloppykeys/
  ui_web/          the pywebview frontend
    index.html     main layout, all screens
    style.css      custom styles (vars, panels, modals)
    app.js         screen switching, js_api bridge, state
    log_view.js    process log rendering + scroll behaviour
  ui/              (removed once migration is complete)
  core/            unchanged
  macro/           unchanged
  config/          unchanged
  content/         unchanged
```

## Commit Conventions for UI Work

- Describe only the technical change. What was refactored, added, fixed, or
  restructured in our code.
- Never reference external tools, products, or inspiration sources.
- Standard language: "Refactor panel layout for clearer section hierarchy",
  "Add structured header to status panel", "Fix spacing in unit detail card".

## Progress Tracking

Major UI refactor work is tracked in `UI_REFACTOR_LOG.md` at the repo root.
Update it at each commit boundary with the date, what changed, why (one line),
and the status. Keep entries minimal — the commit history carries the detail.
