---
inclusion: always
---
# Coding Standards

Non-negotiable for every change. `HANDOFF.md` is frozen; anything durable from it is here.

## What this project is

A **Windows-only** desktop macro for the Roblox game *Anime Expedition*: it shows the live Roblox
window inside its own UI, image-matches that view, and drives the game. Win32 throughout, no
cross-platform path.

**Python 3.14 + pywebview/WebView2** UI (`ui_web/`, `bridge.py` is the `js_api`) · **ctypes** to
Win32 (`core/win32/`) · **OpenCV headless + mss** matching · **RapidOCR + onnxruntime** for the few
strings no template covers · **AutoHotkey v2** for all output (`core/ahk.py`): Python decides
*what*, AHK clicks and presses. Every `requirements.txt` line says why that package and not the
obvious alternative — read it before adding one. PySide6 is **gone**: no QSS, `QThreadPool`,
`sizeHint`, `ui/` package.

**MIT** (`LICENSE`), but the product rules are ours: no paywall, no licence key, no telemetry. The
only outbound traffic is the user's Discord webhook (`core/webhook.py`) and the GitHub release check
(`core/updates.py`), both host-allowlisted. Keep attribution notices intact.

## Stay outside the game — the ban surface

Knowledge comes from **pixels on screen**; output goes out as **ordinary Windows input**.
That boundary is the user's account safety — never traded for a feature, a speed-up or a
reliability fix.

**Never:** inject or load code into Roblox · read/write its memory · hook it
(`SetWindowsHookEx`, detours, remote threads) · `PostMessage`/`SendMessage` input to its
`HWND` · driver-level input emulators · touch, evade or fingerprint anti-cheat · exploit a
game bug · read or ship Roblox files, logs, cookies, `.ROBLOSECURITY` · fast flags.

**Allowed, and only this:** reading the window from outside (`FindWindow`, geometry,
`ClientToScreen`, `SetWindowPos`, `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` for
the exe name) · mss capture · OpenCV matching · `core/ocr.py` on fixed boxes · input through
AHK v2. `macro/camera.py`'s `mouse_event` DllCall is inside the boundary (documented Win32
input API, needed because Roblox recentres the cursor during a right-drag).
`SetForegroundWindow` is activation, not input.

Timing counts: prefer a verified transition over a blind volley of clicks. A capability
needing more than pixels + OS input doesn't get built — say so. The tree is audited clean;
don't redo that grep unless new Win32 lands.

## Calibration is load-bearing

These fail *plausibly* rather than loudly.

- **Viewport pinned 1152×756** (`ui_web/bridge.py::VIEWPORT_W/VIEWPORT_H`). Every `content/`
  coordinate, `settings.json` box, `assets/` PNG, `operations/` block coord and `routes.json`
  step was captured at that size; changing it invalidates all of them. Size the window from
  Win32 *after* the frame comes off, clamped to the work area — pywebview sizes the form
  while it still has a frame, so the client area lands short and the log clips.
- **Display scaling must be 100%.** At 125% a 100%-cropped template scores as a different
  image (measured best match **0.80×**), and Roblox is separately blurry above 100% (a Roblox
  regression — the fix is environmental, not code). `core/win32/display.py::scaling_percent`
  uses `GetDpiForMonitor`, never `GetDpiForWindow` (which answers 96 for a DPI-unaware caller
  and hides the exact case worth warning about).
- **Input timing is a frame count wearing milliseconds.** Roblox acts on the last mouse-move
  it *processed*, one per rendered frame: a settle tuned at 165Hz covers 2.75× fewer frames at
  60Hz and the click lands stale. Scale timings from `display.py`; never hard-code a settle
  that assumes one monitor. Placement coords are tied to `camera.PITCH_DELTA` — retuning the
  pitch invalidates all of them.

`cv2.matchTemplate` is **not scale invariant**: a wrong-size crop can never match, and it
fails intermittently, which reads as a tolerance problem. Wrong scale costs 0.253
correlation; bit depth is a red herring (256 colours costs 0.0003). Never crop a template
from Roblox's own screenshot — it multiplies by the display scale.

## Data, not code

Content and timing are **tables**: add a row, not a branch. Run selectors, the navigator and
task validation all derive from them, so one edit ripples consistently.

| Thing | Table |
|---|---|
| Gamemode / map / target | `content/gamemodes.py` — `GAMEMODES`, `maps_for`, `has_targets`, `selection_complete` |
| Act coordinates | `content/acts.py` |
| Start sequence (hard mode, confirm, start, Expedition's cycling difficulty) | `content/start_stage.py` |
| Navigation images | `content/nav_images.py`; PNGs per `assets/` README |
| Challenge panel geometry | `content/challenge.py` |
| Auto walk paths | `content/walk_paths.py` (target → recording name, act row before map row); recordings are JSON in `paths/defaults/`, and a user recording of the same name wins |
| Events routes | `content/nav_route.py` — `NavStep` kinds click/find/expect/scroll/wait, authored into `routes.json` |
| Delays | `config/delays.py` `DELAY_SPEC` — one entry is the whole change; the Delays tab builds itself from it |
| Keybinds | `config/keybinds.py`, polled in `bridge.py::_hotkey_loop`. `ACTIONS` are ours and polled; `GAME_ACTIONS` are keys we *press* and must never make the app react |

**Read the accessor, never the table.** `settings.json` holds `points`, `regions` and
`confidence`, applied at startup and on every edit (`apply_point_overrides` /
`apply_region_overrides` / `apply_confidence_overrides`). Call `act_coord(...)`,
`start_coords(...)`, `difficulty_coord(...)`; reading `ACT_COORDS` directly ignores the user's
calibration and reintroduces the bug the override exists to fix. A new table of measured
numbers gets a `*_key()`, an accessor and a `*_specs()` for the Vision editor.

**A stored value overrides its default**, so lowering a default does nothing for a user who
already touched that field. Say that instead of claiming the run got faster.

### Waiting

- **A deadline search replaces a fixed sleep, it doesn't follow one.**
  `LobbyNavigator._find(path, timeout=…)` returns the instant the screen appears, so the step
  before it takes no settle (`_nav_step(..., settle=False)`). Sleeping in front of a search is
  latency paid every run.
- Never wait by attempt count; never act on a screen before the search proving it is up has
  succeeded. `image_search_cooldown` is only for a click whose result *cannot* be verified
  (a fixed coordinate, a scroll).
- **A search proves an element is drawn, not interactive.** Normalized correlation ignores a
  uniform brightness scale, so a panel at 40% opacity mid-fade still scores ~0.96 and the
  click is swallowed. An element arriving from a transition we just triggered needs
  `fade_wait` — no threshold can see a fade.
- **Sleep between actions, never after the last one.** A trailing AHK `Sleep` only delays
  `ExitApp` while Python already waits on the process. Guard repeat gaps with
  `if (A_Index > 1)`. An AHK timeout must cover the script's own sleeps.

## Roblox window embedding

Roblox is its **own top-level window**, never reparented: it rides the **topmost** band with its
frame stripped, positioned over the game slot, *above* our normal-band window. Four invariants
hold everywhere, including code that only touches it in passing:

- **Guard every position sync with `IsIconic`** — a minimized window reports ≈−32000 and flings
  Roblox off-screen.
- **Resolve the client origin with `ClientToScreen`**, never arithmetic on window rects.
- **The slot position comes from the page** (its placeholder's `getBoundingClientRect()`), not a
  constant that drifts from the stylesheet.
- **A capture reveals the game first**, inside the bridge (`_game_revealed`) — mss grabs a screen
  rectangle, so a covered window yields our own pixels.

**Details and measurements are the `game-window` skill** — layering, the follow loop, why a modal
shows the empty slot, covering vs hiding off the Dashboard. Load it before changing any of that.

**Dead ends — measured. Do not retry, and load `game-window` before arguing with one:** the
cut-out hole / `SetWindowRgn` over WebView2 · `SetParent` reparenting · `LWA_COLORKEY` ·
caption-drag via `WM_NCLBUTTONDOWN` · Tauri 2 + WebView2 · process DPI-awareness variants ·
runtime multi-scale matching (~24× cost, hides bad templates) ·
`RegionMemory`/`image_regions.json` auto-learned regions · the OCR-template fallback
(`core/text_locate.py`) · per-gamemode `STAGE_SEARCH_REGIONS` (hand-measured, stale after any
resize, and a band shorter than its template can't match) · a **global** match tolerance (drifted
to 0.57 and matched wrong screens; tolerance is per-template — `DEFAULT_CONFIDENCE` 0.70, bounds
`CONFIDENCE_USER_MIN`/`CONFIDENCE_MAX`, no auto-calibrate).

## Python

- **AHK owns synthetic input.** Python never moves the mouse or presses a key via Win32; it
  renders a script with `macro/input_scripts.py` and runs it through `AhkBridge`.
  `wait=False` for long fire-and-forget sequences, `wait=True` for short verifiable actions.
- **Every click goes through the nudge** (`nudge_click_script`): glide on and wiggle before
  clicking — Roblox ignores a click that arrives with no hover event (tested without it, it
  doesn't work). Lobby clicks also retreat (`park=`) so a lingering hover can't draw a tooltip
  over the button the next search needs.
- **Never press a key at a screen you haven't verified.** `UnitPlacer` matches
  `assets/match/unit_ui.png` first; without it a missed click sends `r`/`t`/`x` into the world
  and still looks like a working macro.
- **Never block on a `js_api` call.** AHK `wait=True`, sleeps, capture and OCR go on a
  `threading.Thread`; return as soon as the *ordering* is safe and push the result back with
  `window.evaluate_js` into a `window.on*` handler. Return early only when nothing after it
  depends on the work — a capture must be taken *before* the call returns, or the page
  switches screens and hides the game first.
- **Cross the bridge as JSON** (`json.dumps`). An f-string put Python's `False` into JS and
  crashed the run loop with `False is not defined`.
- **Stopping is cooperative.** F1/F2 set `request_stop()`; poll loops abandon their wait, the
  driver ends the run between steps. **Never kill an AHK process** — the camera script holds
  `i` and the right button down and a kill never releases them.
- **Keep decision logic pure.** `macro/tasks.py` decides what to play next with no capture, no
  clicking, no UI. New rules go there, not into the runner.
- **Win32 behind typed helpers** in `core/win32/`, never raw `ctypes` in UI/macro code. Declare
  argtypes/restypes in `bindings.py` so a wrong pointer type fails loudly (the `LP_POINT`
  lesson). Read state back where a call can silently no-op.
- **No bare `except`.** Catch specific errors, message as `f"Failed to X: {exc}"`.
- **OCR reads are approximate** — `start_game.png` comes back "Start Ge". Never require an
  exact string: match a closed set (`challenge.match_map_name`) or parse digits with the usual
  confusions folded in, and use the returned confidence to spot a weak read.
- `image_search.to_absolute_path` passes an absolute path through **on purpose** (the Macro
  Tester's file dialog). Don't "harden" it.
- AHK v2: `FileDelete` on a missing file throws and hangs the script behind a dialog. Use
  `FileOpen(path, "w")`.

## Naming

Python `snake_case` fn/var, `PascalCase` class, `SCREAMING_SNAKE` constant, `snake_case`
module. JS `camelCase`. CSS classes and DOM ids `kebab-case` with a feature prefix
(`.im-card`, `#im-grid`, `.chal-slot`, `#btn-chal-scan`); custom properties `kebab-case`
(`--text-muted`). A page callback from Python is `on` + PascalCase on `window`
(`window.onChallengeScan`). JSON: `PascalCase` inside records, `snake_case` top-level keys
(`{"Kind": "target"}`, `start_position`).

## Parallel surfaces

Change one, the others usually need it too.

| Group | Surfaces |
|---|---|
| **Gamemode schema** | `content/gamemodes.py` ↔ Run/selector UI ↔ `nav_images.py` ↔ Tasks validation ↔ Task Builder mode fields |
| **Measured numbers** | a `content/` table ↔ its `*_key`/accessor/`*_specs` ↔ `config/regions.py` ↔ the Vision row |
| **Config formats** | `config/` readers/writers ↔ JSON in `operations/`, `paths/`, `recordings/`, `routes.json`, `settings.json` |
| **Settings** | `config/unified.py` default + a `[data-key]` control in `index.html` + where it's read |
| **Delays** | one `DELAY_SPEC` entry ↔ `LobbyNavigator.apply_delays` ↔ `UnitPlacer.apply_delays` |
| **Viewport size** | invalidates every coordinate, template, `operations/` block coord and route |
| **Threading** | anything that clicks, sleeps, captures or OCRs runs off the UI thread |

## Security, data, performance

- **Everything outside the app is untrusted** — matched pixels, OCR text, JSON on disk, the
  private-server link, window titles. Validate type and range before a value reaches logic, a
  path, a numpy slice or an AHK script.
- **Reject, don't repair.** A box the app silently reshaped reads the wrong pixels and looks
  like an OCR fault — the exact failure the feature prevents (`config/regions.py::clean_box`).
  Drop invalid entries rather than refusing to start.
- **Validate anything that becomes a path or a script** — `bridge._template_path`,
  `unit_configs.safe_component`, `nav_routes.clean_name`, `nav_route.safe_rel_path`,
  `keybinds.sanitize_game_key`, `start_position.MOVE_KEYS`. Whitelists and rejections, not
  escapes: an AHK string is code.
- **No secret in the tree or the log.** The private-server link and webhook URL live in the
  gitignored `settings.json`; never ship, print or example one. The webhook POSTs only to
  `core/webhook.py::ALLOWED_HOSTS`.
- **On-disk formats are stable.** `operations/`, `paths/`, `recordings/`, `routes.json`,
  `assets/`, `settings.json` hold user data: readers default missing keys and preserve unknown
  ones, and `store.update_json` takes one lock across read and write because several stores
  share the file and the macro worker writes stats mid-run. A shape change that can't be
  defaulted needs a one-time migration preserving the old intent
  (`TaskStore.take_legacy_challenge_slot`). Known limits: that lock is per-process, so two app
  instances still race, and `routes.json` is rewritten whole with no backup.
- **Bound anything that grows** — log panels cap lines, the template cache keys on mtime, an
  upload is capped before Discord rejects it.
- **Keep the UI responsive**: capture/matching/OCR/AHK off the render thread, timers bounded
  per tick, and a courtesy feature (the webhook) never stalls a run.

## UI

The front end is `ui_web/`: pywebview + HTML/CSS/JS over WebView2, `bridge.py` as `js_api`.
**How to build one is the `ui-feature` skill** — the four-layer split, the component
checklist, the design vocabulary, the live-game traps. Load it before touching `ui_web/`; it
is not repeated here.
