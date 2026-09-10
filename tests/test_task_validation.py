"""Runnable checks for pre-flight task queue validation.

No framework, no input fired:
`.venv\\Scripts\\python.exe tests\\test_task_validation.py`
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sloppykeys.content.gamemodes import validate_task, validate_task_queue

app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. Empty queue check
assert validate_task_queue([]) == "task queue is empty"
assert validate_task_queue(None) == "task queue is empty"

# 2. Mode required
assert validate_task({}) == "gamemode is required"
assert validate_task({"mode": ""}) == "gamemode is required"
assert validate_task({"mode": "UnknownMode"}) == "unknown gamemode 'UnknownMode'"

# 3. Story task validation
assert validate_task({"mode": "Story", "map": "", "stage": "", "macro": ""}) == "map is required"
assert validate_task({"mode": "Story", "map": "School Grounds", "stage": "", "macro": ""}) == "act is required"
assert validate_task({"mode": "Story", "map": "School Grounds", "stage": "Act 1", "macro": ""}) == "macro operation is required"

# 4. Portals task validation
assert validate_task({"mode": "Portals", "map": "", "search": "", "macro": ""}) == "portal map is required"
assert validate_task({"mode": "Portals", "map": "Summer", "search": "", "macro": ""}) == "portal name is required"
assert validate_task({"mode": "Portals", "map": "Summer", "search": "tier 1", "macro": ""}) == "macro operation is required"

# 5. Challenge task validation
assert validate_task({"mode": "Challenge", "challenge_slots": [False, False, False]}) == "all challenge slots are disabled"
assert validate_task({"mode": "Challenge", "challenge_slots": [True, False, False]}) is None

# 6. Operation existence check when app_root provided
assert validate_task({"mode": "Story", "map": "School Grounds", "stage": "Act 1", "macro": "non_existent_op_12345"}, app_root=app_root) == "macro operation 'non_existent_op_12345' not found"

# 7. Multi-task queue validation
queue = [
    {"mode": "Challenge", "challenge_slots": [True, True, True]},
    {"mode": "Story", "map": "East Town", "stage": "", "macro": "auto play"},
]
err = validate_task_queue(queue, app_root=app_root)
assert err == "Task 2 (Story): act is required", f"Expected Task 2 error, got: {err}"

print("task validation: OK")
