"""Move everything an Events name owns when it is renamed.

An event or act name is not just a label: it is a folder under `images/events/`, a file
under `images/reference/Events/`, a file under `configs/Events/`, a key in `routes.json`,
and a target in the task queue. Renaming the label alone orphans the rest — the route keeps
running, the placement backdrop and the unit plan quietly stop being found, and the queued
task points at an event that no longer exists.

`RouteStore.rename_map` / `rename_act` own `routes.json` (including each step's `Image`
path). This owns the files beside it and the keys in `settings.json`, and the two must be
run together — hence `rename_event` / `rename_act` here doing both, in an order chosen so a
failure part-way leaves the *old* state readable rather than half of each.

Nothing here deletes. A move whose destination exists is refused by the caller before it
starts (`RouteStore` rejects a name collision), and anything that cannot be moved is
reported rather than skipped silently.
"""

from __future__ import annotations

import os

from .nav_routes import RouteStore, clean_name

CONFIG_DIR = os.path.join("configs", "Events")
STEP_DIR = os.path.join("images", "events")
REFERENCE_DIR = os.path.join("images", "reference", "Events")


def _move(app_root: str, source: str, target: str, moved: list[str], failed: list[str]) -> None:
    """Move one path if it exists, recording what happened. Never overwrites."""
    src = os.path.join(app_root, source)
    dst = os.path.join(app_root, target)
    if not os.path.exists(src) or os.path.abspath(src) == os.path.abspath(dst):
        return
    if os.path.exists(dst):
        failed.append(f"{target} already exists")
        return
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
    except OSError as exc:
        failed.append(f"{source}: {exc}")
        return
    moved.append(target)


def _prune_empty(app_root: str, *relative: str) -> None:
    """Drop a folder the rename emptied. Ignores one that still holds anything."""
    for path in relative:
        full = os.path.join(app_root, path)
        try:
            if os.path.isdir(full) and not os.listdir(full):
                os.rmdir(full)
        except OSError:
            pass


def rename_event(app_root: str, routes: RouteStore, old: str, new: str) -> tuple[bool, str]:
    """Rename an event everywhere. Returns (ok, message).

    `routes.json` is written **last**: if a file move fails, the record still describes
    where the files actually are, so the event keeps working under its old name instead of
    pointing at paths nothing moved to.
    """
    old_dir, new_dir = clean_name(old), clean_name(new)
    if not old_dir or not new_dir:
        return (False, "that name can't be used as a folder name")
    if old_dir == new_dir:
        return (False, "that is already its name")

    moved: list[str] = []
    failed: list[str] = []
    # Whole folders for the step templates and the acts' unit configs; the reference
    # backdrops are a folder too. One move each rather than per file.
    for parent in (STEP_DIR, CONFIG_DIR, REFERENCE_DIR):
        _move(app_root, os.path.join(parent, old_dir), os.path.join(parent, new_dir), moved, failed)
    if failed:
        return (False, "; ".join(failed[:3]))

    stored = routes.rename_map(old, new_dir)
    if not stored:
        return (False, f"{new_dir} is already an event, or the name can't be stored")
    return (True, f"renamed to {stored}, moved {len(moved)} folder(s)")


def rename_act(
    app_root: str, routes: RouteStore, event: str, old: str, new: str
) -> tuple[bool, str]:
    """Rename one act of an event everywhere. Returns (ok, message)."""
    event_dir = clean_name(event)
    old_name, new_name = clean_name(old), clean_name(new)
    if not (event_dir and old_name and new_name):
        return (False, "that name can't be used as a file name")
    if old_name == new_name:
        return (False, "that is already its name")

    moved: list[str] = []
    failed: list[str] = []
    # The unit plan and the placement backdrop are one file each, named for the act.
    _move(
        app_root,
        os.path.join(CONFIG_DIR, event_dir, f"{old_name}.json"),
        os.path.join(CONFIG_DIR, event_dir, f"{new_name}.json"),
        moved,
        failed,
    )
    _move(
        app_root,
        os.path.join(REFERENCE_DIR, event_dir, f"{old_name}.png"),
        os.path.join(REFERENCE_DIR, event_dir, f"{new_name}.png"),
        moved,
        failed,
    )
    # Step templates are `<Act>_<n>.png`, and a route can hold any number of them. Driven
    # off what is on disk rather than off the step list, so a capture the route no longer
    # references still travels with the act instead of being left behind as litter.
    step_dir = os.path.join(app_root, STEP_DIR, event_dir)
    if os.path.isdir(step_dir):
        stem = f"{old_name}_"
        for name in sorted(os.listdir(step_dir)):
            if name.startswith(stem) and name.lower().endswith(".png"):
                _move(
                    app_root,
                    os.path.join(STEP_DIR, event_dir, name),
                    os.path.join(STEP_DIR, event_dir, f"{new_name}_{name[len(stem):]}"),
                    moved,
                    failed,
                )
    if failed:
        return (False, "; ".join(failed[:3]))

    stored = routes.rename_act(event, old, new_name)
    if not stored:
        return (False, f"{new_name} is already an act of {event_dir}, or it can't be stored")
    return (True, f"renamed to {stored}, moved {len(moved)} file(s)")
