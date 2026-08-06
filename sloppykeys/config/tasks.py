"""The task queue: up to three slots the macro works through, stored in settings.json.

Layout, alongside the other settings without disturbing them (same approach as
`DelaysStore` and `StartPositionStore`):

    "tasks": [
        {"Kind": "target", "Gamemode": "Story", "Map": "King's Tomb",
         "Act": "Act 3", "Limit": 5},
        {"Kind": "target", "Gamemode": "Raid", "Map": "Spirit City",
         "Act": "Act 2", "Limit": 3},
        {"Kind": "off"}
    ]

Model and store live together because there is no content table behind this — the
slots are entirely user data (compare `delays.py`, which also holds its spec next to
its store).

Rules the queue encodes, from the user's design:

- **Three slots, all targets.** Challenges are *not* a slot — they are a toggle,
  `AppSettings.run_challenges`, read into `TaskDirector.challenges`. A challenge slot
  never had a position in the order anyway: `decide()` returns a challenge whenever one
  is runnable, wherever the slot sat, so the slot spent one of three places to store a
  boolean. Now all three can be targets.
- **Challenges preempt** when the toggle is on: they run first and the targets fill the
  gap once the offered challenges are cleared, lost or exhausted.
- **A target slot's limit** is how many matches to run before moving to the next slot,
  and only matters when two targets compete. One target plus challenges never needs it.
- The queue **loops** after the last slot, and a challenge interruption does not reset a
  target's progress toward its limit.

A queue saved under the old shape is migrated once, by
`TaskStore.take_legacy_challenge_slot`, so nobody's challenges silently stop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sloppykeys.content.gamemodes import CHALLENGE, has_targets, selection_complete

from .store import read_json, update_json

SETTINGS_FILE = "settings.json"
TASKS_KEY = "tasks"

MAX_SLOTS = 3

KIND_OFF = "off"
KIND_TARGET = "target"
KINDS = (KIND_OFF, KIND_TARGET)
KIND_LABELS = {
    KIND_OFF: "Empty",
    KIND_TARGET: "Target",
}

# Only for reading a queue saved before challenges became a toggle. Not a selectable kind:
# `from_payload` turns it into an empty slot and `take_legacy_challenge_slot` flips the
# setting on, so the intent survives the shape change.
LEGACY_KIND_CHALLENGE = "challenge"

LIMIT_MIN = 1
LIMIT_MAX = 999
LIMIT_DEFAULT = 5


def clamp_limit(value: object) -> int:
    try:
        limit = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return LIMIT_DEFAULT
    return max(LIMIT_MIN, min(LIMIT_MAX, limit))


@dataclass
class TaskSlot:
    """One row of the queue. `kind` decides which fields matter."""

    kind: str = KIND_OFF
    gamemode: str = ""
    map_name: str = ""
    act: str = ""
    limit: int = LIMIT_DEFAULT

    def is_runnable(self) -> bool:
        """Does this slot have enough to be worked on?

        A target needs a complete selection, which for a gamemode with no act dimension
        is complete at the map.
        """
        if self.kind != KIND_TARGET:
            return False
        return selection_complete(self.gamemode, self.map_name, self.act)

    def uses_limit(self) -> bool:
        return self.kind == KIND_TARGET

    def summary(self) -> str:
        if self.kind != KIND_TARGET:
            return "Empty"
        where = " / ".join(part for part in (self.gamemode, self.map_name, self.act) if part)
        if not where:
            return "Target \u00b7 nothing chosen yet"
        return f"{where} \u00b7 {self.limit} run{'s' if self.limit != 1 else ''}"

    def as_payload(self) -> dict[str, object]:
        if self.kind != KIND_TARGET:
            return {"Kind": KIND_OFF}
        payload: dict[str, object] = {
            "Kind": KIND_TARGET,
            "Gamemode": self.gamemode,
            "Map": self.map_name,
            "Limit": int(self.limit),
        }
        # An act is only written for a gamemode that has the dimension, so a slot
        # can't carry a stale act from a previous gamemode choice.
        if has_targets(self.gamemode):
            payload["Act"] = self.act
        return payload

    @classmethod
    def from_payload(cls, raw: object) -> "TaskSlot":
        """Build from stored JSON. Anything unreadable becomes an empty slot rather
        than a guess: this decides what the macro plays."""
        if not isinstance(raw, dict):
            return cls()
        kind = str(raw.get("Kind", KIND_OFF)).strip().lower()
        if kind not in KINDS:
            return cls()
        if kind != KIND_TARGET:
            return cls(kind=kind)
        return cls(
            kind=KIND_TARGET,
            gamemode=str(raw.get("Gamemode", "")).strip(),
            map_name=str(raw.get("Map", "")).strip(),
            act=str(raw.get("Act", "")).strip(),
            limit=clamp_limit(raw.get("Limit", LIMIT_DEFAULT)),
        )


def normalize(slots: list[TaskSlot]) -> list[TaskSlot]:
    """Exactly `MAX_SLOTS` slots. No duplicate rule any more: three targets is legitimate,
    and the only kind that could not be duplicated was the challenge slot, which is gone."""
    fixed = list(slots[:MAX_SLOTS])
    while len(fixed) < MAX_SLOTS:
        fixed.append(TaskSlot())
    return fixed


class TaskStore:
    def __init__(self, app_root: str) -> None:
        self._path = os.path.join(app_root, SETTINGS_FILE)

    def slots(self) -> list[TaskSlot]:
        raw = read_json(self._path).get(TASKS_KEY, [])
        stored = raw if isinstance(raw, list) else []
        return normalize([TaskSlot.from_payload(item) for item in stored])

    def save(self, slots: list[TaskSlot]) -> bool:
        # `update_json`, not read-then-write: `StatsTracker` persists to this same file
        # from the macro worker on every match result, and its read-modify-write was
        # putting the old queue back after an edit made during a run.
        entries = [slot.as_payload() for slot in normalize(slots)]

        def mutate(payload: dict) -> None:
            payload[TASKS_KEY] = entries

        return update_json(self._path, mutate)

    def take_legacy_challenge_slot(self) -> bool:
        """Was a challenge *slot* stored? Drop it, and say so.

        One-time migration for a queue saved before challenges became a toggle. True tells
        `MainWindow` to switch `run_challenges` on, so an existing setup keeps running
        challenges instead of silently stopping — the queue is user data and must not lose
        meaning across a shape change. Idempotent: the rewrite removes the entry, so a
        second call finds nothing.
        """
        raw = read_json(self._path).get(TASKS_KEY, [])
        if not isinstance(raw, list):
            return False
        found = any(
            isinstance(item, dict)
            and str(item.get("Kind", "")).strip().lower() == LEGACY_KIND_CHALLENGE
            for item in raw
        )
        if not found:
            return False
        # `slots()` has already turned the legacy entry into an empty slot.
        self.save(self.slots())
        return True


def challenge_maps() -> list[str]:
    """The maps a challenge can land on, i.e. which `configs/Challenge/<Map>.json`
    plans need to exist before the task can run unattended."""
    from sloppykeys.content.gamemodes import maps_for

    return maps_for(CHALLENGE)
