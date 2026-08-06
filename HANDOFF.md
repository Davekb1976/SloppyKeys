# HANDOFF

Keep this file under ~250 lines. Facts, file names, current state. No investigation narrative, no
changelog, no re-explaining code comments. Rules at the bottom.

**Now:** the viewport is **1152×756**, the client size Cream's Anime Expeditions macro uses
(`core/config.py::FIXED_WIN_W/H` there) — picked because it is proven on many machines, not just this one.
It was 816×638, briefly 800×599. The **templates and the challenge OCR boxes have been re-captured** at
this size through Settings > Vision, including `select_stage.png` and `repeat.png`; the user reports them
looking right, but no full run has exercised them. What still predates the resize is listed under
[Re-calibration](#re-calibration).

## What / how

Windows-only desktop macro for the Roblox game *Anime Expedition*. Finds the Roblox window, pins its
client area inside a hole punched in our frameless always-on-top window, then plays: template-match
pixels (OpenCV + mss), OCR the few strings that can't be templated (RapidOCR/ONNX, required), send all
input as generated AutoHotkey v2 scripts. User picks Gamemode / Map / Act and a unit plan (up to 72
steps) saved under `configs/`.

Python 3 + PySide6. Entry `main.py` → `sloppykeys.ui.window.run`. Run as `.venv\Scripts\python.exe main.py`
in its own terminal. Shell is PowerShell (`;`, not `&&`).

**Shipping:** `build_exe.py` (PyInstaller 6.21, **onedir**) builds `SloppyKeys.exe` into
`C:\Users\Kylle\Documents\SLOPPYKEYS`. Onefile is wrong here — it unpacks ~340MB every launch.
`images/`, `configs/`, `routes.json` and `settings.json` are **copied next to the exe, never bundled**,
because the app writes to all of them; a rebuild replaces the program and leaves them alone.
The shipped `settings.json` is **filtered, not blanked**: `build_exe.py::shipped_settings` copies the keys in
`SHIPPED_SETTINGS_KEYS` (`run_challenges`, `hard_mode`, `expedition_difficulty`, `keybinds`, `delays`,
`start_position`) out of the project's own file, then *sets* the link and webhook empty and zeroes the stats.
It is an **allowlist on purpose** — a secret added to the settings schema later must not leak because nobody
remembered to exclude it. Deliberately not shipped: `regions`/`points` (this machine's measurements, already
the code defaults, and an override on a fresh install makes the UI's Reset a no-op), `tasks` (an empty queue
makes F1 use the Run page selection, which is right for a first run), `match_confidence` (a removed setting).
The build prints which keys it carried. `--collect-all rapidocr onnxruntime` is required: the OCR models live
inside the rapidocr wheel and PyInstaller's scan misses them.

**The project tree is the source of truth for shipped data**, not `C:\Users\Kylle\Documents\SLOPPYKEYS`.
The user configures against the *built* app, so anything changed there must be copied back into the project
before a rebuild — `build_exe.py::copy_data` `rmtree`s `images/` and `configs/` at the destination and, without
`--keep-settings`, overwrites `settings.json`. **Run `build_exe.py` only after copying back**, or it silently
reverts the user's work.

**Size, measured: `_internal` is 292MB** (was 339), and that is close to the floor.
cv2 82 · PySide6 74 · onnxruntime 38 · rapidocr 31 (the ONNX models) · numpy.libs 20 · PIL 13.
`PRUNE_GLOBS` deletes 47MB of proven-dead binaries: OpenCV's ffmpeg DLL (29MB, nothing calls
`VideoCapture`) and the Qt6Quick/Qml/Pdf/VirtualKeyboard DLLs plus the two **plugins that link them**
(`qpdf.dll`, `qtvirtualkeyboardplugin.dll`). Those two were found by scanning every remaining binary for the
pruned filenames — **a successful launch does not prove a prune is safe, because Qt loads plugins lazily.**
Re-run that scan if the glob list changes.

Dead ends here, measured, don't retry: **`opencv-python-headless` is not smaller** (`cv2.pyd` 81.9MB vs
82.3MB, and the videoio DLL ships either way) — it is used only because it carries no Qt plugins to collide
with PySide6's. **`PIL` and `shapely` can't go**, rapidocr imports both. **Don't prune
`PySide6/opengl32sw.dll` (19.7MB)**: Qt's software GL fallback, for exactly the machine a shipped build has
to survive. **`--onefile`** removes the `_internal` folder but is the same payload compressed inside the exe
and unpacked to `%TEMP%` every launch: tidier, slower, not smaller.

`installer.iss` **compiles** (69s, `installer_output\SloppyKeys-Setup-beta.exe`, **111MB** from the 316MB
folder). Inno Setup 6.7.3 is installed **per-user**, so ISCC is at
`%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`, *not* Program Files. **Never start a `[Code]`
continuation line with `#13`** — the preprocessor reads a leading `#` as a directive and aborts; keep the
linebreaks trailing. Needs 6.3+ for `x64compatible`. Rebuild `build_exe.py` before compiling, or the
installer ships the previous exe. **The install folder is the data folder** — `resolve_app_root()` returns
the **exe's folder** when `sys.frozen`, so `images/`, `configs/`, `routes.json`, `settings.json` and
`log.txt` all live beside the exe, and a zip of the same build behaves identically. Hence **per-user
`{localappdata}\Programs`**: Program Files isn't writable without admin, and a failed capture there is
*silent*. `CheckWritableDir`/`NextButtonClick` write-test the chosen folder and warn.
Data files are `onlyifdoesntexist` **+ `uninsneveruninstall`**: an upgrade never overwrites a recaptured
template, a **reinstall restores anything the user deleted** (so reinstall = repair), and uninstall keeps
the data unless `CurUninstallStepChanged`'s prompt is answered Yes. `AppId` is a real GUID now — **never
change it after a public release.** Warns at start if AutoHotkey v2 is absent; AHK is *not* bundled.
`_install_crash_log` appends unhandled exceptions to `crash.txt`, because a windowed build has no console.

**Self-heal, measured:** a missing folder or JSON file comes back (`store.py::write_json` and every
`makedirs(exist_ok=True)` call site; readers merge defaults). **A deleted PNG or unit-plan JSON does not** —
there is no code default for pixels. Recapture in Vision, or reinstall over the top.

`ui/window.py::VERSION` is the word `"beta"`, not a number, and `installer.iss`'s `AppVersion` says the same.
Titlebar and webhook footer print it bare (no `v` prefix). Keep the two in step.

## Module map

- `ui/window.py` — `MainWindow`: owns every service (settings, stores, `LobbyNavigator`, `MacroRunner`,
  `AhkBridge`, `ChallengeTracker`, `StatsTracker`), titlebar/rail/pages, the mask (`_apply_window_mask`),
  the 40ms hotkey poll (`_poll_hotkeys`), F1/F2 (`_start_macro` / `_stop_macro`), the run-step builders
  (`_build_run_steps`, `_build_match_steps`) and the Macro Tester list (`_build_tests`).
- `ui/viewport.py` `RobloxViewport` (attach + keep Roblox behind the hole), `ui/theme.py` (all QSS,
  `VIEWPORT_WIDTH/HEIGHT`, `WINDOW_WIDTH/HEIGHT`), `ui/pages/` (`run_page`, `units_page`, `settings_page`,
  `selector_page`, `stats_page`), `ui/task_editor.py`, `ui/route_editor.py`, `ui/position_editor.py`,
  `ui/placement_overlay.py`, `ui/sequence_editor.py`, `ui/macro_tester.py`, `ui/widgets.py` (`LogView`),
  `ui/glow.py`, `ui/icons.py`.
- `macro/lobby.py` `LobbyNavigator` — `click_play`, `open_gamemode`, `select_stage`, `select_act`,
  `set_difficulty`, `start_stage`, `click_start_match`, `in_match`, `wait_for_match_ready`,
  `click_start_game`, `leave_match`, `change_gamemode`, `close_challenge_list`, `start_challenge`,
  `open_challenges`, `find_events`/`click_events`, `run_route_step`. Searches poll via
  `_find(path, timeout=…)`.
- `macro/placement.py` `UnitPlacer` — `run_step`, `place_unit`, `open_unit_panel`, `run_moves`,
  `run_sequence`, `press_game_key`, `wait_for_outcome`.
- `macro/input_scripts.py` — every AHK builder (`nudge_click_script`, `move_script`, `scroll_script`,
  `key_script`, `drag_script`) plus `set_refresh_hz`/`nudge_settle_ms`. `macro/camera.py` — the one
  raw-`mouse_event` exception (Roblox recentres the cursor on a right-drag).
- `macro/runner.py` `MacroRunner`/`MacroStep`/`StepResult` — dumb state machine, `tick()` runs one step.
- `macro/tasks.py` `TaskDirector` — what to play next. Pure, no Qt, no capture.
- `macro/challenge.py` `ChallengeScanner` / `ChallengeRead` / `ChallengeTracker` — reads the panel, never
  clicks.
- `core/image_search.py` (capture + match, `SearchRegion`, `best_score`, `DEFAULT_CONFIDENCE` 0.70,
  `capture_png`), `core/ocr.py` `OcrReader`, `core/ahk.py` `AhkBridge`, `core/webhook.py`,
  `core/win32/` (`bindings.py`, `roblox_window.py`, `frameless.py`, `display.py`).
- `content/` = DATA: `gamemodes.py`, `acts.py`, `start_stage.py`, `nav_images.py`, `challenge.py`,
  `nav_route.py`, `units.py`, `start_position.py`. Adding content is a table edit.
- `config/` = stores: `settings.py`, `store.py`, `unit_configs.py`, `delays.py`, `keybinds.py`,
  `tasks.py`, `nav_routes.py`, `start_position.py`, `stats.py`.
- On disk: `configs/<Gamemode>/<Map>/<Act>.json` (41) + `configs/Challenge/<Map>.json`, `images/`,
  `settings.json` (gitignored — holds the PS link and webhook), `routes.json`, `log.txt`.
- **Events / Villian Invasion's act is `Act 1`, not `Main`.** The rename touched every surface at once:
  `routes.json` (act list, route key, and the FIND step's image path), `configs/Events/Villian
  Invasion/Act 1.json`, `images/events/Villian Invasion/Act 1_1.png`, `images/reference/Events/Villian
  Invasion/Act 1.png`. Its walk is now a **code preset** —
  `start_position.PRESETS["Events/Villian Invasion/Act 1"] = [("w", 2000)]` — promoted out of the user's
  `settings.json` so a fresh install walks correctly without re-measuring. An Events preset only holds while
  that event is in rotation; when it rotates out the key stops matching and costs nothing.

## Re-calibration

**Everything measured lives in Settings > Vision** (`ui/image_manager.py`), in four inner tabs: 27
template rows (drag a box, it overwrites that file with those exact pixels), 12 map-image rows (Capture
saves the whole client view as the placement backdrop), the 10 challenge OCR boxes, and 12 click points. No other tab captures an image any more — the
Units page's icon button and the Route tab's *Capture map image* were removed, and so were VISION >
*Dump client for cropping* / *Check template scale*, which existed to work around hand-cropping.
**Never crop from Roblox's own screenshot** — it multiplies by the Windows display scale, which is where
the old wrong-size templates came from. COORDS only reads a coordinate; it cannot capture.

Done: templates, and `content/challenge.py`'s `STAR_REGIONS` / `LIMIT_REGIONS` / `MAP_REGIONS` /
`RESET_TIMER_REGION` (measured at 1152×756 and promoted from the user's `settings.json` `regions`, which
still holds the same values). Still from 816×638 — data entry, not code:

| what | where |
|---|---|
| ~~act click points, Hard Mode toggle~~ | **done** — re-picked in Vision > Points at 1152×756 and promoted into `content/acts.py::ACT_COORDS` (Story 7, Raid 3) and `START_COORDS["Story"]["hard_mode"]`. `settings.json` `points` still holds the same values, so Reset is a no-op. Expedition's difficulty cycle is still unmeasured |
| the five fixed challenge clicks | `content/challenge.py`: `CLOSE_LIST_CLICK`, `SELECT_STAGE_CLICK`, `START_CLICK`, `LOSS_RETRY_CLICK`, `CHANGE_GAMEMODE_CLICK` — code only, no editor yet. Measure with CHALLENGE > *Map challenge panel text* |
| walk plans | `content/start_position.py::PRESETS` + any `settings.json` `start_position` override |
| placement backdrops | the map-image rows in Vision (`images/reference/**` — 5 Story maps, 3 Raid acts, 3 Expedition maps, 1 per Events act) |
| unit placement points | all 41 `configs/` files (Units page picker) |
| Events route | `routes.json` step points/regions + `images/events/**` (Route tab Capture) |

Tools for it: CHALLENGE → *Map challenge panel text* (OCRs the whole client with detection on and prints
every line's box — this is how the challenge regions get re-measured), COORDS rows for single points.
`images/challenge/star_used.png` is unused (the greyed star is read by HSV saturation, and the template
scored 0.999 against *active* stars because matching is grayscale) and can be deleted.
`images/challenge/debug/` and `images/debug/` are dumps, not templates.

## Working

Confirmed in use by the user unless marked otherwise. Most of it was last exercised at 816×638; the
templates are re-captured at 1152×756 but no full run has been watched since.

- Attach, pin the client, mask/hole, minimize→restore size snap-back (`resizeEvent`).
- Window is **1690×1004**, exactly the layout's measured `minimumSizeHint` — no surplus, nothing clipped.
  Fits a 1080p screen (available height 1032). 1152×756 in use, text legible, templates captured at it
  match.
- Titlebar drag is manual (`TitleBar.mousePressEvent` → `_drag_from` + `window().move()`), not
  `startSystemMove()`. That is what killed the white ghost outline: with
  `HKCU\Control Panel\Desktop\DragFullWindows` = "0" on this machine, Windows' modal move loop draws an
  outline instead of moving the window. The window itself was always correct (Qt geometry, `GetWindowRect`,
  `GetClientRect` and DWM extended frame bounds all read 1690×1004; styles are only
  `WS_POPUP | WS_VISIBLE`) — don't re-investigate the mask, DPI or the removed `screenChanged` hook. Cost:
  no Aero Snap while dragging, which a fixed-size always-on-top window can't use anyway.
- Story end to end under F1: lobby → stage → act → start → camera → start position → placement → result,
  looping per match. Raid/Expedition share the chain; Expedition difficulty cycles (clicks = difficulty−1).
- Manual join: `in_match()` true → F1 starts at the camera step, no lobby clicks. Auto-detected.
- **Every lobby click retreats to the client's top-left (8,8) inside the same AHK script**
  (`nudge_click_script(..., park=…)`, passed by `lobby._click`, `_click_client` and `select_act`). A cursor
  left on a button keeps it hovered and Roblox draws a **tooltip over the neighbouring button** — that is
  what made a Select Stage search fail with the button plainly on screen. In the same script rather than a
  second `move_script` run: one AHK launch instead of two, and it can't be forgotten at a call site. There
  is a `CLICK_GAP_MS` pause first, because Roblox acts on its own last processed mouse-move and a move
  issued with the click can land the click at the parked point (same class as `NUDGE_SETTLE_FRAMES`).
  **A plain `MouseMove` to the corner was not enough** — measured in game, the cursor arrived and the
  tooltip stayed. `_park_wiggle` does three legs landing on the park point, so Roblox processes a real
  mouse-leave; `move_script` and `scroll_script` use it too. It wiggles **inward on x** because the park
  point is a corner and a vertical swing would leave the client, and a leave off the *window* is not a
  leave off the button. Nothing clicks at the park point: client (8,8) is where Roblox's own menu button
  sits, and `_header()` already `WinActivate`s Roblox on every script, so a click buys no focus.
  **In-match clicks deliberately don't retreat** — `placement.py` passes no `park`, since there the cursor
  belongs on the unit. The three standalone `_park()` calls stay: they guard against the *user's* cursor
  position when F1 is pressed, which no click of ours has moved.
- **The Start Game step parks first** (`MainWindow._start_game` → `UnitPlacer.park()`, the public wrapper).
  Because in-match clicks don't retreat, a **pre-placement** step leaves the cursor on the unit it just
  placed and Roblox draws a tooltip there — measured: `placed slot 3 at 571,75` then
  `Start Game not found (best 0.47 < 0.70)` with the button on screen. The retreat belongs to the step that
  needs a clear view, not to every placement click. One `move_script` per match cycle, no wait after it (the
  search polls), and it also covers the post-Repeat entry where the cursor sits on Repeat. `_build_match_steps`
  must call `self._start_game`, **not** `self._nav.click_start_game` directly.
- Searches wait on a deadline (`_find(path, timeout=…)`, `search_poll` 0.12s hardcoded, `search_timeout`
  from Settings > Delays). A step whose next step is a search passes `settle=False` — don't put a blind wait
  in front of a search.
- **F1 stops mid-step, not after it.** `should_stop` (a lambda reading `MacroRunner.stop_requested`) is
  threaded into `LobbyNavigator` and `UnitPlacer` and checked inside every poll loop: `find_until`,
  `wait_for_match_ready` (60s, and it sleeps in `search_poll` slices now), `wait_for_outcome` (**900s** — the
  reason stopping used to mean waiting out the whole match), and `_ensure_lobby`'s rejoin poll. Stopping is
  still **cooperative, not a kill**: only waits are abandoned, never an AHK script in flight, because
  killing one mid-press never sends the matching release and leaves a key or mouse button stuck in the game.
  `wait_for_outcome` checks *before* its keep-alive click, so a stop never fires one more click.
  `MacroRunner.tick` returns early when a stop is pending, so a cancelled wait is not logged as
  `Step 'X' failed` — the driver ends the run. A caller that passes no `should_stop` (the Macro Tester) is
  unchanged.
- **`join_wait` is gone** (removed from `DELAY_SPEC` and from `start_stage`/`start_challenge`). It slept 5s
  after the lobby Start click, directly in front of `wait_for_match_ready`'s 60s poll for the same screen —
  10s a match for nothing. A stored value in `settings.json` is ignored, not migrated: `DelaysStore.all`
  only reads keys the spec declares, and `set()` rejects the rest. The Delays tab is now five fields.
- **Start is clicked with `fade_wait`, and that is not optional.** Removing the `click_settle` in front of
  `click_start_match` broke the challenge chain: `clicked Start at 944,606 (0.96)` then
  `Start Game not found within 60.0s`, with `start_match.png` still scoring **0.954 on screen 55s later** —
  the click was swallowed and the lobby was never left. "Start doesn't exist until Select Stage is clicked,
  so the search can't hit a stale button" was true and *insufficient*: the search can hit a button still
  **fading in**, which matches at 0.96 while being unclickable. What proves it is the fade and not the click
  mechanism: the leg that kept its settle (after `select_challenge_row`) worked in the same run. The wait now
  sits **after** the search rather than before it, so a screen already up pays `panel_fade_wait` instead of
  the old 1.5s and the search still returns the instant the button appears. Both `start_challenge` and
  `start_stage` pass it.
- **Three pre-search `click_settle` sleeps removed** (~4.5s a run at the stored 1.5s): before
  `click_select_stage` in both `start_challenge` and `start_stage`, after `close_challenge_list`'s blind
  close (the
  cards can't match while the panel covers them, so an early look costs one 17ms miss), and after
  `click_play` in `open_challenges`. **Two deliberately kept, don't "optimize" them** — both are marked in
  the code: the settle after `select_challenge_row` (a row swap has no on-screen proof, so racing on can
  start the *wrong challenge*) and the one after Story's Hard Mode toggle (no template for the toggled
  state, and Select Stage is already visible, so racing on can commit the run in normal mode). The scroll
  settles stay too: `select_stage`'s post-scroll look is `timeout=0.0`, a single look, so it needs the list
  to have stopped moving. `run_to_stage`/`run_to_act`/`run_and_start`/`run_to_stage_and_start` are
  **Macro Tester only** and were left alone.
- **The win path is `game_won` → Repeat → `start_game`.** `game_won.png` is a crop of the victory screen's
  *text*, and that screen stays up until something dismisses it, so `LobbyNavigator.click_repeat`
  (`images/match/repeat.png`) clicks Repeat and only then does Start Game come back. `_repeat_step` is
  appended **last** in `_build_match_steps`, after `Next task`, deliberately: Repeat replays *this* stage, and
  a switching `Next task` has already called `request_stop()`, which the runner honours between steps — so
  Repeat cannot fire while the queue is leaving. It skips after a loss (the defeat path is unchanged) and
  never fails the run: a missing template or a miss logs and falls through to Start Game, which polls on a
  deadline. `repeat.png` is captured but has never been matched in a real win.
- **`change_gamemode` is searched *and* waits** (`images/match/win_change.png`,
  `nav_images.win_change_image`, a Vision row under *In match*). **Finding a template is not proof the
  element is interactive** — `matchTemplate`'s normalized correlation ignores a uniform brightness scale, so
  a panel at 40% opacity mid-fade still scores ~0.93. Measured from the user's log: `win_change` matched 0.93
  **one second** after Match Play, the click was swallowed, and the run died at the next step with
  `Challenge card not found (best 0.42 < 0.70)`. That is what a failed handover after a win looks like, and
  **no confidence threshold can see it** — only a wait can. So `_find_click(..., fade_wait=)` sleeps
  `panel_fade_wait`, re-finds (the panel slides while it fades, so the first centre goes stale; a single
  look, first match stands if it misses), then clicks. Both paths pay it now, searched and fallback.
  Pass `fade_wait` **only** where the element is arriving from a transition we just triggered — everywhere
  else it is pure latency. `challenge.CHANGE_GAMEMODE_CLICK` (676,391, still an 816×638 coordinate) is the
  missing-template fallback. **The PNG on disk predates the resize** — but it scores 0.93, so it matches.
- **Select Stage then Start, both searched.** `click_select_stage` (`images/lobby/select_stage.png`) runs
  before `click_start_match` (`images/lobby/start_match.png`) in both `start_stage` and `start_challenge`.
  Order is not negotiable: Start does not exist until the stage is selected, which is what "Start wasn't
  there" always meant. Both moved off fixed coordinates because they sit on the stage panel, whose height
  differs per stage. `START_COORDS["confirm"]` / `["start"]` and `challenge.SELECT_STAGE_CLICK` /
  `START_CLICK` are fallbacks used only while a template is missing, and the log says when one was used.
  `select_stage.png` is captured, never matched in a run yet; don't confuse `click_select_stage` (the
  confirm button) with `select_stage` (picking the map card from the list).
- **The placement picker marks the Start Game band.** `placement_overlay.START_GAME_ZONE`
  (450,194 252x42, the user's corners 450,194-702,236) is drawn as a translucent amber block with its label
  above it, under the dots so a placed one stays visible. **`_zone_label_rect` measures the rect from the
  font, not the band** — the label is 528px against a 252px band, and a band-width rect cut both ends off.
  It clamps to the client and drops inside the band when there is no room above. It is a *warning, not a rule* — the pick is still accepted,
  because the button only exists before the wave starts, so only a **pre-placement** step at that
  coordinate presses Start Game instead of placing. `show_zones=not live`, so it appears for placement
  picks and not for sequence-action picks (those aim at live on-screen UI a block would hide).
- Units page: 72 steps, unit/sequence kinds, placement picker, slot colours, auto-upgrade **level**
  (`v` pressed N times, 0–7), Sell / Pre-placement, chip copy/paste (one-shot, never copies x/y),
  save/load/import.
- Task queue (Settings > Tasks, `settings.json` key `tasks`): **three target slots plus a challenges
  toggle.** Challenges are not a slot — `decide()` preempts regardless of position, so a slot spent one of
  three places storing a boolean. The toggle is `AppSettings.run_challenges` → `TaskDirector.challenges`,
  read fresh at each F1, with its own challenge-map picker + *Edit units* (all five maps need a plan,
  because the game picks). `TaskStore.take_legacy_challenge_slot` migrates a queue saved with a challenge
  slot and switches the toggle on, once and idempotently; `KINDS` is now `(off, target)` and
  `TaskSlot.from_payload` turns the old kind into an empty slot. Order is unchanged and probed: challenges
  first, then targets each for its own limit, then it loops, and a challenge interruption does **not** reset
  `_done_in_slot`. `Next task` step appended **only** in Task mode; a plain gamemode run gets an empty
  `TaskDirector`, so the queue can't hijack it.
- **Match tolerance is per template** (Vision > Templates: a 0.60–0.99 spin plus *Test*). Resolved inside
  `find_until` by `image_search.confidence_for(path)` when `confidence=None`, which is what both navigators
  now pass — so a threshold applies to every search of that image with no plumbing. `LobbyNavigator` and
  `UnitPlacer` no longer have a `self.confidence`; `_miss` reports the template's own number and marks it
  `(tuned)`. Stored by `config/regions.py::ConfidenceStore` under the `confidence` key as a plain float
  (`_OverrideStore` took an `encode` hook for that), `clean_confidence` **rejects** rather than clamps, and
  setting a row back to 0.70 *deletes* the override rather than pinning it. Floor 0.60 and no
  auto-calibrate on purpose: the old **global** tolerance setting drifted to 0.57 and matched wrong
  screens, which is why *Test* exists — `best_score` accepts anything, so the number is set against a
  measurement. Not shipped by `build_exe.py`, like `regions`/`points`: it is per-machine tuning.
- **A played row reads "Done" in the stats panel.** `ChallengeRead.played` is set by
  `ChallengeTracker.mark_done`, *not* by the scanner — the skip list is private to the tracker and the panel
  is handed nothing but the reads, so a finished challenge kept showing "Ready" (its star is still bright and
  it still has runs left, so the pixels agree with "Ready"). `_state_key` checks `played` first. `_skipped`
  remains the authority for decisions; the flag is display only, and a rotation roll clears `reads` so it
  can't leak. `_next_task_step` re-emits `challengesRead` right after `note_match`, without which the flag
  never reaches the UI.
- **Camera setup can run once per session** (Settings > Main, `camera_once_per_session`, **default off**).
  Saves the ~8s sequence on every match after the first. Default off on purpose: every placement coordinate
  is stored against one camera angle, so if Roblox resets the camera on a stage load, skipping misplaces
  every unit *silently* — worse than a slow start. `_camera_is_set` is set only by a **blocking** run (a
  fire-and-forget one is still moving the camera as it returns) and reset on attach, on a private-server
  re-join, and when the toggle is switched on. The zoom hold is a delay now (`camera_zoom`, 3.0s, seconds in
  the store and ms in the script) — it is two holds, so it is ~6s of the ~8s. Lower it in steps; if
  placements drift, it is too low. `PITCH_DELTA` and `pitch_steps` are **not** tunable and must not become
  so: retuning the pitch invalidates every stored placement coordinate.
- **The Discord embed carries task progress** (`_queue_fields`): runs left on the current target and what
  follows it, from `TaskDirector.runs_left()` / `next_target_label()`, both derived from `_done_in_slot` so
  they cannot drift from what `note_match` advances. Task mode only, targets only — a challenge row's quota
  is already in `Challenges today`.
- Challenge panel scan: OCR per box, `parse_limit` tolerates noise, `match_map_name` fuzzy-matches the 5
  maps, greyed star by HSV saturation p90 vs `STAR_SATURATION_MIN` (60; measured greyed 6, active 242).
  `scan_if_open` trusts a read only when some row parses a real `n/10`. The poll waits for all three rows
  (`CHALLENGE_PANEL_READ_TIMEOUT` 8s) because they fade in one at a time.
- **`start_challenge` logs all three legs now** (`row N → Select Stage → Start`, joined like
  `start_stage`'s trail). It used to return only the Start message, so a leg that fell back to a **fixed
  coordinate** announced it into a string nobody read. If a click looks misplaced, read that line first:
  `(fixed coordinate` in any leg is the bug, and a searched leg prints its score.
- Challenge play: every runnable row is tried, not just the first; an unidentified map or an empty
  `configs/Challenge/<Map>.json` is marked done and the next row tried. Not all five maps need configuring.
- **A rotation that rolls *during* a challenge is caught on both handover paths.** `_next_task_step` had
  the `needs_rescan()` check only on the non-challenge branch, so a challenge finishing just after :00/:30
  handed over to a target instead of the three fresh challenges — measured: challenge 3 started 08:26:49,
  won 08:31:04, and the queue went to `Events / Villian Invasion`. The decision it acted on said "target"
  only because `decide()` → `note_time()` had just cleared the reads. The challenge branch now checks
  `needs_rescan()` before believing that decision and calls
  **`_reread_challenges_and_stage`** — extracted from `_rescan_challenges_after_match` because that one
  starts with `leave_match`, and this path has already left. Callers of the helper must set
  `_entry_screen = ENTRY_MODE_PANEL` first. Don't collapse them back together.
- **A row is only retired for a reason about the row.** `_start_challenge_run` returns
  `(started, why, about_this_row)`; `_start_task_mode` calls `mark_done` only when `about_this_row`, and
  `break`s otherwise. It used to mark unconditionally, so a *failure to start* (Roblox gone for a moment,
  AHK missing, an exception in the starter) retired a `10/10` row with a bright star for the rest of the
  30-minute rotation — that was the "it skips an available challenge, seemingly at random" report. The scan
  was never the fault: a real panel reads `star sat 244-246`, maps at 1.00, limits `10/10`.
  `_stage_next_after_challenge` now marks a dead row too, so a mid-run handover onto an unconfigured map
  doesn't leave the next F1 choosing the same one.
- `_entry_screen` (`ENTRY_LOBBY` / `ENTRY_MODE_PANEL` / `ENTRY_CHALLENGE_LIST`) decides the first click of
  the next task, because reaching the challenge panel consumes the lobby.
- Discord webhook (Settings > Main): 4-field embeds (Stage / Challenges today / Record / Time) on start,
  win, loss and end; win/loss carry a screenshot grabbed `result_screenshot_delay` after the match.
- Every `settings.json` writer goes through `store.update_json` (one `RLock` across read+write) — six
  stores share the file and the macro worker writes stats every match.
- Stats page, log panels (`LogView`, capped + auto-scroll), `log.txt` rotation at 2MB, private-server join
  from a share link.
- **`PlacementOverlay` cancels when it stops being the active window** (`changeEvent`, guarded by
  `_was_active` so a WindowDeactivate during show can't kill it as it opens). Escape is only delivered to the
  *active* window, so any click on the main window used to leave the picker open with no key that could close
  it — which is one root cause behind three reports: Escape dead after clicking away and back, Escape dead
  after a double-clicked Set (the second click takes activation), and a chip click looking ignored because it
  was spent taking activation back. Cancelling loses nothing: a pick is one click.
  `UnitsPage._open_overlay_for` now **replaces** an open picker instead of refusing, so a second Set always
  leaves exactly one, on the step just asked for. Its cursor is `BlankCursor` + the crosshair `_paint_hover`
  draws, antialiasing off for those two lines — same as `RegionOverlay`, which it was inconsistent with.
- **The picker overlay aims at a pixel** (`macro_tester.RegionOverlay`). The OS `CrossCursor` was several
  pixels thick with no findable centre, so the cursor is `BlankCursor` and the overlay draws its own 1px
  crosshair (both modes, before the drag as well as during), a 1px selection rect inset by one pixel so the
  stroke doesn't cover the row being cropped, antialiasing off so lines land on pixel boundaries, and a
  live `x,y` / `x,y WxH` readout beside the cursor that flips near an edge.
- **Challenge OCR boxes are user-editable** (Settings > Vision, bottom section). They are read *blind* by
  the recogniser, so a box a few pixels off returns confident nonsense rather than failing — one machine's
  measurements can't serve everyone. `config/regions.py::RegionStore` persists overrides to `settings.json`
  under `regions`, keyed by `challenge.region_key` (the same names the panel dump writes, so the PNG you
  look at names the box you fix). `clean_box` **rejects** rather than repairs (4 ints, sides ≥ 4, in
  bounds); a hand-broken entry is dropped without stopping startup.
  `content/challenge.py::apply_region_overrides` holds a module-level override set read through
  `star_region` / `limit_region` / `map_region` / `reset_timer_region` / `row_click` — **read the accessors,
  never the `*_REGIONS` tables**, or an override is ignored. Module-level rather than injected into
  `ChallengeScanner` on purpose: `debug_boxes()` and `row_click()` read the same boxes, and a dump showing
  boxes the scan isn't using is worse than no dump. `row_click` is derived from the *current* map region, so
  re-measuring a row moves its click too. `MainWindow` applies the stored set at construction, before
  anything reads it.
- **Image Manager (Settings > Vision, `ui/image_manager.py`) is the only place images are captured.**
  `catalog()` derives 27 template rows from `content/nav_images.py` + `GAMEMODES` and 12 map-image rows
  from `map_image_catalog()`, so a schema addition appears on its own; each row shows a thumbnail and its
  real pixel size. A template's Capture reuses `macro_tester.RegionOverlay` and
  `ImageSearchEngine.capture_png` — the same mss pixels the matcher reads — rejects a box under 4px and
  waits 150ms after the overlay closes so the crop isn't of the picker. A **map image**
  (`full_client=True`, `images/reference/**`, the placement picker's backdrop) has no drag at all: it
  saves the whole client rect, so the overlay can never cover what is being captured. No cache clear
  needed (the template cache keys on mtime). `PER_ACT_MAPS` decides one picture per act (Raid, Events)
  versus one per map (Story, Expedition); Challenge has no rows because `load_reference` falls back to the
  Story picture of the same map. Events rows come from `RouteStore` (its events and acts are
  user-authored), and **Refresh rebuilds every list** so an act added in Run > Route appears without a
  restart. Overwrites without a confirm dialog, unlike the two buttons it replaced. Four inner tabs
  (Templates / Map images / Boxes / Points), each scrolling its own list; header is one line plus two icon
  buttons.
- **Click points are user-editable** (Vision > Points): 10 act rows from `acts.act_specs()` and 2 from
  `start_stage.point_specs()` — Story's Hard Mode toggle and Expedition's difficulty cycle, the only
  start-sequence clicks that are blind. `confirm` / `start` are deliberately **not** editable
  (`BLIND_STEPS`): `click_select_stage` / `click_start_match` search `select_stage.png` /
  `start_match.png` and only read the coordinate when the template is missing, so a row for them would do
  nothing while looking like it should. Same
  shape as the challenge boxes — `config/regions.py::PointStore` (`settings.json` key `points`,
  `clean_point` rejects rather than repairs) and a module-level override set in each content module, read
  through `act_coord` / `start_coords` / `difficulty_coord`. **Read the accessors, never `ACT_COORDS` /
  `START_COORDS` / `DIFFICULTY_COORDS`**, or an override is ignored. `start_coords` merges per step, so an
  override can't invent a `hard_mode` for a gamemode that has none. `RegionStore` and `PointStore` share
  `_OverrideStore`, so the read/clean/write-under-one-lock logic exists once. `MainWindow` applies both
  stored sets at construction, before anything reads them.
- Input settle scales with refresh rate: `NUDGE_SETTLE_FRAMES = 33`, `nudge_settle_ms(hz)` clamped
  [200, 900], set from `display.refresh_hz_for_window` on attach. 165Hz is identical to the old constant;
  60Hz gets 550ms. **Untested in game.**

## Untested in game

- **Once-per-session camera.** Nobody has confirmed the camera actually survives a stage load — that is the
  whole question the toggle exists to answer, and it is why the default is off. Turn it on, run two
  challenges, and check the second match's placements land where the picker showed them.
- **A lower `camera_zoom`.** Untried below 3.0s; the floor is a property of Roblox's zoom rate.
- **The task-progress embed field.** Built and probed, never seen in Discord.
- **The mid-challenge rotation re-read.** The tracker half is probed against the real 08:26→08:31 timings;
  the navigation half (`_reread_challenges_and_stage` from the gamemode panel after a challenge) has never
  run. Watch a challenge that finishes just after :00 or :30 — it should re-read and play the new rows
  instead of handing over.
- **The Start Game park.** Fixes a reproduced failure, so worth watching: a pre-placement run should reach
  Start Game instead of dying at `best 0.47`. If a tooltip still wins, the next lever is a short settle after
  the park — but the search already polls, so suspect the park point before adding a wait.
- **Mid-step stop.** Probed (a 30s search, the 60s wait and the 900s outcome wait all return in under a
  second, and no keep-alive click leaks out), but not pressed in a real match. Expect F1 to be obeyed within
  ~a second unless an AHK script is mid-flight.
- **`_restart` when frozen.** F3 used to re-exec `sys.executable -m sloppykeys`, which is nonsense for
  `SloppyKeys.exe` — so F3 in the *built* app would have killed it without restarting it. Now it drops the
  `-m` form when `sys.frozen`. Never exercised in a build.
- **The Start `fade_wait`.** This is the fix for a failure that was reproduced twice, so it is the one thing
  most worth watching: the next challenge run should reach `Stage loaded` instead of timing out after 60s.
  If it still doesn't, raise `panel_fade_wait` above 1.0s before suspecting the nudge.
- **The three remaining removed sleeps** (before `click_select_stage` ×2, after the challenge-list close, and
  after `click_play`). Verified by reading what follows each, not by a run — and the Start one taught us that
  reading isn't proof. If a chain fails at Select Stage or a card, give that leg a `fade_wait` the same way,
  rather than restoring a blind sleep or raising `search_timeout`.
- The challenges toggle **saves correctly** (seen in `log.txt`) and the migration **ran** in the project
  tree — `[{challenge},{off},{off}]` became three empty slots with the toggle on, which was the whole of
  that file's queue. The built app's own `settings.json` still holds
  `[{challenge},{Events/Villian Invasion/Act 1 x50},{off}]`, so **the migration has not yet run against a
  queue that contains a target.** It preserves one in a probe; watch the first launch of the rebuilt exe.
- **Per-template thresholds work** (*Test* measured `play.png` 0.972, `events.png` 1.000,
  `select_stage.png` 0.954 in the user's log), but no threshold has been *changed* from 0.70 yet.
  The Vision row's right-hand column is Capture on top, then a 56px spin + a 25px **crosshair-glyph**
  button = `BUTTON_W` exactly. Three things were needed to stop the text clipping, all of them still
  needed: `NoButtons` (Qt spends ~16px on arrows), inline `padding: 0px 2px` (the theme's spinbox rule is
  roomier than 4 characters allow), and the glyph instead of the word "Test". **Don't measure text width in
  an offscreen probe** — Qt has no fonts there and substitutes a much wider one, so the check fails on a
  layout that is fine; the user is the sensor for legibility.
- **"custom" in Vision > Boxes/Points now means *different from the default*.** It used to mean "an override
  row exists", and since several points were stored at exactly their promoted default, every one read
  "custom" while clicking the identical pixel — which looks like the app having changed something behind
  your back. Reset stays enabled whenever a row exists. The user reset those points, so the stored
  duplicates are gone from this tree.
- **The picker changes need eyeballing** — the deactivation cancel is verified headless, but whether a chip
  click now selects on the first press, and whether the blank cursor reads well over a reference image,
  only the user can see.
- **The installer has never been run.** It compiles; nobody has installed from it. Three things to check on
  a first run: a Vision capture still saves under `%LOCALAPPDATA%\Programs\SloppyKeys`, uninstall asks before
  deleting data, and choosing a Program Files path raises the writability warning.
- Refresh-rate-scaled click settle on the 60Hz monitor.
- The map-image rows in Vision: nobody has captured a backdrop through them yet, so the picker has not
  been checked against one.
- The re-picked act points and Hard Mode toggle: saved and promoted to defaults, but no run has clicked
  them yet.
- Start position (`Walk to position`) for any target.
- A handover from a finished challenge into a target, and `_rescan_challenges_after_match` (leave match →
  change gamemode → Challenge card).
- **The `change_gamemode` fade wait**, which is the fix for the one handover failure actually seen in a log.
  If it still dies at `Open challenge list`, raise `panel_fade_wait` above 1.0s before suspecting anything
  else, and check whether the *click* landed (did the gamemode menu open at all?) rather than the search.
- Removing `join_wait`: the two `wait_for_match_ready` polls have never run without a 5s head start.
- An Events full pass (route → camera → position → placement → result), and `_ensure_lobby` re-joining the
  private server when the Events button isn't found.
- Raid: coordinates, stage match, per-act reference lookup, start-position walk — all first-run.
- Auto-upgrade press count (does `v`×3 land on level 3, does a 7th press turn it off?) and the priority
  cycle (`r` from "First").
- Settings page fit (probe says page minimum 346px in a 408px panel; nobody has eyeballed it).

## Known broken / open

- **Qt logs a wrong startup geometry, cause unreproduced.** At launch only:
  `Unable to set geometry 1690x1004 ... Resulting geometry: 1690x1098`. The 1098 is **absolute** — the same
  number came back when the window was 886 tall — so it is not derived from our size. Ruled out by
  measurement: the layout (`minimumSizeHint()` measures exactly 1690x1004) and the flags/content (four probe
  variations — bare widget with the same flags, plain window, shorter window, and the real `MainWindow` with
  `theme.stylesheet()` applied exactly as `run()` does — all produced the correct size).
  `MainWindow.showEvent` re-asserts `_enforce_window_size()` immediately and on the next tick so nothing is
  painted at a size Windows invented. **That patches the symptom, not the cause**, and the final geometry was
  already correct (Qt, `GetWindowRect` and DWM all read 1690x1004), so this is cosmetic. If it ever becomes
  visible, the next thing to try is a `nativeEvent` trace of `WM_WINDOWPOSCHANGING`; a third-party window
  manager altering it is the remaining suspect.

- **The run's first placement (Step 1, ~1s after Start Game) sometimes can't select its unit**, while every
  later step at coordinates 38px away is fine — so it is timing, not position. `open_unit_panel` re-clicks
  the recorded point up to 3 times and parks between. **Don't reintroduce a coordinate offset ladder**
  (`SELECT_OFFSETS`): it was tried twice and `log.txt` showed no non-zero offset ever won. Next moves if 3
  clicks aren't enough: a short settle after Start Game, or a bigger `images/match/unit_ui.png` (6×15px
  today) with a measured region.
- **No mid-run rotation *into* a challenge from inside a stage.** Needs the in-match legs
  (`match_play` → `win_change` → Challenges). The Challenges button needs no template (OCR locates the
  word).
- **The pre-decision challenge scan runs on the UI thread** (`_start_task_mode` from the hotkey poll,
  sleeps + AHK `wait=True`). The UI freezes for a few seconds and the log lines all arrive at once — they
  are late, not missing. Fixing it means marshalling the decision back from a worker.
- **Expedition is unmeasured**: needs `START_COORDS["Expedition"]`, `STAGE_SEARCH_REGIONS["Expedition"]`,
  three stage PNGs, three reference images.
- Only the **Regular** challenge rows are read. Daily and Weekly have their own headers and countdowns and
  would need their own coordinates — ask before assuming.
- Clean-ups: use the Run page selection in the Full-run dialog, `select_stage` scrolls one direction only,
  the website download URL is unset.

## Gotchas

- **AHK owns all synthetic input.** Python never moves the mouse or presses a key via Win32.
- **Stay outside the game**: pixels in (mss + cv2), OS-level input out (AHK). No injection, process memory,
  hooks, `PostMessage` clicks or anti-cheat evasion. Roblox fast flags are out for the same reason.
  Only process call is `OpenProcess` with `PROCESS_QUERY_LIMITED_INFORMATION` for the exe name.
  **Audited whole-tree:** zero hits for ReadProcessMemory/WriteProcessMemory/VirtualAlloc/CreateRemoteThread/
  SetWindowsHookEx/PostMessage/SendMessage/SendInput/keybd_event/PROCESS_VM_READ/ROBLOSECURITY/FFlag. Don't
  redo that grep unless new Win32 lands. `roblox_window.py::activate_window` uses `SetForegroundWindow`,
  which is window activation, not input — the same thing AHK's `WinActivate` does in `_header()`.
- **`image_search.to_absolute_path` passes an absolute path through on purpose** — don't "harden" it. The
  Macro Tester's *Select image* (`window.py::_on_select_image`) hands it a QFileDialog result, so confining
  it to `app_root` breaks that feature. Worst case from a hand-edited `images/images.json` is a `cv2.imread`
  of the user's own file, in the user's own process, scored and discarded.
- **A failed screen capture reports itself now.** `ImageSearchEngine(app_root, log=self._log)`;
  `_report_capture_error` dedupes on the last message, because a capture failing inside `_find`'s 0.12s poll
  would otherwise write hundreds of identical lines. Without it an mss failure reached the caller as "no
  match" and read as a template problem. `log=` is optional, so the engine still works headless.
- **The client size is load-bearing, not a layout choice.** 816×638 gave soft text and off-scale
  templates; that was the cause of the long "blurry on one monitor, templates won't match" saga. It is
  1152×756 now to match Cream's macro. Don't change `theme.VIEWPORT_WIDTH/HEIGHT` without re-capturing
  everything, and keep `WINDOW_WIDTH/HEIGHT` equal to the layout's `minimumSizeHint` (measure it — surplus
  becomes dead space and an oversized drag rect). Coordinates are also tied to `PITCH_DELTA = 1000`.
- **`cv2.matchTemplate` is not scale invariant** — a wrong-size crop can never match, and it fails
  intermittently, which reads as a tolerance problem. Wrong scale costs 0.253 correlation. Bit depth is a
  red herring (measured: 256 colours costs 0.0003). Runtime multi-scale matching was rejected: ~24x cost,
  and it hides bad templates.
- **There is no *global* match-tolerance setting and there must not be one.** The old one reached 0.946 and
  its Auto button calibrated from whatever was on screen; both stay deleted. `DEFAULT_CONFIDENCE` is 0.70
  and that is still the right answer for almost everything — a template that can't clear it is usually the
  wrong crop, so recapture before lowering. Tolerance is **per template** now (floor 0.60, no auto), which
  is a different failure surface: one image can't break the others. `best_score` +
  `LobbyNavigator._miss` log `Play not found (best 0.66 < 0.70)`, which is the diagnostic, and the Vision
  row's *Test* button surfaces the same number on demand.
- **Also deliberately removed, don't rebuild:** `RegionMemory` / `image_regions.json` (auto-learned search
  regions) and the OCR-template fallback (`core/text_locate.py`). Whole-client OCR with detection on is
  1251–1851ms, ~100x a template match, so OCR-primary is off the table. The *existing* OCR — challenge
  scan, `core/ocr.py`, VISION rows — stays and is required.
- **Navigation search regions are gone on purpose.** `nav_images.STAGE_SEARCH_REGIONS` (the per-gamemode
  stage-label band) is deleted; `select_stage` searches the whole client. A region had to be hand-measured
  per gamemode, went stale the moment the viewport size changed, and a band shorter than its template makes
  the match impossible rather than slow — for ~17ms a look. Regions that remain, both editable in the UI and
  both worth keeping: per-step boxes on Events routes (`routes.json`, Route tab) and the challenge OCR crops
  (`settings.json` `regions`, Vision tab). Both are read-a-known-place cases, not search narrowing.
- **Ruled out by measurement, do not re-investigate:** process DPI awareness (unaware vs per-monitor-v2
  returned byte-identical rects), negative coordinates / mss on a left-hand monitor, AHK's coordinate
  space, and capture "sharpness" (the metric was noise and was removed).
- **Roblox above 100% display scaling is separately broken** (bigger *and* blurry, a known Roblox
  regression). Everything here is calibrated at 100%; `display.scale_percent_for_window` +
  `_warn_if_monitor_scaled` say so in the log. Fix is environmental.
- **Never touch a Qt widget or make a dialog from a worker thread**, and no `QTimer.singleShot` on a
  `QThreadPool` worker — no event loop there, so it never fires. Marshal back with a queued signal, and
  keep a reference to a running `QRunnable`.
- **Don't put `runner.tick()` back in `_poll_hotkeys`** — that 40ms timer is the UI thread.
- **Stopping is cooperative.** F1/F2 → `request_stop()`, the worker calls `stop()` between steps. Never
  kill the AHK process: the camera script holds `i` and the right button down and a kill never releases.
- **`compileall` doesn't execute code.** Construct `MainWindow` in a headless probe before claiming a UI
  change works. Probes must fire no input — it lands on the user's live game. Delete them after.
- **A module-level `def` dropped inside a class body** turns every method after it into a nested function:
  it compiles and imports, and F1 dies with an `AttributeError` inside the hotkey timer, printing to the
  terminal and nowhere else. `tests/test_placement_plan.py` asserts `UnitPlacer`'s methods resolve.
- **Guard every position/mask sync with `IsIconic`** — a minimized window reports coords near −32000.
- **Documented dead ends:** reparenting Roblox (`SetParent`), `LWA_COLORKEY`, the Tauri/WebView2 stack.
- **On-disk formats are stable.** `configs/`, `images/`, `settings.json`, `routes.json` all hold user data;
  readers default new keys. `routes.json` is rewritten whole with no backup and this is not a git repo.
- **Two app instances still race on `settings.json`** — `update_json`'s lock is per-process.
- **Validate names that become paths**: `unit_configs.safe_component`, `nav_routes.clean_name`,
  `nav_route.safe_rel_path` (rejects, doesn't repair), `sanitize_game_key`, `start_position.MOVE_KEYS`,
  `settings._CODE_PATTERN`. Rejections, not escapes.
- **An AHK script's timeout must cover its own sleeps** — `placement._press` scales it with hold duration.
- **A stored delay in `settings.json` overrides the default**, so lowering a default does nothing for a
  user who has already touched that field. The user has `image_search_cooldown` at 1.5 and
  `search_timeout` at 1.5.
- **Feedback in a scrolled panel belongs at the top** — `RouteEditor`'s note was below the fold for weeks.
- **Control widths are measured, not guessed.** A widget in a narrow row clips silently. For a
  `QPushButton`/`QComboBox`, `sizeHint().width() > width()` is a real clipping test (the hint includes the
  QSS padding — `#tab`'s `padding: 7px 18px` is 36px, which is why a row button needs `#rowAction`
  instead). For a `QLineEdit`/`QSpinBox` the hint is a generic ~110px default and means nothing; measure
  `fontMetrics().horizontalAdvance(text)` against the field instead. Spin-box step arrows are styled to
  `width: 0` because they ate 16px of every narrow field.
- **Never dump widget text wholesale in a probe.** The Main tab holds the private-server link and the
  Discord webhook URL in `QLineEdit`s, and a width audit that printed field contents leaked both. Exclude
  those fields or print lengths.
- **Never rewrite a file through a PowerShell pipeline.** `Get-Content | Set-Content -Encoding UTF8` reads
  UTF-8 as the console codepage and re-encodes it, mangling every non-ASCII character and adding a BOM. It
  corrupted 12 files once and `HANDOFF.md` a second time. Use the editing tools, or Python with
  `encoding="utf-8"`. To check: decode with `utf-8-sig` and look for `Ã Â â€ ΓÇ`.
- **Widget visibility can't answer a data question** — everything on a non-current `QStackedWidget` page
  reports not-visible.
- Small stylised text OCRs approximately (`start_game.png` → "Start Ge"). No caller may require an exact
  string.
- AHK v2: `FileDelete` on a missing file throws, hangs the script behind a dialog. Use `FileOpen(path,"w")`.

## Rules for this file

- Edit sections in place. No changelog, no dated entries, no second handoff file.
- Update it in the turn that changes reality, before reporting done.
- An item described as broken here **is** broken. When the user moves on to another topic, close the
  previous fix out in that turn: move it to Working, delete its Untested/Next entry, cut the story of how
  it was found.
- Keep only what a new agent needs to act. A dead end earns one line **only** if someone would retry it.
  Delete measurements once they've served their purpose.
- Don't promote anything to Working on the strength of `compileall` or a probe. Say "untested".
