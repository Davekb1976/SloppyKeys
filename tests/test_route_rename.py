"""Runnable checks for renaming an Events event or act in the route store.

    .venv\\Scripts\\python.exe tests\\test_route_rename.py

A name is not a label: it is a key in `routes.json`, each step's `Image` path, a folder
under `assets/events/` and a file under `assets/reference/Events/`. Rename the record and
not the files and the route still runs while its templates quietly stop being found.

**Half of what this file used to check is gone.** `config/route_paths.rename_event` /
`rename_act` moved the three trees and returned `(ok, message)`; they were deleted with the
PySide6 UI and nothing replaced them, so `configs/` no longer exists and no file gets moved
by a rename at all. What is left is the record half — `RouteStore.rename_map` /
`rename_act`, which return the stored name or `""` when they refuse. The file-moving asserts
are not re-pointed at anything: there is nothing to point them at, and no rename in the web
UI to trigger it. See `RouteStore.rename_map`'s own docstring.

No framework, no capture, no input. Everything happens in a temp tree.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.nav_routes import RouteStore, step_image  # noqa: E402
from sloppykeys.content.nav_route import NavStep  # noqa: E402


def build(root: str) -> RouteStore:
    """An event with two acts, each with one captured step template."""
    store = RouteStore(root)
    store.add_map("Old Event")
    store.add_act("Old Event", "Act 1")
    store.add_act("Old Event", "Act 2")
    for act in ("Act 1", "Act 2"):
        store.set_steps(
            "Old Event",
            act,
            [NavStep(kind="find", image=step_image("Old Event", act, 1))],
        )
    return store


# # A step template lives under assets/, with everything else the app searches
assert step_image("Old Event", "Act 1", 1) == "assets/events/Old Event/Act 1_1.png", step_image(
    "Old Event", "Act 1", 1
)

# # Renaming an event keeps its acts and rewrites every step image
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    assert store.rename_map("Old Event", "New Event") == "New Event"
    assert store.maps() == ["New Event"], store.maps()
    assert store.acts("New Event") == ["Main", "Act 1", "Act 2"], store.acts("New Event")
    for act in ("Act 1", "Act 2"):
        steps = store.steps("New Event", act)
        assert steps and steps[0].image == step_image("New Event", act, 1), steps[0].image

# # Renaming one act touches only that act, and keeps its place in the order
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    assert store.rename_act("Old Event", "Act 1", "Prologue") == "Prologue"
    assert store.acts("Old Event") == ["Main", "Prologue", "Act 2"], store.acts("Old Event")
    steps = store.steps("Old Event", "Prologue")
    assert steps and steps[0].image == step_image("Old Event", "Prologue", 1), steps[0].image
    other = store.steps("Old Event", "Act 2")
    assert other[0].image == step_image("Old Event", "Act 2", 1), other[0].image

# # Collisions are refused, not merged: merging two acts loses one route
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    assert store.rename_act("Old Event", "Act 1", "Act 2") == ""
    assert store.steps("Old Event", "Act 1")[0].image == step_image("Old Event", "Act 1", 1)
    assert store.rename_act("Old Event", "Nope", "Anything") == "", "unknown act"

    store.add_map("Other Event")
    assert store.rename_map("Old Event", "Other Event") == ""
    assert store.maps() == ["Old Event", "Other Event"], store.maps()
    assert store.rename_map("Nope", "Anything") == "", "unknown event"

# # A name with nothing usable is refused; a dangerous one is sanitised, not refused
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    for empty in ("", "   "):
        assert store.rename_map("Old Event", empty) == "", repr(empty)
    assert store.maps() == ["Old Event"]

    # `safe_component` neutralises separators and traversal rather than rejecting them — the
    # same contract `add_map` gives, so a rename cannot be stricter than the add that made
    # the name. What matters is that the result is one flat segment.
    assert store.rename_map("Old Event", "../Escape/Act") == "--Escape-Act"
    assert store.maps() == ["--Escape-Act"], store.maps()

# # A step pointing outside the event's own folder is left alone
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    store.set_steps(
        "Old Event", "Act 1", [NavStep(kind="find", image="assets/lobby/play.png")]
    )
    assert store.rename_map("Old Event", "New Event") == "New Event"
    kept = store.steps("New Event", "Act 1")[0].image
    assert kept == "assets/lobby/play.png", kept

# # routes.json stays loadable and keeps its schema through a rename
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    assert store.rename_map("Old Event", "Renamed") == "Renamed"
    with open(os.path.join(root, "routes.json"), encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["Schema"] == 1, payload
    assert list(payload["Maps"]) == ["Renamed"], payload

print("route rename: OK")
