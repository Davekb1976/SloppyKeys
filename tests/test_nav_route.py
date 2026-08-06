"""Events route model + store. Run: .venv\\Scripts\\python.exe tests\\test_nav_route.py

Covers the parts that fail silently: the path trust boundary, the payload
round-trip (a route that doesn't reload is a route the user rebuilds), the
"a map always has one act" invariant the config path depends on, and the
up-front validation that stops a half-navigated menu.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.config.nav_routes import DEFAULT_ACT, RouteStore, clean_name
from sloppykeys.content.gamemodes import has_targets, is_custom, maps_for
from sloppykeys.content.nav_route import (
    KIND_CLICK,
    KIND_FIND,
    KIND_SCROLL,
    KIND_WAIT,
    NavStep,
    route_problems,
    safe_rel_path,
)


def test_safe_rel_path() -> None:
    assert safe_rel_path("images/events/a.png") == "images/events/a.png"
    assert safe_rel_path("images\\events\\a.png") == "images/events/a.png"
    assert safe_rel_path("./images/a.png") == "images/a.png"
    # A template path is opened by the image engine, so escapes are refused
    # outright rather than repaired.
    assert safe_rel_path("../../secrets.png") == ""
    assert safe_rel_path("images/../../x.png") == ""
    assert safe_rel_path("C:/Windows/x.png") == ""
    assert safe_rel_path("") == ""


def test_payload_round_trip() -> None:
    step = NavStep(kind=KIND_FIND, image="images/events/villain.png", max_scrolls=4, notches=6)
    step.region_x, step.region_y, step.region_w, step.region_h = 10, 20, 200, 40
    assert NavStep.from_payload(step.as_payload()) == step

    click = NavStep(kind=KIND_CLICK, x=652, y=785, button="right", count=2, label="Start")
    assert NavStep.from_payload(click.as_payload()) == click

    # Only the fields a kind uses are written.
    assert "X" not in NavStep(kind=KIND_WAIT, wait_ms=500).as_payload()
    assert "Image" not in NavStep(kind=KIND_CLICK, x=1, y=1).as_payload()


def test_payload_defaults_and_clamps() -> None:
    assert NavStep.from_payload({}).kind == KIND_CLICK
    assert NavStep.from_payload({"Kind": "nonsense"}).kind == KIND_CLICK
    assert NavStep.from_payload({"Kind": "wait"}).kind == KIND_WAIT
    # Hand-edited rubbish must not crash the loader.
    assert NavStep.from_payload({"Kind": "click", "X": "abc"}).x == 0
    assert NavStep.from_payload({"Kind": "find", "Region": [1, 2]}).region() is None
    assert NavStep.from_payload({"Kind": "find", "MaxScrolls": 9999}).max_scrolls <= 30
    assert NavStep.from_payload({"Kind": "click", "Button": "sideways"}).button == "left"


def test_region_and_scroll_point_defaults() -> None:
    # A zero-sized region would never match; unset means whole client.
    assert NavStep(kind=KIND_FIND, image="a.png").region() is None
    assert NavStep(kind=KIND_FIND, image="a.png", region_w=10, region_h=0).region() is None
    # (0, 0) means the client centre, matching the unit sequence scroll.
    assert NavStep(kind=KIND_SCROLL, notches=3).scroll_point() is None
    assert NavStep(kind=KIND_SCROLL, notches=3, scroll_x=4, scroll_y=5).scroll_point() == (4, 5)


def test_route_problems() -> None:
    assert route_problems([NavStep(kind=KIND_FIND)]) == ["step 1: no image set"]
    assert route_problems([NavStep(kind=KIND_CLICK)]) == ["step 1: no coordinate set"]
    assert route_problems([NavStep(kind=KIND_WAIT)]) == ["step 1: 0 ms does nothing"]
    assert route_problems([NavStep(kind=KIND_SCROLL, notches=0)]) == ["step 1: 0 notches does nothing"]
    assert route_problems([NavStep(kind=KIND_CLICK, x=100, y=200)]) == []


def test_store_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = RouteStore(tmp)
        assert store.maps() == []
        assert store.add_map("Villain Invasion") == "Villain Invasion"
        # A map always carries one act, so Gamemode/Map/Act always completes and
        # configs/Events/<Map>/<Act>.json keeps Story's shape.
        assert store.acts("Villain Invasion") == [DEFAULT_ACT]
        assert store.add_act("Villain Invasion", "Act 1") == "Act 1"

        saved = [
            NavStep(kind=KIND_FIND, image="images/events/villain.png", max_scrolls=5),
            NavStep(kind=KIND_CLICK, x=652, y=785),
            NavStep(kind=KIND_WAIT, wait_ms=800),
        ]
        assert store.set_steps("Villain Invasion", "Act 1", saved)
        assert store.steps("Villain Invasion", "Act 1") == saved
        # Each act is its own route.
        assert store.steps("Villain Invasion", DEFAULT_ACT) == []

        # A map keeps at least one act.
        assert store.remove_act("Villain Invasion", "Act 1")
        assert not store.remove_act("Villain Invasion", DEFAULT_ACT)
        assert store.remove_map("Villain Invasion")
        assert store.maps() == []


def test_store_rejects_unusable_names() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = RouteStore(tmp)
        # Names become path segments, so traversal is neutralised on the way in.
        assert ".." not in clean_name("../evil")
        assert "/" not in clean_name("a/b")
        assert store.add_map("   ") == ""
        assert store.maps() == []
        assert store.add_act("missing map", "Act 1") == ""


def test_store_survives_a_corrupt_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "routes.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        store = RouteStore(tmp)
        assert store.maps() == []
        assert store.steps("x", "y") == []


def test_events_schema() -> None:
    assert is_custom("Events") and not is_custom("Story")
    # Must stay True or the unit config path collapses to configs/Events/<Map>.json.
    assert has_targets("Events")
    # The static table knows no Events maps; the route store supplies them.
    assert maps_for("Events") == []


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("nav route: OK")
