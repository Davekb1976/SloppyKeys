"""Runnable check for the generated camera script.

No framework: `.venv\\Scripts\\python.exe tests\\test_camera_script.py`.

The script is text handed to AHK, so a mistake here is silent: it still runs, it just leaves
the camera somewhere else and every stored placement coordinate then points at the wrong
ground. This pins the shape — one zoom-out hold, no zoom-in, the pitch drag as raw deltas —
and that `zoom_ms` actually reaches the Sleep.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.camera import PITCH_DELTA, camera_setup_script  # noqa: E402
from sloppykeys.macro.controller import MacroController  # noqa: E402


def main() -> None:
    script = camera_setup_script(576, 378, zoom_ms=1500, pitch_steps=40)

    # The zoom-in hold was removed: it cost a whole zoom_ms to reach first person before a
    # rotation that does not need it.
    assert "{i down}" not in script and "{i up}" not in script, "hold-I is back"

    # One zoom-out hold, and the delay value is the one that lands in it.
    assert script.count("{o down}") == 1 and script.count("{o up}") == 1
    assert "Sleep(1500)" in script, "zoom_ms did not reach the hold"

    # Pitch: right button down, 40 raw moves, right button up — in that order.
    down = script.index('"UInt", 8')     # MOUSEEVENTF_RIGHTDOWN
    move = script.index('"UInt", 1')     # MOUSEEVENTF_MOVE
    up = script.index('"UInt", 16')      # MOUSEEVENTF_RIGHTUP
    assert down < move < up, "pitch drag is out of order"
    assert f"Loop 40" in script
    assert f'"Int", {PITCH_DELTA // 40}' in script, "pitch step size changed"

    # Cursor is glided to the given centre, not teleported.
    assert "MouseMove(576, 378, 10)" in script

    # The bridge's Set Camera button calls this by name.
    assert callable(getattr(MacroController, "run_camera", None)), "run_camera missing"
    assert not hasattr(MacroController, "_run_camera"), "old private name left behind"

    print("OK: camera script pitches then zooms out, no zoom-in hold")


if __name__ == "__main__":
    main()
