"""Runnable checks for renaming an Events event or act.

A name is not a label: it is a folder under `images/events/`, a file under
`images/reference/Events/`, a file under `configs/Events/`, a key in `routes.json` and
each route step's `Image` path. Renaming one and not the others leaves a route that still
runs while the backdrop and the unit plan quietly stop being found — a failure that looks
like the capture was never made.

No framework, no Qt, no capture, no input. Everything happens in a temp tree:
`.venv\\Scripts\\python.exe tests\\test_route_rename.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.nav_routes import RouteStore, step_image  # noqa: E402
from sloppykeys.config.route_paths import rename_act, rename_event  # noqa: E402
from sloppykeys.content.nav_route import NavStep  # noqa: E402


def write(path: str, text: str = "x") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def build(root: str) -> RouteStore:
    """An event with two acts, a captured step template for each, a backdrop and a config."""
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
        write(os.path.join(root, step_image("Old Event", act, 1)))
        write(os.path.join(root, "images", "reference", "Events", "Old Event", f"{act}.png"))
        write(os.path.join(root, "configs", "Events", "Old Event", f"{act}.json"), "{}")
    return store


def exists(root: str, *parts: str) -> bool:
    return os.path.exists(os.path.join(root, *parts))


# # Renaming an event moves all three trees and rewrites every step image
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    ok, message = rename_event(root, store, "Old Event", "New Event")
    assert ok, message

    assert store.maps() == ["New Event"], store.maps()
    assert store.acts("New Event") == ["Main", "Act 1", "Act 2"], store.acts("New Event")
    for act in ("Act 1", "Act 2"):
        steps = store.steps("New Event", act)
        assert steps and steps[0].image == step_image("New Event", act, 1), steps[0].image
        assert exists(root, step_image("New Event", act, 1))
        assert exists(root, "images", "reference", "Events", "New Event", f"{act}.png")
        assert exists(root, "configs", "Events", "New Event", f"{act}.json")
    # Nothing left behind under the old name, in any tree.
    for tree in (("images", "events"), ("images", "reference", "Events"), ("configs", "Events")):
        assert not exists(root, *tree, "Old Event"), tree

# # Renaming one act moves only that act's files
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    ok, message = rename_act(root, store, "Old Event", "Act 1", "Prologue")
    assert ok, message

    assert store.acts("Old Event") == ["Main", "Prologue", "Act 2"], store.acts("Old Event")
    steps = store.steps("Old Event", "Prologue")
    assert steps and steps[0].image == step_image("Old Event", "Prologue", 1), steps[0].image
    assert exists(root, step_image("Old Event", "Prologue", 1))
    assert exists(root, "images", "reference", "Events", "Old Event", "Prologue.png")
    assert exists(root, "configs", "Events", "Old Event", "Prologue.json")
    # The other act is untouched, files and route alike.
    assert exists(root, step_image("Old Event", "Act 2", 1))
    assert store.steps("Old Event", "Act 2")[0].image == step_image("Old Event", "Act 2", 1)
    assert not exists(root, step_image("Old Event", "Act 1", 1))
    assert not exists(root, "configs", "Events", "Old Event", "Act 1.json")

# # Collisions are refused, not merged: merging two acts loses one route
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    ok, message = rename_act(root, store, "Old Event", "Act 1", "Act 2")
    assert not ok and "already" in message, message
    # Refused means *nothing* moved.
    assert exists(root, step_image("Old Event", "Act 1", 1))
    assert store.steps("Old Event", "Act 1")[0].image == step_image("Old Event", "Act 1", 1)

    store.add_map("Other Event")
    ok, message = rename_event(root, store, "Old Event", "Other Event")
    assert not ok, message
    assert store.maps() == ["Old Event", "Other Event"], store.maps()

# # A name with nothing usable in it is refused; a dangerous one is sanitised, not refused
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    for empty in ("", "   "):
        ok, _message = rename_event(root, store, "Old Event", empty)
        assert not ok, repr(empty)
    assert not rename_event(root, store, "Old Event", "Old Event")[0], "same name is a no-op"
    assert store.maps() == ["Old Event"]

    # `safe_component` neutralises separators and traversal rather than rejecting them —
    # the same contract `add_map` already gives, so a rename cannot be stricter than the
    # add that created the name. What matters is that nothing escapes the event folder.
    ok, _message = rename_event(root, store, "Old Event", "../Escape/Act")
    assert ok, _message
    # `..` -> `-` and each separator -> `-`, so the whole thing is one flat segment.
    assert store.maps() == ["--Escape-Act"], store.maps()
    assert exists(root, "images", "events", "--Escape-Act")
    assert not exists(root, "images", "Escape"), "a rename must not climb out of the tree"

# # A step pointing outside the event's own folder is left alone
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    store.set_steps(
        "Old Event",
        "Act 1",
        [NavStep(kind="find", image="images/lobby/play.png")],
    )
    assert rename_event(root, store, "Old Event", "New Event")[0]
    kept = store.steps("New Event", "Act 1")[0].image
    assert kept == "images/lobby/play.png", kept

# # routes.json stays loadable and keeps its schema through a rename
with tempfile.TemporaryDirectory() as root:
    store = build(root)
    assert rename_event(root, store, "Old Event", "Renamed")[0]
    with open(os.path.join(root, "routes.json"), encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["Schema"] == 1, payload
    assert list(payload["Maps"]) == ["Renamed"], payload

print("route rename: OK")
