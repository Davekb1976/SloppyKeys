"""Runnable check for the OCR region previews.

No framework: `.venv\\Scripts\\python.exe tests\\test_region_preview.py`.

Two things here fail quietly if they break. The crop maps a 1152x756-space box onto whatever
size the client really is, so a wrong divisor shows a picture of the wrong pixels and looks
like an OCR fault. And the region key becomes a filename, so it is whitelisted against the
tables rather than escaped.
"""

from __future__ import annotations

import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.ui_web.bridge import Api  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_region_preview")


def make_api() -> Api:
    api = Api.__new__(Api)  # no window needed: nothing here touches pywebview
    api._app_root = ROOT
    api._window = None
    api._cached_snapshot = None
    os.makedirs(ROOT, exist_ok=True)
    return api


def main() -> None:
    api = make_api()
    keys = [s["key"] for s in api.get_vision_region_specs()]
    assert keys, "no region specs to preview"
    key = keys[0]

    # Only a key that exists in a table can become a filename.
    assert api._known_region_key(key) == key
    for bad in ("../../evil", "regions/../x", "nope", 5, None, ""):
        assert api._known_region_key(bad) == "", f"{bad!r} accepted"

    # A 1440x945 client is the same view at a different size: the box scales with it.
    img = np.zeros((945, 1440, 3), dtype=np.uint8)
    crop = api._crop_region(img, [100, 200, 80, 20])
    assert crop.shape[:2] == (25, 100), crop.shape
    # Off the edge clamps to something croppable rather than an empty slice.
    edge = api._crop_region(img, [1140, 750, 100, 100])
    assert edge.shape[0] >= 1 and edge.shape[1] >= 1, edge.shape

    # Saved from the cached snapshot, then read back byte-identical.
    api._cached_snapshot = np.full((756, 1152, 3), 200, dtype=np.uint8)
    saved = api.save_region_preview(key, [10, 10, 40, 16])
    assert saved["ok"] and saved["data_uri"].startswith("data:image/png;base64,"), saved
    assert os.path.isfile(os.path.join(api._region_preview_dir(), f"{key}.png"))
    assert api.get_region_previews().get(key) == saved["data_uri"], "read back differs"

    # Refusals, not repairs.
    assert api.save_region_preview("../evil", [0, 0, 4, 4])["ok"] is False
    assert api.save_region_preview(key, ["x", 0, 4, 4])["ok"] is False
    api._cached_snapshot = None
    assert api.save_region_preview(key, [0, 0, 4, 4])["ok"] is False

    print(f"OK: {len(keys)} region keys, crop + save + read back")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
