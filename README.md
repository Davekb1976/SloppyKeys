# SloppyKeys

A Windows macro for the Roblox game *Anime Expedition*. It shows the live Roblox window
inside its own UI, reads that view with template matching, and plays the game through
ordinary Windows input.

Queue up Story, Challenge, Expedition, Raid and Events runs, place your units where you
want them, and leave it. It reads the challenge panel, tracks wins and losses, and posts
progress to a Discord webhook if you give it one.

- **Windows 10/11, x64 only.** The whole thing is ctypes to Win32; there is no other path.
- Requires **[AutoHotkey v2](https://www.autohotkey.com/)** — every click and keypress
  goes through it, so nothing works without it.
- Requires **display scaling at 100%**. At 125% a template cropped at 100% scores as a
  different image (measured 0.80x) and matching fails.

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

## Install

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

### Your data

`images\`, `configs\`, `routes.json` and `settings.json` live **beside the exe** — the app
writes to all of them, so a captured template has to survive a restart. An upgrade never
overwrites them, and an uninstall asks before removing them.

`settings.json` holds your private-server link and your Discord webhook URL. It stays on
your machine; nothing is uploaded anywhere except the webhook you configured.

## Using it

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
from Qt timers are visible. Close the app first — a running exe can't be overwritten.

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

## Layout

```
sloppykeys/
  content/   the tables — gamemodes, act coordinates, nav images, routes
  config/    readers and writers for settings.json, configs/, routes.json
  core/      Win32 (ctypes), image search, OCR, the AHK bridge, the webhook
  macro/     what to play next, the lobby walk, camera, unit placement, the runner
  ui/        PySide6 — pages, editors, the viewport that hosts the Roblox window
configs/     unit placement plans, per gamemode and map
images/      the templates it matches against
tests/       assert scripts, no framework
```

Content and timing are **tables, not branches**: adding a map or a delay is a row.

## Contributions

None accepted — see [CONTRIBUTING.md](CONTRIBUTING.md). Fork it and go if you want your
own.

## Licence

See [LICENSE](LICENSE). Noncommercial: no paywalls, licence keys, telemetry or resale.

Bundled attribution: the `ponytail` steering guide is MIT, from
[DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail).

## Disclaimer

Automating a game may breach its terms of service, and using this can get your account
actioned. That risk is yours. Not affiliated with, endorsed by, or connected to Roblox or
the developers of Anime Expedition.
