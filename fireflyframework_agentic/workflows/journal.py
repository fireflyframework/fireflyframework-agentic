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

A :class:`Journal` is in-memory by default. Attach a :class:`JournalBackend`
(e.g. :class:`FileJournalBackend`) to make it **durable**: every recorded call is
flushed to the backend, so an out-of-process crash resumes from the last
completed call.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class JournalBackend(Protocol):
    """A durable store for a workflow's call journal, keyed by a stable run key."""

    def load(self, run_key: str) -> dict[int, Any]:
        """Return the persisted journal entries for ``run_key`` (``{}`` if none)."""
        raise NotImplementedError

    def save(self, run_key: str, entries: dict[int, Any]) -> None:
        """Persist the full set of journal entries for ``run_key``."""
        raise NotImplementedError


class Journal:
    """A sequence-keyed cache of agent outputs for resume.

    Args:
        entries: initial entries (e.g. from a prior :meth:`to_dict`).
        backend: an optional :class:`JournalBackend` for durable write-through.
        run_key: the stable key under which the backend stores this run. When a
            ``backend`` and ``run_key`` are given and ``entries`` is ``None``, the
            journal loads any persisted state for that key on construction.
    """

    def __init__(
        self,
        entries: dict[int, Any] | None = None,
        *,
        backend: JournalBackend | None = None,
        run_key: str | None = None,
    ) -> None:
        self._backend = backend
        self._run_key = run_key
        if entries is None and backend is not None and run_key is not None:
            try:
                entries = backend.load(run_key)
            except Exception:  # noqa: BLE001 - a missing/corrupt store starts fresh
                logger.debug("journal backend load failed for %r", run_key, exc_info=True)
                entries = {}
        self._entries: dict[int, Any] = dict(entries or {})

    def has(self, seq: int) -> bool:
        return seq in self._entries

    def get(self, seq: int) -> Any:
        return self._entries[seq]

    def record(self, seq: int, output: Any) -> None:
        self._entries[seq] = output
        if self._backend is not None and self._run_key is not None:
            try:
                self._backend.save(self._run_key, self._entries)
            except Exception:  # noqa: BLE001 - durability is best-effort
                logger.debug("journal backend save failed for %r", self._run_key, exc_info=True)

    def to_dict(self) -> dict[int, Any]:
        """Return a shallow copy suitable for persistence (e.g. a checkpoint)."""
        return dict(self._entries)

    @classmethod
    def from_dict(cls, data: dict[int, Any]) -> Journal:
        return cls(data)

    def __len__(self) -> int:
        return len(self._entries)


def _jsonable(value: Any) -> Any:
    """Best-effort JSON encoder default for pydantic models / dataclasses."""
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)


def _safe_key(run_key: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(run_key))[:128] or "run"


class FileJournalBackend:
    """A :class:`JournalBackend` that persists each run's journal as a JSON file.

    Outputs are stored as their JSON form: strings/numbers/lists/dicts round-trip
    exactly; pydantic / dataclass outputs round-trip as their serialized dict (the
    concrete type is not reconstructed). Use string or dict outputs for
    fully-lossless durable resume.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, run_key: str) -> Path:
        return self._dir / f"{_safe_key(run_key)}.json"

    def load(self, run_key: str) -> dict[int, Any]:
        path = self._path(run_key)
        if not path.exists():
            return {}
        data = json.loads(path.read_text())
        return {int(k): v for k, v in data.items()}

    def save(self, run_key: str, entries: dict[int, Any]) -> None:
        payload = {str(k): v for k, v in entries.items()}
        self._path(run_key).write_text(json.dumps(payload, default=_jsonable))
