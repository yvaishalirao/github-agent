"""LLM call, prompt building, plan validation."""

import json
import os
import time

import db

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

_STUB_RESPONSE = '{"steps": [], "clarification_needed": "LLM not configured"}'

_NETWORK_ERRORS = (ConnectionError, TimeoutError, OSError)

KNOWN_TOOLS = {"git_tool", "github_tool", "intelligence"}
_REQUIRED_TOP_LEVEL_KEYS = {"steps", "clarification_needed"}
_REQUIRED_STEP_KEYS = {"action", "description", "tool", "params", "destructive"}


def _assert_token_not_in_prompt(prompt: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        assert token not in prompt, \
            "SECURITY INVARIANT VIOLATED: GitHub token found in LLM prompt (INV-01)"


def _call_llm(prompt: str) -> str:
    _assert_token_not_in_prompt(prompt)

    if LLM_PROVIDER == "gemini":
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            return _STUB_RESPONSE

        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model.generate_content(prompt).text

    if LLM_PROVIDER == "groq":
        groq_key = os.environ.get("GROQ_API_KEY")
        if not groq_key:
            return _STUB_RESPONSE

        from groq import Groq
        client = Groq(api_key=groq_key)
        response = client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    return _STUB_RESPONSE


def _call_llm_with_retry(prompt: str, retries: int = 2) -> str:
    _assert_token_not_in_prompt(prompt)

    for attempt in range(retries):
        try:
            return _call_llm(prompt)
        except _NETWORK_ERRORS:
            if attempt == retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def build_prompt(user_intent: str, repo_state: dict, session_id: str) -> str:
    assert repo_state and "status" in repo_state, \
        "AGENTIC INVARIANT VIOLATED: build_prompt called without repo state (INV-11)"

    session_history = db.get_session_context(session_id, last_n=10)
    history_lines = "\n".join(
        f"{turn['role']}: {turn['content']}" for turn in session_history
    )

    prompt = (
        "SYSTEM: You are a GitHub AI agent. You MUST respond with ONLY valid JSON "
        "matching the plan schema. No markdown, no explanation, no code fences.\n\n"
        'PLAN SCHEMA: {"steps": [{"action": str, "description": str, "tool": str, '
        '"params": dict, "destructive": bool}], "clarification_needed": null or str}\n\n'
        f"REPO STATE: {json.dumps(repo_state, indent=2)}\n\n"
        f"SESSION HISTORY: {history_lines}\n\n"
        f"USER INTENT: {user_intent}"
    )

    _assert_token_not_in_prompt(prompt)
    return prompt


def _strip_json_fences(raw: str) -> str:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    return clean.strip()


def _validate_plan_schema(plan: dict) -> None:
    """Raises ValueError if plan does not match the required schema. Enforces INV-15."""
    if not isinstance(plan, dict):
        raise ValueError(f"plan must be a dict, got {type(plan)}")

    extra_keys = set(plan.keys()) - _REQUIRED_TOP_LEVEL_KEYS
    if extra_keys:
        raise ValueError(f"plan has unexpected top-level key(s): {extra_keys}")

    missing_keys = _REQUIRED_TOP_LEVEL_KEYS - set(plan.keys())
    if missing_keys:
        raise ValueError(f"plan is missing required top-level key(s): {missing_keys}")

    steps = plan["steps"]
    clarification_needed = plan["clarification_needed"]

    if clarification_needed is not None and not isinstance(clarification_needed, str):
        raise ValueError(
            f"clarification_needed must be null or a string, got {type(clarification_needed)}"
        )

    if not isinstance(steps, list):
        raise ValueError(f"steps must be a list, got {type(steps)}")

    has_steps = len(steps) > 0
    has_clarification = isinstance(clarification_needed, str) and len(clarification_needed) > 0

    if not has_steps and not has_clarification:
        raise ValueError(
            "plan must have either a non-empty steps list or a non-null clarification_needed string"
        )

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {i} must be a dict, got {type(step)}")

        if not isinstance(step.get("action"), str):
            raise ValueError(f"step {i}.action must be a str, got {type(step.get('action'))}")

        if not isinstance(step.get("description"), str):
            raise ValueError(
                f"step {i}.description must be a str, got {type(step.get('description'))}"
            )

        if step.get("tool") not in KNOWN_TOOLS:
            raise ValueError(
                f"step {i}.tool must be one of KNOWN_TOOLS {KNOWN_TOOLS}, got {step.get('tool')!r}"
            )

        if not isinstance(step.get("params"), dict):
            raise ValueError(f"step {i}.params must be a dict, got {type(step.get('params'))}")

        if not isinstance(step.get("destructive"), bool):
            raise ValueError(
                f"step {i}.destructive must be explicit bool, got {type(step.get('destructive'))}"
            )

        extra_step_keys = set(step.keys()) - _REQUIRED_STEP_KEYS
        if extra_step_keys:
            raise ValueError(f"step {i} has unexpected key(s): {extra_step_keys}")
