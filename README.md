<div align="center">

# SloppyKeys

**A macro that plays *Anime Expedition* by looking at it.**<br>
It hosts the live Roblox window inside its own UI, reads that view with template matching,
and plays through ordinary Windows input — nothing injected, no process memory touched.<br>
Queue up Story, Challenge, Expedition, Raid and Events runs, place your units, and leave it.

[![release](https://img.shields.io/github/v/release/Davekb1976/SloppyKeys?label=release&color=blue)](https://github.com/Davekb1976/SloppyKeys/releases/latest)
[![downloads](https://img.shields.io/github/downloads/Davekb1976/SloppyKeys/total?label=downloads&color=success)](https://github.com/Davekb1976/SloppyKeys/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/Davekb1976/SloppyKeys/ci.yml?branch=main&label=CI&logo=github)](https://github.com/Davekb1976/SloppyKeys/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011%20x64-informational)](#requirements)

[Website](https://davekb1976.github.io/SloppyKeys/) · [Download](https://github.com/Davekb1976/SloppyKeys/releases/latest) · [Report a bug](../../issues/new/choose)

</div>

> **Before you download:** Windows 10/11 x64, [AutoHotkey v2](https://www.autohotkey.com/)
> installed, and display scaling at 100%. Miss the last one and every image match fails —
> see [Requirements](#requirements).

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Download & Install](#download--install)
- [Updates](#updates)
- [Your data](#your-data)
- [Usage](#usage)
- [How it works, and what it will not do](#how-it-works-and-what-it-will-not-do)
- [Running from source](#running-from-source)
- [Project layout](#project-layout)
- [Bugs and requests](#bugs-and-requests)
- [Licence](#licence)
- [Disclaimer](#disclaimer)

## Features

- **Every mode.** Story, Challenge, Expedition, Raid and Events, with hard mode and
  Expedition difficulty as toggles.
- **A task queue.** Give each target a run limit; it moves to the next one when that limit
  is met, without stopping between matches.
- **Unit plans you place yourself.** Pick the coordinates on the live window, set the slot
  and the upgrade level, save it per gamemode/map/act.
- **Reads the challenge panel**, including the daily limit, and waits out the 8PM refill
  rather than burning runs.
- **Events routes you author** — click, find, expect, scroll, wait — for the modes whose
  lobby changes with every event.
- **Win/loss stats and a Discord webhook**, if you give it one. Nothing is posted anywhere
  else.
- **Per-template match tolerance** with a test button, so one stubborn image can't drag the
  rest down.
- **In-app updates** from the GitHub release, checksum-verified.

## Requirements

- **Windows 10/11, x64 only.** The whole thing is ctypes to Win32; there is no other path.
- **[AutoHotkey v2](https://www.autohotkey.com/)** — every click and keypress goes through
  it, so nothing works without it.
- **Display scaling at 100%.** At 125% a template cropped at 100% scores as a different
  image (measured 0.80x) and matching fails.

## Download & Install

Grab the latest [release](../../releases):

- **`SloppyKeys-Setup-<version>.exe`** installs per-user to
  `%LOCALAPPDATA%\Programs\SloppyKeys`. No admin prompt, and the folder stays writable, so
  your captures and settings save.
- **`SloppyKeys-<version>-portable.zip`** is the same build with no installer. Unzip
  somewhere writable and run `SloppyKeys.exe`.

Neither is code-signed, so SmartScreen will warn about an unknown publisher. Each release
lists SHA-256 hashes if you want to check what you downloaded.

Then install AutoHotkey v2 if you haven't. The installer says so too, rather than letting
you find out by every click doing nothing.

## Updates

**Settings > Main > Updates.** It asks GitHub once per launch whether there's a newer
release and stays quiet unless there is. Nothing downloads until you click.

If you used the installer, it can update in place: it fetches the new setup, checks it
against the `SHA256SUMS.txt` published with the release, refuses anything that doesn't
match, and won't touch an update while the macro is running. Portable and from-source
copies get the release page instead — running the installer from a portable folder would
just leave a second copy elsewhere.

Turn the whole thing off with the toggle and nothing contacts GitHub.

## Your data

`images\`, `configs\`, `routes.json` and `settings.json` live **beside the exe** — the app
writes to all of them, so a captured template has to survive a restart. An upgrade never
overwrites them, and an uninstall asks before removing them.

`settings.json` holds your private-server link and your Discord webhook URL. It stays on
your machine; nothing is uploaded anywhere except the webhook you configured.

## Usage

| Key | Does |
|---|---|
| `F1` | Start, or stop a run in progress |
| `F2` | Stop |
| `F3` | Reload |
| `Ctrl` + `T` | Open the Macro Tester |

All four are rebindable in Settings, along with the in-game keys the macro presses for
priority, upgrade, sell and auto-upgrade.

Start and stop are separate keys on purpose: with one toggle, pressing it to start a run
you thought had stopped stops it instead, and there's no way to be sure which state you're
in before you press.

## How it works, and what it will not do

Everything the macro knows comes from **pixels on screen**. Everything it does goes out as
**ordinary Windows input**. That boundary is the whole design:

- It captures the screen with [mss](https://github.com/BoboTiG/python-mss) and matches
  templates with OpenCV. Two strings no template can cover (the challenge daily limit and
  the map name) go through offline OCR.
- It sends input by generating an AutoHotkey v2 script and running it. Python decides
  *what* to do; AHK does it.
- Roblox is never reparented, injected into, hooked, or read from memory. Nothing is
  written to a Roblox file. No fast flags, no anti-cheat interaction of any kind.

If a feature would need more than pixels in and OS input out, it doesn't get built.

## Running from source

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Python 3.14. Close the window with the titlebar X; `taskkill /IM python.exe /F` is only for
a stuck process.

### Tests

Framework-free assert scripts, run one at a time:

```powershell
.venv\Scripts\python.exe tests\test_placement_plan.py
```

### Building

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe build_exe.py
```

Onedir, not onefile: a onefile build unpacks ~400MB to a temp folder on every launch. Lands
in `..\..\SLOPPYKEYS` unless you pass `--dest`. `--console` keeps a console so tracebacks
from the worker threads are visible. Close the app first — a running exe can't be overwritten.

The installer needs [Inno Setup 6](https://jrsoftware.org/isdl.php), and takes the version
on the command line rather than defaulting to a stale one:

```powershell
$v = .venv\Scripts\python.exe -c "from sloppykeys.version import VERSION; print(VERSION)"
"$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=$v installer.iss
```

### Releasing

```powershell
.venv\Scripts\python.exe bump_version.py
```

That bumps `sloppykeys/version.py`, commits `Release <version>` with the changes since the
last tag, and pushes the tag. `.github/workflows/release.yml` builds the installer and the
portable zip on a clean runner and publishes them.

Versions are `MAJOR.MINOR.PATCH` with a **single-digit patch**: `0.1.9` is followed by
`0.2.0`, not `0.1.10`.

## Project layout

```
sloppykeys/
  content/   the tables — gamemodes, act coordinates, nav images, routes
  config/    readers and writers for settings.json, operations/, routes.json
  core/      Win32 (ctypes), image search, OCR, the AHK bridge, the webhook
  macro/     what to play next, the lobby walk, camera, unit placement, the runner
  ui_web/    pywebview + HTML/CSS/JS over WebView2; bridge.py is the js_api surface
assets/      the templates it matches against, and the placement backdrops
operations/  the block macros — pre-start, battle and the two loops
paths/       walk recordings
tests/       assert scripts, no framework
```

Content and timing are **tables, not branches**: adding a map or a delay is a row.

## Bugs and requests

[Open an issue](../../issues/new/choose) — bring `log.txt`, a screenshot, and your display
scaling. Pull requests aren't accepted; fork it instead. Details in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[MIT](LICENSE). Use it, change it, ship it.

It carries no paywall, licence key or telemetry, and it never will — but that's a promise
about this build, not a restriction on yours.

Bundled attribution: the `ponytail` steering guide is MIT, from
[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).

## Disclaimer

Automating a game may breach its terms of service, and using this can get your account
actioned. That risk is yours. Not affiliated with, endorsed by, or connected to Roblox or
the developers of Anime Expedition.
