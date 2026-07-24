"""Automated regression guards for INV-13 (plan staleness) and INV-06
(no auto-retry on destructive steps) in executor.py.
"""

import time

from executor import ExecutionEngine


def test_stale_plan_not_executed():
    e = ExecutionEngine()

    dispatched = []
    e.dispatch_step = lambda step, session_id: dispatched.append(step) or {
        "success": True, "verified": True, "output": "should not run",
    }

    plan = {
        "plan_id": "p1",
        "observed_at": time.time() - 130,
        "steps": [
            {"action": "commit_changes", "description": "a", "tool": "git_tool", "params": {}, "destructive": False},
        ],
    }

    result = e.execute_plan(plan, True, "sess")

    assert result["status"] == "stale"
    assert dispatched == []


def test_destructive_step_never_retried():
    e = ExecutionEngine()

    call_count = {"n": 0}

    def failing_dispatch(step, session_id):
        call_count["n"] += 1
        return {"success": False, "verified": False, "error": "ConnectionError: reset by peer"}

    e._dispatch_once = failing_dispatch

    destructive_step = {
        "action": "delete_repo", "description": "d", "tool": "github_tool",
        "params": {"repo": "x"}, "destructive": True,
    }
    e.dispatch_step(destructive_step, "sess")
    assert call_count["n"] == 1, "destructive step must be attempted exactly once — never retried"

    call_count["n"] = 0
    non_destructive_step = {
        "action": "commit_changes", "description": "c", "tool": "git_tool",
        "params": {}, "destructive": False,
    }
    e.dispatch_step(non_destructive_step, "sess")
    assert call_count["n"] == 2, "non-destructive step on a transient error must be retried once"
