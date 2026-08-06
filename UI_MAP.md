# SloppyKeys UI Map

Shared vocabulary for the interface. Use these names when asking for a change and there's
no ambiguity about which widget you mean.

**No sizes here on purpose.** Every number lives in `ui/theme.py` (`WINDOW_WIDTH`,
`VIEWPORT_WIDTH`, `RAIL_WIDTH`, `STRIP_HEIGHT`, …). The previous version of this file quoted
a 1380×886 window and an 816×638 viewport against a real 1690×1012 and 1152×756, which is
exactly what a second copy of a measured number does. The one constant worth knowing is
that the viewport is pinned at **1152×756** and every coordinate, template and unit plan
was captured at that size.

---

## Top level

```
┌──────────────────────────────────────────────────────────────┐
│ TITLEBAR (a card, inset from the window edge)                │
├──────┬───────────────────────────────────────────────────────┤
│      │  ┌────────────────────────┬─────────────────────┐     │
│ RAIL │  │       VIEWPORT         │                     │     │
│      │  ├────────────────────────┤    RIGHT PANEL      │     │
│ ⋮    │  │       RUN STRIP        │                     │     │
│ CLOCK│  └────────────────────────┴─────────────────────┘     │
└──────┴───────────────────────────────────────────────────────┘
```

| Name | What it is | Where |
|---|---|---|
| **Titlebar** | Top card, full width. Drags the window. | `ui/window.py` → `TitleBar` |
| **Rail** | Left nav card: RUN / UNITS / SETTINGS. | `window.py` → `RAIL_ITEMS`, `RailButton` |
| **UptimeTile** | `UPTIME` caption + macro uptime, pinned to the **foot** of the Rail. Same number as the Run panel's `Macro uptime` and the embeds' `macro up`. | `_build_uptime_tile` |
| **Workspace** | Viewport + RunStrip on the left, RightPanel on the right. | `_build_workspace` |

The gamemode **SelectorScreen** replaces the whole workspace, because picking a mode is a
one-off. Everything else is a card in the RightPanel, so the Roblox view and the run strip
stay on screen whatever you're doing.

### Titlebar parts

Left to right: **Brand** ("SloppyKeys") · **VersionPill** (`v0.1.0`, from
`sloppykeys/version.py`) · **HintPills** — one per hotkey (`F1 · Start`, `F2 · Stop`,
`F3 · Reload`, `Ctrl + T · Tester`), rebuilt from the live keybinds by `_hint_texts` ·
stretch · **GamemodePill** (the chosen mode; click to go back to the SelectorScreen) ·
**WindowControls** (minimize, close).

---

## Screens

### SelectorScreen
`ui/pages/selector_page.py`. **ModeGrid** of **ModeCards**, one per gamemode.

### Workspace

| Name | What it is | Where |
|---|---|---|
| **Viewport** | The hole Roblox shows through. Roblox is moved behind it, never reparented. | `ui/viewport.py` → `RobloxViewport` |
| **ViewportPlaceholder** | Dashed frame + **SizePill**, while Roblox is detached. | `_paint_placeholder` |
| **RunStrip** | The bar under the Viewport. | `ui/pages/run_page.py` → `RunPage` |
| **RightPanel** | The stack the Rail switches: StatsPanel / UnitsPanel / SettingsPanel. | `window.py` → `RIGHT_PANELS` |

**RunStrip cards**: `PROCESS LOG` (**LogCard**, with the **StatusLine** under it) ·
`CURRENT CONFIG` (**ConfigCard** — MapSelect, ActSelect, labelled "Difficulty" for
Expedition) · `TASK QUEUE` (**QueueCard**) · `ACTIONS` (**ActionsCard** — Save, Import,
Reset).

### RightPanel: RUN → StatsPanel
`ui/pages/stats_page.py`. Groups: `CURRENT STATUS` · `WIN / LOSS` · `CHALLENGES` (the three
daily rows and their state) · `CURRENCY`.

### RightPanel: UNITS → UnitsPanel
`ui/pages/units_page.py`. **ChipsCard** (**FilterBar**: SearchBox + `All`/`On`/`Off`
**FilterPills**; **ChipGrid** of **StepChips**) over **DetailCard**.

A **StepChip** carries `#N`, the **UpgradeBadge** (`+N`) and a **SlotLine**. The
**DetailCard** is three fixed bands: **DetailHeader** (StepBadge + NameField), a scrolling
**DetailBody** (`BASIC`, `TIMING`, `ACTIONS`), and the pinned **CoordsBar** (X, Y, Set).

### RightPanel: SETTINGS → SettingsPanel
`ui/pages/settings_page.py`. **SettingsTabBar** wraps onto a grid, `TABS_PER_ROW` across:

| Tab | Holds |
|---|---|
| **Main** | `CONNECTION` (private-server link, Join) · `DISCORD` (webhook, Send Test) · `MACRO` (camera-once, Hard Mode, Expedition difficulty) · `UPDATES` (check-on-startup toggle, Check Now, the install/release button) |
| **Tasks** | The task queue editor and the challenges toggle. `ui/task_editor.py` |
| **Route** | Events route authoring, with capture and coordinate pickers. `ui/route_editor.py` |
| **Vision** | Every template: region, per-template threshold, Test. Also the OCR boxes. `ui/image_manager.py` |
| **Keybinds** | `HOTKEYS` — the app's hotkeys plus the in-game keys the macro sends. |
| **Delays** | One row per `DELAY_SPEC` entry. |
| **Position** | Per-target start-position plans. `ui/position_editor.py` |
| **Debug** | `MACRO TESTING` — opens the MacroTesterWindow. |

### MacroTesterWindow
`ui/macro_tester.py`. Always-on-top, runs one step at a time. **CoordsCard** (pick and copy
a client-space point) · **TestRows** grouped `COORDS` / `VISION` / `ENVIRONMENT` /
`LOBBY MACRO` / `MATCH MACRO`, each with a **ResultLabel** and a **TestButton** ·
**TestLog**. Add a case by appending to `MainWindow._build_tests()`: a
`(group, name, description, fn)` tuple where `fn` returns `(ok, message)`.

---

## Reusable pieces

| Name | What it is | Where |
|---|---|---|
| **SectionBox** | The bordered rounded container every card uses. | `theme.py` → `QFrame#sectionBox` |
| **GroupHeader** | Uppercase caption + rule (`BASIC`, `UPDATES`). | each page's `_group()` |
| **Pill** | Fully-rounded fixed-height label (VersionPill, HintPills, UpgradeBadge, SizePill). | `theme.py` |
| **ToggleSwitch** | Animated on/off switch. | `ui/widgets.py` |
| **KeyCaptureButton** | Press-a-key rebinding button. | `ui/widgets.py` |
| **RegionOverlay** | Translucent picker; you click through to the live window and it returns client-space numbers. | `ui/widgets.py` |
| **HoverGlow** | Animated hover/selection glow. | `ui/glow.py` |
| **RailIcon** | Vector-drawn rail glyph. Other glyphs come from Segoe Fluent Icons (`ui/icons.py`). | `window.py` |

---

## How to phrase a request

- "Make the **UpgradeBadge** bigger" → the `+N` pill on each StepChip.
- "The **ActionsCard** buttons are too tall" → Save / Import / Reset in the RunStrip.
- "**CoordsBar** needs a Copy button" → the pinned bottom row of the DetailCard.
- "Move the **SessionTile** back to the Titlebar" → unambiguous.
- "**UPDATES** should say when it last checked" → the Main tab group.

Pattern that works: **\<Name\> + what's wrong + what you want.**
