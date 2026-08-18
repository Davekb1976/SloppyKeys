---
inclusion: always
---

# Where project knowledge goes

## The mechanisms Kiro actually gives us

Verified against `kiro.dev/docs/steering` and `kiro.dev/docs/skills` — check there rather
than guessing, because the wrong front matter fails silently.

| Mechanism | Loads | Front matter |
|---|---|---|
| Steering `always` | every turn | `inclusion: always` |
| Steering `fileMatch` | when a matching file is read or written | `inclusion: fileMatch` + `fileMatchPattern` |
| Steering `auto` | when the **request** matches the description | `inclusion: auto` + `name` + `description` |
| Steering `manual` | only when referenced as `#file-name` | `inclusion: manual` |
| **Skill** | when the request matches the description | `.kiro/skills/<name>/SKILL.md`, `name` + `description` |

A skill is the portable form (the open Agent Skills standard, importable and shareable) and
is what we use for a workflow. `auto` steering is the Kiro-only equivalent — same
description-matching, so **it has the same blind spot: if the user's words don't imply the
topic, neither one fires.** That is the whole reason some things must stay `always`.

Skill rules that bite if ignored: `name` **must match the folder name**, lowercase with
hyphens; long reference material goes in `references/` and is only read when `SKILL.md`
points at it; `.kiro/skills/` is committed so it travels with the repo.

## The decision

Ask in order and stop at the first yes.

1. **Would the code be wrong, unsafe, or silently broken without it — on a turn that never
   mentions the topic?**
   → **Steering `always`.** The ban surface, the pinned viewport, threading, "commit after
   every change". Description matching cannot save these: nobody says "and mind the ban
   surface" before asking for a feature.

2. **Does it only apply while doing one identifiable kind of work, and would the request
   name that work?**
   → **Skill.** Building a UI surface, writing a commit message, cutting a release. Dead
   weight on every other turn, and the request supplies the trigger.

3. **Is it tied to a file path rather than to a request?**
   → **Steering `fileMatch`.** Useful as a *safety net* under a skill, not instead of one:
   it fires once a matching file is touched, which is after the design decisions are made.

4. **Is it a fact about *content* rather than about *how to work*?**
   → **Neither — put it in the code.** A new map, act coordinate, delay or keybind is a row
   in a `content/` or `config/` table. Documenting it here means two sources of truth that
   drift. `content/gamemodes.py` is the spec for gamemodes.

5. **Is it the answer to one question that already got answered?**
   → **Neither.** It belongs in the commit body or a code comment next to the thing. A
   measurement that explains a constant goes above the constant.

## Updating docs when the code moves

Stale guidance is worse than none: it aims work at symbols that no longer exist. This is not
a theoretical risk — `sloppykeys/ui/` was deleted in the pywebview migration and steering
went on describing `QWidget.setMask`, `QThreadPool` and `QT_SCALE_FACTOR` as current for
months, alongside dead references to `configs/` and `images/`.

**The doc edit ships in the same commit as the code, or in one right behind it.** Not "later"
— later is what produced the above.

Five triggers. When one fires, grep the docs for the old name *before* saying the work is
done:

| The change | What to re-check |
|---|---|
| Renamed or deleted a module, folder or symbol that any doc names | Grep for the old name across `.kiro/**` and the root `*.md`. A pointer to a deleted symbol is a bug. |
| Replaced *how* something works (Qt → pywebview, `configs/` → `operations/`, `SW_HIDE` → z-order) | Rewrite the section to lead with the new design and keep the old one **only** as a labelled dead end with its measurement. |
| Added a surface that a checklist should cover | Extend the existing list; don't start a parallel doc. |
| Measured a number that contradicts a documented one | Update it and quote the new measurement. A stale number is why someone retries a dead end. |
| Deleted a feature | Delete its guidance in the same commit. |

Two things that are **not** doc triggers: adding a row to a `content/` table (the table is
the doc), and fixing a bug without changing the approach (the commit body is the record).

When the user says "I want feature X", the doc question is only: *does X change a rule
already written down?* If yes, that edit is part of the feature. If it merely uses the
existing pattern, write no doc — the pattern already covers it.

## Splitting a topic

Version control is the worked example, and it is the case that proves rule 1. The *policy*
— one commit per change, verify first, push after — stayed `always` at ~35 lines; the
*mechanics* — message format, body rules, release procedure — moved to the `git-workflow`
skill.

It cannot all be a skill, and not for lack of a better mode: `inclusion: auto` matches the
**request**, and a request like "add a challenge card to the dashboard" contains nothing
about committing. The trigger for committing is *"a self-contained change is finished"*,
which is a state of the work, not a word in the ask — so description matching never fires
and the work would simply go uncommitted. Anything whose trigger is a state rather than a
phrase belongs in `always`.

When a topic has both halves, split it and have the steering half name the skill. Never
duplicate the content in both.

UI design went the other way entirely: none of it is true on a Win32 or OCR turn, so all
223 lines became the `ui-feature` skill. Architectural facts that *other* code must respect
— the game riding the topmost band, the dead ends — stayed in `coding-standards.md`,
because `bridge.py` and the macro have to honour them too.

## Where things live

```
.kiro/steering/<topic>.md          always-on. Front-matter `inclusion: always`.
.kiro/skills/<name>/SKILL.md       invokable. Front-matter `name` + `description`.
.kiro/skills/<name>/<extra>.md     reference material the skill points at.
```

A skill's `description` is the only thing read when deciding whether to load it, so it
must name the **trigger**, not just the subject: "Use when adding a UI surface, restyling
one, or wiring a control to the Python bridge." Split a skill's reference tables into a
second file so `SKILL.md` stays readable in one pass.

## Look it up instead of inferring it

The front matter above was first written from inference, and it was wrong in two ways —
reference material sat beside `SKILL.md` instead of in `references/`, and the `auto` and
`fileMatch` inclusion modes were reported as not existing. Both are one fetch away at
`kiro.dev/docs/steering` and `kiro.dev/docs/skills`.

The same rule as `implementation-process.md` §3 applies to tooling, not just APIs: search
and fetch the docs rather than reasoning from the shape of the thing, and say which is which.
"I could not find it documented" is only true after looking.

## How much detail

The test: **would a competent stranger do the wrong thing without this line?** If no, cut
it.

- **Write the rule, then the evidence.** A rule with a number behind it survives; a rule
  that reads as taste gets argued with. "Wrong scale costs 0.253 correlation" is why nobody
  retries multi-scale matching.
- **Record dead ends.** The most valuable content is what was measured and *failed*, with
  the reason. That is what stops a costly retry.
- **One place per fact.** If it is already in a code comment, do not restate it here;
  point at the symbol instead.
- **Don't document the obvious or the generic.** No "write clean code", no Python tutorial,
  no restating a library's own docs.
- **Prune when the code changes.** A steering file naming a deleted folder is worse than no
  file — it sends work at something that no longer exists. `configs/` and `images/` both
  outlived their references here.

## Length

**Hard stop: 500 lines for a steering file, 500 for a `SKILL.md`.** Past that, split it —
the file has stopped being one topic.

That number is **headroom, not a budget.** It exists so a genuinely dense file (the ban
surface, the calibration constants, the measured dead ends) never has to be cut for the sake
of a line count. It is not a target, and a file growing toward it is not a file getting
better. Most of these should sit well under half of it: the useful ones here are 36–271
lines, and `version-control.md` does its whole job in 36.

The length test is never the length. It is the paragraph above: *would a competent stranger
do the wrong thing without this line?* A 500-line file of necessary rules is fine; 120 lines
of restating the obvious is not. If a file feels long, the question is which lines fail that
test — not how to redistribute them to get under a number.

Two signals that beat the count outright:

- **Two audiences.** If half the file only matters while doing one kind of work, that half
  is a skill (`ui-design.md` was 223 lines that no Win32 turn ever needed).
- **A section you skim.** If you would skip it while reading for the answer, it is reference
  material: move it to `references/` and point at it. `SKILL.md` is read in full on every
  activation, so keep it actionable and push the tables out.
