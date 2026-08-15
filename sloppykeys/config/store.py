"""JSON persistence helpers.

Reads never raise: a missing or corrupt file yields an empty dict so the UI can
still start.

**Every writer of a shared file must go through `update_json`.** Each store here owns
one key of `settings.json` (tasks, delays, stats, keybinds, start_position, the toggles)
and used to persist it as read the whole file → change my key → write the whole file
back. That is a read-modify-write, and two of them running at once means the slower one
writes back a payload that predates the other's change — silently reverting it.

It happened: the user retargeted task 2 to Events, the next run used it, and a few
minutes later `settings.json` was back to the previous target with nothing in the log.
`StatsTracker.record()` writes from the **macro worker thread** at every match result,
while the Tasks tab writes from the UI thread, so editing the queue during a run was
enough. `update_json` holds a lock across the read *and* the write, which is the part a
lock inside `write_json` alone would not have fixed.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable

# One lock for every file. There are a handful of small JSON files and writes are rare,
# so per-path locks would be book-keeping for no measurable gain.
# ponytail: if a future writer holds this across something slow, key it by path.
_WRITE_LOCK = threading.RLock()


def read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json(path: str, payload: dict[str, Any]) -> bool:
    """Replace the file's whole contents.

    Only for a payload that isn't derived from a previous read of the same file — use
    `update_json` for "change one key", which is what every store here actually does.
    """
    with _WRITE_LOCK:
        return _write(path, payload)


def update_json(
    path: str, mutate: Callable[[dict[str, Any]], None]
) -> bool:
    """Read, let `mutate` change the payload in place, write it back — atomically.

    The read is inside the lock, which is the whole point: a concurrent writer cannot
    slip a change in between this call's read and its write and have it thrown away.
    """
    with _WRITE_LOCK:
        payload = read_json(path)
        mutate(payload)
        return _write(path, payload)


def _write(path: str, payload: dict[str, Any]) -> bool:
    """Atomic write: dump to a temp file, fsync, then os.replace.

    A crash or kill mid-write can only ever leave the OLD complete file or the
    NEW complete file — never a half-written, truncated JSON that read_json
    would report as {}.
    """
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        # Clean up the temp file if replace failed.
        try:
            os.remove(tmp)  # type: ignore[possibly-undefined]
        except OSError:
            pass
        return False
    return True


def ensure_json(path: str, default_payload: dict[str, Any]) -> None:
    if not os.path.isfile(path):
        write_json(path, default_payload)
