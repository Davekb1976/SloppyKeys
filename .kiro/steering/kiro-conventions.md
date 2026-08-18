---
inclusion: always
---

# Where project knowledge goes

Steering is loaded on **every** turn. A skill is loaded only when the work matches it. So
the question is never "is this useful?" — it is **"is this true on a turn that has nothing
to do with it?"**

## The decision

Ask in order and stop at the first yes.

1. **Would the code be wrong, unsafe, or silently broken without it?**
   → **Steering.** Invariants: the ban surface, the pinned viewport, threading, "commit
   after every change". These have no trigger word, so a skill would never fire in time.

2. **Does it only apply while doing one identifiable kind of work?**
   → **Skill.** Building a UI surface, writing a commit message, cutting a release. It has
   a natural trigger, and it is dead weight on every other turn.

3. **Is it a fact about *content* rather than about *how to work*?**
   → **Neither — put it in the code.** A new map, act coordinate, delay or keybind is a row
   in a `content/` or `config/` table. Documenting it in steering means two sources of
   truth that drift. `content/gamemodes.py` is the spec for gamemodes.

4. **Is it the answer to one question that already got answered?**
   → **Neither.** It belongs in the commit body or a code comment next to the thing. A
   measurement that explains a constant goes above the constant.

## Splitting a topic

Version control is the worked example: the *policy* ("one commit per change, push after")
is always-on, so it stayed in steering at ~30 lines; the *mechanics* (message format, body
rules, release procedure) moved to the `git-workflow` skill. When a topic has both, split
it and have the steering half name the skill. Do not duplicate the content in both.

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

Rough ceiling: a steering file over ~250 lines is probably carrying a skill inside it. A
skill over ~200 lines probably needs a companion reference file.
