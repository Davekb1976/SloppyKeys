---
inclusion: always
---

# Coding Standards

These rules apply to every change in this project. They are non-negotiable.

## What This Project Is

SloppyKeys is a **Windows-only** desktop macro for the Roblox game *Anime
Expedition*. The app shows the live Roblox window inside its own UI, image-matches
against that view, and drives the game. It is **not** cross-platform: it depends on
Win32, so there is no Linux/macOS path to keep in sync.

Stack — **Python 3.14 + PySide6 (Qt)** for the UI, **ctypes** to the Win32 API
(`sloppykeys/core/win32/`) for finding/positioning the Roblox window and reading its
client rect, **OpenCV (headless) + mss** for template matching against captured
pixels, **RapidOCR + onnxruntime** for the few strings no template can cover, and
**AutoHotkey v2** for mouse/keyboard output. Python decides *what* to do (position
windows, capture/match pixels, pick coordinates) and hands AHK a v2 script to
click/press/scroll (`core/ahk.py`). Deps are in `requirements.txt`, each with a
comment saying why that package and not the obvious alternative — read it before
adding one.

The project is **noncommercial**: no paywalls, licence keys, telemetry or resale.
Keep existing licences and attribution notices intact (e.g. `ponytail.md`'s MIT
source).

## Stay Outside The Game — The Ban Surface

Everything the macro knows comes from **pixels on screen**, and everything it does
goes out as **ordinary Windows input**. That boundary is the whole safety story for
the user's account, and it is not negotiable for a feature, a speed-up, or a
reliability fix.

Never, for any reason:

- Inject code into Roblox, or load anything into its process.
- Read or write Roblox process memory (`ReadProcessMemory`/`WriteProcessMemory`,
  handle scanning, pointer chasing).
- Hook the game — no `SetWindowsHookEx`, no API/DLL detours, no remote threads.
- Send input into the process behind its back: no `PostMessage`/`SendMessage`
  synthetic clicks or keys at Roblox's `HWND`, no driver-level input emulators.
- Touch, disable, evade or fingerprint anti-cheat, or exploit a game bug.
- Read or ship Roblox files, logs, cookies, or the `.ROBLOSECURITY` cookie.

Allowed, and the only things allowed:

- Reading the window's *outside*: `FindWindow`/geometry/`ClientToScreen`, and
  `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` to confirm the exe name
  (`core/win32/roblox_window.py::get_process_exe_name`) — query only, never a read
  or write of memory.
- Capturing pixels with mss, matching with OpenCV, reading fixed boxes with
  `core/ocr.py`.
- Input through AutoHotkey v2 at the OS level, which is what a physical mouse and
  keyboard produce. `macro/camera.py`'s `mouse_event` DllCall is inside that
  boundary: it's the documented Win32 input API, used because Roblox recentres the
  cursor during a right-drag.

Timing is part of this too: prefer a verified screen transition over a blind volley
of clicks. A run that watches the game and reacts looks like a player; a run that
machine-guns fixed coordinates does not.

New capability that seems to need more than pixels + OS input? The answer is no —
say so and find a pixel-and-input way, or leave the feature out.

## Calibration Is Load-Bearing

The whole macro is calibrated against one screen geometry. Three constants hold it
together, and breaking any of them fails *plausibly* rather than loudly:

- **The viewport is pinned 1152×756** (`ui/theme.py::VIEWPORT_WIDTH/HEIGHT`).
  Every coordinate in `content/`, every box in `settings.json`, every PNG in
  `images/`, all of `configs/` and `routes.json` were captured at that size.
  Changing those two numbers invalidates all of it — templates then match at the
  wrong scale (`cv2.matchTemplate` is not scale invariant) and clicks land on the
  neighbouring element. Re-capture through Settings > Vision.
- **DPI is off and display scaling must be 100%** — `QT_ENABLE_HIGHDPI_SCALING=0`,
  `QT_SCALE_FACTOR=1`, set before `QApplication` in `ui/window.py::run`. At 125% a
  template cropped at 100% scores as the wrong image (measured best match at
  **0.80×**). See `core/win32/display.py`.
- **Input timing is a frame count wearing milliseconds.** Roblox acts on the last
  mouse-move it has *processed*, one per rendered frame, so a settle tuned on a
  165Hz panel covers 2.75× fewer frames at 60Hz and the click lands on a stale
  cursor position. Timings scale by refresh rate via `core/win32/display.py`;
  never hard-code a settle that assumes one monitor.

Never state that a coordinate, template or timing "should be fine" — measure it
(Settings > Vision has a Test button per row, the Macro Tester a VISION group).

## Data, Not Code

Content and timing are **tables**, not logic — add a row, don't add a branch. The
Run selectors, the navigator and `configs/` paths all derive from these, so one data
edit ripples consistently.

- **Gamemode / map / target** → `content/gamemodes.py` (`GAMEMODES`, `maps_for`,
  `has_targets`, `selection_complete`). Adding a gamemode is a data edit.
- **Act coordinates** → `content/acts.py`. **Start-stage sequence** (hard mode,
  confirm, start, Expedition's cycling difficulty) → `content/start_stage.py`.
- **Navigation images** → `content/nav_images.py`; PNGs live in `images/` per its
  README, filenames are slugs derived from the schema. There is deliberately **no**
  stage search region any more (`STAGE_SEARCH_REGIONS` was removed: hand-measured
  per gamemode, silently stale after a viewport change, and a band shorter than the
  template makes the match impossible).
- **Challenge panel geometry** → `content/challenge.py` (OCR boxes, refill rules).
  **Start-position presets** (WASD holds) → `content/start_position.py`.
  **Events routes** → `content/nav_route.py` (`NavStep` kinds: click, find, expect,
  scroll, wait), saved by the user in `routes.json`.
- **Delays** → `config/delays.py` (`DELAY_SPEC`). One entry is the whole change: the
  Delays tab builds itself from the spec and `LobbyNavigator.apply_delays` /
  `UnitPlacer.apply_delays` read it by key. A stored value in `settings.json`
  **overrides the default**, so lowering a default does nothing for a user who has
  already touched that field — say so rather than claiming the run got faster.
- **Keybinds** → `config/keybinds.py` (`ACTIONS`, `DEFAULTS`), polled in
  `MainWindow._poll_hotkeys`.

### Read the accessor, never the table

Most `content/` tables are user-overridable at runtime: `settings.json` holds
`points` (act / start / difficulty clicks), `regions` (OCR boxes) and `confidence`
(per-template thresholds), applied at startup and on every edit through
`apply_point_overrides` / `apply_region_overrides` /
`apply_confidence_overrides`. Read `act_coord(...)`, `start_coords(...)`,
`region_for(...)` — reading `ACT_COORDS` directly ignores the user's calibration and
reintroduces the bug the override exists to fix. New table of measured numbers:
give it a `*_key()`, an accessor, and a `*_specs()` for the Vision editor.

### Waiting

- **A deadline search replaces a fixed sleep, it doesn't follow one.**
  `LobbyNavigator._find(path, timeout=...)` polls until a deadline and returns the
  instant the screen appears, so the step before it takes no settle
  (`_nav_step(..., settle=False)`). Sleeping "to be safe" in front of a search is
  pure latency, paid every run.
- Never wait by attempt count, and never act on a screen (scroll, click a fixed
  coordinate) before the search proving it is up has succeeded.
- `image_search_cooldown` is only for a click whose result *cannot* be verified — a
  fixed coordinate click, or a scroll.
- **Sleep between actions, never after the last one.** A trailing `Sleep` in a
  generated AHK script only delays `ExitApp` while Python is already waiting on the
  process; same for a gap inside a `Loop` that runs once. Guard repeat gaps with
  `if (A_Index > 1)`.

## Project Structure

```
SloppyKeys/
├── main.py                     # launcher (calls sloppykeys.ui.window.run)
├── sloppykeys/
│   ├── content/                # DATA: gamemodes, acts, start_stage, nav_images,
│   │                           #   challenge, nav_route, start_position, units
│   ├── config/                 # stores over settings.json / json files: settings,
│   │                           #   store, delays, keybinds, tasks, stats, regions,
│   │                           #   start_position, nav_routes, unit_configs
│   ├── core/
│   │   ├── image_search.py     # capture (mss) + template match (cv2) + confidence
│   │   ├── ocr.py              # RapidOCR on fixed boxes (approximate by design)
│   │   ├── ahk.py              # AutoHotkey v2 bridge (runs generated .ahk scripts)
│   │   ├── webhook.py          # Discord notifications (stdlib urllib, daemon thread)
│   │   └── win32/              # bindings, roblox_window, frameless, display (ctypes)
│   ├── macro/                  # runner, lobby (LobbyNavigator), placement (UnitPlacer),
│   │                           #   challenge, tasks (queue decisions), camera,
│   │                           #   input_scripts (AHK builders)
│   └── ui/
│       ├── window.py           # MainWindow: titlebar + rail + pages + hotkeys + services
│       ├── viewport.py         # RobloxViewport (hole/mask + position Roblox behind)
│       ├── theme.py            # palette + global QSS + sizes (VIEWPORT_WIDTH/HEIGHT)
│       ├── image_manager.py    # Settings > Vision: templates, OCR boxes, points
│       ├── macro_tester.py     # run one step in isolation; coord/region pickers
│       ├── placement_overlay.py position_editor.py route_editor.py
│       ├── sequence_editor.py task_editor.py widgets.py glow.py icons.py
│       └── pages/              # run_page, units_page, settings_page, selector_page,
│                               #   stats_page
├── configs/                    # unit plans — <Gamemode>/<Map>/<Target>.json, or
│                               #   <Gamemode>/<Map>.json when the mode has no target
├── images/                     # templates (lobby/gamemodes/stages/match) + images.json
├── routes.json                 # user-authored Events maps/acts + nav steps
└── settings.json               # private server link + webhook URL, tasks, delays,
                                #   keybinds, regions/points/confidence, stats  (gitignored)
```

Settings tabs, in order: **Main, Tasks, Route, Vision, Keybinds, Delays, Position,
Debug** (`ui/pages/settings_page.py::TABS`).

Data files (`configs/`, `routes.json`, `images/`, `settings.json`) are plain JSON and
their formats are **stable** — never break a format that has saved user data.
Readers default missing keys and preserve unknown ones (`AppSettings` merges
defaults; `store.update_json` takes one lock across read and write because several
stores share `settings.json` and the macro worker writes stats mid-run). A shape
change that *cannot* be defaulted needs a one-time migration that keeps the old
intent, like `TaskStore.take_legacy_challenge_slot`.

## Roblox Window Embedding (hard-won — read before touching windowing)

Roblox stays its **own top-level window**; we never reparent it (a child dies with
its parent, and reparenting was flaky). Instead:

- Our window is **frameless + always-on-top** (`FramelessWindowHint |
  WindowStaysOnTopHint`), opaque, fixed size.
- We punch a **hole** in our window with `QWidget.setMask` = rounded window rect
  **minus** the viewport rect (`window.py::_apply_window_mask`). A mask physically
  removes pixels, so both rendering and mouse hit-testing fall through to Roblox.
- Roblox is **moved behind the hole** with `SetWindowPos` so its client area lands
  exactly on the viewport
  (`core/win32/roblox_window.py::position_window_to_client_rect`).

Dead ends already paid for — do not retry:

- **Reparenting Roblox (`SetParent` into our widget)** — DPI/focus flakiness and the
  child-dies-with-parent hazard. Position-behind-a-hole is the chosen way.
- **Colour-key transparency (`LWA_COLORKEY`)** — worked in the old CustomTkinter
  build (GDI paints), but it's fragile and unnecessary; the region mask is the
  documented technique.
- **The abandoned Tauri 2 / React / Rust stack** — WebView2 renders via
  DirectComposition, so it could not host the Roblox window. The app is
  Python/PySide6; ignore any Tauri references.

Other gotchas:

- Guard every position/mask sync against `IsIconic`: a minimized window reports
  client coords near −32000, flinging Roblox off-screen (looks like the app hid it).
- Resolve the client origin with `ClientToScreen` in `core/win32`, not Qt geometry.
- Punch the hole only while the viewport is shown and Roblox attached — otherwise it
  exposes the desktop. `RobloxViewport` clears the mask on hide.
- The window opens centred on the **primary** screen (a shorter secondary monitor
  would clip the fixed height).

## Python / PySide6 Rules

- **AHK owns synthetic input.** Python never moves the mouse or presses keys via
  Win32; it renders a v2 script with `macro/input_scripts.py` and runs it through
  `AhkBridge`. `wait=False` for long fire-and-forget sequences (don't freeze the
  UI); `wait=True` for short, verifiable actions.
- **Every click goes through the nudge** (`nudge_click_script`): glide onto the
  target and wiggle before clicking. Roblox often ignores a click that arrives
  without a hover event, so a teleport-and-click is silently dropped. Tested
  without the wiggle — it doesn't work.
- **Never press a key at a screen you haven't verified.** `UnitPlacer` matches
  `images/match/unit_ui.png` before every action on a placed unit; without it a
  missed click sends `r`/`t`/`x` into the world and looks like a working macro.
- **Never block the UI thread.** Anything that calls AHK `wait=True`, sleeps, or
  runs capture/OCR goes on a worker (`QThreadPool`). Marshal results and all
  widget/dialog work back to the UI thread (signals, or a
  `QThread.currentThread()` check). Keep a reference to a running `QRunnable` or
  its signal is lost to GC.
- **Keep decision logic pure.** `macro/tasks.py` decides what to play next with no
  capture, no clicking and no Qt — that's what makes the rules checkable. New rules
  go there, not into the runner.
- **Win32 lives behind typed helpers** in `core/win32/`, never raw `ctypes` scattered
  through UI/macro code. Declare argtypes/restypes in `bindings.py` so a wrong
  pointer type fails loudly (the `LP_POINT` lesson).
- **Verify a Win32 call took effect** where it can silently no-op; read state back.
- **No bare `except`** that hides bugs; catch specific errors. Descriptive messages:
  `f"Failed to X: {exc}"`.
- **Image search** captures the real Roblox client rect and matches templates cropped
  at 1152×756. A `SearchRegion` speeds matching and avoids false hits, but a template
  taller than its region can never match. Per-template thresholds floor at
  `CONFIDENCE_USER_MIN` (0.60) — a global tolerance existed once, drifted to 0.57 and
  started matching the wrong screens.
- **OCR reads are approximate.** `start_game.png` comes back as "Start Ge". Never
  require an exact string: match against a closed set (`macro/challenge.py::
  match_map_name`) or parse digits with the usual confusions folded in, and use the
  returned confidence to tell a weak read from a clean one.

## Qt UI Rules

- Pages live in `ui/pages/` (one page per file), reusable widgets and editors in
  `ui/`. One widget/class per concern.
- **Layout is Qt layouts** (`QVBoxLayout`/`QHBoxLayout`/`QGridLayout`), not absolute
  pixel placement — that flexibility is why we left the old UI. Fixed sizes only
  where a real constraint demands it (the 1152×756 viewport, the window).
- **Styling is centralised QSS** in `theme.py` (`stylesheet()` + palette constants).
  Prefer `objectName` + a QSS rule over per-widget inline styles; inline
  `setStyleSheet` is fine for a one-off dynamic state (status colour).
- **Icons**: rail icons are vector-drawn (`RailIcon`); other glyphs use the **Segoe
  Fluent Icons** font (`ui/icons.py`) — Windows-only app, the font ships with the OS.
  No emoji as interactive affordances.
- **Coordinates are picked, not typed**: `RegionOverlay` is translucent, so the user
  clicks through to the live Roblox window and it returns client-space numbers with
  no conversion. Reuse it instead of adding another picker.
- **External links / deep links** go through `QDesktopServices.openUrl`.

## Naming Conventions

| Context | Convention | Example |
|---------|-----------|---------|
| fn / var | snake_case | `find_roblox_window`, `join_wait` |
| class | PascalCase | `LobbyNavigator`, `RobloxViewport` |
| constant | SCREAMING_SNAKE | `VIEWPORT_WIDTH`, `ACT_COORDS` |
| module file | snake_case | `nav_images.py`, `macro_tester.py` |
| Qt signal | camelCase (Qt convention) | `gamemodeChosen`, `delayChanged` |
| Qt objectName / QSS | camelCase / kebab | `stepChip`, `--color-violet` |
| settings.json key | PascalCase in records, snake_case for top-level keys | `{"Kind": "target"}`, `start_position` |

## Parallel Surfaces

Change one, the others usually need it too. Locate every surface before "done":

| Group | Surfaces |
|-------|----------|
| **Gamemode schema** | `content/gamemodes.py` ↔ Run/selector UI ↔ `configs/` path generation ↔ `nav_images.py` expected paths ↔ the Tasks queue's validation. |
| **Measured numbers** | a `content/` table ↔ its `*_key`/accessor/`*_specs` ↔ the `config/regions.py` store ↔ the Settings > Vision row. |
| **Config formats** | `config/` readers/writers ↔ on-disk JSON in `configs/`, `routes.json`, `images/`, `settings.json`. Never break saved data. |
| **Settings surface** | a new setting = `AppSettings`/store + a Settings-page control + wire-up in `MainWindow` + applied where it's read. |
| **Delays** | one `DELAY_SPEC` entry ↔ both `apply_delays` implementations (`LobbyNavigator`, `UnitPlacer`). |
| **Viewport size** | changing it invalidates every coordinate, template, `configs/` file and route. |
| **Threading** | anything that clicks, sleeps, captures or OCRs runs off the UI thread; results and dialogs marshal back. |

## Security & Performance

- **Treat everything outside the app as untrusted** — matched pixels, OCR text, JSON
  on disk, the private-server link, window titles. Validate type and range before a
  value flows into logic, a file path, a numpy slice or an AHK script.
- **Reject, don't repair.** A hand-edited box that the app silently reshaped would
  read the wrong pixels and look like an OCR fault — the exact failure the feature
  exists to fix (`config/regions.py::clean_box`). Drop invalid entries rather than
  refusing to start.
- **Validate at the boundary before building a path** — a display name that becomes a
  path segment goes through `unit_configs.safe_component` (rejects separators and
  `..`). Interpolating into a generated AHK script needs the same care: whitelist,
  as `content/start_position.py::MOVE_KEYS` does.
- **Never put a secret in the tree or the log** — the private server link and the
  Discord webhook URL live in the gitignored `settings.json`. Don't ship one, don't
  print one (`window.py`'s webhook handlers log status, never the URL), don't put one
  in an example. The webhook POSTs only to `core/webhook.py::ALLOWED_HOSTS`.
- **Bound anything that grows** — log panels cap their line count, the template cache
  keys on mtime, an upload is capped before Discord rejects it. A long session must
  not balloon memory.
- **Keep the UI responsive** — capture/matching/OCR/AHK stay off the render thread;
  timers do bounded work per tick. A courtesy feature (webhook) never stalls a run.

## Things That Are Never Acceptable

- Anything from "Stay Outside The Game": injection, process memory, hooks,
  `PostMessage` input, anti-cheat evasion.
- Committing or logging a secret — webhook URL, private server link, user logs.
- Moving the mouse / pressing keys from Python directly instead of via AHK, or
  clicking without the nudge.
- Blocking the UI thread on an AHK `wait=True` call, a `sleep`, or a capture.
- Touching a Qt widget (or creating a dialog) from a worker thread.
- Breaking a `configs/` / `routes.json` / `settings.json` format that has saved data.
- Reading a raw `content/` table where an override accessor exists.
- Hard-coding a coordinate, template scale or settle that assumes one viewport size,
  one display scaling or one refresh rate.
- Requiring an exact string from an OCR read.
- Emoji/unicode glyphs as interactive UI icons.
- Retrying a documented dead end from "Roblox Window Embedding".
- Raw scattered `ctypes` calls instead of typed `core/win32` helpers.
- Asserting a cause for a visual bug nobody has looked at (see
  `implementation-process.md` — the user is the sensor).
- Adding a dependency without checking an installed one already covers it.
- Rewriting code that already does what the task needs (see
  `implementation-process.md` §5).
- Verifying or writing checks for code the change didn't touch, unasked.
- Reporting done when `HANDOFF.md` still describes the old reality.
