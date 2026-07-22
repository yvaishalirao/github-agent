"""Flask server, OAuth, routing."""

import socket

from dotenv import load_dotenv
from flask import Flask, jsonify

load_dotenv()

HOST = "127.0.0.1"
PORT = 5000

MUTATION_ENDPOINTS = set()

app = Flask(__name__)


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "host": HOST})


# TODO: audit routes that mutations only use POST


if __name__ == "__main__":
    resolved = socket.gethostbyname(HOST)
    assert resolved == "127.0.0.1", \
        f"SECURITY INVARIANT VIOLATED: server would bind to {resolved}"

    app.run(host="127.0.0.1", port=5000, debug=False)
