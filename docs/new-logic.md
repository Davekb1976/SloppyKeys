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
| `walk` | Pathing | `mode`, `pathName` |
| `wait_ms` | Timing | `params.ms` |
| `wait_wave` | Timing | `params.wave` |
| `leave_at_minute` | Timing | `params.minutes` |
| `click` | Setup | `params.x`, `params.y` |
| `send_key` | Setup | `key`, `params.hold_ms` |
| `detect` | Logic | `image`, `region`, `threshold`, `then: []`, `else: []`, `loop`, `loopAttempts` |

Phase constraints:
- Pre Start: `place_unit`, `walk`, `wait_ms`, `click`, `send_key`, `detect`, `target_priority`
- Battle / Loop A / Loop B: all except `walk` (the pre-start walk block)

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

```
sloppykeys/                   source code (unchanged)
data/                         gitignored, beside the exe in a frozen build
  settings.json               single file: settings, hotkeys, tasks, stats
  operations/                 macro operations (one JSON per named operation)
    presets/                   saved task queue snapshots
  paths/                      recorded walk paths
  debug/                      debug screenshots
images/                       shipped with the build, user-editable
  ui/                         nav/match templates (folder-per-name for variants)
  maps/                       map preview thumbnails for position picker
    Story/
    Raid/
    Expedition/
    Events/
```

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

## What to Add (from reference)

- Auto-reopen Roblox on crash mid-run
- Periodic Roblox refresh (rejoin for memory protection)
- Start minimized option
- Compact strip mode (game + small control bar only)
- Settings search/filter
- Settings import/export + reset keybinds to defaults
- Atomic file writes (tmp → fsync → replace)
- Walk path recording/replay system
