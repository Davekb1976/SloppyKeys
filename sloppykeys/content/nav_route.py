"""DATA: user-authored lobby navigation routes (the Events gamemode).

Story/Raid/Expedition navigate through fixed tables (`acts.py`, `start_stage.py`,
`nav_images.py`) because their menus don't move. Events rotate: a new event brings
new cards, new positions, sometimes new acts, so a table baked into the app would
be stale by the next update. A route is the same navigation expressed as data the
user can edit at runtime.

A route is an ordered list of `NavStep`, run after the Events button is clicked
and before the stage-loaded wait. The last step is expected to click Start.

Coordinates are Roblox client-space at the pinned 1152x756 viewport, exactly like
`ACT_COORDS` and placement coordinates, so they carry the same dependency on that
size.

Why a separate model from `content.units.StepAction`: that one is in-game input
for a placed unit (drag, key, priority) and its payload is written into every
saved unit config. A route needs template matching, a scroll-until-found loop and
a search region, and needs none of drag or key. Bolting six lobby-only fields
onto StepAction would put them in the unit sequence editor and in every
`configs/` file that has a Sequence step.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# # Step kinds
# click  — click a fixed client coordinate (the "I measured it" case)
# find   — match a template and click it, scrolling to bring it into view
# expect — match a template but click nothing: proves the screen we think we're on
# scroll — wheel at a point, for a list that needs moving without a target
# wait   — a blind pause, for a transition nothing can verify
KIND_CLICK = "click"
KIND_FIND = "find"
KIND_EXPECT = "expect"
KIND_SCROLL = "scroll"
KIND_WAIT = "wait"

KINDS = (KIND_CLICK, KIND_FIND, KIND_EXPECT, KIND_SCROLL, KIND_WAIT)
KIND_LABELS = {
    KIND_CLICK: "Click",
    KIND_FIND: "Find + click",
    KIND_EXPECT: "Expect image",
    KIND_SCROLL: "Scroll",
    KIND_WAIT: "Wait",
}

# Which fields each kind actually uses, so the editor shows only what applies
# (same contract as units.ACTION_FIELDS).
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    KIND_CLICK: ("x", "y", "button", "count"),
    # No button here: a found card is always left-clicked, and the navigator's
    # match click path (`_click`) has no button argument to feed.
    KIND_FIND: (
        "image",
        "region",
        "timeout",
        "max_scrolls",
        "notches",
        "scroll_x",
        "scroll_y",
    ),
    KIND_EXPECT: ("image", "region", "timeout"),
    KIND_SCROLL: ("notches", "scroll_x", "scroll_y"),
    KIND_WAIT: ("wait_ms",),
}

BUTTON_OPTIONS = ["left", "right", "middle"]
BUTTON_DEFAULT = "left"

# A find that scrolls is a bounded search, not an infinite one.
MAX_SCROLLS_CEILING = 30
NOTCHES_CEILING = 50
TIMEOUT_CEILING = 120.0
WAIT_CEILING = 60000


def safe_rel_path(value: str) -> str:
    """A template path from the UI, reduced to something safe to join onto
    app_root. Returns "" for anything that tries to escape.

    This is a trust boundary: the string arrives from a saved JSON file the user
    can hand-edit and ends up opened by the image engine. Absolute paths and any
    `..` segment are rejected rather than repaired, so a bad value fails the step
    loudly instead of reading somewhere unexpected.
    """
    cleaned = str(value).strip().replace("\\", "/").strip("/")
    if not cleaned or os.path.isabs(cleaned) or ":" in cleaned:
        return ""
    parts = [part for part in cleaned.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        return ""
    return "/".join(parts)


def _int(payload: dict, key: str, default: int = 0) -> int:
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class NavStep:
    """One step of a lobby route. Unused fields for a kind are ignored."""

    kind: str = KIND_CLICK
    label: str = ""
    x: int = 0
    y: int = 0
    button: str = BUTTON_DEFAULT
    count: int = 1
    image: str = ""
    # Search region in client space. Width or height of 0 means "whole client".
    region_x: int = 0
    region_y: int = 0
    region_w: int = 0
    region_h: int = 0
    # 0 means "use the navigator's search_timeout", so lowering that setting
    # speeds up every route step that didn't ask for something specific.
    timeout: float = 0.0
    max_scrolls: int = 0
    notches: int = 8
    # Where to put the cursor before wheeling. (0, 0) means the client centre —
    # the same default the unit sequence scroll already uses.
    scroll_x: int = 0
    scroll_y: int = 0
    wait_ms: int = 0

    def uses(self, field_name: str) -> bool:
        if field_name == "region":
            return "region" in KIND_FIELDS.get(self.kind, ())
        return field_name in KIND_FIELDS.get(self.kind, ())

    def region(self) -> tuple[int, int, int, int] | None:
        """Client-space (x, y, w, h), or None for the whole client area.

        A template taller than its region can never match, so an unset region is
        the safe default rather than a zero-sized one.
        """
        if self.region_w <= 0 or self.region_h <= 0:
            return None
        return (self.region_x, self.region_y, self.region_w, self.region_h)

    def scroll_point(self) -> tuple[int, int] | None:
        """The wheel point, or None to use the client centre."""
        if self.scroll_x <= 0 and self.scroll_y <= 0:
            return None
        return (self.scroll_x, self.scroll_y)

    def is_actionable(self) -> tuple[bool, str]:
        """Can this step run? Returns (ok, why not).

        Checked when a route is loaded rather than mid-run: a route that clicks
        three screens deep and then fails on a blank image path has already left
        the game somewhere the next run can't recover from.
        """
        if self.kind not in KINDS:
            return (False, f"unknown step kind '{self.kind}'")
        if self.kind in (KIND_FIND, KIND_EXPECT) and not self.image:
            return (False, "no image set")
        if self.kind == KIND_CLICK and self.x <= 0 and self.y <= 0:
            return (False, "no coordinate set")
        if self.kind == KIND_SCROLL and self.notches == 0:
            return (False, "0 notches does nothing")
        if self.kind == KIND_WAIT and self.wait_ms <= 0:
            return (False, "0 ms does nothing")
        return (True, "")

    def summary(self) -> str:
        """One-line description for the editor list and the run log."""
        name = KIND_LABELS.get(self.kind, self.kind)
        note = f"  ({self.label})" if self.label else ""
        if self.kind == KIND_CLICK:
            times = f" x{self.count}" if self.count > 1 else ""
            return f"{name}  {self.x}, {self.y}  {self.button}{times}{note}"
        if self.kind == KIND_FIND:
            scrolls = f"  +{self.max_scrolls} scrolls" if self.max_scrolls else ""
            return f"{name}  {os.path.basename(self.image) or '?'}{scrolls}{note}"
        if self.kind == KIND_EXPECT:
            return f"{name}  {os.path.basename(self.image) or '?'}{note}"
        if self.kind == KIND_SCROLL:
            way = "down/right" if self.notches >= 0 else "up/left"
            return f"{name}  {abs(self.notches)} {way}{note}"
        if self.kind == KIND_WAIT:
            return f"{name}  {self.wait_ms} ms{note}"
        return f"{name}{note}"

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"Kind": self.kind}
        if self.label:
            payload["Label"] = self.label
        mapping = {
            "x": "X",
            "y": "Y",
            "button": "Button",
            "count": "Count",
            "image": "Image",
            "timeout": "Timeout",
            "max_scrolls": "MaxScrolls",
            "notches": "Notches",
            "scroll_x": "ScrollX",
            "scroll_y": "ScrollY",
            "wait_ms": "Ms",
        }
        for attr, key in mapping.items():
            if self.uses(attr):
                payload[key] = getattr(self, attr)
        if self.uses("region") and self.region() is not None:
            payload["Region"] = [self.region_x, self.region_y, self.region_w, self.region_h]
        return payload

    @classmethod
    def from_payload(cls, payload: dict) -> "NavStep":
        if not isinstance(payload, dict):
            return cls()
        raw_kind = str(payload.get("Kind", "")).strip().lower()
        kind = raw_kind if raw_kind in KINDS else KIND_CLICK
        button = str(payload.get("Button", BUTTON_DEFAULT)).strip().lower()

        region = payload.get("Region")
        rx = ry = rw = rh = 0
        if isinstance(region, (list, tuple)) and len(region) == 4:
            try:
                rx, ry, rw, rh = (int(value) for value in region)
            except (TypeError, ValueError):
                rx = ry = rw = rh = 0
        try:
            timeout = float(payload.get("Timeout", 0.0))
        except (TypeError, ValueError):
            timeout = 0.0

        return cls(
            kind=kind,
            label=str(payload.get("Label", ""))[:60],
            x=max(0, _int(payload, "X")),
            y=max(0, _int(payload, "Y")),
            button=button if button in BUTTON_OPTIONS else BUTTON_DEFAULT,
            count=max(1, _int(payload, "Count", 1)),
            image=safe_rel_path(payload.get("Image", "")),
            region_x=max(0, rx),
            region_y=max(0, ry),
            region_w=max(0, rw),
            region_h=max(0, rh),
            timeout=min(max(0.0, timeout), TIMEOUT_CEILING),
            max_scrolls=min(max(0, _int(payload, "MaxScrolls")), MAX_SCROLLS_CEILING),
            notches=max(-NOTCHES_CEILING, min(_int(payload, "Notches", 8), NOTCHES_CEILING)),
            scroll_x=max(0, _int(payload, "ScrollX")),
            scroll_y=max(0, _int(payload, "ScrollY")),
            wait_ms=min(max(0, _int(payload, "Ms")), WAIT_CEILING),
        )


def route_problems(steps: list[NavStep]) -> list[str]:
    """Every reason this route can't run, as "step N: why" lines."""
    problems = []
    for position, step in enumerate(steps, start=1):
        ok, why = step.is_actionable()
        if not ok:
            problems.append(f"step {position}: {why}")
    return problems
