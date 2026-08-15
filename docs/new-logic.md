# New Macro Logic

Task-queue-driven. Start runs the queue in order, loops back to task 1 when done.

## Screens

- **Dashboard** — Start/Stop, status, log. No selector.
- **Task Queue** — ordered list + task builder (right panel when a task is selected).
- **Macro Manager** — block-based routine builder with four phases + a position picker.
- **Settings** — auto-save, categorized (General, Hotkeys, Webhook, Debug), searchable, import/export.

## Data Model

### Task (one queue item)

```json
{
  "id": "t<timestamp>",
  "mode": "Story|Raid|Expedition|Events",
  "map": "School Grounds",
  "stage": "Act 1",
  "difficulty": "Normal|Hard",
  "repeat": 1,
  "macro": "<operation name>"
}
```

Stored as an ordered list in `settings.json` under `"tasks"`. Re-read each pass so edits mid-run take effect.

### Macro Operation (reusable template)

Stored per-file in `operations/<name>.json`:

```json
{
  "name": "My Farm",
  "phases": {
    "pre_start": [ ...blocks... ],
    "battle": [ ...blocks... ],
    "loop_a": [ ...blocks... ],
    "loop_b": [ ...blocks... ]
  }
}
```

- **Pre Start** — runs once on stage entry: walk, place starter units, flip settings.
- **Battle** — runs once through at match start: upgrades, sells, waits.
- **Loop A / Loop B** — repeat continuously during the match (detect→act cycles).

### Block (one action inside a phase)

```json
{ "type": "place_unit", "params": { "name": "", "x": 0, "y": 0 }, "hotkey": "q", "once": false }
```

| Type | Group | Key fields |
|------|-------|-----------|
| `place_unit` | Units | `params.x`, `params.y`, `params.name`, `hotkey` |
| `upgrade_unit` | Units | `params.index`, `params.times` |
| `sell_unit` | Units | `params.index` |
| `target_priority` | Units | `params.index` |
| `walk_path` | Pathing | `mode: "auto"|"custom"`, `pathName` — **pinned first block in Pre Start**, always present, not removable |
| `walk` | Pathing | `mode`, `pathName`, `sprint` — a mid-battle repositioning replay |
| `wait_ms` | Timing | `params.ms` |
| `wait_wave` | Timing | `params.wave` |
| `leave_at_minute` | Timing | `params.minutes` |
| `click` | Setup | `params.x`, `params.y` |
| `send_key` | Setup | `key`, `params.hold_ms` |
| `detect` | Logic | `image`, `region`, `threshold`, `then: []`, `else: []`, `loop`, `loopAttempts` |

**Walk Path vs Walk:**
- `walk_path` = the startup walk that gets you from spawn to your placement spot. Lives ONLY in Pre Start, pinned as the first block. Mode is Auto (uses the map's default recorded path) or Custom (a specific named recording). This replaces our current "Start Position" settings tab entirely.
- `walk` = a mid-match repositioning move. Lives in Battle/Loop phases. Replays a recorded WASD path during combat.

Phase constraints:
- Pre Start: `walk_path` (pinned first), `place_unit`, `walk`, `wait_ms`, `click`, `send_key`, `detect`, `target_priority`
- Battle / Loop A / Loop B: all except `walk_path`

`once: true` = skip on repeat entries to the same stage.

## Execution Flow

1. Start → read task queue → for each task:
2. Navigate lobby (mode → map → stage → start).
3. Load the task's macro operation.
4. Run **Pre Start** blocks linearly (walk, place starters).
5. Click Start Game.
6. Run **Battle** blocks once through (one block per tick).
7. Run **Loop A** + **Loop B** repeatedly alongside Battle (one block per tick each, restart at end).
8. Wait for match result (win/loss detection).
9. If repeat > 0 and repeats remaining → go to step 4.
10. Next task.
11. Queue exhausted → restart from task 1.

Detect blocks branch: evaluate condition → run `then` blocks or `else` blocks. Flattened into the linear list with jump offsets so the runner stays a simple index walker.

## Position Picker

A modal showing map screenshots (from `images/maps/`) organized by gamemode. Click to set coordinates. Also offers "Use Roblox Screen" to capture the live game. Coordinates in the 1152×756 client space. Other placed units shown as markers.

## Image Manager

Opens via hotkey (F6) or from Settings. A modal overlay (works from any screen).

**Layout**: Category tabs (UI, Maps, Detect) + name filter + "Open Folder" + "Capture Roblox" buttons at the top. Below is a scrollable grid of cards — one card per searched image name.

**Each card shows**:
- Category badge + name + variant count + "+" add button
- Description (optional, from a readme/comment)
- Per-name match threshold slider (0.50–1.00, default 0.90, persisted in `settings.json["image_thresholds"]`)
- Thumbnail grid of all variant images for that name

**Data model**: Folder-per-name under `images/ui/<name>/` (or `images/maps/<name>/`, `images/detect/<name>/`). Each PNG inside is a variant tried in order during search. The primary variant is `<name>.png`; extras sort alphabetically after it.

**API**:
- `list_vision_templates()` → returns all categories with all names and base64 thumbnails
- `set_image_threshold(name, value)` → persists + applies live
- `capture_image_search_screen()` → freezes the Roblox frame for cropping
- `save_image_search_crop(category, name, x, y, w, h)` → crops + saves as a new variant
- `delete_vision_template_image(category, name, filename)` → removes one variant

**Workflow**: Capture Roblox → draw a box over the element → name it → saved as a variant. The match threshold slider tunes sensitivity per-name without touching code. "Open Folder" launches the OS file explorer for hand-editing.

**For us**: replaces our current `Settings > Vision` screen. The folder-per-name variant system replaces our single-file-per-template approach. The Image Manager hotkey is registered globally so it can open mid-run when a search fails.

Save/load the entire queue under a name. Stored in `operations/presets/<name>.json`. Separate from file export/import (for sharing between installs).

## Settings Redesign

- **Auto-save** — no save button. Every change writes immediately via `update_json`.
- **Categories** — General, Hotkeys, Webhook, Debug. Left nav rail with an "All" option.
- **Search** — text filter over setting labels + descriptions, auto-switches to "All" view.
- **Import/Export** — exports all settings as a JSON file; import applies each key.
- **Reset to Defaults** — per-section (e.g. "Reset Hotkeys").
- Atomic writes (write to `.tmp`, fsync, `os.replace`).

## File Organization (new)

### Source tree (`sloppykeys/`)

```
sloppykeys/
├── __init__.py
├── __main__.py               entry point
├── version.py                VERSION string
│
├── core/                     services — no UI, no macro logic
│   ├── ahk.py               AHK v2 bridge (run scripts, find exe)
│   ├── image_search.py       template matching engine (folder-per-name variants)
│   ├── ocr.py                RapidOCR wrapper
│   ├── updates.py            GitHub release check + Roblox deep-link relaunch
│   ├── webhook.py            Discord webhook (rich embeds, screenshots)
│   ├── pacing.py             global action delay (NEW — ms sleep after every click)
│   └── win32/                typed ctypes bindings + OS helpers
│       ├── bindings.py       raw user32/kernel32/gdi32 signatures
│       ├── display.py        DPI, refresh rate, scale %
│       ├── frameless.py      frameless window helpers (topmost, move, fit)
│       └── roblox_window.py  find/measure/position the Roblox window
│
├── macro/                    execution logic — drives the game
│   ├── runner.py             state machine (block-per-tick, phase tracking)
│   ├── controller.py         task-queue orchestrator (reads queue, loads ops, drives runner)
│   ├── lobby.py              lobby navigation (click Play, select stage, wait for load)
│   ├── blocks.py             block executors: place, upgrade, sell, click, send_key, detect (NEW)
│   ├── camera.py             camera setup AHK script
│   ├── detect.py             Detect block evaluation + flatten (NEW)
│   ├── input_scripts.py      AHK script generators (nudge, walk, sequence)
│   ├── recording.py          walk path + full input recording/replay (NEW — merges paths + input_record)
│   └── challenge.py          challenge scanner (OCR the panel)
│
├── config/                   persistence — JSON store, no game logic
│   ├── store.py              atomic read/write/update_json (enhanced: tmp → fsync → replace)
│   ├── settings.py           single settings.json accessor (all keys consolidated)
│   ├── operations.py         macro operation CRUD (NEW — list/load/save/delete operations/)
│   ├── presets.py            task queue preset save/load (NEW)
│   └── routes.py             events routes.json store (renamed from nav_routes.py)
│
├── content/                  game schema — static data tables, no persistence
│   ├── gamemodes.py          modes, maps, stages, targets
│   ├── acts.py               per-act click coordinates
│   ├── nav_images.py         image path resolution for lobby nav
│   ├── nav_route.py          NavStep dataclass + route validation
│   └── start_stage.py        start/difficulty coordinates
│
└── ui_web/                   pywebview frontend (the only UI)
    ├── __init__.py
    ├── __main__.py           launch entry
    ├── bridge.py             Python↔JS API (all backend methods exposed here)
    ├── index.html            all screens + modals
    ├── style.css             design system (vars, panels, blocks, modals)
    └── app.js                screen switching, drag-drop, macro controls, selectors
```

### Data directory (gitignored, beside the exe in frozen builds)

```
data/                         created on first launch
├── settings.json             everything: settings, hotkeys, tasks, stats, thresholds, delays
├── operations/               macro operations (one JSON per named operation)
│   └── presets/              saved task queue snapshots
├── paths/                    recorded walk paths (WASD JSON)
├── recordings/               full input recordings (mouse+keyboard JSON)
└── debug/                    debug screenshots
```

### Assets (shipped with the build, user-editable)

```
images/
├── ui/                       nav/match templates — folder-per-name for variants
│   ├── start_game/           example: start_game.png + cropped variants
│   ├── victory/
│   ├── defeat/
│   └── ...
├── maps/                     map preview thumbnails for position picker
│   ├── Story/
│   ├── Raid/
│   ├── Expedition/
│   └── Events/
├── detect/                   user-added detection images (Detect block)
└── reference/                reference screenshots (existing, unchanged)
```

### What was removed

```
REMOVED:
  sloppykeys/ui/              entire PySide6 tree (window.py, pages/, editors, theme, icons)
  sloppykeys/config/delays.py         → merged into settings.json
  sloppykeys/config/keybinds.py       → merged into settings.json
  sloppykeys/config/regions.py        → merged into settings.json
  sloppykeys/config/start_position.py → walk_path block in Macro Manager
  sloppykeys/config/stats.py          → merged into settings.json
  sloppykeys/config/tasks.py          → merged into settings.json
  sloppykeys/config/unit_configs.py   → replaced by operations/
  sloppykeys/config/route_paths.py    → merged into routes.py
  sloppykeys/content/challenge.py     → absorbed into macro/challenge.py
  sloppykeys/content/start_position.py→ walk_path block handles this
  sloppykeys/content/units.py         → block executor internal types
  sloppykeys/macro/placement.py       → split into blocks.py executors
  sloppykeys/macro/tasks.py           → simplified in controller.py
  configs/                            → replaced by data/operations/
```

### Notes

- `__pycache__/` folders appear in every package — this is normal Python bytecode caching, covered by `.gitignore`, harmless.
- 4 packages (`core`, `macro`, `config`, `content`) + 1 UI package (`ui_web`). Down from 6.
- No `ui/pages/` sub-package. The webview is one HTML file with screen sections.
- `content/` is read-only game data (coordinates, names). `config/` is read/write user data. Clear split.
- Every module has one job. No 4000-line window.py.

## What Changes from Current

| Current | New |
|---------|-----|
| Dashboard gamemode selector | Removed; Start runs the task queue |
| Unit Planner screen | Replaced by Macro Manager (block-based) |
| `configs/<Mode>/<Map>/<Act>.json` | Replaced by `operations/<name>.json` |
| Manual save button | Auto-save on every change |
| Flat image files | Folder-per-name variant system (later) |
| `settings.json` per-key stores scattered | Single settings.json with sections |
| Separate delay/keybind/region/position stores | Consolidated into settings.json |
| Start Position settings tab | Absorbed into Macro Manager as `walk_path` block (pinned first in Pre Start) |

## What to Add (from reference)

- Auto-reopen Roblox on crash mid-run
- Periodic Roblox refresh (rejoin for memory protection)
- Start minimized option
- Compact strip mode (game + small control bar only)
- Settings search/filter
- Settings import/export + reset keybinds to defaults
- Atomic file writes (tmp → fsync → replace)
- Walk path recording/replay system

## Module Audit — Keep / Rework / Remove

### `config/` (data stores)

| Module | Verdict | Notes |
|--------|---------|-------|
| `store.py` | **Keep + improve** | Add atomic writes (tmp → fsync → replace). Already has `update_json` with RLock. |
| `settings.py` | **Rework** | Consolidate all scattered stores into one `settings.json`. Remove `ImageProfileStore` (replaced by Image Manager). Drop the manual `ensure_json` defaults pattern — read returns defaults merged at runtime. |
| `keybinds.py` | **Merge into settings.json** | One `"hotkeys"` key. Add `reset_hotkeys()` endpoint. |
| `delays.py` | **Merge into settings.json** | One `"delays"` key. |
| `regions.py` | **Merge into settings.json** | `"confidence"` overrides move to `"image_thresholds"`. Points/regions stay. |
| `start_position.py` | **Merge into settings.json** | One `"walk_paths"` or `"start_position"` key. |
| `stats.py` | **Keep** | Stays in settings.json under `"stats"`. |
| `tasks.py` | **Rework** | Tasks move to `settings.json["tasks"]`. Remove `TaskStore` class — read/write through the generic store. |
| `unit_configs.py` | **Remove** | Replaced by operations. Migration reads old configs and converts to operation format on first launch. |
| `nav_routes.py` | **Keep** | Routes stay as their own file (`routes.json`). Events navigation is route-driven. |

### `content/` (game schema / tables)

| Module | Verdict | Notes |
|--------|---------|-------|
| `gamemodes.py` | **Keep** | Drives the task builder's Mode/Map/Stage dropdowns. |
| `acts.py` | **Keep** | Coordinate tables for lobby navigation. |
| `start_stage.py` | **Keep** | Start/difficulty coordinates. |
| `challenge.py` | **Keep** | Challenge panel geometry. |
| `nav_images.py` | **Keep** | Image path resolution for lobby navigation. |
| `nav_route.py` | **Keep** | NavStep dataclass, route validation. |
| `start_position.py` | **Keep** | Walk preset definitions. |
| `units.py` | **Rework** | `UnitStep`/`UnitPlan` become the block executor's internal types, not the user-facing config format. |

### `core/` (services)

| Module | Verdict | Notes |
|--------|---------|-------|
| `image_search.py` | **Rework** | Add folder-per-name variant loading. Remove `ImageProfile`/`SearchRegion` from here — they become settings.json data. Keep the engine + match logic. |
| `ahk.py` | **Keep** | Unchanged. |
| `ocr.py` | **Keep** | Unchanged. |
| `updates.py` | **Keep** | Add auto-reopen Roblox deep-link launch. |
| `webhook.py` | **Keep** | Unchanged. |
| `win32/` | **Keep** | All helpers stay. Add walk-path recording (keyboard/mouse polling). |

### `macro/` (runner + logic)

| Module | Verdict | Notes |
|--------|---------|-------|
| `runner.py` | **Rework** | The state machine stays, but `tick()` now advances one BLOCK per call (not one step). Add loop-phase tracking. |
| `controller.py` | **Rewrite** | Reads task queue, iterates tasks, loads operations, calls phase runners. Replaces the step-chain builder. |
| `lobby.py` | **Keep** | LobbyNavigator stays for lobby navigation. |
| `placement.py` | **Rework** | `UnitPlacer` methods become block executors (`run_place_unit`, `run_upgrade`, `run_sell`, etc.). `wait_for_outcome` stays. |
| `camera.py` | **Keep** | Unchanged. |
| `challenge.py` | **Keep** | Challenge scanner stays. |
| `tasks.py` | **Rework** | `TaskDirector`/`TaskDecision` simplified — the queue IS the decision now, no priority/rotation logic needed. |
| `input_scripts.py` | **Keep** | AHK script generators unchanged. |

### `ui/` (PySide6 — to be removed)

| Module | Verdict |
|--------|---------|
| `window.py` | **Remove** (after migration) |
| `pages/` | **Remove** |
| `sequence_editor.py` | **Remove** (replaced by block editor in Macro Manager) |
| `position_editor.py` | **Remove** (replaced by Position Picker modal) |
| `route_editor.py` | **Remove** (replaced by Route screen in webview) |
| `task_editor.py` | **Remove** (replaced by Task Builder in webview) |
| `theme.py` | **Remove** (CSS handles it now) |
| `icons.py` | **Remove** (SVG in HTML) |
| `glow.py`, `widgets.py`, `viewport.py`, `placement_overlay.py` | **Remove** |
| `image_manager.py` | **Remove** (replaced by Image Manager modal in webview) |
| `macro_tester.py` | **Remove** (Debug section in Settings handles this) |

### `ui_web/` (new pywebview UI)

| Module | Status |
|--------|--------|
| `bridge.py` | Active — will grow to host all API methods |
| `app.js` | Active — screen switching, macro controls, selectors |
| `index.html` | Active — all screens |
| `style.css` | Active — design system |

## Implementation Order

1. **Settings consolidation** — merge all stores into one settings.json, atomic writes, auto-save API
2. **Task Queue screen** — ordered list + builder, wired to settings.json
3. **Macro Manager screen** — block palette, four phases, drag-drop, inline editors
4. **Position Picker modal** — map thumbnails + Roblox capture + click-to-place
5. **Controller rewrite** — reads queue, loads operations, runs phases with block executors
6. **Image Manager modal** — folder-per-name variant grid, threshold sliders, capture+crop
7. **Settings screen** — categories, search, import/export, reset
8. **Dashboard cleanup** — remove selector, wire to queue-driven start
9. **PySide6 removal** — delete `ui/` once everything is covered
10. **Polish** — auto-reopen, compact mode, walk recording, pause/resume

## Features to Adopt

### Compact Strip Mode (F7)
- Window shrinks to just game + a 50px control strip (Start/Pause/Stop + action text + status dot)
- Drops the side panel and log — for when the macro is running fine and the full UI is clutter
- F7 toggles back to full. Game stays docked, macro keeps running unchanged
- Our version: strip the right panel + log, resize window to 1152×(38+756+50)=844

### Pause/Resume (F5)
- A third state between running and stopped. The runner thread stays alive, parked at its current step
- `_checkpoint()` blocks in a spin-sleep while paused, resumes exactly where it left off
- Stop always clears pause (a paused thread doesn't sit forever)
- Dashboard shows Pause button that relabels to "Resume" when paused, with a pulsing dot

### Run History
- Stored in settings.json under `run_history` (list, newest-first, capped at 50)
- Each entry: `{result: "win"|"loss", map, duration, at: epoch}`
- Session wins/losses are in-memory only. All-time persists
- Runs-per-hour from a rolling 1-hour window
- Dashboard panel renders colored W/L rows

### Action Delay (Macro Speed)
- Single global ms delay injected after every click/keypress
- Settings slider, 0–2000ms, 0 is default (original speed)
- Live update — takes effect on the very next click without restart
- Lets users slow the macro for lower-end PCs where clicks arrive before the game processed the last one

### Walk Path Recording
- Polls WASD + I/O keys at 30ms on a background thread
- Only state transitions logged with timestamps
- Stored in `paths/` as JSON
- Replayed by sleeping between events to reproduce original timing
- Default paths shipped with the build; user recordings override by name

### Input Recording (Record block)
- Full mouse + keyboard via global hooks (not polling)
- Coords converted to 1152×756 reference space at capture time
- Events outside game bounds dropped automatically
- Replayed with 1ms timer resolution for precision
- Stored in `recordings/` folder

### Share via Code
- Compress template JSON with DEFLATE + preset dictionary → base64 → `SLOPPY:v1:<code>` string
- Import accepts: code string, raw JSON, or URL
- Bundles walk paths + input recordings alongside blocks
- Preview before importing (shows template names + block counts)
- Bounded decompression (5MB cap) to prevent malicious input

### Webhook Enhancements
- Per-match result embed: title, color, duration, map/stage/difficulty, session stats, all-time stats
- Result screenshot attached (captured while Victory/Defeat screen is up)
- Status card image (rendered — win/loss activity grid like a GitHub contribution graph)
- @mention option + silent mode (no push notification)
- Session elapsed time + runs/hour in the embed

### Debug Tools
- **Test Pre Start / Test Battle**: run a Macro Operation's blocks against live Roblox without lobby nav
- **Health Check**: verify display scale, elevation, assets, OCR, critical images
- **Log pop-out**: separate window with the full log stream
- **Debug screenshot** (F3): numbered PNGs to a debug folder

### Auto-Reopen Roblox
- If the game closes/crashes mid-run, relaunch via deep link (private server URL)
- Throttled to one attempt per 60s
- The dock watchdog detects the window vanishing and drives the relaunch
- The runner picks up the new HWND and resumes from the lobby

### Onboarding
- First-run modal with a checklist (display scale 100%, elevation matching, etc.)
- Dismissible — never reappears after "Get Started"
- Optional subscribe prompt chains after (one-time, either dismissal kills it)

### Theme System
- Base theme (dark variants: Dark, Black, Slate, etc.)
- Accent color (purple, teal, amber, rose, etc.) independent of base
- Applied via CSS variables, persisted in settings
