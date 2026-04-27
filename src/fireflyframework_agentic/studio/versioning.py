"""Git-based version history for Firefly Agentic Studio projects."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class ProjectVersioning:
    """Git-based version history for a project directory."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir).resolve()
        self._ensure_git_init()

    def _ensure_git_init(self) -> None:
        git_dir = self.project_dir / ".git"
        if not git_dir.exists():
            self._run(["git", "init"])
            gitignore = self.project_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("__pycache__/\n*.pyc\n.DS_Store\n")
            self._run(["git", "add", "-A"])
            self._run(["git", "commit", "-m", "Initial project setup", "--allow-empty"])

    def _run(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=self.project_dir,
            capture_output=True,
            text=True,
            timeout=30,
            **kwargs,
        )

    def commit(self, message: str) -> str:
        self._run(["git", "add", "-A"])
        # Check if there are changes to commit
        status = self._run(["git", "status", "--porcelain"])
        if not status.stdout.strip():
            return ""  # Nothing to commit
        self._run(["git", "commit", "-m", message])
        # Extract SHA
        sha_result = self._run(["git", "rev-parse", "HEAD"])
        sha = sha_result.stdout.strip()
        logger.info("Committed %s: %s", sha[:7], message)
        return sha

    def get_history(self, limit: int = 50) -> list[dict]:
        result = self._run(
            [
                "git",
                "log",
                f"--max-count={limit}",
                "--format=%H|%s|%aI",
            ]
        )
        if result.returncode != 0:
            return []

        # Get bookmarked commits
        bookmarks = self._get_bookmark_shas()

        history = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 2)
            if len(parts) >= 3:
                history.append(
                    {
                        "sha": parts[0],
                        "message": parts[1],
                        "timestamp": parts[2],
                        "bookmarked": parts[0] in bookmarks,
                    }
                )
        return history

    def restore(self, commit_sha: str) -> None:
        self._run(["git", "checkout", commit_sha, "--", "."])
        self.commit(f"Restored to version {commit_sha[:7]}")

    def bookmark(self, commit_sha: str, label: str) -> None:
        safe_label = label.replace(" ", "-").replace("/", "-")
        tag_name = f"bookmark/{safe_label}"
        self._run(["git", "tag", "-f", tag_name, commit_sha])

    def list_bookmarks(self) -> list[dict]:
        result = self._run(["git", "tag", "-l", "bookmark/*"])
        if result.returncode != 0:
            return []
        bookmarks = []
        for tag in result.stdout.strip().split("\n"):
            if not tag.strip():
                continue
            label = tag.replace("bookmark/", "")
            sha_result = self._run(["git", "rev-list", "-1", tag])
            sha = sha_result.stdout.strip()
            bookmarks.append({"tag": tag, "label": label, "sha": sha})
        return bookmarks

    def _get_bookmark_shas(self) -> set[str]:
        result = self._run(["git", "tag", "-l", "bookmark/*"])
        if result.returncode != 0:
            return set()
        shas = set()
        for tag in result.stdout.strip().split("\n"):
            if not tag.strip():
                continue
            sha_result = self._run(["git", "rev-list", "-1", tag])
            if sha_result.returncode == 0:
                shas.add(sha_result.stdout.strip())
        return shas
