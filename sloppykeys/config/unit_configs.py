"""Path-safe name components.

All that survives of the per-target unit plan store. Plans are block-based now and
live in `operations/<name>.json` (`config/operations.py`); the `configs/` tree and
its `UnitConfigStore` are gone.

Kept here because a display name still becomes a path segment in two places — a
route's map/act name (`config/nav_routes.py::clean_name`) and the placement
picker's reference images — and both must sanitise the same way.
"""

from __future__ import annotations


def safe_component(value: str) -> str:
    """One path segment from a display name. Shared with the placement picker's
    reference images, so any name that becomes a path goes through here."""
    cleaned = str(value).strip()
    for illegal in '<>:"/\\|?*':
        cleaned = cleaned.replace(illegal, "-")
    # No traversal: none of the real gamemode/map/act names contain "..", so this
    # only ever fires on something that shouldn't be building a path.
    return cleaned.replace("..", "-")
