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

"""File-based project manager for Firefly Agentic Studio.

Each project is a directory under *base_dir* containing a ``project.json``
metadata file and a ``pipelines/`` subdirectory that holds saved pipeline
graphs as JSON files.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ProjectInfo:
    """Metadata for a single Studio project."""

    name: str
    description: str = ""
    created_at: str = ""
    path: Path = field(default_factory=lambda: Path("."))


class ProjectManager:
    """Manage Studio projects stored as directories on disk.

    Parameters
    ----------
    base_dir:
        Root directory under which all project directories live.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, *parts: str) -> Path:
        """Resolve a path and assert it stays within the base directory."""
        resolved = (self._base_dir / Path(*parts)).resolve()
        if not str(resolved).startswith(str(self._base_dir)):
            raise ValueError(f"Invalid path component: {parts}")
        return resolved

    # -- Project CRUD ------------------------------------------------------

    def create(self, name: str, *, description: str = "") -> ProjectInfo:
        """Create a new project directory with metadata.

        Raises
        ------
        ValueError
            If a project with *name* already exists.
        """
        project_dir = self._safe_path(name)
        if project_dir.exists():
            raise ValueError(f"Project '{name}' already exists")

        project_dir.mkdir(parents=True)
        (project_dir / "pipelines").mkdir()
        (project_dir / "custom_tools").mkdir()
        (project_dir / "memory").mkdir()

        created_at = datetime.now(UTC).isoformat()
        meta = {
            "name": name,
            "description": description,
            "created_at": created_at,
        }
        (project_dir / "project.json").write_text(json.dumps(meta, indent=2))

        return ProjectInfo(
            name=name,
            description=description,
            created_at=created_at,
            path=project_dir,
        )

    def list_all(self) -> list[ProjectInfo]:
        """Return all projects sorted alphabetically by name."""
        projects: list[ProjectInfo] = []
        for child in sorted(self._base_dir.iterdir()):
            meta_path = child / "project.json"
            if child.is_dir() and meta_path.is_file():
                data = json.loads(meta_path.read_text())
                projects.append(
                    ProjectInfo(
                        name=data["name"],
                        description=data.get("description", ""),
                        created_at=data.get("created_at", ""),
                        path=child,
                    )
                )
        return projects

    def delete(self, name: str) -> None:
        """Remove a project directory and all its contents.

        Raises
        ------
        FileNotFoundError
            If the project does not exist.
        """
        project_dir = self._safe_path(name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{name}' not found")
        shutil.rmtree(project_dir)

    def rename(self, old_name: str, new_name: str) -> ProjectInfo:
        """Rename a project directory and update its metadata.

        Raises
        ------
        FileNotFoundError
            If the source project does not exist.
        ValueError
            If a project with *new_name* already exists or path is invalid.
        """
        old_dir = self._safe_path(old_name)
        new_dir = self._safe_path(new_name)
        if not old_dir.exists():
            raise FileNotFoundError(f"Project '{old_name}' not found")
        if new_dir.exists():
            raise ValueError(f"Project '{new_name}' already exists")

        old_dir.rename(new_dir)

        # Update name inside project.json
        meta_path = new_dir / "project.json"
        meta = json.loads(meta_path.read_text())
        meta["name"] = new_name
        meta_path.write_text(json.dumps(meta, indent=2))

        return ProjectInfo(
            name=new_name,
            description=meta.get("description", ""),
            created_at=meta.get("created_at", ""),
            path=new_dir,
        )

    def update(self, name: str, *, description: str | None = None) -> ProjectInfo:
        """Update project metadata fields.

        Raises
        ------
        FileNotFoundError
            If the project does not exist.
        """
        project_dir = self._safe_path(name)
        meta_path = project_dir / "project.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"Project '{name}' not found")

        meta = json.loads(meta_path.read_text())
        if description is not None:
            meta["description"] = description
        meta_path.write_text(json.dumps(meta, indent=2))

        return ProjectInfo(
            name=meta["name"],
            description=meta.get("description", ""),
            created_at=meta.get("created_at", ""),
            path=project_dir,
        )

    def delete_all(self) -> int:
        """Delete all projects and return the count of deleted projects."""
        all_projects = self.list_all()
        for p in all_projects:
            self.delete(p.name)
        return len(all_projects)

    # -- Pipeline persistence ----------------------------------------------

    def save_pipeline(self, project_name: str, pipeline_name: str, graph: dict) -> None:
        """Persist a pipeline graph as JSON inside the project directory."""
        pipeline_path = self._safe_path(project_name, "pipelines", f"{pipeline_name}.json")
        if not pipeline_path.parent.exists():
            raise FileNotFoundError(f"Project '{project_name}' not found")
        pipeline_path.write_text(json.dumps(graph, indent=2))

    def load_pipeline(self, project_name: str, pipeline_name: str) -> dict:
        """Load a pipeline graph from the project directory.

        Raises
        ------
        FileNotFoundError
            If the pipeline JSON file does not exist.
        """
        pipeline_path = self._safe_path(project_name, "pipelines", f"{pipeline_name}.json")
        if not pipeline_path.is_file():
            raise FileNotFoundError(f"Pipeline '{pipeline_name}' not found in project '{project_name}'")
        return json.loads(pipeline_path.read_text())
