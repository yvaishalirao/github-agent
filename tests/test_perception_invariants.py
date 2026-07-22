"""AST-based structural enforcement of INV-10 — perception.py must never write."""

import ast
from pathlib import Path

PERCEPTION_PATH = Path(__file__).resolve().parent.parent / "perception.py"

FORBIDDEN_MODULES = {"github", "git", "shutil", "tempfile"}
WRITE_MODE_MARKERS = ("w", "a")


def _parse_perception() -> ast.Module:
    source = PERCEPTION_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(PERCEPTION_PATH))


def test_forbidden_imports():
    tree = _parse_perception()
    found = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level in FORBIDDEN_MODULES:
                    found.append(f"import {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_level = node.module.split(".")[0]
                if top_level in FORBIDDEN_MODULES:
                    found.append(f"from {node.module} import ... (line {node.lineno})")
                if node.module == "io":
                    for alias in node.names:
                        if alias.name == "FileIO":
                            found.append(f"from io import FileIO (line {node.lineno})")

    assert not found, (
        "INV-10 VIOLATED: perception.py must never import a write-capable module. "
        f"Forbidden imports found: {found}"
    )


def test_no_write_open():
    tree = _parse_perception()
    violations = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"):
            continue

        mode = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value

        if isinstance(mode, str) and any(marker in mode for marker in WRITE_MODE_MARKERS):
            violations.append(f"open() with mode {mode!r} at line {node.lineno}")

    assert not violations, (
        "INV-10 VIOLATED: perception.py must never call open() in write mode. "
        f"Violations: {violations}"
    )


def test_no_subprocess_shell():
    tree = _parse_perception()
    violations = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        is_subprocess_call = (
            (isinstance(func, ast.Attribute) and func.attr in ("run", "Popen"))
            or (isinstance(func, ast.Name) and func.id in ("run", "Popen"))
        )
        if not is_subprocess_call:
            continue

        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                violations.append(f"shell=True at line {node.lineno}")

    assert not violations, (
        "INV-10 VIOLATED (also a shell-injection risk): perception.py must never use "
        f"shell=True in a subprocess call. Violations: {violations}"
    )


def test_observed_at_always_set():
    from perception import PerceptionLayer

    state = PerceptionLayer().read_repo_state("/tmp")

    assert isinstance(state, dict)
    assert "observed_at" in state
    assert isinstance(state["observed_at"], float)
    assert state["observed_at"] > 0
