# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Read and write artifact files in `$RUNNER_TEMP/factory/`."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fireflyframework_agentic.factory.action_runtime.exceptions import (
    MissingArtifactError,
)

ARTIFACT_SUBDIR = "factory"


@dataclass(frozen=True)
class ArtifactStore:
    """Filesystem-backed artifact store rooted at `$RUNNER_TEMP/factory/`."""

    root: Path

    @classmethod
    def from_env(cls) -> ArtifactStore:
        runner_temp = os.environ.get("RUNNER_TEMP")
        if not runner_temp:
            raise RuntimeError("RUNNER_TEMP environment variable is not set")
        root = Path(runner_temp) / ARTIFACT_SUBDIR
        root.mkdir(parents=True, exist_ok=True)
        return cls(root=root)

    def _path(self, name: str) -> Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()

    def read_text(self, name: str) -> str:
        path = self._path(name)
        if not path.is_file():
            raise MissingArtifactError(f"required artifact not found: {name}")
        return path.read_text(encoding="utf-8")

    def write_text(self, name: str, content: str) -> None:
        self._path(name).write_text(content, encoding="utf-8")

    def read_json(self, name: str) -> Any:
        return json.loads(self.read_text(name))

    def write_json(self, name: str, payload: Any) -> None:
        self.write_text(name, json.dumps(payload, indent=2, sort_keys=True))
