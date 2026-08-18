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
