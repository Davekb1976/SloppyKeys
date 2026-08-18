"""Runnable check for Auto walk paths.

No framework: `.venv\\Scripts\\python.exe tests\\test_walk_paths.py`.

Two silent failures live here. The target lookup is act-then-map, so a wrong order walks the
map's shared route through an act that needed its own. And every name in the table has to
resolve to a file on disk or Auto does nothing at all — which looks exactly like a macro that
chose not to walk.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.walk_paths import (  # noqa: E402
    DEFAULT_WALK_PATHS,
    default_walk_path,
    target_key,
)
from sloppykeys.macro.recording import (  # noqa: E402
    list_walk_paths,
    replay_walk_script,
    walk_path_file,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    # An incomplete target has no key, so it can never match a two-part row by accident.
    assert target_key("Raid", "", "Act 2") == ""
    assert target_key("", "Spirit City", "Act 2") == ""
    assert target_key("Raid", "Spirit City", "Act 2") == "Raid/Spirit City/Act 2"

    assert default_walk_path("Raid", "Spirit City", "Act 2") == "Spirit City Act 2"
    assert default_walk_path("Raid", "Spirit City", "Act 3") == "Spirit City Act 3"
    # A map-level row serves every act, including the two icon acts.
    assert default_walk_path("Story", "East Town", "Act 1") == "East Town"
    assert default_walk_path("Story", "East Town", "Mastery") == "East Town"
    # Same map name in another gamemode is a different spawn: no row, no walk.
    assert default_walk_path("Expedition", "East Town", "") == ""
    # No row, act or map: Auto has nothing and the caller skips.
    assert default_walk_path("Story", "Flower Forest", "Act 1") == ""
    assert default_walk_path("Raid", "Spirit City", "Act 1") == ""

    # Every shipped mapping resolves to a file, and that file replays.
    available = list_walk_paths(ROOT)
    for target, name in DEFAULT_WALK_PATHS.items():
        found = walk_path_file(ROOT, name)
        assert found, f"{target} -> {name!r} has no recording on disk"
        assert os.path.isfile(found), found
        assert name in available, f"{name!r} missing from the dropdown list"
        script = replay_walk_script(ROOT, name)
        assert script.startswith("#Requires AutoHotkey v2.0"), name
        # Every key pressed is released: a script that exits holding W walks forever.
        assert script.count("{w up}") >= script.count("{w down}"), name
        assert script.count("{a up}") >= script.count("{a down}"), name
        assert script.count("{d up}") >= script.count("{d down}"), name
        assert script.count("{s up}") >= script.count("{s down}"), name

    # A name nobody recorded is a miss, not an exception.
    assert walk_path_file(ROOT, "no such path") == ""
    assert replay_walk_script(ROOT, "no such path") == ""

    print(f"OK: {len(DEFAULT_WALK_PATHS)} Auto targets, all resolving")


if __name__ == "__main__":
    main()
