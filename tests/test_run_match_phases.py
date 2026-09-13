"""Runnable check for execution ordering between Battle and Loop phases in _run_match.

No framework: `.venv\\Scripts\\python.exe tests\\test_run_match_phases.py`.

Ensures:
1. When Battle has blocks, all Battle blocks run to completion before Loop A or Loop B execute.
2. Multi-tick Battle blocks do not allow Loop A/B to interleave while waiting/rechecking.
3. When Battle is empty, Loop A/B run immediately from tick 0.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController, OUTCOME_WON  # noqa: E402


class MockPlacer:
    won_poll_click = 5.0
    won_timeout = 900.0

    def park(self) -> None:
        pass

    def park_click(self) -> None:
        pass


class MockStats:
    def record(self, won: bool = True, target: str = "") -> None:
        pass

    def abandon_stage(self) -> None:
        pass


def _setup_controller(execution_log: list[str]) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    ctrl._stop_requested = False
    ctrl._checkpoint = lambda: False
    ctrl._expedition_state = lambda: None
    ctrl._is_eclipse_active = lambda: False
    ctrl._placer = MockPlacer()
    ctrl._stats = MockStats()
    ctrl._current_task = {}
    ctrl._task_label = lambda: "TestTask"
    ctrl._log = lambda msg: None
    ctrl._send_webhook_result = lambda result: None
    return ctrl


def test_battle_completes_before_loops_start() -> None:
    order: list[str] = []
    ctrl = _setup_controller(order)

    # Battle has 2 blocks, Loop A has 1 block
    battle = [{"type": "autoplay"}, {"type": "fishing"}]
    loop_a = [{"type": "click"}]

    ticks = 0

    def mock_execute(block: dict) -> bool:
        order.append(f"battle:{block['type']}")
        return True  # 1-tick completion

    ctrl._execute_battle_block = mock_execute

    def mock_advance_loop(blocks: list, idx: int, spent: set[int]) -> int:
        order.append(f"loop_a:{blocks[idx]['type']}")
        return (idx + 1) % len(blocks)

    ctrl._advance_loop = mock_advance_loop

    # Stop after 5 ticks
    def mock_check_outcome() -> tuple[str, str] | None:
        nonlocal ticks
        ticks += 1
        if ticks >= 5:
            return (OUTCOME_WON, "Victory")
        return None

    ctrl._check_outcome = mock_check_outcome

    ctrl._run_match(battle, loop_a, [])

    # Expected order across 5 ticks:
    # Tick 1: battle:autoplay
    # Tick 2: battle:fishing
    # Tick 3: loop_a:click
    # Tick 4: loop_a:click
    # Tick 5: loop_a:click, then outcome won
    assert order == [
        "battle:autoplay",
        "battle:fishing",
        "loop_a:click",
        "loop_a:click",
        "loop_a:click",
    ], f"Unexpected order: {order}"


def test_multitick_battle_block_does_not_leak_loops() -> None:
    order: list[str] = []
    ctrl = _setup_controller(order)

    battle = [{"type": "autoplay"}, {"type": "fishing"}]
    loop_a = [{"type": "click"}]

    autoplay_ticks = 0

    def mock_execute(block: dict) -> bool:
        nonlocal autoplay_ticks
        btype = block["type"]
        order.append(f"battle:{btype}")
        if btype == "autoplay":
            autoplay_ticks += 1
            return autoplay_ticks >= 3  # takes 3 ticks to finish
        return True

    ctrl._execute_battle_block = mock_execute

    def mock_advance_loop(blocks: list, idx: int, spent: set[int]) -> int:
        order.append(f"loop_a:{blocks[idx]['type']}")
        return (idx + 1) % len(blocks)

    ctrl._advance_loop = mock_advance_loop

    ticks = 0

    def mock_check_outcome() -> tuple[str, str] | None:
        nonlocal ticks
        ticks += 1
        if ticks >= 6:
            return (OUTCOME_WON, "Victory")
        return None

    ctrl._check_outcome = mock_check_outcome

    ctrl._run_match(battle, loop_a, [])

    # Across 6 ticks:
    # Autoplay takes ticks 1, 2, 3.
    # Fishing takes tick 4.
    # Loop A runs on tick 5, tick 6.
    assert order == [
        "battle:autoplay",
        "battle:autoplay",
        "battle:autoplay",
        "battle:fishing",
        "loop_a:click",
        "loop_a:click",
    ], f"Unexpected order during multi-tick: {order}"


def test_empty_battle_runs_loops_immediately() -> None:
    order: list[str] = []
    ctrl = _setup_controller(order)

    battle: list[dict] = []
    loop_a = [{"type": "click"}]

    def mock_advance_loop(blocks: list, idx: int, spent: set[int]) -> int:
        order.append(f"loop_a:{blocks[idx]['type']}")
        return (idx + 1) % len(blocks)

    ctrl._advance_loop = mock_advance_loop

    ticks = 0

    def mock_check_outcome() -> tuple[str, str] | None:
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            return (OUTCOME_WON, "Victory")
        return None

    ctrl._check_outcome = mock_check_outcome

    ctrl._run_match(battle, loop_a, [])

    # Across 3 ticks: loop_a runs ticks 1, 2, 3
    assert order == [
        "loop_a:click",
        "loop_a:click",
        "loop_a:click",
    ], f"Unexpected order with empty battle: {order}"


def main() -> None:
    test_battle_completes_before_loops_start()
    test_multitick_battle_block_does_not_leak_loops()
    test_empty_battle_runs_loops_immediately()
    print("OK: Battle completion before Loop execution")


if __name__ == "__main__":
    main()
