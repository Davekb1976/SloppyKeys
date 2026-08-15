# UI Refactor Progress

Tracks the migration from PySide6 to pywebview + HTML/CSS/JS.

| Date | What changed | Why | Status |
|---|---|---|---|
| 2026-08-07 | Design conventions steering file created | Establish stack, layout, color, and commit rules before code begins | done |
| 2026-08-07 | Progress log created | Track refactor work across sessions | done |
| 2026-08-07 | HTML/CSS/JS skeleton v1 (right-panel layout) | Initial structure attempt | replaced |
| 2026-08-07 | HTML/CSS/JS skeleton v2 (full-page screens) | Each screen owns the full window; game visible only on Dashboard | replaced |
| 2026-08-07 | Rebuild with sharp-edge chunky plate design language | Square corners, inset bevels, fixed control heights, opacity hierarchy on tabs | done |
| 2026-08-07 | Window button hover icons + pywebview bridge with js_api | Buttons show minimize/close SVGs on hover; bridge loads the UI and exposes window controls | done |
| 2026-08-07 | Roblox HWND docking loop in the bridge | Background thread finds Roblox and positions it over the game-slot div; hides it off-screen on non-Dashboard screens | replaced |
| 2026-08-15 | Docking rebuilt on a window mask instead of reparenting | A reparented game window dies with ours on close; masking leaves it untouched, so its caption returns intact | done |
| 2026-08-15 | Window move handed to the OS caption-drag loop | Removes the per-frame IPC that made dragging stutter while the game window followed | replaced |
| 2026-08-15 | Drag tracked by a backend cursor loop instead | The OS loop never moved the window: WebView2 holds the mouse capture in its own process | done |
| 2026-08-15 | Game window pinned to the front of the normal z-order band | It had been promoted to topmost, so clicking the game raised it over the UI | replaced |
| 2026-08-15 | Cutout applied before the game window is moved under it | A fully covered client reads as occluded and stops presenting until clicked | replaced |
| 2026-08-15 | Cutout dropped: game floats topmost over the slot instead | WebView2 composites via DirectComposition and ignores GDI window regions, so the hole never showed | done |
| 2026-08-15 | Window sized from Win32 to 1536x1014, clamped to the work area | pywebview sized the Form with its frame still on, leaving the client 39px short and clipping the log | done |
| 2026-08-15 | Game slot rect reported from the DOM to the backend | The cutout is measured where the slot rendered rather than duplicated as a constant | done |
| | Wire macro controls (Start/Stop) to the existing runner | Clicking Start in the new UI should start a run the same as F1 does | next |
