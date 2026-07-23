"""Automated regression guards for INV-01, INV-11, and INV-15 in agent.py."""

import time

import pytest

from agent import AgentBrain, _validate_plan_schema


def _valid_repo_state(extra=None):
    state = {
        "status": "clean",
        "observed_at": time.time(),
        "staged_diff": "",
        "unstaged_diff": "",
        "last_commits": [],
        "file_tree": [],
        "readme_exists": False,
        "gitignore_exists": False,
        "branches": [],
        "current_branch": "main",
    }
    if extra:
        state.update(extra)
    return state


def test_token_not_in_prompt_raises(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "supersecrettoken")
    repo_state = _valid_repo_state({"staged_diff": "diff contains supersecrettoken embedded"})

    with pytest.raises(AssertionError, match="SECURITY INVARIANT VIOLATED"):
        AgentBrain().build_plan("commit this", repo_state, "sess-inv01")


def test_empty_token_skips_assertion(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "")
    monkeypatch.setattr(
        "agent._call_llm_with_retry",
        lambda prompt, retries=2: '{"steps": [], "clarification_needed": "ok"}',
    )
    repo_state = _valid_repo_state()

    # Must not raise on the token check — any other failure here is a different bug.
    result = AgentBrain().build_plan("do something", repo_state, "sess-inv01-empty")
    assert "plan_id" in result


def test_build_plan_requires_repo_state():
    with pytest.raises(AssertionError):
        AgentBrain().build_plan("intent", None, "sess")

    with pytest.raises(AssertionError):
        AgentBrain().build_plan("intent", {}, "sess")


def test_build_plan_requires_status_key():
    with pytest.raises(AssertionError):
        AgentBrain().build_plan("intent", {"other_key": "value"}, "sess")


def test_plan_schema_rejects_missing_destructive():
    plan = {
        "steps": [
            {"action": "commit_changes", "description": "test", "tool": "git_tool", "params": {}}
        ],
        "clarification_needed": None,
    }
    with pytest.raises(ValueError):
        _validate_plan_schema(plan)


def test_plan_schema_rejects_unknown_tool():
    plan = {
        "steps": [
            {
                "action": "commit_changes",
                "description": "test",
                "tool": "unknown_tool",
                "params": {},
                "destructive": False,
            }
        ],
        "clarification_needed": None,
    }
    with pytest.raises(ValueError, match="KNOWN_TOOLS"):
        _validate_plan_schema(plan)
