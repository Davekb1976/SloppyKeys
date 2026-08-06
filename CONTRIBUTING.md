# Contributing

**Bug reports and feature requests: yes, please.** [Open an
issue](../../issues/new/choose) — there are two templates, and both ask for the things that
actually make a report usable.

**Pull requests: no.** They're closed unread, and it isn't a judgement on the patch. Every
change here has to be verified against a live game on a real screen at 100% scaling, and
nobody but the author can do that, so a PR would sit unmerged while looking like it might
land. Fork it instead — MIT, it's yours.

## What makes a bug report usable

The macro reads pixels and sends clicks, so "it didn't work" has a hundred causes. Three
things narrow it down almost every time:

- **`log.txt`**, from beside the exe. It timestamps every step, every match score and every
  search that timed out. Paste the last 50 lines or so, not the whole file.
- **A screenshot** of the app when it went wrong. Whoever reads the report can't see your
  screen, and a match failure is usually visible in it.
- **Your display scaling.** If it isn't 100%, that's the answer: a template cropped at 100%
  scores as a different image at 125%.

Check these before opening anything, because they're most of the reports:

- Is AutoHotkey **v2** installed? v1 won't do — nothing will click.
- Is display scaling at 100%?
- Is the game window attached, and not minimized?
- Did you recapture templates after changing anything about your screen?

`log.txt` never contains your private-server link or your webhook URL, so it's safe to
paste. Skim it anyway.

## Feature requests

Say what you're trying to get done, not just the control you imagine. Two things get
declined every time, so they're worth knowing up front:

- Anything that needs more than **pixels in and Windows input out** — reading Roblox's
  memory, injecting into it, hooking it, fast flags. That boundary is the whole design; see
  the README.
- Anything that changes the **1152x756 viewport**. Every coordinate, template, unit plan and
  route was captured at that size, so moving it invalidates all of them at once.
