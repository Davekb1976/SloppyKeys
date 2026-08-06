---
title: Version control — commits are the record
inclusion: always
---

# Commits are the record

`SloppyKeys` is a private git repo (`gh` account `davekb1976-beep`, remote `origin`, branch
`main`). **The commit history is the log of what changed and why.** `HANDOFF.md` is no longer
a changelog — see [What HANDOFF.md is now](#what-handoffmd-is-now).

This exists because the handoff reached 1,200 lines by absorbing every fix, diagnosis and
dead end. A commit already carries the diff, the date and the order; writing that into a
document as well was the same fact twice, and the second copy went stale.

## Commit when a change is complete, not when the turn ends

One commit per **self-contained change**: a fix, a feature, a refactor. Not per file, not
per turn. A turn that fixes three unrelated things makes three commits.

Commit only after the change is verified — `python -m compileall sloppykeys` plus whatever
probe the change warranted (`implementation-process.md` §Validating). A commit that doesn't
compile is worse than no commit, because `git bisect` then lands on it.

Never commit: `settings.json` (private-server link, Discord webhook), `log.txt`,
`log.prev.txt`, `crash.txt`, `.venv/`, `build/`, `dist/`, `installer_output/`, any
`images/**/debug/` dump. `.gitignore` covers all of these — if `git status` shows one of
them, fix the ignore rule rather than the `git add`.

Stage named paths, never `git add .` or `-A`. The working tree usually holds the user's own
in-flight edits (a recaptured template, a tweaked config) and those are theirs to commit.

## Message format

```
<type>(<scope>): <subject>

<body: root cause, and the evidence for it>

Untested: <what has not run in game>
```

**Subject line**: imperative, lower case after the colon, no trailing period, **≤ 72 chars**.
Say what changed, not what was wrong: `fix(lobby): wait for the panel to fade before
clicking Start`, not `Start was broken`.

**`<type>`** — `fix`, `feat`, `refactor`, `perf`, `docs`, `build`, `chore`.

**`<scope>`** — the module or surface, matching the tree: `lobby`, `placement`, `challenge`,
`tasks`, `runner`, `vision`, `ui`, `settings`, `delays`, `installer`, `build`, `steering`.

**Body** — only what the diff cannot say. Reach for it when there is a root cause, a
measurement, or a rejected alternative worth naming:

- The **root cause**, not the symptom.
- The **number that proves it**, verbatim from a log where there is one:
  `matched 0.96 mid-fade, then Start Game not found within 60.0s`.
- Why the obvious fix was **not** taken, if a future reader would try it.

Skip the body entirely for a one-liner whose subject already says everything. A typo fix
does not need a paragraph.

**`Untested:` footer** — required whenever the change has not been exercised in the game,
which is most of them. One line. This is what stops a later reader assuming a green
`compileall` meant it worked.

### Examples

```
fix(lobby): wait for the panel to fade before clicking Start

Start matched at 0.96 while still fading in, so the click was swallowed and
the run sat in the lobby until `Stage loaded` timed out after 60s; the button
still scored 0.954 on screen 55s later. Normalized correlation ignores a
uniform brightness scale, so no threshold can tell a fading button from a
live one — only a wait can. The wait sits after the search, not before it, so
a screen already up pays 1.0s instead of the old 1.5s settle.

Untested: no challenge run since the change.
```

```
perf(camera): make the zoom hold tunable

Two 3s holds are ~6s of the ~8s sequence. `PITCH_DELTA` stays fixed: retuning
the pitch invalidates every stored placement coordinate.

Untested: not tried below 3.0s.
```

```
docs(steering): commits replace the handoff changelog
```

## Branches and pushes

Work on `main` for this project — it is a private, single-author repo and a branch per fix
would be ceremony. Push when the user asks, or when a batch of commits is worth backing up;
`git push` is not automatic after every commit.

Follow the global git safety rules: no force push, no `reset --hard`, no amending a pushed
commit, no `--no-verify`. Amend only your own unpushed commit, and only to fold in something
that belonged in it.

## What HANDOFF.md is now

**Current state only, and it must shrink.** It answers what a new agent cannot get from
`git log`:

- What works, and what is **untested in game**.
- Measured constants and calibration that live in code (`PITCH_DELTA`, the viewport size,
  the OCR boxes) and why they are load-bearing.
- **Dead ends not to retry** — the ones that cost real time.
- Where things live: the module map.

Delete from it, in this order: dated entries, "fixed X" lines (that is a commit), narrative
about how a bug was found (that is a commit body), and any measurement that has served its
purpose. If a line would read naturally as a commit message, it belongs in one.

Keep it under ~250 lines. It is over that today; trim it as you touch each section rather
than in one pass.
