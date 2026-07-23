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
from perception import PerceptionLayer

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


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    repo_path = data.get("repo_path", ".")

    try:
        repo_state = perception.read_repo_state(repo_path)
    except Exception:
        return jsonify({
            "reply": f"I couldn't read '{repo_path}'. Please check the path exists and try again.",
            "plan": None,
        })

    assert repo_state is not None and len(repo_state) > 0

    if repo_state.get("status") == "not a git repository":
        return jsonify({
            "reply": f"'{repo_path}' doesn't look like a git repository. Point me at a valid git repo.",
            "plan": None,
        })

    return jsonify({
        "reply": "perception ok",
        "repo_state_keys": list(repo_state.keys()),
        "observed_at": repo_state["observed_at"],
    })


@app.route("/confirm", methods=["POST"])
def confirm():
    return jsonify({"status": "confirm not yet implemented"})


@app.route("/cancel", methods=["POST"])
def cancel():
    return jsonify({"status": "cancelled"})


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
