"""Terminal and console stream buffer for runtime diagnostics.

Captures Python's stdout and stderr into a thread-safe bounded ring buffer while
preserving the original terminal output. Used by the Debug > Diagnostics UI to display
what the macro is doing on the console side (RapidOCR init, ONNX warnings, macro events,
and error tracebacks) and allow copying error lines.
"""

from __future__ import annotations

import collections
from datetime import datetime
import io
import re
import sys
import threading
from typing import Any

MAX_TERMINAL_LINES = 1000

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_INFO_KEYWORDS = ("[info]", "[debug]", "[notice]")
_ERROR_KEYWORDS = (
    "error",
    "exception",
    "traceback",
    "failed:",
    "failure",
    "critical",
    "errno",
    "fatal",
)


class TerminalBuffer:
    """Thread-safe bounded ring buffer of terminal output lines."""

    def __init__(self, maxlen: int = MAX_TERMINAL_LINES) -> None:
        self._maxlen = maxlen
        self._lines: collections.deque[dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._counter = 0
        self._lock = threading.Lock()

    def append(self, text: str, stream: str = "stdout", is_err: bool | None = None) -> dict[str, Any]:
        """Record one line of text."""
        clean = _ANSI_ESCAPE.sub("", text).rstrip("\r\n")
        if not clean:
            return {}

        if is_err is None:
            lower = clean.lower()
            if any(kw in lower for kw in _INFO_KEYWORDS):
                is_err = False
                if stream == "stderr":
                    stream = "info"
            else:
                is_err = (stream == "stderr") or any(kw in lower for kw in _ERROR_KEYWORDS)

        now = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._counter += 1
            entry = {
                "id": self._counter,
                "ts": now,
                "stream": stream,
                "text": clean,
                "is_err": bool(is_err),
            }
            self._lines.append(entry)
            return entry

    def get_lines(self, after_id: int = 0, limit: int = 500) -> dict[str, Any]:
        """Fetch lines recorded after `after_id` up to `limit`."""
        with self._lock:
            if after_id <= 0:
                selected = list(self._lines)[-limit:]
            else:
                selected = [item for item in self._lines if item["id"] > after_id][:limit]

            return {
                "ok": True,
                "lines": selected,
                "latest_id": self._counter,
                "total": len(self._lines),
            }

    def get_text(self, errors_only: bool = False) -> str:
        """Format buffer lines as newline-delimited text for clipboard copy."""
        with self._lock:
            items = list(self._lines)
            if errors_only:
                items = [item for item in items if item.get("is_err")]
            return "\n".join(f"[{item['ts']}] [{item['stream']}] {item['text']}" for item in items)

    def clear(self) -> None:
        """Clear all buffered lines."""
        with self._lock:
            self._lines.clear()


class TeeStream(io.TextIOBase):
    """Passthrough wrapper that writes to an underlying stream and buffers lines."""

    def __init__(self, orig_stream: Any, buffer: TerminalBuffer, stream_name: str) -> None:
        self._orig = orig_stream
        self._buffer = buffer
        self._stream_name = stream_name
        self._acc = ""
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            s = str(s)

        if self._orig is not None:
            try:
                self._orig.write(s)
            except Exception:
                pass

        with self._lock:
            self._acc += s
            while "\n" in self._acc:
                line, self._acc = self._acc.split("\n", 1)
                line = line.rstrip("\r")
                if line:
                    self._buffer.append(line, stream=self._stream_name)

        return len(s)

    def flush(self) -> None:
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass

        with self._lock:
            if self._acc:
                line = self._acc.rstrip("\r\n")
                self._acc = ""
                if line:
                    self._buffer.append(line, stream=self._stream_name)

    @property
    def encoding(self) -> str:
        return getattr(self._orig, "encoding", "utf-8")

    @property
    def errors(self) -> str:
        return getattr(self._orig, "errors", "replace")

    def isatty(self) -> bool:
        return bool(getattr(self._orig, "isatty", lambda: False)())

    def fileno(self) -> int:
        if hasattr(self._orig, "fileno"):
            return self._orig.fileno()
        raise io.UnsupportedOperation("fileno")

    def writable(self) -> bool:
        return True


_GLOBAL_BUFFER = TerminalBuffer()
_INSTALLED = False
_INSTALL_LOCK = threading.Lock()


def get_terminal_buffer() -> TerminalBuffer:
    """Access the global terminal buffer singleton."""
    return _GLOBAL_BUFFER


def install_terminal_stream() -> TerminalBuffer:
    """Install TeeStream wrappers onto sys.stdout and sys.stderr once."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if _INSTALLED:
            return _GLOBAL_BUFFER

        orig_out = sys.stdout
        orig_err = sys.stderr

        sys.stdout = TeeStream(orig_out, _GLOBAL_BUFFER, "stdout")  # type: ignore[assignment]
        sys.stderr = TeeStream(orig_err, _GLOBAL_BUFFER, "stderr")  # type: ignore[assignment]

        _INSTALLED = True
        return _GLOBAL_BUFFER
