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

"""Dataset management for evaluation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class EvalCase(BaseModel):
    """A single evaluation test case."""

    input: str
    expected_output: str = ""
    metadata: dict[str, Any] = {}


class EvalDataset:
    """Manages evaluation test cases.

    Parameters:
        cases: Initial test cases.
    """

    def __init__(self, cases: Sequence[EvalCase] | None = None) -> None:
        self._cases = list(cases) if cases else []

    @property
    def cases(self) -> list[EvalCase]:
        return list(self._cases)

    def add(self, case: EvalCase) -> None:
        """Add a test case."""
        self._cases.append(case)

    @classmethod
    def from_json(cls, path: str | Path) -> EvalDataset:
        """Load a dataset from a JSON file."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cases = [EvalCase(**item) for item in data]
        return cls(cases)

    def to_json(self, path: str | Path) -> None:
        """Save the dataset to a JSON file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps([c.model_dump() for c in self._cases], indent=2),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self._cases)
