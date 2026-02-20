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

"""Checkpoint system for time-travel debugging in Studio.

The :class:`CheckpointManager` stores immutable snapshots of execution
state at each pipeline step.  Users can rewind to any checkpoint, fork
execution with modified state, and compare state diffs between any two
points in the timeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Checkpoint:
    """An immutable snapshot of pipeline execution state.

    Attributes:
        index: Sequential index in the timeline.
        node_id: Identifier of the node that produced this checkpoint.
        state: Node output / pipeline state at this point.
        inputs: Inputs that were fed to the node.
        timestamp: UTC ISO 8601 timestamp (auto-set on creation).
        branch_id: Non-``None`` for forked checkpoints.
        parent_index: Index of the parent checkpoint (for forks).
    """

    index: int
    node_id: str
    state: dict
    inputs: dict
    timestamp: str = ""
    branch_id: str | None = None
    parent_index: int | None = None


class CheckpointManager:
    """Manages an ordered timeline of :class:`Checkpoint` snapshots.

    Every time a pipeline node completes, the execution engine calls
    :meth:`create` to record a checkpoint.  The manager auto-assigns
    sequential indices and UTC timestamps.

    Supports forking (re-running from a previous checkpoint with
    modified state) and diffing (comparing the ``state`` dicts of
    two checkpoints).
    """

    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        node_id: str,
        state: dict,
        inputs: dict,
        branch_id: str | None = None,
    ) -> Checkpoint:
        """Create a new checkpoint.

        The index is auto-assigned sequentially and the timestamp is
        set to the current UTC time in ISO 8601 format.

        Parameters:
            node_id: Identifier of the node that produced this state.
            state: The pipeline state to snapshot.
            inputs: The inputs that were fed to the node.
            branch_id: Optional branch identifier for forked checkpoints.

        Returns:
            The newly created :class:`Checkpoint`.
        """
        cp = Checkpoint(
            index=len(self._checkpoints),
            node_id=node_id,
            state=state,
            inputs=inputs,
            timestamp=datetime.now(UTC).isoformat(),
            branch_id=branch_id,
        )
        self._checkpoints.append(cp)
        return cp

    def get(self, index: int) -> Checkpoint:
        """Retrieve a checkpoint by its sequential index.

        Parameters:
            index: Non-negative checkpoint index.

        Returns:
            The :class:`Checkpoint` at *index*.

        Raises:
            IndexError: If *index* is out of range or negative.
        """
        if index < 0 or index >= len(self._checkpoints):
            raise IndexError(f"Checkpoint index {index} out of range")
        return self._checkpoints[index]

    def list_all(self) -> list[Checkpoint]:
        """Return all checkpoints as a defensive copy.

        Returns:
            A new list containing all recorded checkpoints in order.
        """
        return list(self._checkpoints)

    def fork(self, from_index: int, modified_state: dict) -> Checkpoint:
        """Fork from an existing checkpoint with modified state.

        Creates a new checkpoint that inherits the parent's ``node_id``
        and ``inputs`` but uses *modified_state*.  A new ``branch_id``
        (8-character hex UUID) is assigned and ``parent_index`` is set
        to *from_index*.

        Parameters:
            from_index: Index of the checkpoint to fork from.
            modified_state: The new state for the forked checkpoint.

        Returns:
            The newly created forked :class:`Checkpoint`.
        """
        parent = self.get(from_index)
        branch_id = uuid.uuid4().hex[:8]
        cp = Checkpoint(
            index=len(self._checkpoints),
            node_id=parent.node_id,
            state=modified_state,
            inputs=parent.inputs,
            timestamp=datetime.now(UTC).isoformat(),
            branch_id=branch_id,
            parent_index=from_index,
        )
        self._checkpoints.append(cp)
        return cp

    def diff(self, index_a: int, index_b: int) -> dict:
        """Compare the ``state`` dicts of two checkpoints.

        Parameters:
            index_a: Index of the first checkpoint.
            index_b: Index of the second checkpoint.

        Returns:
            A dict with keys ``added``, ``removed``, and ``changed``,
            each containing a :class:`set` of state-dict keys.

            - **added**: keys present in *index_b* but not *index_a*.
            - **removed**: keys present in *index_a* but not *index_b*.
            - **changed**: keys present in both but with different values.
        """
        state_a = self.get(index_a).state
        state_b = self.get(index_b).state

        keys_a = set(state_a.keys())
        keys_b = set(state_b.keys())

        added = keys_b - keys_a
        removed = keys_a - keys_b
        common = keys_a & keys_b
        changed = {k for k in common if state_a[k] != state_b[k]}

        return {"added": added, "removed": removed, "changed": changed}

    def clear(self) -> None:
        """Clear all checkpoints and reset the index counter."""
        self._checkpoints.clear()
