"""Runnable check for the placement picker's map reference lookup.

No framework: `.venv\\Scripts\\python.exe tests\\test_reference_images.py`.
Writes only into a temp dir; never touches images/reference.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sloppykeys.ui.placement_overlay import load_reference, reference_path  # noqa: E402

app = QApplication([])

with tempfile.TemporaryDirectory() as images_dir:
    # An incomplete selection has no path, so nothing can be looked up.
    assert reference_path(images_dir, "", "") is None
    assert reference_path(images_dir, "Story", "") is None
    assert reference_path("", "Story", "Flower Forest") is None
    assert load_reference(images_dir, "Story", "Flower Forest") is None

    path = reference_path(images_dir, "Story", "Flower Forest")
    assert path is not None
    assert path.endswith(os.path.join("reference", "Story", "Flower Forest.png")), path

    # Names that become a path are sanitised, and traversal can't escape the dir —
    # including the act, which is now part of the path too.
    for dodgy in (
        reference_path(images_dir, "..", "../../evil"),
        reference_path(images_dir, "Raid", "Spirit City", "../../../evil"),
    ):
        assert dodgy is not None
        assert os.path.commonpath([os.path.abspath(dodgy), os.path.abspath(images_dir)]) == (
            os.path.abspath(images_dir)
        ), dodgy

    # A real file at that path loads back at its own size.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shot = QPixmap(816, 638)
    shot.fill()
    assert shot.save(path, "PNG")

    loaded = load_reference(images_dir, "Story", "Flower Forest")
    assert loaded is not None
    assert (loaded.width(), loaded.height()) == (816, 638), (loaded.width(), loaded.height())

    # # Per-act references (Raid: one map, three separate areas)
    act_path = reference_path(images_dir, "Raid", "Spirit City", "Act 2")
    assert act_path is not None
    assert act_path.endswith(
        os.path.join("reference", "Raid", "Spirit City", "Act 2.png")
    ), act_path

    # Missing act file falls back to the map file, so Story keeps working as before.
    assert load_reference(images_dir, "Story", "Flower Forest", "Act 3") is not None
    # Nothing for Raid yet, so no background at all.
    assert load_reference(images_dir, "Raid", "Spirit City", "Act 2") is None

    os.makedirs(os.path.dirname(act_path), exist_ok=True)
    act_shot = QPixmap(816, 638)
    act_shot.fill()
    assert act_shot.save(act_path, "PNG")
    assert load_reference(images_dir, "Raid", "Spirit City", "Act 2") is not None
    # A different act of the same map still has no image of its own and no map file.
    assert load_reference(images_dir, "Raid", "Spirit City", "Act 1") is None

    # A file that isn't a readable image is treated as missing, not as a crash.
    broken = reference_path(images_dir, "Story", "Rose Kingdom")
    assert broken is not None
    with open(broken, "wb") as handle:
        handle.write(b"not a png")
    assert load_reference(images_dir, "Story", "Rose Kingdom") is None

print("reference images: OK")
