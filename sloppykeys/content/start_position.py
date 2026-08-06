"""Start position: movement-key holds that walk the character into place.

Some maps drop you somewhere the stored placement coordinates don't line up with —
Raid's Spirit City is the case that forced this: its three acts are separate areas
of one map, so an act can need the character moved before anything is placed.

A plan is an ordered list of "hold this movement key for this long", run once per
run, straight after the camera step (see `MainWindow._build_run_steps`). It is not
a general input sequence: a Sequence step already covers that. Only WASD, because
the point is walking, and anything else belongs in a Sequence step where it can be
seen next to the clicks it goes with.

Presets here are defaults, not settings. `config/start_position.py` stores the
user's per-target overrides and falls back to these.
"""

from __future__ import annotations

from dataclasses import dataclass

# The only keys a plan may hold. A whitelist, not an escape: these are interpolated
# into a generated AutoHotkey script.
MOVE_KEYS = ("w", "a", "s", "d")
MOVE_LABELS = {"w": "W  (forward)", "a": "A  (left)", "s": "S  (back)", "d": "D  (right)"}

DEFAULT_HOLD_MS = 1000
MIN_HOLD_MS = 0
# A single hold longer than this is almost certainly a typo (30s of walking), and it
# also bounds how long one AHK script can sit there holding a key down.
MAX_HOLD_MS = 30000


@dataclass
class PositionMove:
    """One "hold `key` for `hold_ms`" instruction."""

    key: str = "w"
    hold_ms: int = DEFAULT_HOLD_MS

    def is_actionable(self) -> bool:
        return self.key in MOVE_KEYS and self.hold_ms > 0

    def summary(self) -> str:
        return f"Hold {self.key.upper()} for {self.hold_ms}ms"

    def as_payload(self) -> dict[str, object]:
        return {"key": self.key, "hold_ms": int(self.hold_ms)}

    @classmethod
    def from_payload(cls, raw: object) -> "PositionMove | None":
        """Build from stored JSON, or None if it isn't a usable move.

        Rejecting rather than repairing: this value ends up in an AHK `Send()`, and
        a settings file can be hand-edited.
        """
        if not isinstance(raw, dict):
            return None
        key = str(raw.get("key", "")).strip().lower()
        if key not in MOVE_KEYS:
            return None
        try:
            hold = int(raw.get("hold_ms", DEFAULT_HOLD_MS))
        except (TypeError, ValueError):
            return None
        return cls(key=key, hold_ms=clamp_hold(hold))


def clamp_hold(value: object) -> int:
    try:
        hold = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_HOLD_MS
    return max(MIN_HOLD_MS, min(MAX_HOLD_MS, hold))


def target_key(gamemode: str, map_name: str, act: str) -> str:
    """The settings key for one target. Empty when the target is incomplete.

    A JSON object key, never a file path — but the same "/" shape as `configs/` so
    it reads the same in settings.json. A gamemode with no act dimension
    (Expedition) has a two-part key.

    Gamemode and map are both required rather than "any two parts": dropping the
    map would turn (Raid, "", Act 2) into "Raid/Act 2", which reads exactly like a
    complete two-part key for a map called "Act 2".
    """
    mode, stage, target = (part.strip() for part in (gamemode, map_name, act))
    if not mode or not stage:
        return ""
    return "/".join(part for part in (mode, stage, target) if part)


# target key -> the moves that target starts with, before any user edit.
PRESETS: dict[str, list[tuple[str, int]]] = {
    # Act 2's playfield sits away from the spawn: back, right, back again. 1s per
    # hold is the user's measurement — a starting point, not a calibration. Edit it
    # in Settings > Position; that override wins over this table.
    "Raid/Spirit City/Act 2": [("s", 1000), ("d", 1000), ("s", 1000)],
    # Act 3 is straight to the right of the spawn.
    "Raid/Spirit City/Act 3": [("d", 2500)],
    # Villian Invasion drops you short of the placement points: 2s forward. Promoted from
    # the user's `settings.json` override into a preset so a fresh install walks correctly
    # without anyone re-measuring it. An Events preset is only stable while the event is in
    # rotation — when it rotates out, this key stops matching anything and costs nothing.
    "Events/Villian Invasion/Act 1": [("w", 2000)],
}


def preset_moves(gamemode: str, map_name: str, act: str) -> list[PositionMove]:
    """A fresh copy of the preset for this target — empty for most targets."""
    key = target_key(gamemode, map_name, act)
    return [PositionMove(key=move_key, hold_ms=hold) for move_key, hold in PRESETS.get(key, ())]


def total_hold_ms(moves: list[PositionMove]) -> int:
    return sum(max(0, move.hold_ms) for move in moves)
