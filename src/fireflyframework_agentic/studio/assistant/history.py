"""Persistent chat history for Firefly Agentic Studio projects."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STUDIO_DIR = Path.home() / ".firefly-studio" / "projects"


def _history_path(project_name: str) -> Path:
    return _STUDIO_DIR / project_name / "chat_history.json"


def save_chat_history(project_name: str, messages: list[dict]) -> None:
    path = _history_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2, default=str))


def load_chat_history(project_name: str) -> list[dict]:
    path = _history_path(project_name)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load chat history for %s: %s", project_name, exc)
        return []


def clear_chat_history(project_name: str) -> None:
    path = _history_path(project_name)
    if path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# Smith chat history
# ---------------------------------------------------------------------------


def _smith_history_path(project_name: str) -> Path:
    return _STUDIO_DIR / project_name / "smith_history.json"


def save_smith_history(project_name: str, messages: list[dict]) -> None:
    path = _smith_history_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2, default=str))


def load_smith_history(project_name: str) -> list[dict]:
    path = _smith_history_path(project_name)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load Smith history for %s: %s", project_name, exc)
        return []


def clear_smith_history(project_name: str) -> None:
    path = _smith_history_path(project_name)
    if path.is_file():
        path.unlink()


# ---------------------------------------------------------------------------
# Smith generated files (code tab)
# ---------------------------------------------------------------------------


def _smith_files_path(project_name: str) -> Path:
    return _STUDIO_DIR / project_name / "smith_files.json"


def save_smith_files(project_name: str, files: list[dict]) -> None:
    path = _smith_files_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(files, indent=2, default=str))


def load_smith_files(project_name: str) -> list[dict]:
    path = _smith_files_path(project_name)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load Smith files for %s: %s", project_name, exc)
        return []


# ---------------------------------------------------------------------------
# Oracle chat history
# ---------------------------------------------------------------------------


def _oracle_history_path(project_name: str) -> Path:
    return _STUDIO_DIR / project_name / "oracle_history.json"


def save_oracle_history(project_name: str, messages: list[dict]) -> None:
    path = _oracle_history_path(project_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2, default=str))


def load_oracle_history(project_name: str) -> list[dict]:
    path = _oracle_history_path(project_name)
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load Oracle history for %s: %s", project_name, exc)
        return []


def clear_oracle_history(project_name: str) -> None:
    path = _oracle_history_path(project_name)
    if path.is_file():
        path.unlink()
