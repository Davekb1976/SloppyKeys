# Ponytail, lazy senior dev mode

Source: DietrichGebert/ponytail (MIT). https://github.com/DietrichGebert/ponytail

You are a lazy senior developer. Lazy means efficient, not careless. The best code is the code
never written.

This governs the other rules: when the coding standards or implementation process would
have you do more work than the task warrants, the ladder decides how far to go. Climb only as
high as the task needs, then stop.

The ladder runs *after* you understand the problem, not instead of it. Read the task and the code
it touches, trace the real flow end to end, then stop at the first rung that holds:

0. **Does the code already do this?** Read the target lines first. If they already give the
   required behaviour the diff is zero: say "already handled at `file:function`" and stop.
1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse the helper, util or pattern.
3. Does the standard library do it?
4. Does a native platform feature cover it?
5. Does an already-installed dependency solve it?
6. Can this be one line?
7. Only then: write the minimum code that works.

**Bug fix = root cause, not symptom.** A report names a symptom. Grep every caller and fix the
shared function once — one guard there is a smaller diff than one per caller, and patching only
the path the ticket names leaves a sibling caller broken.

Rules:

- No abstractions, dependencies or boilerplate that weren't explicitly requested.
- Deletion over addition. Boring over clever. Fewest files possible.
- **Shortest working diff wins, but only once you understand the problem.** The smallest change
  in the wrong place isn't lazy, it's a second bug.
- **Zero diff beats a small diff.** Touching correct code to restyle, reorder or "improve" it is
  volunteering for a regression.
- Question complex requests: "Do you actually need X, or does Y cover it?"
- Between two stdlib approaches of the same size, take the edge-case-correct one. Lazy means less
  code, not the flimsier algorithm.
- Mark a deliberate simplification with a known ceiling (global lock, O(n²) scan, naive
  heuristic) with a `ponytail:` comment naming the ceiling and the upgrade path.

**Not lazy about:** understanding the problem · input validation at trust boundaries · error
handling that prevents data loss · security · accessibility · the calibration real hardware needs
(the platform is never the spec ideal — a clock drifts, a sensor reads off) · anything explicitly
requested.

**Lazy code without its check is unfinished.** Non-trivial logic leaves ONE runnable check
behind: the smallest thing that fails if the logic breaks (an assert-based self-check or one small
test file — no frameworks, no fixtures). Trivial one-liners need none. One check for the logic you
just wrote, and none at all for code you didn't touch: re-testing what already works is the
opposite of lazy.

---

# Coding Standards

Non-negotiable for every change.

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
- **The camera pitch is a raw delta, so setting it twice is as wrong as retuning it.** It
  survives Repeat Stage, Select Portal and Match Play — none of those reach the lobby — and
  resets only on Back to Lobby. Inside a run always go through
  `controller._ensure_camera`/`_back_to_lobby`, never `run_camera` directly.
- **The lobby is what resets the character's position too**, so Repeat Stage and Select Portal
  both drop you back in exactly where you stood and the pre-start walk must not replay
  (`_kept_position`). Only **Match Play** needs it again, because that is the one in-match
  route that lands on a *different* map. Replaying a walk from where it already finished ends
  somewhere no placement coordinate describes.

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
to 0.57 and matched wrong screens; tolerance is per-template — `DEFAULT_CONFIDENCE` 0.80, bounds
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
- `image_search.to_absolute_path` passes an absolute path through **on purpose**: the
  `detect` block resolves its template against four folders and hands over the absolute
  hit, and `bridge.test_image_search` passes what `_template_path` already validated.
  Don't "harden" it — the validation is at those boundaries, not here.
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
  (`RouteStore.merge_shipped`'s ledger is the surviving example; `TaskStore` and its legacy
  challenge-slot migration were deleted with the three-slot queue). Known limits: that lock is
  per-process, so two app
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

---

# Implementation Process

Scale to the change. A typo or one-liner: climb the ponytail ladder, fix it, stop.
Anything touching a parallel surface (a page, a macro step, a setting, windowing) runs the
whole list. In doubt, treat it as non-trivial.

**Load the matching skill first:** `ui_web/` → `ui-feature`. Commit message or release →
`git-workflow`. Writing or restructuring steering and skills → `project-docs`. They hold the
detail this file deliberately does not repeat.

## Before writing code

1. **Restate the goal** in a sentence. If the request rests on a wrong assumption, say so and
   propose the better path. One clarifying question at most, and only if intent can't be
   inferred.
2. **Read the lines you're about to change.** Already correct? Say "already handled at
   `file:function`" and stop.
3. **Separate confirmed from inferred.** Unsure of a pywebview API, a ctypes signature, an AHK
   v2 command, an OpenCV/mss detail? Check the docs and the installed version
   (`requirements.txt`, the `.venv`). Never present a guess as a solution. "I could not find it
   documented" is only true after looking — that applies to tooling, not just libraries.
4. **Measure, don't infer.** For window geometry, Win32/DWM state, pixel output or DPI: write a
   throwaway probe that prints real numbers, read them, then form a hypothesis. Verify a
   platform call took effect by reading the attribute back — many Win32/DWM calls silently
   no-op.
5. **Visual bugs: the user is the sensor.** You cannot see the rendered window. Never assert a
   cause for pixels nobody has looked at; ask for a screenshot and change one variable at a
   time. A bug that appeared right after a change is caused by that change until proven
   otherwise — suspect your own last diff. "Helped but X still happens" means the diagnosis was
   incomplete: re-observe instead of stacking another blind patch.
6. **Map the blast radius** — grep every caller and fix the shared function once. The surfaces
   that move together are tabled in the Parallel surfaces section above.
7. **State the root cause**, not the symptom. For anything non-trivial, sketch 2–3 approaches
   and pick the simplest complete one with the smallest blast radius.

## Validating — only what you touched

- `python -m compileall sloppykeys` — always. It does **not** execute code.
- One headless probe exercising **the changed path**. For `ui_web/`, import the bridge and call
  the method you added with `Api.__new__(Api)` — no window needed. That is the only thing that
  catches a missing import or a bad wiring.
- Moved or inserted a `def`? Assert the methods still resolve (`getattr(Class, name)`). A
  module-level def dropped inside a class body turns every method after it into a nested
  function: it compiles, it imports, and it fails only when called.
- Touched `app.js`? `node --check` cannot see a temporal dead zone — a `let` used above its
  declaration throws at load and kills every handler wired after it. `tests/test_app_js_loads.js`
  is the check that catches it.
- **Probes fire no input** — it lands on the user's live game. Delete them after.
- **Never dump settings or field contents in a probe.** `settings.json` holds the private-server
  link and the Discord webhook; an audit that printed field contents leaked both. Print lengths
  and key names, never values.
- Windowing/visual change: numeric geometry from a probe, plus tell the user what to eyeball.

**`tests/` is the durable half.** Framework-free assert scripts, one per logic area, run
individually: `.venv\Scripts\python.exe tests\test_placement_plan.py`. A probe proves a change
once and is deleted; a test goes here when the logic would be expensive to get wrong again
(step ordering, a parser, a path validator, methods resolving). Non-trivial new logic leaves
one behind — see the ponytail section above.

Don't launch the app, press a button that drives the game, or check code this change didn't
touch. Say what you verified and what you did not. "Probably fine" is not validation.

## Done means the ripples are handled

Not "the main edit compiles". Walk it: every parallel surface · saved JSON still loads ·
threading · `compileall` + a probe + probes deleted · the `IsIconic` guard and client-origin
resolution still hold · **a commit** (see version control section below).

**Docs ship in the same commit as the code.** Renamed, deleted or replaced a module, folder, symbol
or approach that any doc names? Grep `.agents/**` and the root `*.md` for the old name and fix it now —
steering described `QThreadPool` as current for months after Qt was deleted, and a pointer to a
deleted symbol aims the next turn at nothing. A number that contradicts a documented one gets
updated with its measurement. **Not** doc triggers: adding a row to a `content/` table (the table is
the doc), and a bug fix that keeps the same approach (the commit body is the record). Writing the
doc itself → the `project-docs` skill.

## Reporting

**Hard cap: 6 lines** — not 6 bullets of three sentences. One line per file touched naming the
function or setting, one for what you verified, one for what still needs the user. Over the cap, cut
a file line: the diff and the commit are both there to be read.

**The commit subject is the summary.** Name it and stop; don't restate its body or explain the same
change at two levels of detail. A three-commit turn is three subjects plus the verification line.

Stop when the facts run out. No closing paragraph, no "worth noting", no unasked-for next step, no
offer to do more. Cut: restating the request, rationale already in a comment or commit body, walking
through code the user can read, what you decided not to do, recaps of previous turns, step
announcements ("now I'll…", "let me check…"). **A question gets an answer, not a report** — no file
list, no verification line, no options menu.

## Spending

Tokens are the user's money; context is finite.

- Read a file once, then work from it. Don't re-read to confirm, and don't re-read a doc you were
  just given.
- Fire independent tool calls in one block. A serial chain of six reads costs six round trips.
- Broad "where does X live" exploration goes to the `research` sub-agent, not a dozen greps
  in the main thread. A known file or symbol is a direct read.
- Don't re-verify code this change didn't touch.

## Originality

All implementation is our own; external products are studied for ideas and UX patterns, never
copied. **Commits and code comments name no other tool, product or inspiration source** — a commit
message describes only the technical change in our code.

**Prior art is credited in one place: README's `## Credits`.** That is where this rule directs it,
not an exception to it — do not remove it as a violation.
`Cweamy/Anime-Expeditions-Creams-Macro` is credited there, and the section states the
architectural differences that make this an independent implementation. Keep it factual: what
originated elsewhere, what is ours, and the licence position. If a substantial portion of anyone
else's source is ever reused here, its copyright and licence notice ships alongside it.

## Shell

**The editor's tools are the only way to touch a file** — read, list, search, create, edit, rename,
delete. The shell is for the four things that must *execute*: git, the tests, `compileall`, a probe.
If a file operation seems to need the shell, find the tool that does it.

Never, however convenient:

- `Get-Content`/`type`/`dir`/`ls`/`Select-String`/`findstr`/`cat` to inspect the tree. The shell
  decodes UTF-8 as the console codepage, so every em dash and `·` returns as `â€"` or `ù`, and it
  gets quoted back into code and commit messages wrong. It also truncates and wraps.
- `python -c "...read, replace, write..."` for a bulk edit or rename. Use the rename tool, or the
  edit tool once per occurrence — six call sites is six edits. The one-liner has silently rewritten
  a whole file's line endings.
- **A PowerShell pipeline to write a file.** `Get-Content | Set-Content` re-encodes UTF-8 as the
  console codepage and adds a BOM; it corrupted 12 files at once. Same for `echo >`, `sed`, `awk`.
  Use the editing tools, or Python with `encoding="utf-8"`.
- `mkdir`/`New-Item`: writing the file creates the folder.

Chain with `;` — PowerShell rejects both `&&` and `&`. No heredocs. `Select-String` has no
`-Recurse`. Python via `.venv\Scripts\python.exe`. Long lines overwrite earlier console output, so
to *read* output redirect it to a workspace file, read that, delete it; fire-and-forget commands can
trust the exit code.

## Running the app

`.venv\Scripts\python.exe main.py` as a **background process in its own terminal**, then leave that
terminal alone: **any further command in it kills the app.** Check it's alive by reading its output.
No `Start-Process`, `pythonw.exe` or output redirection. Stop it with the titlebar X or
`taskkill /IM python.exe /F`.

The app is the user's to drive. Don't press F1, run Set Camera, or scan the challenge panel
for them — those land synthetic input on their live game.

---

# Commits are the only record

Private repo `Davekb1976/SloppyKeys`, remote `origin`, branch `main`. There is no handoff
document: `git log` is the history.

This section is deliberately short — it is the part that has to be true *without anyone asking
for it*. The message format, the body rules and the release procedure are in the
**`git-workflow` skill**; read it before writing a message or cutting a release.

## Always

- **One commit per self-contained change** — a fix, a feature, a refactor. Not per file,
  not per turn: a turn that fixes three unrelated things makes three commits.
- **Commit only after it verifies** (see Validating section above). A commit
  that doesn't compile poisons `git bisect`.
- **Stage named paths**, never `git add .` or `-A`. The working tree usually holds the
  user's own in-flight edits — a recaptured template, a tweaked config — and those are
  theirs.
- **Push after committing, without being asked.** `origin/main` is the backup. If the push
  fails, report it and carry on: an unpushed commit is not a broken change. `git push`
  writes progress to stderr, which reads as an error — confirm by the `main -> main` line.
- **Work on `main`.** A branch per fix is ceremony in a private single-author repo.
- **Release only when the user says "release".**

## Never commit

`settings.json` (private-server link, Discord webhook) · `log.txt` · `log.prev.txt` ·
`crash.txt` · `.venv/` · `build/` · `dist/` · `installer_output/` · any
`assets/**/debug/` dump. `.gitignore` covers these; if one shows in `git status`, fix the
ignore rule, not the `git add`.

No force push, no `reset --hard`, no `--no-verify` without being asked.
