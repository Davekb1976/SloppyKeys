---
inclusion: always
---

# Commits are the only record

Private repo `Davekb1976/SloppyKeys`, remote `origin`, branch `main`. There is no handoff
document to maintain: `git log` is the history, and the `Untested:` footer below is the
list of what hasn't been exercised in game (`git log --grep Untested`).

## When

One commit per **self-contained change** — a fix, a feature, a refactor. Not per file, not
per turn: a turn that fixes three unrelated things makes three commits.

Commit only after it verifies (`implementation-process.md` §Validating). A commit that
doesn't compile poisons `git bisect`.

Stage **named paths**, never `git add .` or `-A` — the working tree usually holds the
user's own in-flight edits (a recaptured template, a tweaked config) and those are theirs.

Never commit: `settings.json` (private-server link, Discord webhook), `log.txt`,
`log.prev.txt`, `crash.txt`, `.venv/`, `build/`, `dist/`, `installer_output/`, any
`images/**/debug/` dump. `.gitignore` covers these; if one shows in `git status`, fix the
ignore rule, not the `git add`.

## Message

```
<type>(<scope>): <subject>

<root cause, and the number that proves it>

Untested: <what has not run in game>
```

- **subject** — imperative, lower case, no full stop, ≤72 chars. What changed, not what was
  broken: `fix(lobby): wait for the panel to fade before clicking Start`.
- **type** — `fix` `feat` `refactor` `perf` `docs` `build` `chore`.
- **scope** — the module or surface: `lobby` `placement` `challenge` `tasks` `runner`
  `vision` `ui` `settings` `delays` `installer` `build` `steering`.
- **body** — **three sentences at most, and usually none.** Only what the diff can't say:
  the root cause, the measurement quoted from a log, or an obvious fix that was rejected so
  nobody retries it. One fact per sentence, no restating the subject, no explaining the
  design — the code is right there. A body that reads as a paragraph of prose is too long;
  a list of seven before/after numbers belongs in one sentence with the worst one quoted.
- **`Untested:`** — required unless the change was exercised in the game. This is the
  tracker; without it a green `compileall` later reads as "it worked".

```
fix(lobby): wait for the panel to fade before clicking Start

Start matched 0.96 while still fading in, so the click was swallowed and the run
sat in the lobby until `Stage loaded` timed out at 60s — the button still scored
0.954 on screen 55s later. Normalized correlation ignores a uniform brightness
scale, so no threshold can separate a fading button from a live one.

Untested: no challenge run since.
```

## Releasing

**Only when the user says "release".** Never cut one because a change looks finished, and
never as the tail end of another task. A tag can't be moved once it's pushed.

When they say it, one commit, and it is the only commit that breaks the format above:

```
Release 0.1.1

<the changes since the last release, one line each>
```

That is `bump_version.py`, which verifies, writes the subject, collects the body from the
commits since the previous tag, and pushes the tag that `release.yml` builds. Run it; don't
hand-roll the commit. Patch carries at 10 — `0.1.9` is followed by `0.2.0`.

The body is a **changelog for the build**, so `feat` `fix` `perf` only; docs, chore,
refactor, ci and the `build`/`steering`/`website` scopes are dropped. A subject that would
read as noise in a release note is a sign the subject was written for the diff, not the
reader.

**Rehearse the pipeline before spending a version.** `gh workflow run release.yml` builds the
installer, the zip and the notes and publishes nothing, handing them back as artifacts. Every
release bug so far was found by cutting a real release and unwinding it, which costs a tag, a
force-push and a re-cut — a dry run costs nothing.

## Branch and push

Work on `main`; a branch per fix is ceremony in a private single-author repo.

**Push after committing, without being asked.** `origin/main` is the backup and the user
shouldn't have to prompt for it. Report the failure and carry on if the push fails — an
unpushed commit is not a broken change.

### Say what the change is, plainly

A subject is read months later by someone scrolling a list of forty of them. It has to name
the thing that is different now, in the words the project already uses for it.

- **Name the change, not the git operation.** `docs(steering): add rules for writing a
  commit subject`, not `squash a correction into the commit it corrects`. Rebasing,
  amending and squashing are how the commit got there; they are not what it does.
- **Plain over clever.** No metaphor, no euphemism, no wording that sounds like something
  is being tidied away. `fix(updates): delete the downloaded installer after installing`
  beats "keep the download out of the way".
- **Name the real subject when a fix has an odd shape.** `feat(build): release without
  bumping the version` says it; "let the first release tag the version already in the file"
  describes the plumbing and leaves the reader guessing.
- **Proportional.** Don't write `feat` over a renamed variable or `fix` over a comment, and
  don't let a subject imply a whole surface changed when one function did.
- **The body states facts, not the conversation.** Root cause, the measurement, the option
  rejected. Never why it was asked for, never what a previous commit got wrong, never
  anything a reader could mistake for a motive. If the diff already says it, leave it out.

### One commit per change

A correction to a commit that isn't pushed yet belongs *in* it — amend, don't stack a second
commit beside it. Once pushed, leave it: rewriting shared history needs asking first, and a
tag with a published release behind it is frozen.

No force push, no `reset --hard`, no `--no-verify` without being asked.
