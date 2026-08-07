---
inclusion: always
---

# Coding Standards

Non-negotiable for every change. `HANDOFF.md` is frozen and no longer maintained — anything
durable from it lives here.

## What this project is

A **Windows-only** desktop macro for the Roblox game *Anime Expedition*. It shows the live
Roblox window inside its own UI, image-matches that view, and drives the game. Win32
throughout: there is no cross-platform path to keep in sync.

**Python 3.14 + PySide6** UI · **ctypes** to Win32 (`core/win32/`) · **OpenCV headless +
mss** for template matching · **RapidOCR + onnxruntime** for the few strings no template can
cover · **AutoHotkey v2** for all output. Python decides *what* to do and hands AHK a v2
script to click/press/scroll (`core/ahk.py`). Every entry in `requirements.txt` carries a
comment saying why that package and not the obvious alternative — read it before adding one.

**MIT** (`LICENSE`), so the licence restricts nobody — the product rules are ours to keep,
not the licence's to enforce: no paywall, no licence key, no telemetry. The only outbound
requests are the user's own Discord webhook (`core/webhook.py`) and the GitHub release check
(`core/updates.py`), both host-allowlisted. Keep licence and attribution notices intact
(e.g. `ponytail.md`'s MIT source).

## Stay outside the game — the ban surface

Everything the macro knows comes from **pixels on screen**; everything it does goes out as
**ordinary Windows input**. That boundary is the user's account safety and is not negotiable
for a feature, a speed-up or a reliability fix.

Never: inject code or load anything into Roblox · read/write its process memory · hook it
(`SetWindowsHookEx`, detours, remote threads) · `PostMessage`/`SendMessage` input at its
`HWND` · driver-level input emulators · touch, evade or fingerprint anti-cheat · exploit a
game bug · read or ship Roblox files, logs, cookies or `.ROBLOSECURITY` · Roblox fast flags.

Allowed, and only these: reading the window's *outside* (`FindWindow`, geometry,
`ClientToScreen`, `SetWindowPos`, and `OpenProcess` with
`PROCESS_QUERY_LIMITED_INFORMATION` for the exe name) · mss capture · OpenCV matching ·
`core/ocr.py` on fixed boxes · input through AHK v2. `macro/camera.py`'s `mouse_event`
DllCall is inside the boundary — the documented Win32 input API, needed because Roblox
recentres the cursor during a right-drag. `SetForegroundWindow` is activation, not input.

Timing counts too: prefer a verified screen transition over a blind volley of clicks.
A capability that needs more than pixels + OS input doesn't get built — say so.

The tree has been audited clean of every forbidden call; don't redo that grep unless new
Win32 lands.

## Calibration is load-bearing

Three constants hold the macro together, and breaking one fails *plausibly* rather than
loudly:

- **Viewport pinned 1152×756** (`ui/theme.py::VIEWPORT_WIDTH/HEIGHT`). Every coordinate in
  `content/`, every box in `settings.json`, every PNG in `images/`, all of `configs/` and
  `routes.json` was captured at that size; changing it invalidates all of them. Keep
  `WINDOW_WIDTH/HEIGHT` equal to the layout's measured `minimumSizeHint`. Re-capture through
  Settings > Vision.
- **DPI off, display scaling 100%** — `QT_ENABLE_HIGHDPI_SCALING=0`, `QT_SCALE_FACTOR=1`, set
  before `QApplication`. At 125% a template cropped at 100% scores as a different image
  (measured best match **0.80×**), and Roblox is separately blurry above 100% — a known
  Roblox regression, so the fix is environmental. `core/win32/display.py` warns.
- **Input timing is a frame count wearing milliseconds.** Roblox acts on the last mouse-move
  it *processed*, one per rendered frame, so a settle tuned at 165Hz covers 2.75× fewer
  frames at 60Hz and the click lands on a stale position. Timings scale from
  `display.py`; never hard-code a settle that assumes one monitor. Placement coordinates are
  also tied to `camera.PITCH_DELTA` — retuning the pitch invalidates all of them.

`cv2.matchTemplate` is **not scale invariant**: a wrong-size crop can never match, and it
fails intermittently, which reads as a tolerance problem. Wrong scale costs 0.253
correlation; bit depth is a red herring (256 colours costs 0.0003). Never crop a template
from Roblox's own screenshot — it multiplies by the display scale.

## Data, not code

Content and timing are **tables**; add a row, not a branch. The Run selectors, the navigator
and `configs/` paths all derive from them, so one edit ripples consistently.

- **Gamemode / map / target** → `content/gamemodes.py` (`GAMEMODES`, `maps_for`,
  `has_targets`, `selection_complete`).
- **Act coordinates** → `content/acts.py`. **Start sequence** (hard mode, confirm, start,
  Expedition's cycling difficulty) → `content/start_stage.py`.
- **Navigation images** → `content/nav_images.py`; PNGs in `images/` per its README.
- **Challenge panel geometry** → `content/challenge.py`. **Walk presets** →
  `content/start_position.py`. **Events routes** → `content/nav_route.py` (`NavStep` kinds:
  click, find, expect, scroll, wait), authored by the user into `routes.json`.
- **Delays** → `config/delays.py` (`DELAY_SPEC`). One entry is the whole change: the Delays
  tab builds itself from the spec and both `apply_delays` implementations read it by key.
- **Keybinds** → `config/keybinds.py`, polled in `MainWindow._poll_hotkeys`.

**Read the accessor, never the table.** Measured numbers are user-overridable at runtime —
`settings.json` holds `points`, `regions` and `confidence`, applied at startup and on every
edit through `apply_point_overrides` / `apply_region_overrides` /
`apply_confidence_overrides`. Call `act_coord(...)`, `start_coords(...)`,
`difficulty_coord(...)`; reading `ACT_COORDS` directly ignores the user's calibration and
reintroduces the bug the override exists to fix. A new table of measured numbers gets a
`*_key()`, an accessor and a `*_specs()` for the Vision editor.

**A stored value overrides its default**, so lowering a default does nothing for a user who
has already touched that field. Say that instead of claiming the run got faster.

### Waiting

- **A deadline search replaces a fixed sleep, it doesn't follow one.**
  `LobbyNavigator._find(path, timeout=…)` polls and returns the instant the screen appears,
  so the step before it takes no settle (`_nav_step(..., settle=False)`). Sleeping in front
  of a search is pure latency, paid every run.
- Never wait by attempt count, and never act on a screen before the search proving it is up
  has succeeded.
- `image_search_cooldown` is only for a click whose result *cannot* be verified — a fixed
  coordinate or a scroll.
- **A search proves an element is drawn, not that it is interactive.** Normalized
  correlation ignores a uniform brightness scale, so a panel at 40% opacity mid-fade still
  scores ~0.96 and the click is swallowed. An element arriving from a transition we just
  triggered needs `fade_wait`; no threshold can see the fade.
- **Sleep between actions, never after the last one.** A trailing `Sleep` in a generated AHK
  script only delays `ExitApp` while Python already waits on the process. Guard repeat gaps
  with `if (A_Index > 1)`. An AHK timeout must cover the script's own sleeps.

## Roblox window embedding (hard-won)

Roblox stays its **own top-level window** — never reparented. Our window is frameless +
always-on-top and opaque; we punch a **hole** with `QWidget.setMask` (rounded window rect
minus the viewport) so rendering and hit-testing fall through, and move Roblox behind it with
`SetWindowPos` (`roblox_window.py::position_window_to_client_rect`).

- Guard every position/mask sync with `IsIconic`: a minimized window reports coords near
  −32000 and flings Roblox off-screen.
- Resolve the client origin with `ClientToScreen`, not Qt geometry.
- Punch the hole only while the viewport is shown and Roblox attached, or it exposes the
  desktop.
- The window opens centred on the **primary** screen; a shorter secondary would clip it.

**Dead ends — measured, do not retry:** reparenting via `SetParent` (DPI/focus flakiness,
child dies with parent) · colour-key transparency `LWA_COLORKEY` · the Tauri 2 / WebView2
stack (DirectComposition can't host the window) · process DPI-awareness variants (byte-
identical rects) · runtime multi-scale matching (~24× cost, and it hides bad templates) ·
`RegionMemory`/`image_regions.json` auto-learned regions · the OCR-template fallback
(`core/text_locate.py`) · per-gamemode stage search regions (`STAGE_SEARCH_REGIONS`:
hand-measured, stale after any resize, and a band shorter than its template can't match) ·
a **global** match-tolerance setting (drifted to 0.57 and matched wrong screens; tolerance is
per-template now — `DEFAULT_CONFIDENCE` 0.70, bounds `CONFIDENCE_USER_MIN`/`CONFIDENCE_MAX`,
no auto-calibrate).

## Python / PySide6

- **AHK owns synthetic input.** Python never moves the mouse or presses a key via Win32; it
  renders a script with `macro/input_scripts.py` and runs it through `AhkBridge`.
  `wait=False` for long fire-and-forget sequences, `wait=True` for short verifiable actions.
- **Every click goes through the nudge** (`nudge_click_script`): glide on and wiggle before
  clicking. Roblox ignores a click that arrives with no hover event — tested without it, it
  doesn't work. Lobby clicks also retreat (`park=`) so a lingering hover can't draw a tooltip
  over the button the next search needs.
- **Never press a key at a screen you haven't verified.** `UnitPlacer` matches
  `images/match/unit_ui.png` before acting on a placed unit; without it a missed click sends
  `r`/`t`/`x` into the world and still looks like a working macro.
- **Never block the UI thread.** AHK `wait=True`, sleeps, capture and OCR go on a worker
  (`QThreadPool`). Marshal results and *all* widget/dialog work back with a queued signal;
  keep a reference to a running `QRunnable` or its signal is lost to GC. No
  `QTimer.singleShot` on a pool worker — no event loop there, so it never fires. Never put
  `runner.tick()` in `_poll_hotkeys`; that 40ms timer is the UI thread.
- **Stopping is cooperative.** F1/F2 set `request_stop()`; poll loops abandon their wait, the
  driver ends the run between steps. **Never kill an AHK process** — the camera script holds
  `i` and the right button down and a kill never releases them.
- **Keep decision logic pure.** `macro/tasks.py` decides what to play next with no capture,
  no clicking, no Qt. New rules go there, not into the runner.
- **Win32 behind typed helpers** in `core/win32/`, never raw `ctypes` in UI/macro code.
  Declare argtypes/restypes in `bindings.py` so a wrong pointer type fails loudly (the
  `LP_POINT` lesson). Read state back where a call can silently no-op.
- **No bare `except`.** Catch specific errors; message as `f"Failed to X: {exc}"`. A silently
  swallowed failure surfaces as the wrong diagnosis two steps later.
- **OCR reads are approximate** — `start_game.png` comes back "Start Ge". Never require an
  exact string: match a closed set (`challenge.match_map_name`) or parse digits with the
  usual confusions folded in, and use the returned confidence to spot a weak read.
- `image_search.to_absolute_path` passes an absolute path through **on purpose** (the Macro
  Tester's file dialog). Don't "harden" it.

## Qt UI

- Pages in `ui/pages/`, reusable widgets and editors in `ui/`. One class per concern.
- **Qt layouts**, not absolute placement. Fixed sizes only where a real constraint demands
  it (the viewport, the window).
- **Centralised QSS** in `theme.py`; prefer `objectName` + a rule over inline
  `setStyleSheet`, which is for one-off dynamic state (a status colour).
- **Control widths are measured, not guessed** — a widget in a narrow row clips silently. For
  a `QPushButton`/`QComboBox`, `sizeHint().width() > width()` is a real clipping test. For a
  `QLineEdit`/`QSpinBox` the hint is a meaningless ~110px default: measure
  `fontMetrics().horizontalAdvance(text)` against the field. Spin arrows cost ~16px, so hide
  them on a narrow field.
- **Widget visibility can't answer a data question**: everything on a non-current
  `QStackedWidget` page reports not-visible. Track it as data.
- Feedback in a scrolled panel belongs at the **top**, or it sits below the fold.
- **Icons**: rail icons are vector-drawn (`RailIcon`); other glyphs use **Segoe Fluent
  Icons** (`ui/icons.py`), which ships with Windows. No emoji as interactive affordances.
- Coordinates are **picked, not typed** — `RegionOverlay` is translucent, so the user clicks
  through to the live window and it returns client-space numbers. Reuse it.
- External and deep links go through `QDesktopServices.openUrl`.

## Naming

| Context | Convention | Example |
|---|---|---|
| fn / var | snake_case | `find_roblox_window` |
| class | PascalCase | `LobbyNavigator` |
| constant | SCREAMING_SNAKE | `VIEWPORT_WIDTH` |
| module | snake_case | `nav_images.py` |
| Qt signal | camelCase | `gamemodeChosen` |
| Qt objectName / QSS | camelCase / kebab | `stepChip`, `--color-violet` |
| JSON | PascalCase inside records, snake_case top-level keys | `{"Kind": "target"}`, `start_position` |

## Parallel surfaces

Change one, the others usually need it too:

| Group | Surfaces |
|---|---|
| **Gamemode schema** | `content/gamemodes.py` ↔ Run/selector UI ↔ `configs/` paths ↔ `nav_images.py` ↔ Tasks validation |
| **Measured numbers** | a `content/` table ↔ its `*_key`/accessor/`*_specs` ↔ `config/regions.py` ↔ the Vision row |
| **Config formats** | `config/` readers/writers ↔ JSON in `configs/`, `routes.json`, `images/`, `settings.json` |
| **Settings** | store + a Settings control + `MainWindow` wire-up + where it's read |
| **Delays** | one `DELAY_SPEC` entry ↔ `LobbyNavigator.apply_delays` ↔ `UnitPlacer.apply_delays` |
| **Viewport size** | invalidates every coordinate, template, `configs/` file and route |
| **Threading** | anything that clicks, sleeps, captures or OCRs runs off the UI thread |

## Security, data, performance

- **Everything outside the app is untrusted** — matched pixels, OCR text, JSON on disk, the
  private-server link, window titles. Validate type and range before a value reaches logic,
  a path, a numpy slice or an AHK script.
- **Reject, don't repair.** A box the app silently reshaped reads the wrong pixels and looks
  like an OCR fault — the exact failure the feature exists to prevent
  (`config/regions.py::clean_box`). Drop invalid entries rather than refusing to start.
- **Validate anything that becomes a path or a script**: `unit_configs.safe_component`,
  `nav_routes.clean_name`, `nav_route.safe_rel_path`, `keybinds.sanitize_game_key`,
  `start_position.MOVE_KEYS`. Whitelists and rejections, not escapes — an AHK string is code.
- **No secret in the tree or the log.** The private-server link and webhook URL live in the
  gitignored `settings.json`; never ship, print or example one. The webhook POSTs only to
  `core/webhook.py::ALLOWED_HOSTS`.
- **On-disk formats are stable.** `configs/`, `routes.json`, `images/`, `settings.json` all
  hold user data: readers default missing keys and preserve unknown ones, and
  `store.update_json` takes one lock across read and write because several stores share the
  file and the macro worker writes stats mid-run. A shape change that can't be defaulted
  needs a one-time migration preserving the old intent
  (`TaskStore.take_legacy_challenge_slot`). Known limits: that lock is per-process, so two
  app instances still race, and `routes.json` is rewritten whole with no backup.
- **Bound anything that grows** — log panels cap lines, the template cache keys on mtime, an
  upload is capped before Discord rejects it.
- **Keep the UI responsive**: capture/matching/OCR/AHK off the render thread, timers bounded
  per tick, and a courtesy feature (the webhook) never stalls a run.
- AHK v2 gotcha: `FileDelete` on a missing file throws and hangs the script behind a dialog.
  Use `FileOpen(path, "w")`.
