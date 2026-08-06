"""Generic macro state machine.

The runner knows nothing about Anime Expedition. It advances a list of steps
that callers supply, which is what the old hardcoded lobby sequence lacked.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Phase(str, Enum):
    IDLE = "idle"
    NAVIGATING = "navigating"
    PLACING = "placing"
    CHALLENGE = "challenge"
    FINISHED = "finished"


class StepResult(str, Enum):
    DONE = "done"
    RETRY = "retry"
    FAILED = "failed"


@dataclass
class MacroTarget:
    gamemode: str = ""
    map_name: str = ""
    target: str = ""

    def is_ready(self) -> bool:
        # Target is optional: some gamemodes have no third dimension. Whether a
        # selection is complete is schema knowledge, which lives in content/, not
        # in this deliberately game-agnostic runner.
        return bool(self.gamemode and self.map_name)

    def label(self) -> str:
        parts = [part for part in (self.gamemode, self.map_name, self.target) if part]
        return " / ".join(parts)


@dataclass
class MacroStep:
    """One unit of work.

    action returns a StepResult. RETRY is re-attempted until timeout_seconds
    elapses, then the step is treated as FAILED unless optional is set.
    """

    name: str
    action: Callable[[], StepResult]
    timeout_seconds: float = 5.0
    optional: bool = False

    _started_at: float | None = field(default=None, init=False, repr=False)

    def begin(self) -> None:
        self._started_at = time.monotonic()

    def reset(self) -> None:
        """Forget this attempt's clock, so the step can run again in a later cycle."""
        self._started_at = None

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def timed_out(self) -> bool:
        return self.elapsed() >= max(0.1, float(self.timeout_seconds))


class MacroRunner:
    def __init__(self, log: Callable[[str], None] | None = None) -> None:
        self._log = log or (lambda _message: None)
        self._running = False
        self._phase = Phase.IDLE
        self._steps: list[MacroStep] = []
        self._position = 0
        self._cycle = 0
        self._target = MacroTarget()
        self._stop_requested = False
        self._loop_from: int | None = None

    # # State
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def target(self) -> MacroTarget:
        return self._target

    @property
    def cycle(self) -> int:
        return self._cycle

    @property
    def stop_requested(self) -> bool:
        """Set from another thread. Read by the driver between steps **and inside the
        steps themselves**, which is what makes F1 feel immediate.

        Stopping is still cooperative, not a kill: the parts of a step that get abandoned
        are its *waits* (`find_until`'s poll, `wait_for_match_ready`'s 60s, the placer's
        900s `wait_for_outcome`, the lobby-rejoin poll), all of which hold no input. An
        AutoHotkey script in flight is always allowed to finish, because killing one
        mid-press never sends the matching release and leaves the game with a stuck key or
        mouse button. So the worst case is one short AHK script, not one whole step —
        before this, stopping during a match meant waiting out the match.
        """
        return self._stop_requested

    def request_stop(self) -> None:
        self._stop_requested = True

    def start(
        self,
        target: MacroTarget,
        steps: list[MacroStep],
        loop_from: int | None = None,
    ) -> bool:
        """Begin a run. With `loop_from` set, finishing the list jumps back to that
        index instead of ending — that's the match cycle: the lobby steps before it
        run once, the steps from there on repeat per match."""
        if self._running:
            return False

        self._stop_requested = False
        self._running = True
        self._target = target
        self._steps = list(steps)
        self._position = 0
        self._cycle = 0
        self._loop_from = loop_from if loop_from is None else max(0, int(loop_from))
        self._phase = Phase.NAVIGATING if steps else Phase.FINISHED
        return True

    def stop(self) -> bool:
        if not self._running:
            return False
        self._running = False
        self._phase = Phase.IDLE
        self._steps = []
        self._position = 0
        return True

    def toggle(self, target: MacroTarget, steps: list[MacroStep]) -> bool:
        if self._running:
            self.stop()
        else:
            self.start(target, steps)
        return self._running

    # # Execution
    def tick(self) -> None:
        """Advance at most one step. Call from the UI scheduler."""
        if not self._running or self._phase is Phase.FINISHED:
            return

        if self._position >= len(self._steps):
            if self._loop_from is not None and self._loop_from < len(self._steps):
                self._cycle += 1
                self._position = self._loop_from
                # Step timers are per-attempt, so a looped step has to start clean
                # or it would look like it had already timed out.
                for step in self._steps[self._loop_from :]:
                    step.reset()
                self._log(f"Match cycle {self._cycle} complete — looping.")
                return
            self._phase = Phase.FINISHED
            self._log("Macro sequence complete.")
            return

        step = self._steps[self._position]
        if step.elapsed() == 0.0:
            step.begin()
            self._log(f"Step: {step.name}")

        try:
            result = step.action()
        except Exception as exc:
            self._log(f"Step '{step.name}' raised: {exc}")
            result = StepResult.FAILED

        # A stop that arrived *during* the step is not a step failure. The cancellable
        # waits give up the moment they see it, so they return "not found" — and reporting
        # that as `Step 'Stage loaded' failed. Stopping macro.` would blame the step for
        # doing what it was told. The driver ends the run on the next pass.
        if self._stop_requested:
            return

        if result is StepResult.DONE:
            self._advance()
            return

        if result is StepResult.FAILED:
            self._fail_step(step)
            return

        if step.timed_out():
            self._fail_step(step, timed_out=True)

    def _advance(self) -> None:
        # cycle counts completed loops, not steps: with a match cycle running, "how
        # many matches" is the number anyone wants.
        self._position += 1

    def _fail_step(self, step: MacroStep, timed_out: bool = False) -> None:
        reason = "timed out" if timed_out else "failed"
        if step.optional:
            self._log(f"Step '{step.name}' {reason}. Skipping (optional).")
            self._advance()
            return

        self._log(f"Step '{step.name}' {reason}. Stopping macro.")
        self.stop()
