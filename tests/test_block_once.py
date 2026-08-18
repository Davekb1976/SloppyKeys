"""Runnable check for blocks that run only once inside a looping phase.

No framework: `.venv\\Scripts\\python.exe tests\\test_block_once.py`.

The Macro Manager draws two promises the run loop has to keep: the 1x toggle on any block,
and the unconditional RUNS ONCE badge on walk_path. Breaking them is silent and expensive —
a re-placed unit on a gamemode that allows one placement, or a recorded route re-walked from
somewhere it was never recorded. The second failure here is subtler: a loop whose every block
has spent its run must count as no loop at all, or the tick spins without ever parking and the
keep-alive click that stops Roblox idle-kicking the session never happens.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.macro.controller import MacroController  # noqa: E402


def _controller(ran: list) -> MacroController:
    ctrl = MacroController.__new__(MacroController)
    # Every block completes on its first tick, which is the one-shot contract.
    ctrl._execute_battle_block = lambda block: (ran.append(block["type"]) or True)
    return ctrl


def test_which_blocks_run_once() -> None:
    assert MacroController._runs_once({"type": "click", "once": True}) is True
    assert MacroController._runs_once({"type": "walk_path"}) is True
    assert MacroController._runs_once({"type": "click"}) is False
    assert MacroController._runs_once({"type": "click", "once": False}) is False


def test_loop_skips_a_spent_block() -> None:
    ran: list[str] = []
    ctrl = _controller(ran)
    blocks = [{"type": "place_unit", "once": True}, {"type": "send_key"}]
    spent: set[int] = set()
    idx = 0
    for _ in range(6):
        idx = ctrl._advance_loop(blocks, idx, spent)
    # The once block ran on the first pass and was stepped over on every wrap after it.
    assert ran.count("place_unit") == 1, ran
    assert ran.count("send_key") == 3, ran
    # Something is still pending, so the loop is live and must not park.
    assert ctrl._loop_pending(blocks, spent) is True


def test_unfinished_block_keeps_its_slot() -> None:
    ran: list[str] = []
    ctrl = _controller(ran)
    ctrl._execute_battle_block = lambda block: False  # multi-tick block, never done
    blocks = [{"type": "upgrade_unit", "once": True}, {"type": "send_key"}]
    assert ctrl._advance_loop(blocks, 0, set()) == 0
    # Not marked spent either: it never finished, so its one run has not happened.
    spent: set[int] = set()
    ctrl._advance_loop(blocks, 0, spent)
    assert spent == set()


def test_all_spent_loop_reads_as_empty() -> None:
    ran: list[str] = []
    ctrl = _controller(ran)
    blocks = [{"type": "walk_path"}, {"type": "place_unit", "once": True}]
    spent: set[int] = set()
    idx = 0
    for _ in range(len(blocks)):
        idx = ctrl._advance_loop(blocks, idx, spent)
    assert ran == ["walk_path", "place_unit"], ran
    # Nothing left to run, so the match loop is free to park and keep the session alive.
    assert ctrl._loop_pending(blocks, spent) is False
    # An empty phase has never been a loop.
    assert ctrl._loop_pending([], spent) is False


def main() -> None:
    test_which_blocks_run_once()
    test_loop_skips_a_spent_block()
    test_unfinished_block_keeps_its_slot()
    test_all_spent_loop_reads_as_empty()
    print("OK: run-once blocks inside loop phases")


if __name__ == "__main__":
    main()
