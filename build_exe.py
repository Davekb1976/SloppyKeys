"""Build SloppyKeys.exe and lay out a ready-to-run folder.

    .venv\\Scripts\\python.exe build_exe.py [--dest PATH] [--console] [--keep-settings]

**Onedir, not onefile.** A onefile build unpacks ~400MB of PySide6 + onnxruntime to a temp
directory on every launch (seconds of delay, and antivirus dislikes it). Onedir starts fast
and the exe sits beside its own data.

**Nothing is bundled that the user edits.** `assets/`, `routes.json` and
`settings.json` are *copied next to the exe*, not packed inside it, because the app writes
to all of them — a captured template has to survive a restart. `window.resolve_app_root()`
returns the exe's folder when frozen, which is what makes that work.

Not bundled at all: **AutoHotkey v2**. It is a separate install the user needs on PATH or in
Program Files (`core/ahk.py::_find_exe`); the app reports its absence rather than failing.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "SloppyKeys"
DEFAULT_DEST = os.path.join(os.path.dirname(os.path.dirname(HERE)), "SLOPPYKEYS")

# Copied beside the exe. Folders the user's work lives in, plus the route data.
# `operations/`, `paths/` and `recordings/` are not here on purpose: they are created
# by the app on first save and a shipped build has none.
DATA_DIRS = ("assets",)
DATA_FILES = ("routes.json",)
# `routes.json` again under a second name. The installer writes `routes.json` only if it is
# missing (it is the user's own events once they have any) but always replaces this copy, so
# it is the only way a route shipped with a new version reaches an existing install —
# `nav_routes.RouteStore.merge_shipped` reads it at startup.
SHIPPED_ROUTES = ("routes.json", "routes.default.json")
# Never copied wholesale: settings.json holds the private-server link and the Discord
# webhook. A filtered one is written instead — see `shipped_settings` and
# `SHIPPED_SETTINGS_KEYS`, which carry the tuning forward and leave the secrets behind.
SECRET_FILES = ("settings.json",)
# Build leftovers and dumps that must not ship.
SKIP_DIRS = {"debug", "__pycache__"}

# `--collect-all` because these ship data next to their Python: rapidocr carries the three
# ONNX models and their YAML config inside the wheel (that is why recognition is offline),
# and onnxruntime carries native DLLs. PyInstaller's module scan finds neither.
COLLECT_ALL = ("rapidocr", "onnxruntime")
# Imported lazily or by string, so the scan can miss them.
HIDDEN = ("rapidocr", "onnxruntime", "cv2", "mss")

# Nothing in the app imports these — grep before adding one. The Qt entries matter most:
# PySide6 ships every module it was built with, and QML/Quick alone is ~11MB of DLLs for a
# UI built entirely from QWidgets.
#
# **Not excluded, though it looks tempting:** `PIL` and `shapely` (12.8MB + 3.8MB) are
# imported by rapidocr itself — `from PIL import Image` and `from shapely.geometry import
# Polygon` — so dropping them breaks OCR, which is required. `numpy.libs` is OpenBLAS.
EXCLUDE_MODULES = (
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "tkinter",
    "unittest",
    "pydoc_data",
)

# Deleted from the built folder by name. Only files proven unused: this project never calls
# `cv2.VideoCapture` or any other videoio entry point (grep for it before trusting that),
# and the ffmpeg DLL is 29MB of video decoding for an app that reads pixels from mss.
#
# **Deliberately kept:** `PySide6/opengl32sw.dll` (19.7MB). It is Qt's software OpenGL
# fallback, used only on a machine whose GPU driver can't provide GL — exactly the machine
# a distributed build has to survive. Dropping it saves size and buys "blank window on some
# user's PC", which no size number is worth.
# The Qt DLLs are orphans, not guesses: `EXCLUDE_MODULES` removes the bindings that could
# load them (only QtCore/QtGui/QtWidgets/QtNetwork `.pyd` survive), but PyInstaller's PySide6
# hook copies the DLLs anyway. Qt6Quick depends on Qt6Qml and nothing depends on Qt6Quick;
# Qt6Pdf stands alone. Verified by launching the pruned build.
#
# The last three entries are **not** optional extras: `qpdf.dll` (an imageformats plugin)
# links Qt6Pdf, and `qtvirtualkeyboardplugin.dll` links Qt6VirtualKeyboard, which links
# Qt6Qml and Qt6Quick. Leaving them behind after pruning their libraries would leave Qt
# trying to load plugins whose dependencies are gone. Found by scanning every remaining
# binary for the pruned filenames — a single successful launch does *not* prove this, since
# Qt loads plugins lazily. Neither plugin is wanted anyway: nothing here opens a PDF as an
# image or wants an on-screen keyboard.
PRUNE_GLOBS = (
    "opencv_videoio_ffmpeg*.dll",
    "Qt6Quick*.dll",
    "Qt6Qml*.dll",
    "Qt6Pdf*.dll",
    "Qt6VirtualKeyboard*.dll",
    "qpdf.dll",
    "qtvirtualkeyboardplugin.dll",
)


# What a shipped `settings.json` may carry over from the project's own file. An
# **allowlist, not a denylist**: a secret added to the settings schema later must not start
# leaking because nobody remembered to exclude it. Every store merges its own defaults over
# what it finds, so a key left out here is simply the default.
#
# Deliberately excluded, each for its own reason:
#   private_server_link, discord_webhook — secrets. Always shipped blank.
#   stats                                — the developer's win/loss counters. Zeroed.
#   regions, points                      — measurements from *this* machine. They are
#       already the code defaults (`content/challenge.py`, `acts.py`, `start_stage.py`), so
#       shipping them adds nothing — and an override present on a fresh install turns the
#       UI's Reset button into a no-op, which is worse than not shipping it.
#   tasks                                — the developer's own queue. An empty queue makes
#       F1 use the Run page selection, which is the right first-run behaviour; a queue
#       pointing at maps a new user hasn't configured is not.
#   match_confidence                     — a setting that was removed. Don't resurrect it.
SHIPPED_SETTINGS_KEYS = (
    "run_challenges",
    "hard_mode",
    "camera_once_per_session",
    "keybinds",
    "game_keys",
    "delays",
    "start_position",
)


def shipped_settings(source: str) -> tuple[dict, list[str]]:
    """The `settings.json` to ship, plus the list of keys carried from `source`.

    Secrets are set, not merely omitted, so the shipped file is blank at those keys even if
    the allowlist ever grows to include one by mistake.
    """
    try:
        with open(source, encoding="utf-8") as handle:
            existing = json.load(handle)
    except (OSError, json.JSONDecodeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    payload: dict = {}
    carried: list[str] = []
    for key in SHIPPED_SETTINGS_KEYS:
        if key in existing:
            payload[key] = existing[key]
            carried.append(key)
    payload["private_server_link"] = ""
    payload["discord_webhook"] = ""
    payload["stats"] = {"wins": 0, "losses": 0}
    return (payload, carried)


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {name for name in names if name in SKIP_DIRS}


def copy_data(dest: str, keep_settings: bool) -> list[str]:
    done: list[str] = []
    for folder in DATA_DIRS:
        source = os.path.join(HERE, folder)
        if not os.path.isdir(source):
            continue
        target = os.path.join(dest, folder)
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target, ignore=_ignore)
        done.append(f"{folder}/")
    for name in DATA_FILES:
        source = os.path.join(HERE, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(dest, name))
            done.append(name)

    source = os.path.join(HERE, SHIPPED_ROUTES[0])
    if os.path.isfile(source):
        shutil.copy2(source, os.path.join(dest, SHIPPED_ROUTES[1]))
        done.append(SHIPPED_ROUTES[1])

    settings_path = os.path.join(dest, SECRET_FILES[0])
    if keep_settings and os.path.isfile(settings_path):
        done.append("settings.json (left as it was)")
    else:
        payload, carried = shipped_settings(os.path.join(HERE, SECRET_FILES[0]))
        with open(settings_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        summary = ", ".join(carried) if carried else "nothing"
        done.append(f"settings.json (no link, no webhook; carried {summary})")
    return done


def prune(folder: str) -> int:
    """Delete the known-dead binaries. Returns the megabytes reclaimed."""
    freed = 0
    for pattern in PRUNE_GLOBS:
        for path in glob.glob(os.path.join(folder, "**", pattern), recursive=True):
            freed += os.path.getsize(path)
            os.remove(path)
            print(f"pruned {os.path.relpath(path, folder)}")
    return round(freed / (1024 * 1024))


def build(dest: str, console: bool, onefile: bool) -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        NAME,
        "--distpath",
        os.path.join(HERE, "dist"),
        "--workpath",
        os.path.join(HERE, "build"),
        "--specpath",
        os.path.join(HERE, "build"),
        "--console" if console else "--windowed",
        "--onefile" if onefile else "--onedir",
    ]
    for package in COLLECT_ALL:
        command += ["--collect-all", package]
    for module in HIDDEN:
        command += ["--hidden-import", module]
    for module in EXCLUDE_MODULES:
        command += ["--exclude-module", module]
    command.append(os.path.join(HERE, "main.py"))
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=HERE)

    if onefile:
        # One file, no `_internal`. It is the same payload compressed *inside* the exe and
        # unpacked to %TEMP% on every launch, so this trades startup time for tidiness —
        # it is not a way to make the program smaller.
        source = os.path.join(HERE, "dist", f"{NAME}.exe")
        if not os.path.isfile(source):
            raise SystemExit(f"PyInstaller produced no {source}")
        shutil.rmtree(os.path.join(dest, "_internal"), ignore_errors=True)
        shutil.copy2(source, os.path.join(dest, f"{NAME}.exe"))
        return

    built = os.path.join(HERE, "dist", NAME)
    if not os.path.isdir(built):
        raise SystemExit(f"PyInstaller produced no {built}")
    freed = prune(built)
    if freed:
        print(f"pruned {freed}MB of unused binaries")
    # Replace the program, keep the data: a rebuild must not wipe captured templates.
    for entry in os.listdir(built):
        source = os.path.join(built, entry)
        target = os.path.join(dest, entry)
        if os.path.isdir(source):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=DEFAULT_DEST, help="where the runnable folder goes")
    parser.add_argument(
        "--console",
        action="store_true",
        help="keep a console window — tracebacks from Qt timers are visible in it",
    )
    parser.add_argument(
        "--keep-settings",
        action="store_true",
        help="don't overwrite an existing settings.json at the destination",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="one exe with no _internal folder — same payload inside, unpacked to %%TEMP%% "
        "on every launch, so it starts slower",
    )
    parser.add_argument("--skip-build", action="store_true", help="copy data only")
    args = parser.parse_args()

    dest = os.path.abspath(args.dest)
    os.makedirs(dest, exist_ok=True)
    if not args.skip_build:
        build(dest, args.console, args.onefile)
    copied = copy_data(dest, args.keep_settings)

    exe = os.path.join(dest, f"{NAME}.exe")
    total = sum(
        os.path.getsize(os.path.join(root, name))
        for root, _dirs, names in os.walk(dest)
        for name in names
    )
    print("\n--- done ---")
    print(f"exe   : {exe} ({'present' if os.path.isfile(exe) else 'MISSING'})")
    print(f"data  : {', '.join(copied)}")
    print(f"size  : {round(total / (1024 * 1024))}MB total in {dest}")
    print("needs : AutoHotkey v2 installed (all synthetic input goes through it)")


if __name__ == "__main__":
    main()
