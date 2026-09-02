---
inclusion: always
---
# Implementation Process

Scale to the change. A typo or one-liner: climb the `ponytail.md` ladder, fix it, stop.
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
   documented" is only true after looking — that applies to tooling (Kiro's own docs included),
   not just libraries.
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
   that move together are tabled in `coding-standards.md` §Parallel surfaces.
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
one behind — see `ponytail.md`.

Don't launch the app, press a button that drives the game, or check code this change didn't
touch. Say what you verified and what you did not. "Probably fine" is not validation.

## Done means the ripples are handled

Not "the main edit compiles". Walk it: every parallel surface · saved JSON still loads ·
threading · `compileall` + a probe + probes deleted · the `IsIconic` guard and client-origin
resolution still hold · **a commit** (`version-control.md`).

**Docs ship in the same commit as the code.** Renamed, deleted or replaced a module, folder, symbol
or approach that any doc names? Grep `.kiro/**` and the root `*.md` for the old name and fix it now —
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
- Broad "where does X live" exploration goes to the `context-gatherer` sub-agent, not a dozen greps
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
