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
- **body** — only what the diff can't say: the root cause, the measurement quoted from a
  log, and any obvious fix you rejected so nobody retries it. Omit it for a one-liner.
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

## Branch and push

Work on `main`; a branch per fix is ceremony in a private single-author repo.

**Push after committing, without being asked.** `origin/main` is the backup and the user
shouldn't have to prompt for it. Report the failure and carry on if the push fails — an
unpushed commit is not a broken change.

No force push, no `reset --hard`, no `--no-verify`, no amending a pushed commit. Amend only
your own unpushed commit, to fold in something that belonged in it.
