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

"""ScriptMapper: dynamically loads user-supplied mapping scripts.

Each script in the configured directory must declare:

* ``PATTERN`` -- a compiled :class:`re.Pattern` matched against
  :attr:`RawFile.name` (or :attr:`RawFile.source_id` for path-based
  dispatch).
* ``map(file: RawFile, schema: TargetSchema) -> Iterator[TypedRecord]`` --
  a callable that yields typed records.

Scripts that fail to satisfy this contract raise :class:`MappingScriptError`
at load time; this is fail-fast on configuration errors rather than at run
time when a file happens to match.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import cast

from fireflyframework_agentic.ingestion.domain import (
    RawFile,
    TargetSchema,
    TypedRecord,
)
from fireflyframework_agentic.ingestion.exceptions import (
    MappingScriptError,
    MultipleMappersError,
)

logger = logging.getLogger(__name__)

MapFn = Callable[[RawFile, TargetSchema], Iterator[TypedRecord]]


class _LoadedScript:
    __slots__ = ("path", "pattern", "map_fn")

    def __init__(self, path: Path, pattern: re.Pattern[str], map_fn: MapFn) -> None:
        self.path = path
        self.pattern = pattern
        self.map_fn = map_fn

    def matches(self, file: RawFile) -> bool:
        return bool(self.pattern.search(file.name) or self.pattern.search(file.source_id))


class ScriptMapper:
    """Loads mapping scripts from a directory and dispatches by PATTERN."""

    def __init__(self, scripts_dir: str | Path) -> None:
        self._scripts_dir = Path(scripts_dir)
        if not self._scripts_dir.is_dir():
            raise MappingScriptError(f"scripts_dir {self._scripts_dir} does not exist or is not a directory")
        self._scripts: list[_LoadedScript] = self._load_all(self._scripts_dir)

    @property
    def scripts_dir(self) -> Path:
        return self._scripts_dir

    @property
    def script_count(self) -> int:
        return len(self._scripts)

    def supports(self, file: RawFile) -> bool:
        return any(s.matches(file) for s in self._scripts)

    def map(self, file: RawFile, schema: TargetSchema) -> Iterator[TypedRecord]:
        matches = [s for s in self._scripts if s.matches(file)]
        if not matches:
            raise MappingScriptError(f"no mapping script matches file {file.source_id!r}")
        if len(matches) > 1:
            paths = [str(s.path) for s in matches]
            raise MultipleMappersError(f"multiple mapping scripts match {file.source_id!r}: {paths}")
        yield from matches[0].map_fn(file, schema)

    @staticmethod
    def _load_all(scripts_dir: Path) -> list[_LoadedScript]:
        loaded: list[_LoadedScript] = []
        for path in sorted(scripts_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = ScriptMapper._load_module(path)
            pattern = ScriptMapper._extract_pattern(module, path)
            map_fn = ScriptMapper._extract_map(module, path)
            loaded.append(_LoadedScript(path=path, pattern=pattern, map_fn=map_fn))
        return loaded

    @staticmethod
    def _load_module(path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"firefly_mapping_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise MappingScriptError(f"could not import script {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            raise MappingScriptError(f"error executing script {path}: {exc}") from exc
        return module

    @staticmethod
    def _extract_pattern(module: ModuleType, path: Path) -> re.Pattern[str]:
        if not hasattr(module, "PATTERN"):
            raise MappingScriptError(f"script {path} does not declare PATTERN")
        pattern = module.PATTERN
        if isinstance(pattern, str):
            try:
                return re.compile(pattern)
            except re.error as exc:
                raise MappingScriptError(f"script {path} PATTERN is not a valid regex: {exc}") from exc
        if not isinstance(pattern, re.Pattern):
            raise MappingScriptError(f"script {path} PATTERN must be a re.Pattern or str, got {type(pattern).__name__}")
        return pattern

    @staticmethod
    def _extract_map(module: ModuleType, path: Path) -> MapFn:
        if not hasattr(module, "map"):
            raise MappingScriptError(f"script {path} does not declare map()")
        fn = module.map
        if not callable(fn):
            raise MappingScriptError(f"script {path} map is not callable")
        return cast("MapFn", fn)
