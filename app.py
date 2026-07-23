"""Flask server, OAuth, routing."""

import logging
import re
import secrets
import socket
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session

import config
import db
from agent import AgentBrain
from perception import PerceptionLayer
from safety import SafetyLayer

load_dotenv()

HOST = "127.0.0.1"
PORT = 5000

MUTATION_ENDPOINTS = {"chat", "confirm", "cancel"}

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
OAUTH_SCOPES = "repo delete_repo read:user"

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

db.init_db()

perception = PerceptionLayer()
agent_brain = AgentBrain()
safety_layer = SafetyLayer()

# In-memory pending-plan store, keyed by plan_id.
pending_plans = {}


# Redacts any string matching a GitHub token pattern from log records —
# a token must never appear in app.logger output (defence in depth,
# independent of any single storage point).
_TOKEN_PATTERN = re.compile(r"\b(?:gh[poasru]_[A-Za-z0-9]{20,255}|[a-f0-9]{40})\b")


class TokenRedactionFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _TOKEN_PATTERN.sub("[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                _TOKEN_PATTERN.sub("[REDACTED]", arg) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


app.logger.addFilter(TokenRedactionFilter())


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "host": HOST})


@app.route("/login", methods=["GET"])
def login():
    state = secrets.token_hex(16)
    session["oauth_state"] = state

    params = {
        "client_id": config.GITHUB_CLIENT_ID,
        "scope": OAUTH_SCOPES,
        "state": state,
    }
    return redirect(f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}")


@app.route("/callback", methods=["GET"])
def callback():
    state = request.args.get("state")
    code = request.args.get("code")
    expected_state = session.pop("oauth_state", None)

    if not state or not expected_state or state != expected_state:
        flash("OAuth state mismatch — possible CSRF attempt. Please try again.")
        return redirect("/login")

    if not code:
        flash("GitHub did not return an authorization code. Please try again.")
        return redirect("/login")

    try:
        response = requests.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": config.GITHUB_CLIENT_ID,
                "client_secret": config.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError("No access_token in GitHub response")
    except Exception:
        flash("GitHub authentication failed. Please try again.")
        return redirect("/login")

    # Token stored in session ONLY — never logged, never put in a response body.
    session["github_token"] = token
    # Token must never be logged — enforce at storage point.

    return redirect("/")


@app.route("/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect("/login")


def _next_turn(session_id: str, role: str, content: str) -> None:
    turn = session.get("turn", 0)
    db.add_context_turn(session_id, turn, role, content)
    session["turn"] = turn + 1


def _extract_stated_repos(message: str) -> set:
    """User-stated repo names — literal tokens from the raw message text only (INV-08)."""
    return set(re.findall(r"[A-Za-z0-9_.-]+", message))


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    repo_path = data.get("repo_path", ".")

    session_id = session.get("session_id")
    if not session_id:
        session_id = secrets.token_hex(8)
        session["session_id"] = session_id

    try:
        repo_state = perception.read_repo_state(repo_path)
    except Exception:
        return jsonify({
            "reply": f"I couldn't read '{repo_path}'. Please check the path exists and try again.",
            "plan": None,
        })

    assert repo_state is not None and len(repo_state) > 0

    _next_turn(session_id, "user", message)

    plan = agent_brain.build_plan(message, repo_state, session_id)

    clarification_needed = plan.get("clarification_needed")
    steps = plan.get("steps") or []
    confirmation = None

    # Never return a plan with steps to the frontend if clarification_needed is set.
    if clarification_needed:
        reply, response_type, response_plan = clarification_needed, "clarification", None
    elif steps:
        # INV-08: a destructive step's repo must be user-stated, never inferred — checked
        # before any confirmation token is issued.
        user_stated_repos = _extract_stated_repos(message)
        try:
            for step in steps:
                safety_layer.assert_repo_is_user_stated(step, user_stated_repos)
        except AssertionError:
            reply = "I can't tell which repository that destructive action should target. Please name it explicitly."
            _next_turn(session_id, "agent", reply)
            return jsonify({"reply": reply, "plan": None, "type": "clarification"})

        pending_plans[plan["plan_id"]] = plan
        confirmation = safety_layer.inspect_plan(plan, session_id)
        reply, response_type, response_plan = "Here is my plan:", "plan", plan
    else:
        reply, response_type, response_plan = (
            "I could not determine what to do. Please rephrase.", "error", None
        )

    _next_turn(session_id, "agent", reply)
    response = {"reply": reply, "plan": response_plan, "type": response_type}
    if confirmation is not None:
        response["confirmation"] = confirmation
    return jsonify(response)


@app.route("/confirm", methods=["POST"])
def confirm():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")

    session_id = session.get("session_id")
    plan = pending_plans.get(plan_id)

    if plan is None or not session_id:
        return jsonify({"error": "Confirmation expired or invalid. Please re-confirm."})

    destructive_steps = [s for s in plan.get("steps", []) if s.get("destructive") is True]

    if destructive_steps:
        first = destructive_steps[0]
        step_id = first["action"] + "_" + plan_id
        ok, reason = safety_layer.check_and_consume(session_id, step_id, plan_id)
        if not ok:
            return jsonify({"error": "Confirmation expired or invalid. Please re-confirm."})

    # TODO: hand off to executor.execute_plan() once the Execution Engine exists (Session 4 Task 3).
    del pending_plans[plan_id]
    return jsonify({"status": "plan confirmed — execution not yet implemented", "plan_id": plan_id})


@app.route("/cancel", methods=["POST"])
def cancel():
    data = request.get_json(silent=True) or {}
    plan_id = data.get("plan_id")

    pending_plans.pop(plan_id, None)

    return jsonify({"status": "plan cancelled"})


def _audit_mutation_routes():
    """Every route registered in MUTATION_ENDPOINTS must be POST-only — never GET."""
    for rule in app.url_map.iter_rules():
        if rule.endpoint in MUTATION_ENDPOINTS:
            assert "GET" not in rule.methods, \
                f"INVARIANT VIOLATED: mutation endpoint {rule.endpoint} allows GET"


if __name__ == "__main__":
    resolved = socket.gethostbyname(HOST)
    assert resolved == "127.0.0.1", \
        f"SECURITY INVARIANT VIOLATED: server would bind to {resolved}"

    _audit_mutation_routes()

    app.run(host="127.0.0.1", port=5000, debug=False)
