"""Environment variable loading and validation."""

import os

from dotenv import load_dotenv

load_dotenv()

REQUIRED_KEYS = ["FLASK_SECRET_KEY", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"]


def validate_config() -> dict:
    """Validate required env vars are present.

    Raises ValueError with a clear message if any required key is missing.
    Returns a dict of {key: "present"/"missing"} — never the actual values.
    """
    presence = {}

    for key in REQUIRED_KEYS:
        value = os.environ.get(key)
        presence[key] = "present" if value else "missing"
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")

    llm_provider = os.environ.get("LLM_PROVIDER", "gemini")
    presence["LLM_PROVIDER"] = "present" if os.environ.get("LLM_PROVIDER") else "missing (defaulted to 'gemini')"

    if llm_provider == "gemini":
        value = os.environ.get("GEMINI_API_KEY")
        presence["GEMINI_API_KEY"] = "present" if value else "missing"
        if not value:
            raise ValueError(
                "Missing required environment variable: GEMINI_API_KEY (required when LLM_PROVIDER=gemini)"
            )
    elif llm_provider == "groq":
        value = os.environ.get("GROQ_API_KEY")
        presence["GROQ_API_KEY"] = "present" if value else "missing"
        if not value:
            raise ValueError(
                "Missing required environment variable: GROQ_API_KEY (required when LLM_PROVIDER=groq)"
            )

    return presence


def get_github_token() -> str:
    """Reads GITHUB_TOKEN from the environment at call time — the live session token."""
    return os.environ.get("GITHUB_TOKEN", "")


FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")

_presence = validate_config()
print("Config keys present:", _presence)
