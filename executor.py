"""Execution engine, step dispatch, adapt loop."""

import time

import db

STALENESS_LIMIT_SECONDS = 120

TRANSIENT_ERRORS = ["ConnectionError", "TimeoutError", "HTTPError 5"]


class ExecutionEngine:
    KNOWN_TOOLS = {"git_tool", "github_tool", "intelligence"}

    def __init__(self, safety_layer=None):
        if safety_layer is None:
            from safety import SafetyLayer
            safety_layer = SafetyLayer()
        self.safety = safety_layer

    def execute_plan(self, plan: dict, confirmed: bool, session_id: str) -> dict:
        # INV-12: confirmed must be explicitly True
        assert confirmed is True, \
            "AGENTIC INVARIANT VIOLATED: execute_plan called without confirmation (INV-12)"

        # INV-13: a plan built from stale repo state must not execute. Missing/zero
        # observed_at fails safe — treated as maximally stale, not as "0 seconds old".
        staleness = time.time() - plan.get("observed_at", 0)
        if staleness >= STALENESS_LIMIT_SECONDS:
            return {
                "status": "stale",
                "message": (
                    f"This plan was based on repo state from {staleness:.0f} seconds ago. "
                    "Your repo may have changed. Please re-observe and generate a new plan."
                ),
                "staleness_seconds": staleness,
            }

        results = []
        for i, step in enumerate(plan["steps"]):
            # INV-06: a destructive step must never dispatch without a valid, unexpired,
            # single-use confirmation token for THIS step — checked independently here,
            # not just trusted from the caller's `confirmed` flag. Defence in depth.
            if step.get("destructive"):
                step_id = step["action"] + "_" + plan["plan_id"]
                ok, reason = self.safety.check_and_consume(session_id, step_id, plan["plan_id"])
                if not ok:
                    return {
                        "status": "blocked", "completed": i, "total": len(plan["steps"]),
                        "results": results,
                        "error": reason or "No valid confirmation for this destructive step.",
                    }

            result = self.dispatch_step(step, session_id)
            # INV-14: log BEFORE processing result
            self._log_step(step, result, session_id)
            results.append(result)

            # INV-09: do not proceed if step not verified
            if not result.get("verified"):
                recovery_suggestion = self._suggest_recovery(step, result)
                return {
                    "status": "partial", "completed": i, "total": len(plan["steps"]),
                    "results": results, "recovery": recovery_suggestion,
                }

        return {"status": "complete", "results": results}

    def dispatch_step(self, step: dict, session_id: str) -> dict:
        result = self._dispatch_once(step, session_id)

        # INV-06: destructive steps never auto-retry. Fail-safe: only an EXPLICIT
        # destructive=False is eligible for retry — a missing/uncertain flag is not
        # (unlike `not step.get("destructive")`, which would wrongly treat a missing
        # key the same as destructive=False and auto-retry it).
        if step.get("destructive") is False and self._is_transient_error(result):
            db.log_step(
                session_id=session_id,
                action=step["action"],
                repo=step.get("params", {}).get("repo"),
                status="retry",
                summary=result.get("error", ""),
            )
            result = self._dispatch_once(step, session_id)

        return result

    def _dispatch_once(self, step: dict, session_id: str) -> dict:
        # Stub: return a mock result for now
        return {
            "success": True, "verified": True,
            "output": f"[stub] {step['action']} executed", "step": step["action"],
        }

    def _is_transient_error(self, result: dict) -> bool:
        error_text = str(result.get("error", ""))
        return any(pattern in error_text for pattern in TRANSIENT_ERRORS)

    def _log_step(self, step: dict, result: dict, session_id: str) -> None:
        # INV-14: called BEFORE returning, not conditional on success
        db.log_step(
            session_id=session_id,
            action=step["action"],
            repo=step["params"].get("repo"),
            status="success" if result.get("success") else "failed",
            summary=result.get("output", ""),
        )

    def _suggest_recovery(self, step: dict, result: dict) -> str:
        return f"Step '{step['action']}' failed: {result.get('error', 'unknown error')}. Manual recovery may be required."
