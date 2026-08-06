# SloppyKeys UI Map

Shared vocabulary for the interface. Use these names when asking for changes and
I'll know exactly which widget you mean. Every name below maps to real code.

Window: **1380 x 886**, frameless, fixed size, always-on-top, rounded corners.

---

## Top level

```
┌──────────────────────────────────────────────────────────────┐
│ TITLEBAR                                                     │
├──────┬───────────────────────────────────────────────────────┤
│      │                                                       │
│ RAIL │                    SCREEN                             │
│      │   (SelectorScreen | Workspace | SettingsScreen)        │
│      │                                                       │
└──────┴───────────────────────────────────────────────────────┘
```

| Name | What it is | File |
|---|---|---|
| **Titlebar** | Top bar, full width. Drags the window. | `ui/window.py` → `TitleBar` |
| **Rail** | Left vertical nav card (RUN / UNITS / SETTINGS). | `ui/window.py` → `rail`, `RailButton` |
| **Screen** | The swappable area right of the Rail. One of the three screens below. | `ui/window.py` → `self._stack` |

---

## Titlebar parts

`Titlebar` → left to right:

| Name | What it is |
|---|---|
| **Brand** | The white bold "SloppyKeys" text. |
| **VersionPill** | Rounded `v0.3.0` pill. |
| **HintPills** | The `F1 · Start` and `F3 · Reload` pills. |
| **ModeButton** | Right side. Shows the selected gamemode (`‹ Story · change`). Hidden on the SelectorScreen. Clicking it clears the mode and returns to the SelectorScreen. |
| **SessionClock** | `SESSION` caption + running timer, right of the ModeButton. |
| **WindowControls** | Minimize and Close glyphs, far right. |

---

## Screens

### 1. SelectorScreen
Shown on launch. Pick what the macro runs.

| Name | What it is | File |
|---|---|---|
| **SelectorHeader** | "Selectors" title + "Choose what the macro runs" subtitle. | `ui/pages/selector_page.py` |
| **ModeGrid** | The grid of gamemode cards (3 per row). | `SelectorPage` |
| **ModeCard** | One gamemode card: letter badge + name + subtitle, accent-colored, hover glow. | `GamemodeCard` |

### 2. Workspace
The main working screen. Shown after picking a mode, or via the Rail's UNITS button.

```
┌───────────────────────┬───────────────┐
│                       │  ChipsCard    │
│      Viewport         ├───────────────┤
│                       │               │
├───────────────────────┤  DetailCard   │
│      RunStrip         │               │
└───────────────────────┴───────────────┘
```

| Name | What it is | File |
|---|---|---|
| **Viewport** | The Roblox area. Fixed **816 x 638** hole; Roblox is moved/resized to fit it exactly. | `ui/viewport.py` → `RobloxViewport` |
| **ViewportPlaceholder** | Dashed frame + monitor icon + "Roblox Window" + **SizePill** (`816 x 638`). Only visible while Roblox is detached. | `RobloxViewport._paint_placeholder` |
| **RunStrip** | The horizontal bar under the Viewport. Holds the three cards below. | `ui/pages/run_page.py` → `RunPage` |
| **StepsPanel** | The whole right column (ChipsCard + DetailCard). | `ui/pages/units_page.py` → `UnitsPage` |

#### RunStrip cards (left to right)

| Name | Header text | Contents |
|---|---|---|
| **LogCard** | `PROCESS LOG` | Scrolling log output + the **StatusLine** underneath it. |
| **ConfigCard** | `CURRENT CONFIG` | **MapSelect** dropdown, **ActSelect** dropdown (labeled "Difficulty" for Expedition). Appears only after a Map is picked. |
| **ActionsCard** | `ACTIONS` | **SaveButton** (gradient), **ImportButton**, **ResetButton**. |

#### StepsPanel cards (top to bottom)

| Name | Contents | File |
|---|---|---|
| **ChipsCard** | **FilterBar** + **ChipGrid**. | `UnitsPage` |
| **FilterBar** | **SearchBox** + the **FilterPills** (`All` / `On` / `Off`). | `UnitsPage` |
| **ChipGrid** | Scrollable grid of all 72 **StepChips**, 3 per row. | `UnitsPage._grid` |
| **StepChip** | One step: `#N` number, **UpgradeBadge** (`+N` pill), **SlotLine** (`Slot -`). Selected chip gets a violet outline. | `StepChip` |
| **DetailCard** | The editor for the selected step. Three fixed bands below. | `DetailEditor` |

#### DetailCard bands

| Name | Position | Contents |
|---|---|---|
| **DetailHeader** | Pinned top | **StepBadge** (round number) + **NameField** ("Custom name..."). |
| **DetailBody** | Scrolls | Groups: **BasicGroup** (Slot #, Priority, Upgrade Level), **TimingGroup** (Wait), **ActionsGroup** (Mouse) + the auto-on hint. |
| **CoordsBar** | Pinned bottom | **XField**, **YField**, **SetButton**. |

### 3. SettingsScreen
Global config, split into tabs. The Viewport is hidden here.

| Name | What it is | File |
|---|---|---|
| **SettingsHeader** | "Settings" + subtitle + **SaveSettingsButton**. | `ui/pages/settings_page.py` |
| **SettingsTabBar** | The tab row: `Main`, `Keybinds`, `Debug`. | `SettingsPage._build_tabbar` |
| **MainTab** | See groups below. | `_build_main_tab` |
| **KeybindsTab** | Rebind hotkeys via **KeyCaptureButton** rows (Start/Stop, Reload, Open Macro Tester). | `_build_keybinds_tab` |
| **DelaysTab** | **DelaySpin** rows (Join wait, Image search cooldown). Applied live to the navigator; stored in `settings.json`. | `_build_delays_tab` |
| **DebugTab** | See groups below. | `_build_debug_tab` |

**MainTab groups**

| Name | Header | Contents |
|---|---|---|
| **ConnectionGroup** | `CONNECTION` | Private server link field + **JoinButton**. |
| **MacroGroup** | `MACRO` | Challenges **ToggleSwitch** + **HardModeToggle** (Story only). |

Keybinds are stored in `settings.json` under `keybinds` (`config/keybinds.py`),
polled in `MainWindow._poll_hotkeys`, and shown as the titlebar **HintPills**.
Defaults: Start/Stop = F1, Reload = F3, Open Macro Tester = Ctrl+T.

**DebugTab groups**

| Name | Header | Contents |
|---|---|---|
| **MacroTestingGroup** | `MACRO TESTING` | **OpenTesterButton** — opens the MacroTesterWindow. |

### MacroTesterWindow
Separate always-on-top window for running one macro step at a time. All testing
tools live here, including the image tester.

| Name | What it is | File |
|---|---|---|
| **TesterHeader** | "Macro Tester" + subtitle. | `ui/macro_tester.py` |
| **TestList** | Scrollable, grouped list. | `MacroTesterWindow` |
| **CoordsCard** | `COORDS` group: **PickCoordsButton** (arm, then click the Roblox area) + **CopyButton**. Reports the clicked point as Roblox client X/Y. | `_build_coords` |
| **ImageTesterCard** | Lives under the `VISION` group: current image path + **SelectImageButton** + **TestSearchButton** + inline PASS/FAIL. Single source of image-search testing. | `_build_image_tester` |
| **TestRow** | One check: name + description + **ResultLabel** (PASS/FAIL) + **TestButton**. | `TestRow` |
| **TestLog** | Log of every test result + **ClearLogButton**. | `MacroTesterWindow` |

Test groups (top to bottom): `COORDS`, `VISION` (image tester), `ENVIRONMENT`,
`LOBBY MACRO`, `MATCH MACRO`.

**LOBBY MACRO steps** (in `macro/lobby.py` → `LobbyNavigator`):
- `Find Play` — locate `images/lobby/play.png` (no click).
- `Click Play` — find + click Play.
- `Open gamemode` — find + click the selected gamemode's card.
- `Select stage` — scroll (wheel-down) searching for the stage image, then click.
- `Select act` — click the selected act at its fixed coordinate.
- `Start stage` — Hard Mode click (if on) -> confirm -> Start -> wait the join delay.
- `Full: Play -> mode -> stage -> act -> start` — the whole chain, then starts.

Uses the current gamemode (falls back to Story) and the Run page's selected Map
(falls back to the gamemode's first map). Image search runs over the real Roblox
client rect; clicks/scrolls go through AHK at screen coordinates.
Add a case by appending to `MainWindow._build_tests()` — a tuple of
`(group, name, description, fn)` where `fn` returns `(ok, message)`.

---

## Reusable pieces

| Name | What it is | File |
|---|---|---|
| **SectionBox** | The bordered, rounded container used by RunStrip cards, ChipsCard, DetailCard. | `ui/theme.py` → `QFrame#sectionBox` |
| **GroupHeader** | Small uppercase caption + horizontal rule (e.g. `BASIC`, `ACTIONS`). | `_group()` |
| **FieldLabel** | Tiny uppercase label above an input. | `QLabel#fieldLabel` |
| **Pill** | Fixed-height fully-rounded label/button (VersionPill, HintPills, UpgradeBadge, SizePill). | `ui/theme.py` |
| **ToggleSwitch** | Animated on/off switch. | `ui/widgets.py` |
| **HoverGlow** | Animated glow on hover/selection. | `ui/glow.py` |

---

## Layout budget

Changing one of these means changing the others. All in `ui/theme.py`.

```
WINDOW_HEIGHT (886) - TITLEBAR_HEIGHT (40) - 18px body margins = 828 available
  Viewport widget (638 + 12 frame inset) = 650
+ 12 spacing
+ STRIP_HEIGHT (166)
= 828   ← exact fit
```

So: **grow the Viewport or the RunStrip and `WINDOW_HEIGHT` must grow with it.**
Width: `RAIL_WIDTH` (78) + Viewport (828) + `PANEL_MIN_WIDTH` (400) + margins.

---

## How to phrase a request

- "Make the **UpgradeBadge** bigger" → the `+N` pill on each StepChip.
- "The **ActionsCard** buttons are too tall" → Save/Import/Reset in the RunStrip.
- "Move **StatusLine** back into the **ConfigCard**" → unambiguous.
- "**CoordsBar** should have a Copy button" → the pinned bottom row of DetailCard.
- "**ModeCard** hover is too subtle" → SelectorScreen cards.

Pattern that works well: **\<Name\> + what's wrong + what you want.**
