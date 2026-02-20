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

"""Experiments REST API endpoints for Firefly Studio.

Provides CRUD operations for A/B experiment definitions and a manual
``run-variant`` action.  Advanced features such as automatic traffic
splitting and statistical analysis are planned for a future release.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]

from fireflyframework_genai.studio.projects import ProjectManager


def create_experiments_router(manager: ProjectManager) -> APIRouter:
    """Create an :class:`APIRouter` for experiment management.

    Endpoints
    ---------
    ``GET /api/projects/{name}/experiments``
        List all experiments in a project.
    ``POST /api/projects/{name}/experiments``
        Create a new experiment.
    ``GET /api/projects/{name}/experiments/{exp_id}``
        Get a single experiment.
    ``DELETE /api/projects/{name}/experiments/{exp_id}``
        Delete an experiment.
    ``POST /api/projects/{name}/experiments/{exp_id}/run``
        Run a specific variant of an experiment.
    """
    router = APIRouter(prefix="/api/projects", tags=["experiments"])

    def _experiments_dir(project_name: str) -> Any:
        """Return the experiments directory for a project, creating it if needed."""
        from pathlib import Path

        try:
            project_dir = manager._safe_path(project_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not project_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Project '{project_name}' not found")

        exp_dir: Path = project_dir / "experiments"
        exp_dir.mkdir(exist_ok=True)
        return exp_dir

    def _load_experiment(exp_dir: Any, exp_id: str) -> dict[str, Any]:
        """Load a single experiment JSON file."""
        path = exp_dir / f"{exp_id}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
        return json.loads(path.read_text(encoding="utf-8"))

    @router.get("/{name}/experiments")
    async def list_experiments(name: str) -> list[dict[str, Any]]:
        exp_dir = _experiments_dir(name)
        results: list[dict[str, Any]] = []
        for path in sorted(exp_dir.iterdir()):
            if path.is_file() and path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
        return results

    @router.post("/{name}/experiments")
    async def create_experiment(name: str, body: dict[str, Any]) -> dict[str, Any]:
        exp_dir = _experiments_dir(name)

        exp_name = body.get("name")
        if not exp_name:
            raise HTTPException(status_code=400, detail="Experiment 'name' is required")

        variants = body.get("variants", [])
        if not variants or not isinstance(variants, list):
            raise HTTPException(status_code=400, detail="At least one variant is required")

        exp_id = uuid.uuid4().hex[:12]
        experiment: dict[str, Any] = {
            "id": exp_id,
            "name": exp_name,
            "status": "draft",
            "created_at": datetime.now(UTC).isoformat(),
            "variants": [
                {
                    "name": v.get("name", f"Variant {chr(65 + i)}"),
                    "pipeline": v.get("pipeline", ""),
                    "traffic": v.get("traffic", round(100 / len(variants))),
                }
                for i, v in enumerate(variants)
            ],
        }

        path = exp_dir / f"{exp_id}.json"
        path.write_text(json.dumps(experiment, indent=2), encoding="utf-8")
        return experiment

    @router.get("/{name}/experiments/{exp_id}")
    async def get_experiment(name: str, exp_id: str) -> dict[str, Any]:
        exp_dir = _experiments_dir(name)
        return _load_experiment(exp_dir, exp_id)

    @router.delete("/{name}/experiments/{exp_id}")
    async def delete_experiment(name: str, exp_id: str) -> dict[str, str]:
        exp_dir = _experiments_dir(name)
        path = exp_dir / f"{exp_id}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"Experiment '{exp_id}' not found")
        path.unlink()
        return {"status": "deleted"}

    @router.post("/{name}/experiments/{exp_id}/run")
    async def run_variant(name: str, exp_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Run a single variant of an experiment manually.

        Request body:
            ``variant_name``: Name of the variant to run.
            ``input``: The input to feed to the pipeline.
            ``graph``: The pipeline graph for this variant.
        """
        exp_dir = _experiments_dir(name)
        experiment = _load_experiment(exp_dir, exp_id)

        variant_name = body.get("variant_name")
        graph_data = body.get("graph")
        input_data = body.get("input", "")

        if not variant_name or not graph_data:
            raise HTTPException(status_code=400, detail="Request body must include 'variant_name' and 'graph'")

        # Verify variant exists
        matching = [v for v in experiment["variants"] if v["name"] == variant_name]
        if not matching:
            raise HTTPException(
                status_code=404,
                detail=f"Variant '{variant_name}' not found in experiment '{exp_id}'",
            )

        from fireflyframework_genai.studio.codegen.models import GraphModel
        from fireflyframework_genai.studio.execution.compiler import CompilationError, compile_graph

        graph = GraphModel.model_validate(graph_data)
        try:
            engine = compile_graph(graph)
        except CompilationError as exc:
            raise HTTPException(status_code=400, detail=f"Compilation error: {exc}") from exc

        try:
            result = await engine.run(inputs=input_data)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Execution error: {exc}") from exc

        output = ""
        if result.outputs:
            last_node = list(result.outputs.values())[-1]
            output = str(last_node.output) if last_node.output is not None else ""

        return {
            "experiment_id": exp_id,
            "variant_name": variant_name,
            "success": result.success,
            "output": output,
        }

    return router
