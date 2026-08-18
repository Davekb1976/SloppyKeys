---
inclusion: always
---

# Commits are the only record

Private repo `Davekb1976/SloppyKeys`, remote `origin`, branch `main`. There is no handoff
document: `git log` is the history.

This file is deliberately short — it is the part that has to be true *without anyone asking
for it*. The message format, the body rules and the release procedure are in the
**`git-workflow` skill**; read it before writing a message or cutting a release.

## Always

- **One commit per self-contained change** — a fix, a feature, a refactor. Not per file,
  not per turn: a turn that fixes three unrelated things makes three commits.
- **Commit only after it verifies** (`implementation-process.md` §Validating). A commit
  that doesn't compile poisons `git bisect`.
- **Stage named paths**, never `git add .` or `-A`. The working tree usually holds the
  user's own in-flight edits — a recaptured template, a tweaked config — and those are
  theirs.
- **Push after committing, without being asked.** `origin/main` is the backup. If the push
  fails, report it and carry on: an unpushed commit is not a broken change. `git push`
  writes progress to stderr, which reads as an error — confirm by the `main -> main` line.
- **Work on `main`.** A branch per fix is ceremony in a private single-author repo.
- **Release only when the user says "release".**

## Never commit

`settings.json` (private-server link, Discord webhook) · `log.txt` · `log.prev.txt` ·
`crash.txt` · `.venv/` · `build/` · `dist/` · `installer_output/` · any
`assets/**/debug/` dump. `.gitignore` covers these; if one shows in `git status`, fix the
ignore rule, not the `git add`.

No force push, no `reset --hard`, no `--no-verify` without being asked.
