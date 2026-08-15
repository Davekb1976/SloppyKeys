"""Macro Operation CRUD — stored as individual JSON files in data/operations/.

Each operation is a named routine with four phases of blocks. Display name is
stored inside the file; the filename is a safe slug derived from it.
"""

from __future__ import annotations

import json
import os
import re
import threading

from .store import read_json

_lock = threading.Lock()


def _ops_dir(app_root: str) -> str:
    return os.path.join(app_root, "operations")


def _safe_slug(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 _\-']", "", name or "").strip().strip(".")
    return cleaned or "operation"


def _resolve(app_root: str, name: str) -> str:
    """File path for a named operation."""
    d = _ops_dir(app_root)
    # Check if a file already claims this display name.
    if os.path.isdir(d):
        for fname in os.listdir(d):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(d, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("name") == name:
                    return path
            except (OSError, json.JSONDecodeError):
                continue
    return os.path.join(d, f"{_safe_slug(name)}.json")


def list_operations(app_root: str) -> list[str]:
    """All operation display names, sorted."""
    d = _ops_dir(app_root)
    if not os.path.isdir(d):
        return []
    names = []
    for fname in os.listdir(d):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(d, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            names.append(data.get("name") or fname[:-5])
        except (OSError, json.JSONDecodeError):
            names.append(fname[:-5])
    return sorted(set(names))


def load_operation(app_root: str, name: str) -> dict:
    """Load an operation by display name. Returns {name, phases: {pre_start, battle, loop_a, loop_b}}."""
    path = _resolve(app_root, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    phases = data.get("phases")
    if not isinstance(phases, dict):
        phases = {"pre_start": [], "battle": [], "loop_a": [], "loop_b": []}
    return {"name": data.get("name", name), "phases": phases}


def save_operation(app_root: str, name: str, phases: dict) -> bool:
    """Save an operation. Creates the directory if needed."""
    name = (name or "").strip() or "Untitled"
    d = _ops_dir(app_root)
    os.makedirs(d, exist_ok=True)
    path = _resolve(app_root, name)
    # If the resolve didn't find an existing file, use the slug.
    if not os.path.isfile(path):
        path = os.path.join(d, f"{_safe_slug(name)}.json")
    payload = {"name": name, "phases": phases}
    tmp = path + ".tmp"
    with _lock:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False


def delete_operation(app_root: str, name: str) -> bool:
    path = _resolve(app_root, name)
    try:
        os.remove(path)
        return True
    except OSError:
        return False
