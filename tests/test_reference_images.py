"""Runnable checks for where a placement backdrop lives.

    .venv\\Scripts\\python.exe tests\\test_reference_images.py

Two layouts (see assets/reference/README.md): one file per map, or one per act where the
acts are separate areas of it. Getting the shape wrong means the picker shows the wrong
ground, and every coordinate read off it is wrong in a way that looks like a bad click.

This used to test `sloppykeys.ui.placement_overlay.reference_path` / `load_reference` and
their QPixmap loading. That module went with the PySide6 front end: the path is
`content/nav_images.map_reference_image` now and the loading is `Api.get_map_image`. The
name sanitisation is the part worth keeping either way — a gamemode/map/act reaches the
filesystem, and for an Events route the user typed all three.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.gamemodes import GAMEMODES  # noqa: E402
from sloppykeys.content.nav_images import (  # noqa: E402
    map_reference_image,
    map_reference_paths,
)
from sloppykeys.ui_web.bridge import Api  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# # Per map: Story's five acts share one playfield.
assert map_reference_image("Story", "Flower Forest") == os.path.join(
    "assets", "reference", "Story", "Flower Forest.png"
), map_reference_image("Story", "Flower Forest")

# # Per act: Raid's acts are separate areas of Spirit City, so each needs its own.
assert map_reference_image("Raid", "Spirit City", "Act 2") == os.path.join(
    "assets", "reference", "Raid", "Spirit City", "Act 2.png"
), map_reference_image("Raid", "Spirit City", "Act 2")

# # Nothing escapes assets/reference, whatever the name says. An Events map and act are
# typed by the user, and this path is what a capture overwrites.
for dodgy in (
    map_reference_image("..", "../../evil"),
    map_reference_image("Raid", "Spirit City", "../../../evil"),
    map_reference_image("Story", 'bad:name*here?'),
):
    assert ".." not in dodgy, dodgy
    assert dodgy.startswith(os.path.join("assets", "reference") + os.sep), dodgy
    assert dodgy.count(os.sep) <= 4, dodgy  # assets/reference/<mode>/<map>[/<act>]

# # The schema drives the list, so a new map needs no edit here.
paths = map_reference_paths()
assert len(paths) == len(set(paths)), "a backdrop is claimed twice"
for name, gamemode in GAMEMODES.items():
    want = [p for p in paths if p.startswith(os.path.join("assets", "reference", name) + os.sep)]
    if gamemode.custom or gamemode.side_task:
        # Events' maps live in routes.json; Challenge plays Story's maps and reads Story's
        # backdrops.
        assert not want, (name, want)
        continue
    expected = len(gamemode.maps) * (len(gamemode.targets) if gamemode.per_act_reference else 1)
    assert len(want) == expected, (name, len(want), expected)

# # The bridge refuses to read outside the folder rather than trusting the page.
api = Api.__new__(Api)  # no window: nothing here touches pywebview
api._app_root = ROOT
for cat, name in (("..", "settings"), ("Story", "../../settings"), ("Story", "../../../evil")):
    assert api.get_map_image(cat, name)["ok"] is False, (cat, name)

print("reference images: OK")
