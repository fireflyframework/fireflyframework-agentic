"""Layer 1 of the unification (#245): PipelineEngine gains checkpoint, audit, and resume.

These tests pin the contract for port-based pipelines to opt into the same
checkpointing + audit machinery that StatePipeline already has — without
becoming state-based. Resume via ``run(run_id=...)`` is the headline feature.
"""

from __future__ import annotations

import pytest

from fireflyframework_agentic.exceptions import PipelineError
from fireflyframework_agentic.pipeline.audit import FileAuditLog
from fireflyframework_agentic.pipeline.checkpoint import FileCheckpointer
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_agentic.pipeline.engine import PipelineEngine


class _CountingStep:
    """Step that records how many times its .execute() was called."""

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix
        self.calls = 0

    async def execute(self, ctx, inputs):
        self.calls += 1
        val = inputs.get("input", "")
        return f"{self._prefix}{val}"


class _FailOnceStep:
    """Step that raises on the first call and succeeds afterward."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, ctx, inputs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("flake")
        return "b:done"


def _chain_dag(*node_ids: str) -> tuple[DAG, dict[str, _CountingStep]]:
    dag = DAG("chain")
    steps: dict[str, _CountingStep] = {}
    for nid in node_ids:
        step = _CountingStep(f"{nid}:")
        steps[nid] = step
        dag.add_node(DAGNode(node_id=nid, step=step))
    for i in range(len(node_ids) - 1):
        dag.add_edge(DAGEdge(source=node_ids[i], target=node_ids[i + 1]))
    return dag, steps


# ---- run_id -----------------------------------------------------------------


async def test_run_returns_non_empty_run_id():
    dag, _ = _chain_dag("a", "b")
    engine = PipelineEngine(dag)
    result = await engine.run(inputs="x")
    assert result.success
    assert result.run_id  # non-empty


async def test_explicit_run_id_is_preserved():
    dag, _ = _chain_dag("a")
    engine = PipelineEngine(dag)
    result = await engine.run(inputs="x", run_id="manual-id")
    assert result.run_id == "manual-id"


# ---- checkpointing ---------------------------------------------------------


async def test_checkpoint_written_per_successful_node(tmp_path):
    dag, _ = _chain_dag("a", "b", "c")
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp)
    result = await engine.run(inputs="x")
    assert result.success
    files = sorted((tmp_path / "chain" / result.run_id).glob("*.json"))
    assert len(files) == 3
    # Sequence prefix preserves completion order.
    assert files[0].name.endswith("_a.json")
    assert files[1].name.endswith("_b.json")
    assert files[2].name.endswith("_c.json")


async def test_checkpoint_omitted_when_no_checkpointer(tmp_path):
    dag, _ = _chain_dag("a", "b")
    engine = PipelineEngine(dag)  # no checkpointer
    result = await engine.run(inputs="x")
    assert result.success
    # tmp_path should still be empty since no checkpointer was wired.
    assert not any(tmp_path.iterdir())


async def test_checkpoint_records_completed_nodes(tmp_path):
    dag, _ = _chain_dag("a", "b")
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp)
    result = await engine.run(inputs="x")
    record = cp.load_latest("chain", result.run_id)
    assert record is not None
    assert record.completed_nodes == ["a", "b"]
    assert record.node_id == "b"


# ---- resume ----------------------------------------------------------------


async def test_resume_completed_run_is_a_noop(tmp_path):
    dag, steps = _chain_dag("a", "b", "c")
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp)
    result = await engine.run(inputs="x")
    assert all(s.calls == 1 for s in steps.values())
    # All nodes are completed; resume should not re-execute anything.
    result2 = await engine.run(run_id=result.run_id)
    assert result2.success
    assert all(s.calls == 1 for s in steps.values())


async def test_resume_after_failure_skips_completed_and_finishes(tmp_path):
    a_step = _CountingStep("a:")
    b_step = _FailOnceStep()
    c_step = _CountingStep("c:")
    dag = DAG("recoverable")
    dag.add_node(DAGNode(node_id="a", step=a_step))
    dag.add_node(DAGNode(node_id="b", step=b_step, failure_strategy=FailureStrategy.FAIL_PIPELINE))
    dag.add_node(DAGNode(node_id="c", step=c_step))
    dag.add_edge(DAGEdge(source="a", target="b"))
    dag.add_edge(DAGEdge(source="b", target="c"))

    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp)

    result1 = await engine.run(inputs="x")
    assert not result1.success
    assert a_step.calls == 1
    assert b_step.calls == 1
    assert c_step.calls == 0

    result2 = await engine.run(run_id=result1.run_id)
    assert result2.success
    # 'a' was already done — must not be re-executed on resume.
    assert a_step.calls == 1
    # 'b' is re-executed (its second attempt succeeds via _FailOnceStep).
    assert b_step.calls == 2
    # 'c' runs once, after b succeeds on resume.
    assert c_step.calls == 1


async def test_resume_without_checkpointer_raises():
    dag, _ = _chain_dag("a")
    engine = PipelineEngine(dag)
    with pytest.raises(PipelineError, match="checkpoint"):
        await engine.run(run_id="anything")


async def test_resume_unknown_run_id_raises(tmp_path):
    dag, _ = _chain_dag("a")
    cp = FileCheckpointer(tmp_path)
    engine = PipelineEngine(dag, checkpointer=cp)
    with pytest.raises(PipelineError, match="No checkpoint"):
        await engine.run(run_id="missing")


# ---- audit log -------------------------------------------------------------


async def test_audit_log_writes_entry_per_node(tmp_path):
    dag, _ = _chain_dag("a", "b")
    al = FileAuditLog(tmp_path)
    engine = PipelineEngine(dag, audit_log=al)
    result = await engine.run(inputs="x")
    entries = al.list_entries("chain", result.run_id)
    assert len(entries) == 2
    assert [e.node_id for e in entries] == ["a", "b"]
    assert all(e.status == "success" for e in entries)
    assert all(e.visit == 1 for e in entries)
    assert all(e.latency_ms >= 0 for e in entries)


async def test_audit_log_captures_failure(tmp_path):
    class _Bad:
        async def execute(self, ctx, inputs):
            raise RuntimeError("boom")

    dag = DAG("fail")
    dag.add_node(DAGNode(node_id="bad", step=_Bad(), failure_strategy=FailureStrategy.FAIL_PIPELINE))
    al = FileAuditLog(tmp_path)
    engine = PipelineEngine(dag, audit_log=al)
    result = await engine.run(inputs="x")
    assert not result.success
    entries = al.list_entries("fail", result.run_id)
    assert len(entries) == 1
    assert entries[0].status == "error"
    assert entries[0].error_message is not None
    assert "boom" in entries[0].error_message


async def test_audit_skipped_nodes_not_recorded_as_success(tmp_path):
    """Skipped nodes (condition gate) shouldn't show up as successful audits."""
    step = _CountingStep("a:")
    dag = DAG("skipping")
    dag.add_node(DAGNode(node_id="skipped", step=step, condition=lambda ctx: False))
    al = FileAuditLog(tmp_path)
    engine = PipelineEngine(dag, audit_log=al)
    await engine.run(inputs="x")
    entries = al.list_entries("skipping", _last_run_id(al, "skipping"))
    # Skipped nodes are not work that happened — leave them out.
    assert entries == [] or all(e.status != "success" for e in entries)


def _last_run_id(al: FileAuditLog, pipeline: str) -> str:
    pipeline_dir = al._root / pipeline
    if not pipeline_dir.exists():
        return ""
    files = list(pipeline_dir.glob("*.jsonl"))
    return files[0].stem if files else ""


# ---- combined checkpoint + audit + resume ----------------------------------


async def test_full_stack_resume_with_audit(tmp_path):
    cp_dir = tmp_path / "cp"
    al_dir = tmp_path / "al"
    a_step = _CountingStep("a:")
    b_step = _FailOnceStep()
    dag = DAG("full")
    dag.add_node(DAGNode(node_id="a", step=a_step))
    dag.add_node(DAGNode(node_id="b", step=b_step, failure_strategy=FailureStrategy.FAIL_PIPELINE))
    dag.add_edge(DAGEdge(source="a", target="b"))
    cp = FileCheckpointer(cp_dir)
    al = FileAuditLog(al_dir)
    engine = PipelineEngine(dag, checkpointer=cp, audit_log=al)

    r1 = await engine.run(inputs="x")
    assert not r1.success
    r2 = await engine.run(run_id=r1.run_id)
    assert r2.success
    entries = al.list_entries("full", r1.run_id)
    # Three entries: a-success, b-error (first attempt), b-success (resume).
    assert len(entries) == 3
    assert entries[0].node_id == "a" and entries[0].status == "success"
    assert entries[1].node_id == "b" and entries[1].status == "error"
    assert entries[2].node_id == "b" and entries[2].status == "success"
