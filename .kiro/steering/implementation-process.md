---
inclusion: always
---

# Implementation Process

Scale to the change. A typo or one-liner: climb the `ponytail.md` ladder, fix it, stop.
Anything touching a parallel surface (a page, a macro step, a setting, windowing) runs the
whole list. In doubt, treat it as non-trivial.

## Before writing code

1. **Restate the goal** in a sentence. If the request rests on a wrong assumption, say so
   and propose the better path. One clarifying question at most, and only if intent can't
   be inferred.
2. **Read the lines you're about to change.** Already correct? Say "already handled at
   `file:function`" and stop.
3. **Separate confirmed from inferred.** Unsure of a PySide6/Qt API, a ctypes signature, an
   AHK v2 command, an OpenCV/mss detail? Check the docs and the installed version
   (`requirements.txt`, the `.venv`). Never present a guess as a solution.
4. **Measure, don't infer.** For window geometry, Win32/DWM state, pixel output or DPI:
   write a throwaway probe that prints real numbers, read them, then form a hypothesis.
   Verify a platform call took effect by reading the attribute back — many Win32/DWM calls
   silently no-op.
5. **Visual bugs: the user is the sensor.** You cannot see the rendered window. Never assert
   a cause for pixels nobody has looked at; ask for a screenshot and change one variable at
   a time. A bug that appeared right after a change is caused by that change until proven
   otherwise — suspect your own last diff. "Helped but X still happens" means the diagnosis
   was incomplete: re-observe instead of stacking another blind patch.
6. **Map the blast radius** — grep every caller and fix the shared function once. The
   surfaces that move together are tabled in `coding-standards.md` §Parallel Surfaces.
7. **State the root cause**, not the symptom. For anything non-trivial, sketch 2–3
   approaches and pick the simplest complete one with the smallest blast radius.

## Validating — only what you touched

- `python -m compileall sloppykeys` — always. It does **not** execute code.
- One headless probe exercising **the changed path**, constructing `MainWindow` if `ui/` was
  touched. That is the only thing that catches a missing import or a bad signal wiring.
- Moved or inserted a `def`? Assert the methods still resolve (`getattr(Class, name)`). A
  module-level def dropped inside a class body turns every method after it into a nested
  function: it compiles, it imports, and it fails only when called.
- **Probes fire no input** — it lands on the user's live game. Delete them after.
- **Never print widget text wholesale in a probe.** The Main tab holds the private-server
  link and the webhook URL in `QLineEdit`s; a width audit that dumped field contents leaked
  both. Print lengths.
- Windowing/visual change: numeric geometry from a probe, plus tell the user what to eyeball.

**`tests/` is the durable half.** Framework-free assert scripts, one per logic area, run
individually: `.venv\Scripts\python.exe tests\test_placement_plan.py`. A probe proves a
change once and is deleted; a test goes here when the logic would be expensive to get wrong
again (step ordering, a parser, a path validator, methods resolving). Non-trivial new logic
leaves one behind — see `ponytail.md`.

Don't run a Macro Tester row, launch the app, or check code this change didn't touch. Say
what you verified and what you did not. "Probably fine" is not validation.

## Done means the ripples are handled

Not "the main edit compiles". Walk it: every parallel surface · saved JSON still loads ·
threading · `compileall` + a probe + probes deleted · the `IsIconic` guard and client-origin
resolution still hold · **a commit** (`version-control.md`).

## Reporting

**10 lines or fewer.** Files touched, one line each, naming the function or setting. Then
what you verified and what still needs the user. Name the commits rather than re-describing
them.

Cut: restating the request, rationale that's already a code comment or a commit body,
walking through code the user can read, what you decided not to do, recaps of previous
turns, and step announcements ("now I'll…", "let me check…"). A question gets an answer,
not a report.

## Shell

- PowerShell. Chain with `;`. No heredocs. `Select-String` has no `-Recurse`.
- Long lines overwrite earlier console output. To *read* output, redirect to a workspace
  file and read it back, then delete it. Fire-and-forget commands can trust the exit code.
- Python via `.venv\Scripts\python.exe`.
- **Never rewrite a file through a PowerShell pipeline.** `Get-Content | Set-Content` reads
  UTF-8 as the console codepage and re-encodes it, mangling every non-ASCII character and
  adding a BOM. It has corrupted 12 files at once. Use the editing tools, or Python with
  `encoding="utf-8"`.

## Running the app

`.venv\Scripts\python.exe main.py`, as a **background process in its own terminal**. Then
leave that terminal alone: **any further command in it kills the app.** To check it's alive,
read its output. Don't wrap it in `Start-Process`, `pythonw.exe` or output redirection. Stop
it with the titlebar X or `taskkill /IM python.exe /F`.

The app is the user's to drive. Don't press F1 or run a Macro Tester row for them — that
lands synthetic input on their live game.
