# New Macro Logic

Task-queue-driven. Start runs the queue in order, loops back to task 1 when done.

## Screens

- **Dashboard** — Start/Stop, status, log. No selector.
- **Task Queue** — ordered list + task builder (right panel when a task is selected).
- **Macro Manager** — block-based routine builder with four phases + a position picker.
- **Settings** — unchanged.

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

Stored as an ordered list in `tasks.json`. Re-read each pass so edits mid-run take effect.

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

A modal that shows map screenshots (from `images/maps/`) organized by gamemode. Click to set coordinates. Also offers "Use Roblox Screen" to capture the live game. Coordinates are in the 1152×756 client space.

## Task Presets

Save/load the entire queue under a name. Stored in `operations/presets/<name>.json`. Separate from file export/import (which is for sharing between installs).

## What This Replaces

- The per-gamemode selector on the Dashboard → gone; Start just runs the queue.
- The Unit Planner screen (steps grid + sequence editor) → replaced by Macro Manager.
- The current `configs/<Gamemode>/<Map>/<Act>.json` unit plans → replaced by `operations/<name>.json`.
- The `MacroRunner` step-chain builder in `controller.py` → reworked to read task queue + operation phases.
