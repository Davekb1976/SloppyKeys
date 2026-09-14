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

- [Features & Overview](#features--overview)
- [Getting Started](#getting-started)
- [Usage & Controls](#usage--controls)
- [Development & Source](#development--source)
- [Credits & Tooling](#credits--tooling)
- [License & Disclaimer](#license--disclaimer)

---

## Features & Overview

### Features

- **Every mode.** Story, Challenge, Expedition, Raid and Events, with hard mode and
  Expedition difficulty as toggles.
- **A task queue.** Give each target a run limit; it moves to the next one when that limit
  is met, without stopping between matches.
- **Unit plans you place yourself.** Pick the coordinates on the live window, set the slot
  and the upgrade level, save it per gamemode/map/act.
- **Autoplay preset selector.** Select in-game autoplay presets per task before match start
  using OCR matching.
- **Reads the challenge panel**, including the daily limit, and waits out the 8PM refill
  rather than burning runs.
- **Events routes you author** — click, find, expect, scroll, wait — for the modes whose
  lobby changes with every event.
- **Win/loss stats and a Discord webhook**, if you give it one. Nothing is posted anywhere
  else.
- **Per-template match tolerance** with a test button, so one stubborn image can't drag the
  rest down.
- **In-app updates** from the GitHub release, checksum-verified.

### How it works, and what it will not do

Everything the macro knows comes from **pixels on screen**. Everything it does goes out as
**ordinary Windows input**. That boundary is the whole design:

- It captures the screen with [mss](https://github.com/BoboTiG/python-mss) and matches
  templates with OpenCV. Two strings no template can cover (the challenge daily limit and
  the map name) go through offline OCR via RapidOCR.
- It sends input by generating an AutoHotkey v2 script and running it. Python decides
  *what* to do; AHK does it.
- Roblox is never reparented, injected into, hooked, or read from memory. Nothing is
  written to a Roblox file. No fast flags, no anti-cheat interaction of any kind.

If a feature would need more than pixels in and OS input out, it doesn't get built.

---

## Getting Started

### Requirements

- **Windows 10/11, x64 only.** The whole thing is ctypes to Win32; there is no other path.
- **[AutoHotkey v2](https://www.autohotkey.com/)** — every click and keypress goes through
  it, so nothing works without it.
- **Display scaling at 100%.** At 125% a template cropped at 100% scores as a different
  image (measured 0.80x) and matching fails.

### Download & Install

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

### Updates & Your Data

- **Updates (Settings > Main > Updates):** It asks GitHub once per launch whether there's a newer
  release and stays quiet unless there is. Nothing downloads until you click. Installer copies
  update in place with SHA-256 verification against `SHA256SUMS.txt`.
- **Your Data:** `assets\`, `operations\`, `paths\`, `presets\`, `routes.json` and `settings.json` live
  **beside the exe** — the app writes to all of them, so captured templates and plans survive
  restarts and upgrades.
- `settings.json` holds your private-server link and your Discord webhook URL. It stays on
  your machine; nothing is uploaded anywhere except the webhook you configured.

---

## Usage & Controls

| Key | Does |
|---|---|
| `F1` | Start |
| `F2` | Pause / resume |
| `F3` | Stop |
| `F4` | Reload |
| `F6` | Open the Image Manager |
| `F7` | Compact mode |

All six are rebindable in Settings, along with the in-game keys the macro presses for
priority, upgrade, sell and auto-upgrade.

Start and stop are separate keys on purpose: with one toggle, pressing it to start a run
you thought had stopped stops it instead, and there's no way to be sure which state you're
in before you press.

---

## Development & Source

### Running from source

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

### Building & Releasing

```powershell
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe build_exe.py
```

Onedir, not onefile: a onefile build unpacks ~400MB to a temp folder on every launch. Lands
in `..\..\SLOPPYKEYS` unless you pass `--dest`.

The installer needs [Inno Setup 6](https://jrsoftware.org/isdl.php), taking the version
on the command line:

```powershell
$v = .venv\Scripts\python.exe -c "from sloppykeys.version import VERSION; print(VERSION)"
"$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=$v installer.iss
```

To bump version and tag:

```powershell
.venv\Scripts\python.exe bump_version.py
```

### Project layout

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

---

## Credits & Tooling

### Acknowledgements

This project follows
[Cweamy/Anime-Expeditions-Creams-Macro](https://github.com/Cweamy/Anime-Expeditions-Creams-Macro),
which established several of the capabilities built here: the task queue, the walk-path
recorder, the block-based match plan, and Discord match reporting. That prior work is
acknowledged with thanks.

The implementation is independent: input is delegated to an external AutoHotkey v2
process rather than direct in-process Win32 calls; the Roblox window rides in the
topmost band with its frame removed rather than being reparented as a child window;
and text recognition runs offline via a self-contained RapidOCR (ONNX) engine without
requiring external Tesseract or Windows SDK installers.

Bundled attribution: the `ponytail` steering guide is MIT, from
[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).

### AI Assistance & IDEs

This project was built with the assistance of frontier AI models across specialized agentic IDEs:

- **AI Models:** Claude Opus 5, Claude Sonnet 5, Opus 4.8, Claude Opus 4.6 (Thinking), and Gemini 4.8 Flash.
- **IDEs:** Developed using **Antigravity IDE** (for Gemini 4.8 Flash and Claude Opus 4.6 Thinking) and **Kiro IDE** (for Claude Opus 5, Claude Sonnet 5, and Opus 4.8).

---

## License & Disclaimer

### Licence

[MIT](LICENSE). Use it, change it, ship it.

It carries no paywall, licence key or telemetry, and it never will — but that's a promise
about this build, not a restriction on yours.

### Bugs and requests

[Open an issue](../../issues/new/choose) — bring `log.txt`, a screenshot, and your display
scaling. Pull requests aren't accepted; fork it instead. Details in
[CONTRIBUTING.md](CONTRIBUTING.md).

### Disclaimer

Automating a game may breach its terms of service, and using this can get your account
actioned. That risk is yours. Not affiliated with, endorsed by, or connected to Roblox or
the developers of Anime Expedition.
