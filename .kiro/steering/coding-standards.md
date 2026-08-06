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

Stack: **Python + PySide6 (Qt)** for the UI, **ctypes** to the Win32 API
(`sloppykeys/core/win32/`) for finding/positioning the Roblox window and reading
its client rect, **OpenCV + mss** for template matching against captured pixels,
and **AutoHotkey v2** for mouse/keyboard output. AHK owns all synthetic input —
Python decides *what* to do (position windows, capture/match pixels, pick
coordinates) then hands AHK a v2 script to click/press/scroll (`core/ahk.py`).

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
- Capturing pixels with mss and matching with OpenCV.
- Input through AutoHotkey v2 at the OS level, which is what a physical mouse and
  keyboard produce. `macro/camera.py`'s `mouse_event` DllCall is inside that
  boundary: it's the documented Win32 input API, used because Roblox recentres the
  cursor during a right-drag.

Timing is part of this too: prefer a verified screen transition over a blind
volley of clicks. A run that watches the game and reacts looks like a player; a
run that machine-guns fixed coordinates does not.

New capability that seems to need more than pixels + OS input? The answer is no —
say so and find a pixel-and-input way, or leave the feature out.

## Adding content & tuning (data-driven)

Content and timing are data, not code — add to the table, not the logic. Within
blast radius: the UI selectors, the navigator, and `configs/` paths all read from
these, so a change ripples to all three consistently.

- **Gamemode / map / stage** → `content/gamemodes.py` (`GAMEMODES`). The Run
  selectors, `configs/<Gamemode>/<Map>/<Act>.json` paths, and expected image paths
  all derive from this.
- **Act coordinates** (fixed-position acts, e.g. Story) → `content/acts.py`
  (`ACT_COORDS[gamemode][act] = (client_x, client_y)`).
- **Start-stage sequence** (hard-mode/confirm/start clicks) →
  `content/start_stage.py` (`START_COORDS[gamemode]`).
- **Navigation images + search regions** → `content/nav_images.py`. Filenames are
  slugs derived from the schema; drop PNGs into `images/` per its README. Scope a
  search with `STAGE_SEARCH_REGIONS[gamemode] = (x, y, w, h)` (client space) so
  matching is faster and can't false-hit elsewhere.
- **Delays** → `config/delays.py` (`DELAY_SPEC`), edited live in Settings > Delays.
  A stored value in `settings.json` **overrides the default**, so lowering a default
  does nothing for a user who has already touched that field — say so instead of
  claiming the change made their run faster.
  Values are stored in `settings.json` and applied via `LobbyNavigator.apply_delays`
  / `UnitPlacer.apply_delays` (each takes the whole delays dict). Add a tunable by
  adding one `DELAY_SPEC` entry — the Delays tab builds itself from it and
  `apply_delays` reads it by key.
- **Waiting for a screen** → `LobbyNavigator._find(path, timeout=...)` polls until a
  deadline. Never wait by attempt count, and never act on a screen (scroll, click a
  fixed coordinate) before the search that proves it is up has succeeded.
- **A deadline search replaces a fixed sleep, it doesn't follow one.** If the next
  step begins with an image search, the step before it takes no settle
  (`_nav_step(..., settle=False)`): the search already polls until the screen
  appears and returns the instant it does. A blind wait
  (`image_search_cooldown`) is only for a click whose result *cannot* be verified —
  a fixed coordinate click or a scroll. Sleeping "to be safe" in front of a search
  is pure latency, paid on every run.
- **Sleep between actions, never after the last one.** A `Sleep` at the end of a
  generated AHK script only delays `ExitApp`, and Python is already waiting on the
  process; the same goes for a gap inside a `Loop` that runs once. Guard repeat
  gaps with `if (A_Index > 1)`.
- **Keybinds** → `config/keybinds.py` (`ACTIONS`, `DEFAULTS`), edited in
  Settings > Keybinds, polled in `MainWindow._poll_hotkeys`.

Coordinates/regions are captured with the Macro Tester's COORDS tools at the pinned
800×599 client size, so they only stay valid at that size.

## Project Structure

```
SloppyKeys/
├── main.py                     # launcher (calls sloppykeys.ui.window.run)
├── sloppykeys/
│   ├── __main__.py             # python -m sloppykeys
│   ├── content/                # DATA: gamemodes, acts, start_stage, nav_images, units
│   ├── config/                 # settings, store, unit_configs, keybinds, delays
│   ├── core/
│   │   ├── image_search.py     # capture (mss) + template match (cv2)
│   │   ├── ahk.py              # AutoHotkey v2 bridge (runs generated .ahk scripts)
│   │   └── win32/              # bindings.py, roblox_window.py, frameless.py (ctypes)
│   ├── macro/                  # runner, challenge, camera, lobby (LobbyNavigator)
│   └── ui/
│       ├── window.py           # MainWindow: titlebar + rail + pages + hotkeys + services
│       ├── viewport.py         # RobloxViewport (hole/mask + position Roblox behind)
│       ├── theme.py            # palette + global QSS + sizes
│       ├── widgets.py glow.py icons.py macro_tester.py
│       └── pages/              # run_page, units_page, settings_page, selector_page
├── configs/                    # saved unit configs — <Gamemode>/<Map>/<Act>.json
├── images/                     # search templates (lobby/gamemodes/stages) + images.json
└── settings.json               # private server link, run_challenges, hard_mode, keybinds, delays
```

Data files (`configs/`, `images/`, `settings.json`) are plain JSON and their
formats are **stable** — never break a format that has saved user data; readers
that add keys must default them (see `AppSettings`, which merges defaults so
unknown keys are preserved).

## Roblox Window Embedding (hard-won — read before touching windowing)

Roblox stays its **own top-level window**; we never reparent it (a child dies with
its parent, and reparenting was flaky). Instead:

- Our window is **frameless + always-on-top** (`FramelessWindowHint |
  WindowStaysOnTopHint`), opaque, fixed size.
- We punch a **hole** in our window with `QWidget.setMask` = rounded window rect
  **minus** the viewport rect (`window.py::_apply_window_mask`). A mask physically
  removes pixels, so both rendering and mouse hit-testing fall through to Roblox.
- Roblox is **moved behind the hole** with `SetWindowPos` so its client area lands
  exactly on the viewport (`core/win32/roblox_window.py::position_window_to_client_rect`).
- **DPI is disabled** (`QT_ENABLE_HIGHDPI_SCALING=0`, `QT_SCALE_FACTOR=1`) so 1
  logical px = 1 physical px. This is why the fixed window math works and why
  captured coordinates are stable. The viewport is pinned **800×599**.

Dead ends already paid for — do not retry:

- **Reparenting Roblox (`SetParent` into our widget)** — DPI/focus flakiness and
  the child-dies-with-parent hazard. Position-behind-a-hole is the chosen way.
- **Colour-key transparency (`LWA_COLORKEY`)** — worked in the old CustomTkinter
  build (GDI paints), but it's fragile and unnecessary now; the region mask is the
  documented technique.
- **The abandoned Tauri 2 / React / Rust stack** — WebView2 renders via
  DirectComposition, so it could not host the Roblox window (no color key, region
  fought the compositor). The app is Python/PySide6; ignore any Tauri references.

Other gotchas:

- Guard every position/mask sync against `IsIconic`: a minimized window reports
  client coords near −32000, flinging Roblox off-screen (looks like the app hid it).
- Resolve the client origin with `ClientToScreen` in `core/win32`, not Qt geometry.
- Punch the hole only while the viewport is shown and Roblox attached — otherwise
  it exposes the desktop. `RobloxViewport` clears the mask on hide.
- The window opens centred on the **primary** screen (a shorter secondary monitor
  would clip the fixed height).

## Python / PySide6 Rules

- **AHK owns synthetic input.** Python never moves the mouse or presses keys via
  Win32; it builds a v2 script (`macro/camera.py`, `macro/lobby.py`) and runs it
  through `AhkBridge`. `wait=False` for long fire-and-forget sequences (don't
  freeze the UI); `wait=True` for short, verifiable actions.
- **Never block the UI thread.** Anything that calls AHK `wait=True` or sleeps
  (macro steps, image search) runs on a worker (see the Macro Tester's
  `QThreadPool`). Marshal results and any widget/dialog work back to the UI thread
  (signals, or `QThread.currentThread()` check). Keep a reference to a running
  `QRunnable` or its signal is lost to GC.
- **Win32 lives behind typed helpers** in `core/win32/`, never raw `ctypes` calls
  scattered through UI/macro code. Declare argtypes/restypes in `bindings.py` so
  wrong pointer types fail loudly (the `LP_POINT` lesson).
- **Verify a Win32 call took effect** where it can silently no-op; read state back.
- **No bare `except`** that hides bugs; catch specific errors. Descriptive
  messages: `f"Failed to X: {exc}"`.
- **Image search** captures the real Roblox client rect and matches templates
  cropped at 800×599. A search region (`SearchRegion`) speeds matching and avoids
  false hits; a template taller than its region never matches.

## Qt UI Rules

- Pages live in `ui/pages/` (one page per file), reusable widgets in `ui/`
  (`widgets.py`, `viewport.py`, `macro_tester.py`). One widget/class per concern.
- **Layout is Qt layouts** (`QVBoxLayout`/`QHBoxLayout`/`QGridLayout`), not
  absolute pixel placement — that flexibility is why we left the old UI. Fixed
  sizes only where a real constraint demands it (the 800×599 viewport, the window).
- **Styling is centralised QSS** in `theme.py` (`stylesheet()` + palette
  constants). Prefer `objectName` + a QSS rule over per-widget inline styles;
  inline `setStyleSheet` is fine for one-off dynamic states (status colour).
- **Icons**: the rail icons are vector-drawn (`RailIcon`); other glyphs use the
  **Segoe Fluent Icons** font (`ui/icons.py`) — Windows-only app, the font ships
  with the OS. No emoji as interactive affordances.
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

## Parallel Surfaces

Change one, the others usually need it too. Locate every surface before "done":

| Group | Surfaces |
|-------|----------|
| **Gamemode schema** | `content/gamemodes.py` ↔ Run/selector UI ↔ `configs/` path generation ↔ `nav_images.py` expected paths. Add a gamemode = data edit. |
| **Config formats** | `config/` readers/writers ↔ on-disk JSON in `configs/`, `images/`, `settings.json`. Never break saved data. |
| **Settings surface** | a new setting = `AppSettings`/`config` store + a Settings-page control + wire-up in `MainWindow`. |
| **Nav coordinates** | coords/regions in `content/` are captured at 800×599; changing the viewport size invalidates them. |
| **Threading** | anything that clicks/sleeps runs off the UI thread; results and dialogs marshal back. |

## Security & Performance

- **Treat everything outside the app as untrusted** — matched pixels, files on
  disk, the private-server link, window titles. Validate type/range before it
  flows into logic, a path, or an AHK script.
- **Validate at the boundary before building a path** — a config name that becomes
  a file path must reject `..` and separators (`config/unit_configs.py`).
- **Never put a secret in the tree or the log** — the private server link and the
  Discord webhook URL live in the user's `settings.json`, which is gitignored.
  Don't add a secret to a file that ships, don't print one (`window.py`'s webhook
  handlers log status, never the URL), and don't include one in an example.
- **Bound anything that grows** — the log panels cap their line count; the template
  cache keys on mtime. A long session must not balloon memory.
- **Keep the UI responsive** — capture/matching/AHK stay off the render thread;
  timers do bounded work per tick.

## Things That Are Never Acceptable

- Anything from "Stay Outside The Game": injection, process memory, hooks,
  `PostMessage` input, anti-cheat evasion.
- Committing or logging a secret — webhook URL, private server link, user logs.
- Moving the mouse / pressing keys from Python directly instead of via AHK.
- Blocking the UI thread on an AHK `wait=True` call or a `sleep`.
- Touching a Qt widget (or creating a dialog) from a worker thread.
- Breaking a `configs/` / `images/` / `settings.json` format with saved data.
- Emoji/unicode glyphs as interactive UI icons.
- Retrying a documented dead end from "Roblox Window Embedding".
- Raw scattered `ctypes` calls instead of typed `core/win32` helpers.
- Asserting a cause for a visual bug nobody has looked at (see
  `implementation-process.md` — the user is the sensor).
- Adding a dependency without checking an installed one already covers it.
- Rewriting code that already does what the task needs (see `implementation-process.md` §5).
- Verifying or writing checks for code the change didn't touch, unasked.
- Reporting done when `HANDOFF.md` still describes the old reality.
