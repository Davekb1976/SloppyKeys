"""AutoHotkey v2 bridge.

Per the project design, AHK owns all synthetic mouse/keyboard output. Python
positions windows and decides *what* to do; it hands AHK a v2 script to actually
press keys and move the mouse.

A script is written to a temp .ahk file and run with the installed AutoHotkey v2
interpreter. `run(wait=False)` fires and returns immediately (good for long
sequences that shouldn't freeze the UI); `wait=True` blocks and reports the exit
code (good for quick, verifiable actions).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from shutil import which

# Common install locations for the AutoHotkey v2 interpreter, 64-bit first.
_CANDIDATES = (
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe",
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey32.exe",
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",
)


class AhkBridge:
    def __init__(self, exe_path: str | None = None) -> None:
        self._exe = exe_path or self._find_exe()
        self._last_script: str | None = None

    @staticmethod
    def _find_exe() -> str | None:
        for path in _CANDIDATES:
            if os.path.isfile(path):
                return path
        return which("AutoHotkey64") or which("AutoHotkey")

    @property
    def exe_path(self) -> str | None:
        return self._exe

    def available(self) -> bool:
        return bool(self._exe) and os.path.isfile(self._exe)

    def run(self, script: str, wait: bool = False, timeout: float = 20.0) -> tuple[bool, str]:
        """Write `script` to a temp .ahk and run it. Returns (ok, message)."""
        if not self.available():
            return (False, "AutoHotkey v2 not found")

        # Reuse a single temp file so we don't litter; overwrite each run.
        try:
            if self._last_script is None:
                fd, self._last_script = tempfile.mkstemp(suffix=".ahk", prefix="sloppykeys_")
                os.close(fd)
            with open(self._last_script, "w", encoding="utf-8") as handle:
                handle.write(script)
        except OSError as exc:
            return (False, f"could not write AHK script: {exc}")

        try:
            if wait:
                result = subprocess.run(
                    [self._exe, "/ErrorStdOut", self._last_script],
                    timeout=timeout,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    return (True, "completed")
                detail = (result.stderr or "").strip() or f"exit {result.returncode}"
                return (False, detail)
            subprocess.Popen([self._exe, self._last_script])
            return (True, "launched")
        except subprocess.TimeoutExpired:
            return (False, f"timed out after {timeout:.0f}s")
        except OSError as exc:
            return (False, f"failed to run AHK: {exc}")
