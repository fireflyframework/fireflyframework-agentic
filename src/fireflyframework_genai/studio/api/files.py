# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""File browsing REST API endpoints for Firefly Agentic Studio.

Provides read-only access to project files so the Studio frontend can
display a file explorer with content preview.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]

from fireflyframework_genai.studio.projects import ProjectManager

# Directories to exclude from recursive file listings.
_EXCLUDED_DIRS: set[str] = {
    "__pycache__",
    ".git",
    "node_modules",
    ".env",
    ".venv",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
}

# Maximum file size (in bytes) we are willing to read into memory for preview.
_MAX_READ_SIZE: int = 2 * 1024 * 1024  # 2 MiB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_project_dir(manager: ProjectManager, project_name: str) -> Path:
    """Return the resolved project directory, raising 404 if it does not exist."""
    try:
        project_dir = manager._safe_path(project_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not project_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")
    return project_dir


def _validate_within_project(project_dir: Path, resolved: Path) -> None:
    """Raise 403 if *resolved* escapes *project_dir*."""
    try:
        resolved.relative_to(project_dir)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Path escapes the project directory") from exc


def _is_text_file(path: Path) -> bool:
    """Heuristic: read a small chunk and check for null bytes (binary indicator)."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" not in chunk
    except OSError:
        return False


def _collect_entries(root: Path, base: Path) -> list[dict[str, Any]]:
    """Recursively collect file/directory entries under *root*, relative to *base*."""
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return entries

    for child in children:
        if child.name in _EXCLUDED_DIRS:
            continue
        # Skip hidden files/dirs (dotfiles) except common config files
        if child.name.startswith(".") and child.name not in {".gitignore", ".env.example"}:
            continue

        relative = child.relative_to(base)
        is_dir = child.is_dir()

        entry: dict[str, Any] = {
            "path": str(relative),
            "name": child.name,
            "is_dir": is_dir,
            "size": 0 if is_dir else child.stat().st_size,
        }
        entries.append(entry)

        if is_dir:
            entries.extend(_collect_entries(child, base))

    return entries


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_files_router(manager: ProjectManager) -> APIRouter:
    """Create an :class:`APIRouter` for project file browsing.

    Endpoints
    ---------
    ``GET /api/projects/{name}/files``
        Recursive listing of all files in the project directory.
    ``GET /api/projects/{name}/files/{path:path}``
        Read a single file's text content.
    """
    router = APIRouter(prefix="/api/projects", tags=["files"])

    @router.get("/{name}/files")
    async def list_files(name: str) -> list[dict[str, Any]]:
        project_dir = _resolve_project_dir(manager, name)
        return _collect_entries(project_dir, project_dir)

    @router.get("/{name}/files/{file_path:path}")
    async def read_file(name: str, file_path: str) -> dict[str, Any]:
        project_dir = _resolve_project_dir(manager, name)
        resolved = (project_dir / file_path).resolve()

        _validate_within_project(project_dir, resolved)

        if not resolved.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

        size = resolved.stat().st_size
        if size > _MAX_READ_SIZE:
            raise HTTPException(status_code=413, detail="File too large to preview")

        if not _is_text_file(resolved):
            raise HTTPException(status_code=422, detail="Binary files cannot be previewed")

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read file: {exc}") from exc

        return {
            "path": file_path,
            "content": content,
            "size": size,
        }

    return router
