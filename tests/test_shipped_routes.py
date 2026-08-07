"""Runnable checks for merging the routes a build ships into the user's routes.json.

An upgrade can never overwrite `routes.json` — it holds the user's own events — so a route
shipped with a new version arrives through `routes.default.json` instead. The risk is the
other way round: a merge that runs every launch and re-adds an act the user deleted, or
overwrites steps they edited under a shipped name.

No framework, no Qt, no capture, no input. Everything happens in a temp tree:
`.venv\\Scripts\\python.exe tests\\test_shipped_routes.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.nav_routes import (  # noqa: E402
    ROUTES_FILE,
    SHIPPED_FILE,
    RouteStore,
)
from sloppykeys.content.nav_route import NavStep  # noqa: E402


def ship(root: str, maps: dict) -> None:
    with open(os.path.join(root, SHIPPED_FILE), "w", encoding="utf-8") as handle:
        json.dump({"Schema": 1, "Maps": maps}, handle)


def one_act(image: str = "images/events/Villain/Act 3_1.png") -> dict:
    return {
        "Villain": {
            "Acts": ["Act 1", "Act 3"],
            "Routes": {"Act 3": [{"Kind": "find", "Image": image}]},
        }
    }


def payload(root: str) -> dict:
    with open(os.path.join(root, ROUTES_FILE), encoding="utf-8") as handle:
        return json.load(handle)


# # A shipped act the user doesn't have arrives, with its steps
with tempfile.TemporaryDirectory() as root:
    store = RouteStore(root)
    store.add_map("Villain")
    store.add_act("Villain", "Act 1")
    store.set_steps("Villain", "Act 1", [NavStep(kind="click", x=10, y=20)])
    ship(root, one_act())

    added = store.merge_shipped()
    assert added == ["Villain / Act 3"], added
    assert store.acts("Villain") == ["Main", "Act 1", "Act 3"], store.acts("Villain")
    steps = store.steps("Villain", "Act 3")
    assert len(steps) == 1 and steps[0].image.endswith("Act 3_1.png"), steps
    # The user's own act is untouched.
    assert store.steps("Villain", "Act 1")[0].kind == "click"

    # # Idempotent: a second launch adds nothing and writes nothing
    before = os.path.getmtime(os.path.join(root, ROUTES_FILE))
    assert store.merge_shipped() == []
    assert os.path.getmtime(os.path.join(root, ROUTES_FILE)) == before, "rewrote for nothing"

    # # An act deleted after the merge stays deleted
    assert store.remove_act("Villain", "Act 3")
    assert store.merge_shipped() == []
    assert "Act 3" not in store.acts("Villain"), store.acts("Villain")
    # The ledger survived the write that removed the act.
    assert "Villain/Act 3" in payload(root)["Shipped"], payload(root)

# # An act the user already has is recorded but never overwritten
with tempfile.TemporaryDirectory() as root:
    store = RouteStore(root)
    store.add_map("Villain")
    store.add_act("Villain", "Act 3")
    store.set_steps("Villain", "Act 3", [NavStep(kind="wait", wait_ms=2000)])
    ship(root, {"Villain": {"Acts": ["Act 3"], "Routes": {"Act 3": [{"Kind": "click"}]}}})

    assert store.merge_shipped() == []
    mine = store.steps("Villain", "Act 3")
    assert len(mine) == 1 and mine[0].kind == "wait", mine
    # Recorded anyway, so a later launch doesn't keep reconsidering it.
    assert payload(root)["Shipped"] == ["Villain/Act 3"], payload(root)

# # A shipped map the user has never seen arrives whole
with tempfile.TemporaryDirectory() as root:
    store = RouteStore(root)
    added = store.merge_shipped()
    assert added == [], "no shipped file means no merge"

    ship(root, one_act())
    added = store.merge_shipped()
    assert added == ["Villain / Act 1", "Villain / Act 3"], added
    assert store.maps() == ["Villain"], store.maps()
    assert store.acts("Villain") == ["Act 1", "Act 3"], store.acts("Villain")

# # A fresh install already holds the shipped routes: recorded, nothing added, no duplicates
with tempfile.TemporaryDirectory() as root:
    maps = one_act()
    with open(os.path.join(root, ROUTES_FILE), "w", encoding="utf-8") as handle:
        json.dump({"Schema": 1, "Maps": maps}, handle)
    ship(root, maps)

    store = RouteStore(root)
    assert store.merge_shipped() == []
    assert store.acts("Villain") == ["Act 1", "Act 3"], store.acts("Villain")
    assert sorted(payload(root)["Shipped"]) == ["Villain/Act 1", "Villain/Act 3"]

# # Junk in the shipped file is dropped, not trusted into a path
with tempfile.TemporaryDirectory() as root:
    store = RouteStore(root)
    ship(
        root,
        {
            "../Escape": {"Acts": ["Act 1"], "Routes": {}},
            "   ": {"Acts": ["Act 1"], "Routes": {}},
            "Fine": {"Acts": ["Act 1", "", 7], "Routes": {"Act 1": "not a list"}},
            "Broken": "not a dict",
        },
    )
    added = store.merge_shipped()
    # `..` and the separator are neutralised the same way `add_map` does it, so the name
    # stays one flat segment; the blank and the non-dict entry are dropped.
    assert added == ["--Escape / Act 1", "Fine / Act 1", "Fine / 7"], added
    assert store.steps("Fine", "Act 1") == [], "a non-list route must not be stored"

with tempfile.TemporaryDirectory() as root:
    # A corrupt shipped file is a no-op, not a crash.
    with open(os.path.join(root, SHIPPED_FILE), "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert RouteStore(root).merge_shipped() == []

print("shipped routes: OK")
