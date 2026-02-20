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

"""Evaluation REST API endpoints for Firefly Studio.

Provides endpoints for uploading JSONL test datasets, listing datasets
within a project, and running a pipeline against a dataset to measure
quality.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile  # type: ignore[import-not-found]

from fireflyframework_genai.studio.evaluation import (
    EvaluationResult,
    load_dataset,
    run_evaluation,
)
from fireflyframework_genai.studio.projects import ProjectManager


def create_evaluate_router(manager: ProjectManager) -> APIRouter:
    """Create an :class:`APIRouter` for evaluation endpoints.

    Endpoints
    ---------
    ``POST /api/projects/{name}/datasets/upload``
        Upload a JSONL test dataset to a project.
    ``GET /api/projects/{name}/datasets``
        List available datasets for a project.
    ``POST /api/evaluate/run``
        Run a pipeline graph against a dataset and return results.
    """
    router = APIRouter(prefix="/api", tags=["evaluate"])

    @router.post("/projects/{name}/datasets/upload")
    async def upload_dataset(name: str, file: UploadFile) -> dict[str, Any]:
        """Upload a JSONL dataset file to a project's datasets directory."""
        try:
            project_dir = manager._safe_path(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not project_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

        if not file.filename or not file.filename.endswith((".jsonl", ".json")):
            raise HTTPException(status_code=400, detail="File must be a .jsonl or .json file")

        datasets_dir = project_dir / "datasets"
        datasets_dir.mkdir(exist_ok=True)

        content = await file.read()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="File must be UTF-8 encoded") from exc

        # Validate the JSONL format
        line_count = 0
        for lineno, line in enumerate(text.strip().splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Invalid JSON on line {lineno}: {exc}") from exc
            if "input" not in obj:
                raise HTTPException(status_code=400, detail=f"Line {lineno} is missing required 'input' field")
            line_count += 1

        if line_count == 0:
            raise HTTPException(status_code=400, detail="Dataset file is empty")

        dest = datasets_dir / file.filename
        dest.write_text(text, encoding="utf-8")

        return {"filename": file.filename, "test_cases": line_count, "status": "uploaded"}

    @router.get("/projects/{name}/datasets")
    async def list_datasets(name: str) -> list[dict[str, Any]]:
        """List available JSONL datasets in a project."""
        try:
            project_dir = manager._safe_path(name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if not project_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

        datasets_dir = project_dir / "datasets"
        if not datasets_dir.is_dir():
            return []

        results: list[dict[str, Any]] = []
        for path in sorted(datasets_dir.iterdir()):
            if path.is_file() and path.suffix in {".jsonl", ".json"}:
                # Count lines to show test case count
                text = path.read_text(encoding="utf-8", errors="replace")
                line_count = sum(1 for ln in text.strip().splitlines() if ln.strip())
                results.append(
                    {
                        "filename": path.name,
                        "test_cases": line_count,
                        "size": path.stat().st_size,
                    }
                )

        return results

    @router.post("/evaluate/run")
    async def run_eval(body: dict[str, Any]) -> dict[str, Any]:
        """Run a pipeline against a dataset and return evaluation results.

        Request body:
            ``project``: Project name containing the dataset.
            ``dataset``: Dataset filename (e.g. ``"my-tests.jsonl"``).
            ``graph``: The pipeline graph to evaluate.
        """
        project_name = body.get("project")
        dataset_name = body.get("dataset")
        graph_data = body.get("graph")

        if not project_name or not dataset_name or not graph_data:
            raise HTTPException(
                status_code=400,
                detail="Request body must include 'project', 'dataset', and 'graph'",
            )

        try:
            project_dir = manager._safe_path(str(project_name))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        dataset_path = project_dir / "datasets" / str(dataset_name)
        if not dataset_path.is_file():
            raise HTTPException(status_code=404, detail=f"Dataset '{dataset_name}' not found")

        try:
            cases = load_dataset(dataset_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        result: EvaluationResult = await run_evaluation(graph_data, cases)
        result.dataset_name = str(dataset_name)

        return {
            "dataset": result.dataset_name,
            "total": result.total,
            "passed": result.passed,
            "failed": result.failed,
            "error_count": result.error_count,
            "pass_rate": result.pass_rate,
            "results": [
                {
                    "input": r.input,
                    "expected_output": r.expected_output,
                    "actual_output": r.actual_output,
                    "passed": r.passed,
                    "error": r.error,
                }
                for r in result.results
            ],
        }

    return router
