# Copyright 2026 Firefly Software Foundation
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

"""Call-level journal for deterministic workflow resume.

Each ``agent()`` call is keyed by its sequence number within the run. On resume
(re-running the workflow with a populated journal), completed calls return their
cached output instantly and only new calls run live — the same model Claude's
workflow engine uses. Replay is correct only when the orchestration code is
deterministic (no wall-clock/``random`` driving control flow); only the agent
calls themselves are treated as non-deterministic.
"""

from __future__ import annotations

from typing import Any


class Journal:
    """A sequence-keyed cache of agent outputs for resume."""

    def __init__(self, entries: dict[int, Any] | None = None) -> None:
        self._entries: dict[int, Any] = dict(entries or {})

    def has(self, seq: int) -> bool:
        return seq in self._entries

    def get(self, seq: int) -> Any:
        return self._entries[seq]

    def record(self, seq: int, output: Any) -> None:
        self._entries[seq] = output

    def to_dict(self) -> dict[int, Any]:
        """Return a shallow copy suitable for persistence (e.g. a checkpoint)."""
        return dict(self._entries)

    @classmethod
    def from_dict(cls, data: dict[int, Any]) -> Journal:
        return cls(data)

    def __len__(self) -> int:
        return len(self._entries)
