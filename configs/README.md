# configs

Saved unit plans, one file per farm target:

```
configs/<Gamemode>/<Map>/<Target>.json
```

e.g. `configs/Story/King's Tomb/Act 3.json`, `configs/Expedition/Rose Kingdom/Difficulty 2.json`

Every target the schema defines is scaffolded here: **Story 35** (5 maps × 7 acts),
**Raid 3** (1 map × 3 acts), **Expedition 3** (one per map). Paths are generated
from `content/gamemodes.py`, so adding a map or act there is what creates a new
target.

## Challenge

Challenge is a **side task**: the macro enters it from inside a match, never from
the lobby, so it is not on the gamemode Selector. It still needs its own plan per
map, because a challenge on Rose Kingdom is not the same fight as Rose Kingdom
Act 3. It has no act dimension, so it saves one config per map:

```
configs/Challenge/Rose Kingdom.json
```

Its maps are the five Story maps (`STORY_MAPS` in `content/gamemodes.py`, shared so
the two lists can't drift). The game rotates which map each of the three offered
challenges is on, so all five plans need to exist before the task can run
unattended. Every challenge is Hard regardless of the Hard Mode setting.

## Gamemodes without a target

Expedition has no third dimension — its difficulty is a toggle for how hard the
same map gets, like Story's Hard Mode, so it saves **one config per map** and the
path drops a level:

```
configs/Expedition/Rose Kingdom.json
```

The difficulty itself lives in `settings.json` under `expedition_difficulty`
(1–3), edited in Settings → Main. The Run strip hides its third selector for a
gamemode with no targets.

## Shape

```json
{
  "Schema": 1,
  "Gamemode": "Story",
  "Map": "King's Tomb",
  "Target": "Act 3",
  "Units": [ { "Step": 1, "Kind": "unit", ... } ]
}
```

`Units` is sparse — only steps holding data are written. The loader starts from an
empty 72-step plan and slots each entry in by its `Step` number, so a file with
two entries restores the same plan as one with 72.

A step is one of two kinds:

- `"unit"` — a placement: `Slot`, `Upgrades`, `X`, `Y`, `Priority`, `Wait`,
  `SellWait`, `Sell`, `AutoUpgrade`, `PrePlacement`.
- `"sequence"` — an `Actions` list of raw inputs (`move`, `click`, `drag`, `key`,
  `scroll`, `wait`), run in order.

A missing `Kind` reads as `"unit"`, and any missing field defaults, so older files
keep loading. Adding a field does not need a `Schema` bump for that reason.

### `AutoUpgrade` is a press count

The game's auto upgrade is a cycling control on the unit panel, not a switch: each
press of the auto-upgrade key steps it up one level, 1 through 6, and a **7th press
returns it to off**. So `AutoUpgrade` stores **how many times to press**:

| Value | Meaning |
|-------|---------|
| `0`   | leave it alone; `Upgrades` is bought manually instead |
| `1`–`6` | auto upgrade level 1–6, and `Upgrades` is **not** pressed |
| `7`   | full cycle, ending back on off — then `Upgrades` applies as normal |

It used to be a `0`/`1` flag. `1` meant "auto upgrade on", which was one press,
so old files keep behaving exactly as before and need no migration.

## Coordinates

`X`/`Y` and every coordinate inside a sequence action are Roblox **client-space**
pixels captured at the pinned 816×638 viewport, with the camera set by the macro's
camera step. Change the viewport size or the camera pitch and every stored
coordinate points somewhere else.
