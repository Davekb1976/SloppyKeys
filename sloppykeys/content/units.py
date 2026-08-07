"""Per-step unit placement field definitions."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Shared with the route steps on purpose: a template path is a template path, and one
# validator means a Find + Click action can't be laxer than a route's Find step.
from .nav_route import safe_rel_path

# 12 index tabs x 6 steps per tab.
INDEX_COUNT = 12
STEPS_PER_INDEX = 6
TOTAL_STEPS = INDEX_COUNT * STEPS_PER_INDEX

# Hotbar slots available in Anime Expedition: six units per loadout.
SLOT_MIN = 1
SLOT_MAX = 6


SLOT_OPTIONS = [str(number) for number in range(SLOT_MIN, SLOT_MAX + 1)]
SLOT_PLACEHOLDER = "Slot"


def slot_index(slot: str) -> int | None:
    """Parse a typed slot into 1..SLOT_MAX, or None if it isn't a valid slot.

    Slot identity is what ties steps together in the UI — two steps using slot 2
    are the same unit, so they get the same colour wherever they're drawn.
    """
    try:
        value = int(str(slot).strip())
    except (TypeError, ValueError):
        return None
    return value if SLOT_MIN <= value <= SLOT_MAX else None

# Confirmed from the in-game targeting menu.
PRIORITY_OPTIONS = [
    "First",
    "Last",
    "Closest",
    "Strongest",
    "Boss",
    "Weakest",
    "Shielded",
    "Fastest",
    "None",
]


# Anime Expedition counts upgrades from 0: level 0 is the unit as placed, with no
# upgrade bought. So 0 is a real, meaningful choice and the natural default — it
# is not an "unset" placeholder, which is why this list starts at 0 and the
# Upgrade Level control has no separate placeholder entry.
UPGRADE_MIN = 0
UPGRADE_MAX = 19
UPGRADE_OPTIONS = [str(level) for level in range(UPGRADE_MIN, UPGRADE_MAX + 1)]
UPGRADE_DEFAULT = str(UPGRADE_MIN)

# # Auto upgrade
# The game's auto upgrade is a *cycling* control on the unit panel, not an on/off
# switch: each press of the auto-upgrade key steps it up one level — 1 through 6 —
# and a 7th press brings it back to off. So what a step stores is a **press
# count**, and for 1..6 that count is the auto level it lands on. 7 is the full
# cycle: useful only to force a unit that is already auto-upgrading back to off,
# since a freshly placed unit starts there anyway.
AUTOUPGRADE_OFF = 0
AUTOUPGRADE_CYCLE = 7  # presses that bring the panel back round to off
AUTOUPGRADE_MAX_LEVEL = AUTOUPGRADE_CYCLE - 1  # 6 real levels
# (label, presses) for the Upgrade Level row's dropdown.
AUTOUPGRADE_OPTIONS: list[tuple[str, int]] = (
    [("Off", AUTOUPGRADE_OFF)]
    + [(str(level), level) for level in range(1, AUTOUPGRADE_CYCLE)]
    + [("7 (back to off)", AUTOUPGRADE_CYCLE)]
)


def autoupgrade_presses(value: object) -> int:
    """How many times to press the auto-upgrade key, 0..7.

    Tolerates the 0/1 flag older configs stored, where 1 meant "auto upgrade on" —
    which is exactly one press, i.e. level 1, so those configs keep behaving the
    same. Anything unreadable is off rather than a guessed level: this drives
    keypresses into the game.
    """
    if isinstance(value, bool):  # bool is an int subclass, so check it first
        return 1 if value else AUTOUPGRADE_OFF
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "on"}:
            return 1
        if text in {"", "false", "no", "off"}:
            return AUTOUPGRADE_OFF
        value = text
    try:
        presses = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return AUTOUPGRADE_OFF
    return max(AUTOUPGRADE_OFF, min(AUTOUPGRADE_CYCLE, presses))


def autoupgrade_is_on(value: object) -> bool:
    """True when the step leaves auto upgrade running, so the manual upgrade level
    doesn't apply. A full cycle (7) ends on off, so it doesn't count."""
    return AUTOUPGRADE_OFF < autoupgrade_presses(value) < AUTOUPGRADE_CYCLE

PRIORITY_PLACEHOLDER = "Select Priority"

# # Step kinds
# A chip is either a unit placement or a hand-authored input sequence. They're
# mutually exclusive: making one chip do both turns every field conditional and
# the detail card unreadable. Steps still run in chip order, so a run interleaves
# placements and sequences naturally.
KIND_UNIT = "unit"
KIND_SEQUENCE = "sequence"
KINDS = (KIND_UNIT, KIND_SEQUENCE)
KIND_LABELS = {KIND_UNIT: "Unit", KIND_SEQUENCE: "Sequence"}

# # Sequence action types
ACTION_MOVE = "move"
ACTION_CLICK = "click"
ACTION_DRAG = "drag"
ACTION_KEY = "key"
ACTION_SCROLL = "scroll"
ACTION_WAIT = "wait"
# Click where a template is on screen, rather than at a coordinate. For an ability button
# that moves, or appears more than once: `click_all` presses every instance found.
ACTION_FIND_CLICK = "findclick"
# A gate, not an input: OCR the wave counter and only let the rest of the sequence run once
# the match has reached `wave`. `max_wave` is the map's total, and it is what makes the read
# trustworthy — a counter that reads "12/25" is checked against it, and a bare "125" is
# rejected as a misread instead of being taken as wave 125.
ACTION_WAVE = "wave"

ACTION_TYPES = (
    ACTION_MOVE,
    ACTION_CLICK,
    ACTION_FIND_CLICK,
    ACTION_DRAG,
    ACTION_KEY,
    ACTION_SCROLL,
    ACTION_WAIT,
    ACTION_WAVE,
)
ACTION_LABELS = {
    ACTION_MOVE: "Move",
    ACTION_CLICK: "Click",
    ACTION_FIND_CLICK: "Find + Click",
    ACTION_DRAG: "Drag",
    ACTION_KEY: "Key",
    ACTION_SCROLL: "Scroll",
    ACTION_WAIT: "Wait",
    ACTION_WAVE: "Wait for Wave",
}
# Which fields each type actually uses, so the editor shows only what applies.
ACTION_FIELDS = {
    ACTION_MOVE: ("x", "y"),
    ACTION_CLICK: ("x", "y", "button", "count"),
    ACTION_FIND_CLICK: ("image", "region", "button", "click_all"),
    ACTION_DRAG: ("x", "y", "to_x", "to_y", "button"),
    ACTION_KEY: ("key", "hold_ms"),
    ACTION_SCROLL: ("notches",),
    ACTION_WAIT: ("wait_ms",),
    # `wait_ms` here is how long to keep looking, not a delay: 0 means one look, and the
    # rest of the sequence is skipped this pass if the wave hasn't arrived.
    ACTION_WAVE: ("wave", "max_wave", "region", "wait_ms"),
}

BUTTON_OPTIONS = ["left", "right", "middle"]
BUTTON_DEFAULT = "left"

# Ceiling for a wave number. No stage in this game runs to three figures, and the bound is
# what lets a bare OCR read be trusted: "125" from a counter on a 25-wave map is a misread
# of "12", not wave 125.
WAVE_MAX = 99


@dataclass
class StepAction:
    """One input primitive inside a Sequence step.

    Coordinates are Roblox client-space, same as placement coordinates, so they
    carry the same dependency on the 1152x756 viewport and the macro's camera
    angle. Unused fields for a given type are simply ignored.
    """

    type: str = ACTION_CLICK
    x: int = 0
    y: int = 0
    to_x: int = 0
    to_y: int = 0
    button: str = BUTTON_DEFAULT
    count: int = 1
    key: str = ""
    hold_ms: int = 0
    notches: int = 0
    wait_ms: int = 0
    # Find + Click only. `image` is a path under `images/`, validated by `safe_rel_path`
    # like a route step's template. The region is client-space; width or height of 0 means
    # the whole client, same convention as `NavStep`. No per-action confidence: tolerance
    # is per *template* in this project (Settings > Vision), so a threshold here would be
    # a second answer to the same question.
    image: str = ""
    region_x: int = 0
    region_y: int = 0
    region_w: int = 0
    region_h: int = 0
    click_all: bool = False
    # Wait for Wave only. `wave` is the wave the gate opens on, `max_wave` the map's total.
    wave: int = 0
    max_wave: int = 0

    def uses(self, field_name: str) -> bool:
        if field_name == "region":
            return "region" in ACTION_FIELDS.get(self.type, ())
        return field_name in ACTION_FIELDS.get(self.type, ())

    def region(self) -> tuple[int, int, int, int] | None:
        """Client-space (x, y, w, h), or None for the whole client area.

        A template taller than its region can never match, so an unset region is the safe
        default rather than a zero-sized one — same rule as `NavStep.region`.
        """
        if self.region_w <= 0 or self.region_h <= 0:
            return None
        return (self.region_x, self.region_y, self.region_w, self.region_h)

    def summary(self) -> str:
        """One-line description for the editor list."""
        label = ACTION_LABELS.get(self.type, self.type)
        if self.type == ACTION_MOVE:
            return f"{label}  {self.x}, {self.y}"
        if self.type == ACTION_CLICK:
            times = f" x{self.count}" if self.count > 1 else ""
            return f"{label}  {self.x}, {self.y}  {self.button}{times}"
        if self.type == ACTION_DRAG:
            return f"{label}  {self.x}, {self.y} -> {self.to_x}, {self.to_y}  {self.button}"
        if self.type == ACTION_KEY:
            hold = f"  hold {self.hold_ms}ms" if self.hold_ms else ""
            return f"{label}  '{self.key or '?'}'{hold}"
        if self.type == ACTION_SCROLL:
            way = "down" if self.notches >= 0 else "up"
            return f"{label}  {abs(self.notches)} {way}"
        if self.type == ACTION_WAIT:
            return f"{label}  {self.wait_ms} ms"
        if self.type == ACTION_FIND_CLICK:
            every = "  all" if self.click_all else ""
            return f"{label}  {os.path.basename(self.image) or '?'}  {self.button}{every}"
        if self.type == ACTION_WAVE:
            of = f" of {self.max_wave}" if self.max_wave else ""
            budget = f"  up to {self.wait_ms} ms" if self.wait_ms else "  one look"
            return f"{label}  {self.wave or '?'}{of}{budget}"
        return label

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"Type": self.type}
        mapping = {
            "x": "X",
            "y": "Y",
            "to_x": "ToX",
            "to_y": "ToY",
            "button": "Button",
            "count": "Count",
            "key": "Key",
            "hold_ms": "HoldMs",
            "notches": "Notches",
            "wait_ms": "Ms",
            "image": "Image",
            "wave": "Wave",
            "max_wave": "MaxWave",
        }
        # Only the fields this type uses get written, so a Wait doesn't carry
        # meaningless coordinates around.
        for attr, key in mapping.items():
            if self.uses(attr):
                payload[key] = getattr(self, attr)
        if self.uses("click_all"):
            payload["ClickAll"] = 1 if self.click_all else 0
        if self.uses("region") and self.region() is not None:
            payload["Region"] = [self.region_x, self.region_y, self.region_w, self.region_h]
        return payload

    @classmethod
    def from_payload(cls, payload: dict) -> "StepAction":
        def number(key: str, default: int = 0) -> int:
            try:
                return int(payload.get(key, default))
            except (TypeError, ValueError):
                return default

        raw_type = str(payload.get("Type", "")).strip().lower()
        action_type = raw_type if raw_type in ACTION_TYPES else ACTION_CLICK
        button = str(payload.get("Button", BUTTON_DEFAULT)).strip().lower()

        region = payload.get("Region")
        rx = ry = rw = rh = 0
        if isinstance(region, (list, tuple)) and len(region) == 4:
            try:
                rx, ry, rw, rh = (int(value) for value in region)
            except (TypeError, ValueError):
                rx = ry = rw = rh = 0

        def flag(key: str) -> bool:
            value = payload.get(key, 0)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        return cls(
            type=action_type,
            x=number("X"),
            y=number("Y"),
            to_x=number("ToX"),
            to_y=number("ToY"),
            button=button if button in BUTTON_OPTIONS else BUTTON_DEFAULT,
            count=max(1, number("Count", 1)),
            key=str(payload.get("Key", "")).strip().lower()[:1],
            hold_ms=max(0, number("HoldMs")),
            notches=number("Notches"),
            wait_ms=max(0, number("Ms")),
            # Same validator the route steps use: this becomes a path on disk.
            image=safe_rel_path(payload.get("Image", "")),
            region_x=max(0, rx),
            region_y=max(0, ry),
            region_w=max(0, rw),
            region_h=max(0, rh),
            click_all=flag("ClickAll"),
            wave=max(0, min(number("Wave"), WAVE_MAX)),
            max_wave=max(0, min(number("MaxWave"), WAVE_MAX)),
        )


@dataclass
class UnitStep:
    """One step: a unit placement, or a sequence of raw inputs.

    Empty strings mean "leave unset". `kind` decides which half of the fields
    matter — the unit fields, or `actions`.
    """

    step: int
    kind: str = KIND_UNIT
    enabled: bool = False
    unit_name: str = ""
    slot: str = ""
    # Upgrade level, "0" meaning placed and left alone. Stored as text like the
    # rest; saved configs that predate this default to 0 on read.
    upgrades: str = UPGRADE_DEFAULT
    x: str = ""
    y: str = ""
    priority: str = ""
    wait: str = ""
    # Delay between the rest of the step finishing and the sell, in ms. Only
    # meaningful with `sell` on: it's how long the unit is left to earn before it
    # gets sold. Blank means sell immediately.
    sell_wait: str = ""
    # Presses of the game's auto-upgrade key: 0 = don't touch it, 1..6 = that auto
    # level, 7 = cycle back to off. While auto is left on (1..6) the `upgrades`
    # level above is not pressed — the game is doing the upgrading.
    autoupgrade: int = AUTOUPGRADE_OFF
    # sell removes the unit instead of keeping it; preplacement runs the step
    # during the placement phase, before the wave starts, instead of mid-wave.
    sell: bool = False
    preplacement: bool = False
    # Third phase, and the only *repeating* one: the step runs over and over while the
    # macro waits for the match result, every `wait` milliseconds. That is what makes an
    # ability usable — the placement pass all happens in the first seconds of a wave, and
    # the run loop is strictly sequential, so nothing else can act during a match.
    #
    # `wait` is the interval here rather than a delay before acting. For a repeating step
    # "wait 2s then act, again" and "act every 2s" are the same number, and a second field
    # for it would only be a second way to be wrong. A step with no interval runs once per
    # poll, which is every `OUTCOME_POLL` (0.2s) — usually not what anyone wants, so the
    # editor defaults it.
    during_match: bool = False
    # Sequence steps only.
    actions: list[StepAction] = field(default_factory=list)

    def is_sequence(self) -> bool:
        return self.kind == KIND_SEQUENCE

    # Everything a copy carries. `x`/`y` are deliberately absent: the placement point is
    # the one thing that is never right on another step, so copying it would silently
    # stack two units on the same tile. `step` is absent for the same reason — a step's
    # number is its identity, not its data.
    COPYABLE = (
        "kind",
        "unit_name",
        "slot",
        "upgrades",
        "priority",
        "wait",
        "sell_wait",
        "sell",
        "autoupgrade",
        "preplacement",
        "during_match",
    )

    def copy_settings(self) -> dict[str, object]:
        """This step's settings, minus its coordinate, for pasting onto another step."""
        import copy as _copy

        data: dict[str, object] = {name: getattr(self, name) for name in self.COPYABLE}
        # A sequence's actions *are* its settings, so they come along — deep-copied, or
        # the two steps would share one list and edits to either would hit both.
        data["actions"] = _copy.deepcopy(self.actions)
        return data

    def apply_settings(self, data: dict[str, object]) -> None:
        """Overwrite this step's settings from `copy_settings`, keeping its coordinate."""
        import copy as _copy

        for name in self.COPYABLE:
            if name in data:
                setattr(self, name, data[name])
        self.actions = _copy.deepcopy(data.get("actions") or [])

    def is_actionable(self) -> bool:
        # No manual enable flag: a step is "on" once it has something to do. For
        # a unit that means coordinates, for a sequence at least one action.
        if self.is_sequence():
            return bool(self.actions)
        return bool(self.x) and bool(self.y)

    def as_payload(self) -> dict[str, object]:
        if self.is_sequence():
            # Unit fields are deliberately not written for a sequence — they
            # aren't editable in this mode, so persisting them would save stale
            # values a user can't see.
            return {
                "Step": int(self.step),
                "Kind": KIND_SEQUENCE,
                "Enable": 1 if self.is_actionable() else 0,
                "Unit Name": self.unit_name,
                "Wait": self.wait,
                "DuringMatch": 1 if self.during_match else 0,
                "Actions": [action.as_payload() for action in self.actions],
            }
        return {
            "Step": int(self.step),
            "Kind": KIND_UNIT,
            "Enable": 1 if self.is_actionable() else 0,
            "Unit Name": self.unit_name,
            "Slot": self.slot,
            "Upgrades": self.upgrades,
            "X": self.x,
            "Y": self.y,
            "Priority": self.priority,
            "Wait": self.wait,
            "SellWait": self.sell_wait,
            "Sell": 1 if self.sell else 0,
            # Same key as the old 0/1 flag, widened to a press count. A config
            # written by an older build reads back as 1 = one press = auto level 1.
            "AutoUpgrade": autoupgrade_presses(self.autoupgrade),
            "PrePlacement": 1 if self.preplacement else 0,
            "DuringMatch": 1 if self.during_match else 0,
        }

    @classmethod
    def from_payload(cls, payload: dict, fallback_step: int) -> "UnitStep":
        def text(key: str) -> str:
            value = payload.get(key, "")
            if value is None:
                return ""
            return str(value).strip()

        try:
            step_number = int(payload.get("Step", fallback_step))
        except (TypeError, ValueError):
            step_number = fallback_step

        def flag(key: str) -> bool:
            """Read a 0/1 (or "true"/"yes") flag, defaulting to off so configs
            saved before these fields existed still load."""
            value = payload.get(key, 0)
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        enabled = flag("Enable")

        # No "Kind" means a config written before sequences existed, which was
        # always a unit step.
        raw_kind = str(payload.get("Kind", KIND_UNIT)).strip().lower()
        kind = raw_kind if raw_kind in KINDS else KIND_UNIT

        raw_actions = payload.get("Actions", [])
        actions = (
            [StepAction.from_payload(item) for item in raw_actions if isinstance(item, dict)]
            if isinstance(raw_actions, list)
            else []
        )

        return cls(
            step=step_number,
            kind=kind,
            enabled=enabled,
            actions=actions,
            unit_name=text("Unit Name"),
            slot=text("Slot"),
            # Older configs wrote "" (or omitted it) when no upgrade was chosen;
            # that means "no upgrades", which is level 0.
            upgrades=text("Upgrades") or UPGRADE_DEFAULT,
            x=text("X"),
            y=text("Y"),
            priority=text("Priority"),
            wait=text("Wait"),
            # Missing in configs written before the sell delay existed, which
            # means "sell straight away".
            sell_wait=text("SellWait"),
            # A "Mouse" key in older configs is simply ignored now.
            sell=flag("Sell"),
            autoupgrade=autoupgrade_presses(payload.get("AutoUpgrade", AUTOUPGRADE_OFF)),
            preplacement=flag("PrePlacement"),
            during_match=flag("DuringMatch"),
        )


@dataclass
class UnitPlan:
    """All 72 steps for one farm target."""

    steps: list[UnitStep] = field(default_factory=list)

    @classmethod
    def empty(cls) -> "UnitPlan":
        return cls(steps=[UnitStep(step=number) for number in range(1, TOTAL_STEPS + 1)])

    def step(self, step_number: int) -> UnitStep:
        return self.steps[step_number - 1]

    def steps_for_index(self, index_number: int) -> list[UnitStep]:
        start = (index_number - 1) * STEPS_PER_INDEX
        return self.steps[start : start + STEPS_PER_INDEX]

    def enabled_steps(self) -> list[UnitStep]:
        return [step for step in self.steps if step.is_actionable()]

    def chain_steps(self) -> list[UnitStep]:
        """The steps that run once, in order, as their own entries in the run chain."""
        return [step for step in self.enabled_steps() if not step.during_match]

    def match_steps(self) -> list[UnitStep]:
        """The steps that repeat while the macro waits for the result, in step order.

        Kept out of the chain: a chain entry runs once and holds the run loop until it
        returns, so a repeating step there would stop anything else happening — including
        looking for the win screen.
        """
        return [step for step in self.enabled_steps() if step.during_match]

    def reset_step(self, step_number: int) -> UnitStep:
        """Blank one step in place and return the fresh object. Used by the detail
        card's Reset, so a single chip can be cleared without wiping the config."""
        blank = UnitStep(step=step_number)
        self.steps[step_number - 1] = blank
        return blank

    def reset_index(self, index_number: int) -> None:
        for step in self.steps_for_index(index_number):
            blank = UnitStep(step=step.step)
            self.steps[step.step - 1] = blank

    def reset_all(self) -> None:
        self.steps = UnitPlan.empty().steps
