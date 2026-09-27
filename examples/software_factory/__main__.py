# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Build a real local Python release: ``python -m examples.software_factory``.

Outputs, checkpoints, and audit records remain in the printed workspace. Resume a
failed run after correcting its environment with ``--workspace PATH --resume ID``.
External checkpoint stores are opt-in through FIREFLY_CKPT and caller credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path

from examples.software_factory.pipeline import build_pipeline
from examples.software_factory.state import BuildState
from fireflyframework_agentic.pipeline import Checkpointer, FileAuditLog, FileCheckpointer


def _resolve_checkpointer(default_dir: Path, resources: ExitStack) -> Checkpointer:
    backend = os.environ.get("FIREFLY_CKPT", "file").lower()
    if backend == "postgres":
        import psycopg

        from examples.software_factory.checkpointers.postgres import PostgresCheckpointer

        connection = resources.enter_context(psycopg.connect(os.environ["PG_DSN"], autocommit=True))
        return PostgresCheckpointer(connection)
    if backend == "redis":
        import redis

        from examples.software_factory.checkpointers.redis import RedisCheckpointer

        client = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        resources.callback(client.close)
        return RedisCheckpointer(client)
    if backend != "file":
        raise ValueError(f"Unknown FIREFLY_CKPT backend: {backend!r}; choose file, postgres, or redis")
    return FileCheckpointer(default_dir)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate, compile, test, and archive an integer-cent order totals project."
    )
    parser.add_argument("--workspace", type=Path, help="Output directory; defaults to a retained temporary directory")
    parser.add_argument(
        "--request", default="Integer-cent order totals with discounts", help="Description recorded in the ADR"
    )
    parser.add_argument(
        "--source", type=Path, help="Existing total_price implementation to validate and repair if QA fails"
    )
    parser.add_argument("--resume", metavar="RUN_ID", help="Resume a checkpointed run in the same workspace")
    args = parser.parse_args(argv)
    if args.resume and (args.workspace is None or args.source is not None):
        parser.error("--resume requires --workspace and cannot be combined with --source")
    workspace = (args.workspace or Path(tempfile.mkdtemp(prefix="firefly-factory-"))).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    with ExitStack() as resources:
        checkpointer = _resolve_checkpointer(workspace / ".checkpoints", resources)
        pipeline = build_pipeline(checkpointer, audit_log=FileAuditLog(workspace / ".audit"))
        if args.resume:
            result = await pipeline.invoke(run_id=args.resume)
        else:
            result = await pipeline.invoke(
                BuildState(
                    request=args.request,
                    workspace=str(workspace),
                    code=args.source.read_text(encoding="utf-8") if args.source else None,
                )
            )
    summary = {
        "success": result.success,
        "run_id": result.run_id,
        "failed_node": result.failed_node,
        "workspace": str(workspace),
        "iteration": result.state.iteration,
        "artifact_path": result.state.artifact_path,
        "artifact_sha256": result.state.artifact_sha256,
    }
    (workspace / "run.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not result.success:
        print(f"Correct the reported error, then resume with --workspace {workspace} --resume {result.run_id}")
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
