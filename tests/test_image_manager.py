"""Runnable check for the Image Manager listing and the map-reference save.

No framework: `.venv\\Scripts\\python.exe tests\\test_image_manager.py`.

Map references are the one category that is not a searched template: they are whole-screen
backdrops the position picker draws placement coordinates on. If `kind` came back as
"template" the page would offer a match threshold and a Test that can never mean anything,
and a capture would crop — which silently makes every coordinate read off that map wrong.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.gamemodes import GAMEMODES  # noqa: E402
from sloppykeys.content.nav_images import map_reference_image  # noqa: E402
from sloppykeys.ui_web.bridge import Api  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    api = Api.__new__(Api)  # no window: nothing here touches pywebview
    api._app_root = ROOT
    api._window = None
    api._ctrl = None
    api._cached_snapshot = None

    result = api.list_vision_templates()
    assert result["ok"], result
    kinds = {c["key"]: c.get("kind") for c in result["categories"]}
    assert kinds.get("reference") == "map", f"maps missing or mislabelled: {kinds}"
    for key, kind in kinds.items():
        if key != "reference":
            assert kind == "template", f"{key} should be a template, got {kind}"

    maps = next(c for c in result["categories"] if c["key"] == "reference")
    assert maps["names"], "no map references found under assets/reference"
    for entry in maps["names"]:
        assert entry["path"].startswith("assets/reference/"), entry["path"]

    # Every backdrop the schema implies gets a card, captured or not: a mode absent from
    # the listing has nowhere to capture into, which is how Expedition ended up with no
    # maps at all. Raid is the per-act layout, Expedition the per-map one.
    listed = {e["path"] for e in maps["names"]}
    for name, gamemode in GAMEMODES.items():
        # Events' maps live in routes.json; Challenge plays Story's maps and reads Story's
        # backdrops, so neither gets cards of its own.
        if gamemode.custom or gamemode.side_task:
            continue
        for map_name in gamemode.maps:
            acts = gamemode.targets if gamemode.per_act_reference else [""]
            for act in acts:
                want = map_reference_image(name, map_name, act).replace("\\", "/")
                assert want in listed, f"no card for {want}"
    assert "assets/reference/Expedition/East Town.png" in listed
    assert "assets/reference/Raid/Spirit City/Act 2.png" in listed
    assert not [p for p in listed if p.startswith("assets/reference/Challenge/")]
    # Grouping the page renders sections from: category-relative subfolder.
    groups = {e["group"] for e in maps["names"]}
    assert {"Story", "Expedition", "Raid/Spirit City"} <= groups, groups

    # Refusals: traversal, a non-PNG, and no snapshot to save.
    for bad in ("../evil.png", "assets/reference/../../evil.png", "assets/reference/x.txt"):
        assert api.save_map_reference(bad)["ok"] is False, bad
    good = maps["names"][0]["path"]
    assert api.save_map_reference(good)["ok"] is False, "saved with no snapshot cached"

    # Refused without a controller rather than raising into the bridge.
    assert api.run_camera_setup()["ok"] is False

    print(f"OK: {len(maps['names'])} map references, {len(kinds) - 1} template categories")


if __name__ == "__main__":
    main()
