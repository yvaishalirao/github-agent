"""Regression guards for the highest-consequence invariants in the system:
INV-06 (destructive steps require a valid, unexpired confirmation token),
INV-07 (confirmation tokens are single-use and bound to one step), and
INV-08 (a destructive step's repo must be user-stated, never inferred).

These tests call the real SafetyLayer (and, for test 1, the real ExecutionEngine
wired to a real SafetyLayer) — no mocking of the enforcement code itself.
"""

import time

import pytest

from executor import ExecutionEngine
from safety import SafetyLayer


def test_no_execution_without_token():
    real_safety = SafetyLayer()  # nothing issued — genuinely empty pending store
    e = ExecutionEngine(safety_layer=real_safety)

    dispatched = []
    e.dispatch_step = lambda step, session_id: dispatched.append(step) or {
        "success": True, "verified": True,
    }

    plan = {
        "plan_id": "plan1",
        "observed_at": time.time(),
        "steps": [
            {
                "action": "delete_repo", "description": "delete it", "tool": "github_tool",
                "params": {"repo": "weather-app"}, "destructive": True,
            },
        ],
    }

    result = e.execute_plan(plan, True, "sess1")

    assert result["status"] not in ("complete", "partial")
    assert dispatched == [], "dispatch_step must never run without a valid confirmation token"


def test_token_expires_after_60s():
    s = SafetyLayer()
    step = {"action": "delete_repo", "params": {"repo": "weather-app"}, "destructive": True}
    s.issue_token("sess1", step, "plan1")

    pending = s.get_pending("sess1")
    pending["expires_at"] = time.time() - 1  # force expiry

    ok, reason = s.check_and_consume("sess1", "delete_repo_plan1", "plan1")

    assert ok is False


def test_token_single_use():
    s = SafetyLayer()
    step = {"action": "delete_repo", "params": {"repo": "weather-app"}, "destructive": True}
    s.issue_token("sess1", step, "plan1")

    ok1, _ = s.check_and_consume("sess1", "delete_repo_plan1", "plan1")
    assert ok1 is True

    ok2, reason2 = s.check_and_consume("sess1", "delete_repo_plan1", "plan1")
    assert ok2 is False


def test_token_bound_to_step():
    s = SafetyLayer()
    step = {"action": "delete_repo", "params": {"repo": "weather-app"}, "destructive": True}
    s.issue_token("sess1", step, "plan1")  # step_id becomes "delete_repo_plan1"

    ok, reason = s.check_and_consume("sess1", "hard_reset_plan1", "plan1")

    assert ok is False


def test_destructive_requires_explicit_repo():
    s = SafetyLayer()
    step = {"action": "delete_repo", "params": {}, "destructive": True}

    with pytest.raises(AssertionError):
        s.assert_repo_is_user_stated(step, {"some-repo"})


def test_inferred_repo_blocked():
    s = SafetyLayer()
    step = {"action": "delete_repo", "params": {"repo": "weather-app"}, "destructive": True}

    with pytest.raises(AssertionError, match="inferred"):
        s.assert_repo_is_user_stated(step, {"other-repo"})
