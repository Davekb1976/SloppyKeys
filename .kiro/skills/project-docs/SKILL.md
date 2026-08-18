---
name: project-docs
description: Decide where project knowledge belongs and write it — steering file, skill, code table, or nothing. Covers Kiro's inclusion modes and their blind spots, the always-vs-skill decision, how to split a topic, and how much detail earns its tokens. Use when adding or editing a steering file or skill, when asked where a rule or convention should live, or when docs need pruning after a refactor.
---
# Where project knowledge goes

The rule that does *not* live here: **a doc edit ships in the same commit as the code that
invalidated it.** That one is in `implementation-process.md` §Done, because its trigger is a state
of the work, not a phrase in the request.

## The mechanisms Kiro gives us

Verified against `kiro.dev/docs/steering` and `kiro.dev/docs/skills` — check there rather than
guessing, because wrong front matter fails silently.

| Mechanism | Loads | Front matter |
|---|---|---|
| Steering `always` | every turn | `inclusion: always` |
| Steering `fileMatch` | when a matching file is read or written | `inclusion: fileMatch` + `fileMatchPattern` |
| Steering `auto` | when the **request** matches the description | `inclusion: auto` + `name` + `description` |
| Steering `manual` | only when referenced as `#file-name` | `inclusion: manual` |
| **Skill** | when the request matches the description | `.kiro/skills/<name>/SKILL.md`, `name` + `description` |

A skill is the portable form (the open Agent Skills standard, importable and shareable) and is what
we use for a workflow. `auto` steering is the Kiro-only equivalent — same description matching, so
**the same blind spot: if the user's words don't imply the topic, neither one fires.** That is why
some things must stay `always`.

Skill rules that bite: `name` **must match the folder name**, lowercase with hyphens; long
reference material goes in `references/` and is only read when `SKILL.md` points at it;
`.kiro/skills/` is committed so it travels with the repo.

## The decision

Ask in order, stop at the first yes.

1. **Would the code be wrong, unsafe or silently broken without it — on a turn that never mentions
   the topic?** → **Steering `always`.** The ban surface, the pinned viewport, threading, "commit
   after every change". Description matching cannot save these: nobody says "and mind the ban
   surface" before asking for a feature.
2. **Does it only apply while doing one identifiable kind of work, and would the request name that
   work?** → **Skill.** Building a UI surface, writing a commit message, cutting a release. Dead
   weight on every other turn, and the request supplies the trigger.
3. **Is it tied to a file path rather than a request?** → **Steering `fileMatch`.** Useful as a
   *safety net* under a skill, not instead of one: it fires once a matching file is touched, which
   is after the design decisions are made.
4. **Is it a fact about *content* rather than about *how to work*?** → **Neither — put it in the
   code.** A new map, act coordinate, delay or keybind is a row in a `content/` or `config/` table.
   Documenting it here means two sources of truth that drift.
5. **Is it the answer to one question that already got answered?** → **Neither.** It belongs in the
   commit body or a comment next to the thing. A measurement that explains a constant goes above
   the constant.

When the user says "I want feature X", the doc question is only: *does X change a rule already
written down?* If yes, that edit is part of the feature. If it merely uses the existing pattern,
write no doc.

## Splitting a topic

Version control is the worked example and the case that proves rule 1. The *policy* — one commit
per change, verify first, push after — stayed `always` at ~35 lines; the *mechanics* — message
format, body rules, release procedure — moved to the `git-workflow` skill. It cannot all be a
skill: the trigger for committing is *"a self-contained change is finished"*, a state of the work,
not a word in the ask, so description matching never fires and the work goes uncommitted. Anything
whose trigger is a state belongs in `always`.

When a topic has both halves, split it and have the steering half **name** the skill. Never
duplicate content in both.

UI design went the other way entirely: none of it is true on a Win32 or OCR turn, so all 223 lines
became the `ui-feature` skill. Architectural facts *other* code must respect — the game riding the
topmost band, the dead ends — stayed in `coding-standards.md`, because `bridge.py` and the macro
have to honour them too.

The general shape: **always-on keeps the rule and the trip-wire; the skill or a code comment keeps
the evidence.** A dead end needs its name resident so nobody retries it; the measurement behind it
can be one fetch away.

## Where things live

```
.kiro/steering/<topic>.md          always-on. Front matter `inclusion: always`.
.kiro/skills/<name>/SKILL.md       invokable. Front matter `name` + `description`.
.kiro/skills/<name>/references/    reference material the skill points at.
```

A skill's `description` is the only thing read when deciding whether to load it, so it must name
the **trigger**, not just the subject: "Use when adding a UI surface, restyling one, or wiring a
control to the Python bridge."

## How much detail

The test: **would a competent stranger do the wrong thing without this line?** If no, cut it.

- **Write the rule, then the evidence.** A rule with a number behind it survives; a rule that reads
  as taste gets argued with. "Wrong scale costs 0.253 correlation" is why nobody retries
  multi-scale matching.
- **Record dead ends.** The most valuable content is what was measured and *failed*, with the
  reason. That is what stops a costly retry.
- **One place per fact.** If it is already in a code comment, point at the symbol instead.
- **Nothing obvious or generic.** No "write clean code", no Python tutorial, no restating a
  library's own docs.
- **Prune when the code changes.** A file naming a deleted folder is worse than no file — it aims
  work at something that no longer exists.

## Length

**Hard stop: 500 lines for a steering file, 500 for a `SKILL.md`.** Past that, split it: the file
has stopped being one topic.

That number is **headroom, not a budget** — it exists so a genuinely dense file (the ban surface,
the calibration constants, the measured dead ends) never gets cut for a line count. A file growing
toward it is not a file getting better; the useful ones here are 36–271 lines, and
`version-control.md` does its whole job in 36.

Always-on files are different: every line is billed on every turn, including the ones about
something else entirely. Treat resident length as a cost to justify per line, not as headroom.

Two signals that beat the count outright:

- **Two audiences.** If half the file only matters while doing one kind of work, that half is a
  skill.
- **A section you skim.** If you would skip it while reading for the answer, it is reference
  material: move it to `references/` and point at it. `SKILL.md` is read in full on every
  activation, so keep it actionable and push the tables out.

## Look it up instead of inferring it

The front-matter table above was first written from inference and was wrong twice: reference
material sat beside `SKILL.md` instead of in `references/`, and the `auto` and `fileMatch` modes
were reported as not existing. Both are one fetch away at `kiro.dev/docs/steering` and
`kiro.dev/docs/skills`. Search and fetch the docs rather than reasoning from the shape of the
thing, and say which is which.
