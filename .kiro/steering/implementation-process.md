
# Implementation Process

Scale to the change. A typo or one-liner: climb the `ponytail.md` ladder, fix it, stop. Anything touching
a parallel surface (a new page, macro step, setting, windowing change) runs the whole list. In doubt,
treat it as non-trivial.

## Before writing code

1. **Restate the goal** in a sentence. If the request rests on a wrong assumption, say so and propose the
   better path. At most one clarifying question, and only if intent can't be inferred.
2. **Read the lines you're about to change.** If they already do the job, say
   "already handled at `file:function`" and stop. A rewrite of correct code is a regression waiting.
3. **Separate confirmed from inferred.** Unsure about a PySide6/Qt API, a ctypes signature, an AHK v2
   command, an OpenCV/mss detail? Check the official docs and the installed version
   (`requirements.txt`, the `.venv`). Never present a guess as a solution.
4. **Measure, don't infer.** For window geometry, Win32/DWM state, pixel output or DPI: write a throwaway
   probe that prints real numbers, read them, then form a hypothesis. Verify a platform call took effect
   by reading the attribute back — many Win32/DWM calls silently no-op. Probes must fire **no** input; it
   lands on the user's live game. Delete them after.
5. **Visual bugs: the user is the sensor.** You cannot see the rendered window. Never assert a cause for
   pixels nobody has looked at. Ask for a screenshot, change one variable at a time. A bug that appeared
   right after a change is caused by that change until proven otherwise — suspect your own last diff.
   "Helped but X still happens" means the diagnosis was incomplete; re-observe instead of stacking
   another blind patch.
6. **Map the blast radius.** Grep every caller and fix the shared function once. Surfaces that move
   together: the settings store ↔ a Settings control ↔ `MainWindow` wire-up; the gamemode schema ↔ Run
   selectors ↔ `configs/` paths ↔ `nav_images`; on-disk JSON (never break saved data); `core/win32`
   helpers; threading (anything that clicks or sleeps is off the UI thread, results marshalled back);
   `requirements.txt`.
7. **State the root cause**, not the symptom. For a non-trivial problem sketch 2–3 approaches, then pick
   the simplest complete one with the smallest blast radius, and say why.

## Executing

- Apply the change to every surface from step 6. Follow `coding-standards.md`.
- New macro step: logic in `macro/`, input via a generated AHK v2 script, exposed as a Macro Tester row,
  runnable in isolation.
- New setting: store + Settings control + `MainWindow` wire-up, applied where it's read.
- Win32 stays behind typed `core/win32` helpers with declared argtypes.

## Validating — only what you touched

- `python -m compileall sloppykeys` — always.
- One headless probe exercising **the changed path**, constructing `MainWindow` if `ui/` was touched.
  `compileall` doesn't execute code, so a missing import only shows up here.
- Moved or inserted a `def`? Re-probe the path that calls it and assert the methods still resolve
  (`getattr(Class, name)`). A module-level def dropped inside a class body turns every method after it
  into a nested function: it compiles, imports, and fails only when called.
- Windowing/visual change: numeric geometry from a probe, plus tell the user what to eyeball.
- Delete every probe.

Don't run a Macro Tester row, launch the app, or write a check for code this change didn't touch. Say what
you verified and what you did not. "Probably fine" is not validation.

## Done means the ripples are handled

Not "the main edit compiles". Walk this: the settings surface · every parallel variant · saved JSON still
loads · threading · `compileall` + a probe + probes deleted · the `IsIconic` guard and client-origin
resolution still hold · **a commit** · `HANDOFF.md` if the *state* changed. If unsure whether something
ripples, check.

## Recording it

**The commit is the record.** Format, scope names and the `Untested:` footer are in
`version-control.md`; follow it. One commit per self-contained change, staged by named path, after it
verifies.

`HANDOFF.md` is **current state only** — never a changelog. Touch it when the state changes: something
became untested, something is now known broken, a constant was re-measured, a dead end is worth warning
about. A fix that is already described by its commit needs no handoff edit.

- Write the state, not the story. Failed theories, intermediate diagnoses and the order things were ruled
  out belong in a commit body, not here. A dead end earns **one line** only if someone would otherwise
  retry it. Delete a measurement once it has served its purpose.
- Name real files and functions. One line each; no paragraph re-explaining a code comment.
- Untested is "untested" — never promote an item on the strength of `compileall` or a probe.
- **Moving on means it worked.** The user rarely says "that's fixed", they raise the next thing. When a
  turn arrives about a different topic, close the previous fix out **in that turn**: delete its Untested
  entry and any "in progress" wording. Don't leave a fixed bug described as broken. If the fix was never
  exercised, write "presumed working, never exercised".
- It is over its ~250-line budget. Every edit should leave it shorter than you found it.

## Reporting

**10 lines or fewer.** Files touched, one line each, naming the function or setting. Then what you
verified and what still needs the user. Name the commits you made rather than re-describing them.

Cut: restating the request, rationale that's already a code comment, in a commit body or in `HANDOFF.md`,
walking through code the user can read, what you decided not to do, recaps of previous turns, and step
announcements ("now I'll…", "let me check…"). A question gets an answer, not a report.

## Shell

- PowerShell. Chain with `;`. No heredocs. `Select-String` has no `-Recurse`.
- Long lines overwrite earlier console output. When you need to *read* output, redirect to a workspace
  file and read it back, then delete it. Fire-and-forget commands can trust the exit code.
- Python via `.venv\Scripts\python.exe`.

## Running the app

`.venv\Scripts\python.exe main.py`, started as a **background process in its own terminal**. Then leave
that terminal alone: **running any further command in it terminates the app.** That cost several turns
chasing a phantom startup crash. One dedicated terminal per launch; to check it's alive, read its output
rather than running a process query in it. Don't wrap it in `Start-Process`, `pythonw.exe` or output
redirection. Stop it with the titlebar X or `taskkill /IM python.exe /F`.

The app is the user's to drive. Don't press F1 or run a Macro Tester row for them — that lands synthetic
input on their live game.
