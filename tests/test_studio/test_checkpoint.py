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

"""Tests for the Studio checkpoint system (time-travel debugging)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fireflyframework_genai.studio.execution.checkpoint import (
    Checkpoint,
    CheckpointManager,
)

# ---------------------------------------------------------------------------
# Checkpoint dataclass
# ---------------------------------------------------------------------------


class TestCheckpointDataclass:
    def test_checkpoint_fields(self) -> None:
        cp = Checkpoint(
            index=0,
            node_id="node_a",
            state={"result": 42},
            inputs={"prompt": "hello"},
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert cp.index == 0
        assert cp.node_id == "node_a"
        assert cp.state == {"result": 42}
        assert cp.inputs == {"prompt": "hello"}
        assert cp.timestamp == "2026-01-01T00:00:00+00:00"
        assert cp.branch_id is None
        assert cp.parent_index is None

    def test_checkpoint_with_branch(self) -> None:
        cp = Checkpoint(
            index=3,
            node_id="node_b",
            state={"x": 1},
            inputs={"y": 2},
            timestamp="2026-01-01T00:00:00+00:00",
            branch_id="abc12345",
            parent_index=1,
        )
        assert cp.branch_id == "abc12345"
        assert cp.parent_index == 1


# ---------------------------------------------------------------------------
# CheckpointManager — create
# ---------------------------------------------------------------------------


class TestCheckpointManagerCreate:
    def test_create_returns_checkpoint(self) -> None:
        mgr = CheckpointManager()
        cp = mgr.create(node_id="node_a", state={"out": 1}, inputs={"in": 0})
        assert isinstance(cp, Checkpoint)

    def test_create_assigns_correct_fields(self) -> None:
        mgr = CheckpointManager()
        cp = mgr.create(node_id="node_a", state={"out": 1}, inputs={"in": 0})
        assert cp.node_id == "node_a"
        assert cp.state == {"out": 1}
        assert cp.inputs == {"in": 0}

    def test_create_assigns_index_zero_for_first(self) -> None:
        mgr = CheckpointManager()
        cp = mgr.create(node_id="n", state={}, inputs={})
        assert cp.index == 0

    def test_create_auto_sets_timestamp(self) -> None:
        mgr = CheckpointManager()
        before = datetime.now(UTC)
        cp = mgr.create(node_id="n", state={}, inputs={})
        after = datetime.now(UTC)

        ts = datetime.fromisoformat(cp.timestamp)
        assert before <= ts <= after

    def test_create_timestamp_is_utc_iso8601(self) -> None:
        mgr = CheckpointManager()
        cp = mgr.create(node_id="n", state={}, inputs={})
        # Should parse as ISO 8601 and be in UTC
        ts = datetime.fromisoformat(cp.timestamp)
        assert ts.tzinfo is not None


# ---------------------------------------------------------------------------
# CheckpointManager — sequential index assignment
# ---------------------------------------------------------------------------


class TestCheckpointManagerSequentialIndex:
    def test_sequential_indices(self) -> None:
        mgr = CheckpointManager()
        cp0 = mgr.create(node_id="a", state={}, inputs={})
        cp1 = mgr.create(node_id="b", state={}, inputs={})
        cp2 = mgr.create(node_id="c", state={}, inputs={})
        assert cp0.index == 0
        assert cp1.index == 1
        assert cp2.index == 2


# ---------------------------------------------------------------------------
# CheckpointManager — get
# ---------------------------------------------------------------------------


class TestCheckpointManagerGet:
    def test_get_by_index(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"v": 1}, inputs={})
        mgr.create(node_id="b", state={"v": 2}, inputs={})

        cp = mgr.get(0)
        assert cp.node_id == "a"
        assert cp.state == {"v": 1}

        cp = mgr.get(1)
        assert cp.node_id == "b"
        assert cp.state == {"v": 2}

    def test_get_invalid_index_raises(self) -> None:
        mgr = CheckpointManager()
        import pytest

        with pytest.raises(IndexError):
            mgr.get(0)

    def test_get_negative_index_raises(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        import pytest

        with pytest.raises(IndexError):
            mgr.get(-1)


# ---------------------------------------------------------------------------
# CheckpointManager — list_all
# ---------------------------------------------------------------------------


class TestCheckpointManagerListAll:
    def test_list_all_empty(self) -> None:
        mgr = CheckpointManager()
        assert mgr.list_all() == []

    def test_list_all_returns_all_checkpoints(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        mgr.create(node_id="b", state={}, inputs={})
        result = mgr.list_all()
        assert len(result) == 2
        assert result[0].node_id == "a"
        assert result[1].node_id == "b"

    def test_list_all_returns_defensive_copy(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        first = mgr.list_all()
        second = mgr.list_all()
        assert first is not second
        # Mutating the returned list should not affect the manager
        first.clear()
        assert len(mgr.list_all()) == 1


# ---------------------------------------------------------------------------
# CheckpointManager — fork
# ---------------------------------------------------------------------------


class TestCheckpointManagerFork:
    def test_fork_creates_new_checkpoint(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="node_a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 99})
        assert isinstance(forked, Checkpoint)

    def test_fork_inherits_node_id_and_inputs(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="node_a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 99})
        assert forked.node_id == "node_a"
        assert forked.inputs == {"in": 0}

    def test_fork_uses_modified_state(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="node_a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 99})
        assert forked.state == {"x": 99}

    def test_fork_assigns_branch_id(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="node_a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 99})
        assert forked.branch_id is not None
        # 8-char hex string
        assert re.fullmatch(r"[0-9a-f]{8}", forked.branch_id)

    def test_fork_sets_parent_index(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="node_a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 99})
        assert forked.parent_index == 0

    def test_fork_gets_next_sequential_index(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        mgr.create(node_id="b", state={}, inputs={})
        forked = mgr.fork(from_index=0, modified_state={"z": 1})
        assert forked.index == 2

    def test_fork_is_retrievable(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1}, inputs={"in": 0})
        forked = mgr.fork(from_index=0, modified_state={"x": 42})
        retrieved = mgr.get(forked.index)
        assert retrieved.branch_id == forked.branch_id
        assert retrieved.state == {"x": 42}


# ---------------------------------------------------------------------------
# CheckpointManager — diff
# ---------------------------------------------------------------------------


class TestCheckpointManagerDiff:
    def test_diff_added_keys(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1}, inputs={})
        mgr.create(node_id="b", state={"x": 1, "y": 2}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == {"y"}
        assert result["removed"] == set()
        assert result["changed"] == set()

    def test_diff_removed_keys(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1, "y": 2}, inputs={})
        mgr.create(node_id="b", state={"x": 1}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == set()
        assert result["removed"] == {"y"}
        assert result["changed"] == set()

    def test_diff_changed_keys(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1, "y": 2}, inputs={})
        mgr.create(node_id="b", state={"x": 99, "y": 2}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == set()
        assert result["removed"] == set()
        assert result["changed"] == {"x"}

    def test_diff_mixed(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1, "y": 2, "z": 3}, inputs={})
        mgr.create(node_id="b", state={"x": 99, "w": 4, "z": 3}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == {"w"}
        assert result["removed"] == {"y"}
        assert result["changed"] == {"x"}

    def test_diff_identical_states(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={"x": 1}, inputs={})
        mgr.create(node_id="b", state={"x": 1}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == set()
        assert result["removed"] == set()
        assert result["changed"] == set()

    def test_diff_empty_states(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        mgr.create(node_id="b", state={}, inputs={})
        result = mgr.diff(0, 1)
        assert result["added"] == set()
        assert result["removed"] == set()
        assert result["changed"] == set()


# ---------------------------------------------------------------------------
# CheckpointManager — clear
# ---------------------------------------------------------------------------


class TestCheckpointManagerClear:
    def test_clear_empties_checkpoints(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        mgr.create(node_id="b", state={}, inputs={})
        mgr.clear()
        assert mgr.list_all() == []

    def test_clear_resets_index_counter(self) -> None:
        mgr = CheckpointManager()
        mgr.create(node_id="a", state={}, inputs={})
        mgr.create(node_id="b", state={}, inputs={})
        mgr.clear()
        cp = mgr.create(node_id="c", state={}, inputs={})
        assert cp.index == 0
