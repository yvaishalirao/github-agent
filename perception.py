# READ-ONLY — this module must never call any write operation
"""Read-only repo state reader."""

import os
import subprocess
import time
import pathlib


class PerceptionLayer:
    def _assert_no_writes(self):
        pass

    def _read_status(self, repo_path: str) -> dict:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"status_summary": "not a git repository", "current_branch": None}

        lines = [line for line in result.stdout.splitlines() if line.strip()]

        counts = {"modified": 0, "untracked": 0, "added": 0, "deleted": 0, "renamed": 0}
        for line in lines:
            code = line[:2]
            if code == "??":
                counts["untracked"] += 1
            elif "M" in code:
                counts["modified"] += 1
            elif "A" in code:
                counts["added"] += 1
            elif "D" in code:
                counts["deleted"] += 1
            elif "R" in code:
                counts["renamed"] += 1

        labels = {
            "modified": "modified file",
            "untracked": "untracked file",
            "added": "added file",
            "deleted": "deleted file",
            "renamed": "renamed file",
        }
        parts = []
        for key, label in labels.items():
            n = counts[key]
            if n:
                parts.append(f"{n} {label}{'s' if n != 1 else ''}")

        status_summary = ", ".join(parts) if parts else "clean, no changes"

        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True,
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

        return {"status_summary": status_summary, "current_branch": current_branch}

    def _read_branch_list(self, repo_path: str) -> list:
        result = subprocess.run(
            ["git", "branch", "-a"],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []

        branches = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("* "):
                line = line[2:].strip()
            branches.append(line)
        return branches

    def _strip_sensitive(self, text: str) -> str:
        token = os.environ.get("GITHUB_TOKEN", "")
        if token and token in text:
            return text.replace(token, "[REDACTED]")
        return text

    def _read_staged_diff(self, repo_path: str, max_chars: int = 32000) -> str:
        result = subprocess.run(
            ["git", "diff", "--cached"],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return ""

        diff = self._strip_sensitive(result.stdout)
        if len(diff) > max_chars:
            diff = diff[:max_chars] + f"... [diff truncated at {max_chars} chars]"
        return diff

    def _read_unstaged_diff(self, repo_path: str, max_chars: int = 32000) -> str:
        result = subprocess.run(
            ["git", "diff"],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout:
            return ""

        diff = self._strip_sensitive(result.stdout)
        if len(diff) > max_chars:
            diff = diff[:max_chars] + f"... [diff truncated at {max_chars} chars]"
        return diff

    def _read_commits(self, repo_path: str, n: int = 10) -> list:
        result = subprocess.run(
            ["git", "log", "--oneline", "--format=%H|%s|%ad", "--date=short", "-n", str(n)],
            cwd=repo_path, capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            commit_hash, message, date = parts
            commits.append({
                "hash": self._strip_sensitive(commit_hash),
                "message": self._strip_sensitive(message),
                "date": date,
            })
        return commits

    def read_repo_state(self, repo_path: str) -> dict:
        self._assert_no_writes()

        status_info = self._read_status(repo_path)
        branches = self._read_branch_list(repo_path)

        return {
            "status": status_info["status_summary"],
            "staged_diff": self._read_staged_diff(repo_path),
            "unstaged_diff": self._read_unstaged_diff(repo_path),
            "last_commits": self._read_commits(repo_path),
            "file_tree": [],
            "readme_exists": False,
            "gitignore_exists": False,
            "branches": branches,
            "current_branch": status_info["current_branch"],
            "observed_at": time.time(),
        }
