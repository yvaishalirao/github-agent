"""Destructive action intercept, confirmation TTL."""

import time
from uuid import uuid4

_DESCRIPTIONS = {
    "delete_repo": "Delete repository {repo}. This cannot be undone.",
    "hard_reset": "Hard reset {repo}. Commits not present on another branch will be lost.",
    "force_push": "Force push to {branch} on {repo}. This may overwrite remote history.",
    "delete_file": "Delete file {path} from {repo}.",
}


class SafetyLayer:
    CONFIRMATION_TTL = 60  # seconds

    def __init__(self):
        self._pending: dict = {}  # session_id -> pending confirmation

    def _describe(self, step: dict) -> str:
        action = step.get("action", "")
        params = step.get("params", {}) or {}
        repo = params.get("repo", "this repository")

        template = _DESCRIPTIONS.get(action)
        if template is None:
            return f"Perform '{action}' on {repo}. This action may be irreversible."

        return template.format(
            repo=repo,
            branch=params.get("branch", "the target branch"),
            path=params.get("path", "the specified file"),
        )

    def issue_token(self, session_id: str, step: dict, plan_id: str) -> str:
        token = str(uuid4())
        self._pending[session_id] = {
            "token": token,
            "step_id": step["action"] + "_" + plan_id,
            "plan_id": plan_id,
            "expires_at": time.time() + self.CONFIRMATION_TTL,
            "step": step,
            "summary": self._describe(step),
        }
        return token

    def get_pending(self, session_id: str):
        return self._pending.get(session_id)

    def consume_token(self, session_id: str) -> dict:
        pending = self._pending[session_id]  # raises KeyError if absent
        del self._pending[session_id]  # delete BEFORE returning — prevents double-use
        return pending

    def is_expired(self, session_id: str) -> bool:
        pending = self._pending.get(session_id)
        if pending is None:
            return True
        return time.time() > pending["expires_at"]

    def check_and_consume(self, session_id: str, step_id: str, plan_id: str):
        pending = self._pending.get(session_id)

        if pending is None:
            return False, "no pending confirmation for this session"

        if pending["step_id"] != step_id:
            return False, "step_id does not match pending confirmation"

        if pending["plan_id"] != plan_id:
            return False, "plan_id does not match pending confirmation"

        if time.time() > pending["expires_at"]:
            return False, "confirmation token has expired"

        self.consume_token(session_id)
        return True, None

    def inspect_plan(self, plan: dict, session_id: str) -> dict:
        """Scans plan for destructive steps. Returns result with confirmation_required flag."""
        destructive_steps = [s for s in plan["steps"] if s.get("destructive") is True]
        if not destructive_steps:
            return {"confirmation_required": False, "destructive_steps": []}

        # Issue a token for the FIRST destructive step only.
        first = destructive_steps[0]
        token = self.issue_token(session_id, first, plan["plan_id"])
        return {
            "confirmation_required": True,
            "destructive_steps": [s["action"] for s in destructive_steps],
            "confirmation_summary": self._describe(first),
            "token": token,
            "plan_id": plan["plan_id"],
        }

    def assert_repo_is_user_stated(self, step: dict, user_stated_repos: set) -> None:
        if step.get("destructive"):
            repo = step["params"].get("repo")
            assert repo is not None, \
                "SAFETY INVARIANT VIOLATED: destructive step has no explicit repo (INV-08)"
            assert repo in user_stated_repos, \
                f"SAFETY INVARIANT VIOLATED: repo '{repo}' was inferred, not stated by user (INV-08)"
