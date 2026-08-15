# UI Refactor Progress

Tracks the migration from PySide6 to pywebview + HTML/CSS/JS.

| Date | What changed | Why | Status |
|---|---|---|---|
| 2026-08-07 | Design conventions steering file created | Establish stack, layout, color, and commit rules before code begins | done |
| 2026-08-07 | Progress log created | Track refactor work across sessions | done |
| 2026-08-07 | HTML/CSS/JS skeleton v1 (right-panel layout) | Initial structure attempt | replaced |
| 2026-08-07 | HTML/CSS/JS skeleton v2 (full-page screens) | Each screen owns the full window; game visible only on Dashboard | replaced |
| 2026-08-07 | Rebuild with sharp-edge chunky plate design language | Square corners, inset bevels, fixed control heights, opacity hierarchy on tabs | done |
| | Wire pywebview bridge and viewport positioning | Connect the static shell to the Python backend | next |
