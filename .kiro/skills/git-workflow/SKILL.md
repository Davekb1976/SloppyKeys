---
name: git-workflow
description: Write a commit message for this repo, or cut a release. Covers the subject/body/Untested format, what belongs in a body and what does not, staging rules, and the release procedure including the dry run. Use when committing, when a commit message needs writing or fixing, or when the user says "release".
---

# Committing and releasing

`git log` is the project history — there is no handoff document. The `Untested:` footer is
the record of what has not been exercised in game (`git log --grep Untested`).

The *policy* — one commit per self-contained change, stage named paths, push after
committing — is in `.kiro/steering/version-control.md` because it applies whether or not
anyone invoked this skill. This file is the mechanics.

## Message format

```
<type>(<scope>): <subject>

<root cause, and the number that proves it>

Untested: <what has not run in game>
```

- **subject** — imperative, lower case, no full stop, ≤72 chars. What changed, not what
  was broken: `fix(lobby): wait for the panel to fade before clicking Start`.
- **type** — `fix` `feat` `refactor` `perf` `docs` `build` `chore`.
- **scope** — the module or surface: `lobby` `placement` `challenge` `tasks` `runner`
  `vision` `ui` `planner` `dashboard` `settings` `delays` `installer` `build` `steering`.
- **body** — **three sentences at most, usually none.** Only what the diff cannot say: the
  root cause, a measurement quoted from a log, or an obvious fix that was rejected so
  nobody retries it. One fact per sentence. No restating the subject, no explaining the
  design. A body that reads as a paragraph of prose is too long; seven before/after
  numbers belong in one sentence quoting the worst one.
- **`Untested:`** — required unless the change was exercised in the game. Without it a
  green `compileall` later reads as "it worked".

```
fix(lobby): wait for the panel to fade before clicking Start

Start matched 0.96 while still fading in, so the click was swallowed and the run
sat in the lobby until `Stage loaded` timed out at 60s — the button still scored
0.954 on screen 55s later. Normalized correlation ignores a uniform brightness
scale, so no threshold can separate a fading button from a live one.

Untested: no challenge run since.
```

## Say what the change is, plainly

A subject is read months later by someone scrolling forty of them. Name the thing that is
different now, in the words the project already uses.

- **Name the change, not the git operation.** `docs(steering): add rules for writing a
  commit subject`, not `squash a correction into the commit it corrects`.
- **Plain over clever.** No metaphor, no euphemism, nothing that sounds like something is
  being tidied away. `fix(updates): delete the downloaded installer after installing`
  beats "keep the download out of the way".
- **Name the real subject when a fix has an odd shape.** `feat(build): release without
  bumping the version` says it; describing the plumbing leaves the reader guessing.
- **Proportional.** Not `feat` over a renamed variable, not `fix` over a comment, and
  don't imply a whole surface changed when one function did.
- **The body states facts, not the conversation.** Never why it was asked for, never what
  a previous commit got wrong, never anything mistakable for a motive.

## Releasing

**Only when the user says "release".** Never because a change looks finished, never as the
tail of another task. A tag cannot be moved once pushed.

One commit, and it is the only one that breaks the format above:

```
Release 0.1.1

<the changes since the last release, one line each>
```

That is `bump_version.py` — it verifies, writes the subject, collects the body from the
commits since the previous tag, and pushes the tag `release.yml` builds. Run it; do not
hand-roll the commit. Patch carries at 10, so `0.1.9` is followed by `0.2.0`.

The body is a **changelog for the build**: `feat` `fix` `perf` only. Drop docs, chore,
refactor, ci and the `build`/`steering`/`website` scopes. A subject that reads as noise in
a release note was written for the diff, not the reader.

**Rehearse before spending a version.** `gh workflow run release.yml` builds the installer,
the zip and the notes, publishes nothing, and hands them back as artifacts. Every release
bug so far was found by cutting a real release and unwinding it — a tag, a force-push and
a re-cut. A dry run costs nothing.

## Corrections

A fix to a commit that is not pushed belongs *in* it — amend, don't stack a second commit
beside it. Once pushed, leave it: rewriting shared history needs asking first, and a tag
with a published release behind it is frozen.

No force push, no `reset --hard`, no `--no-verify` without being asked.
