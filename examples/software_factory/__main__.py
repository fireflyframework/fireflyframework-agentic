# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Entry point: ``python -m examples.software_factory``.

Demonstrates the full QA-loop + checkpoint-resume flow:

1. First ``invoke`` runs architect → codegen → builder. The builder raises on
   its first call (simulated transient ``dep install`` failure); the engine
   checkpoints the failure and returns ``success=False``.
2. Second ``invoke(run_id=...)`` resumes from the checkpoint. The builder
   succeeds, QA fails with PSD2 feedback, the cycle re-enters codegen, the
   rewritten code passes QA, ``stable_release`` runs, and the pipeline
   finishes with ``success=True``.

By default uses :class:`FileCheckpointer` over a tmp directory. Set
``FIREFLY_CKPT=postgres`` (with ``PG_DSN``) or ``FIREFLY_CKPT=redis`` (with
``REDIS_URL``) to swap in the templates under ``checkpointers/``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from examples.software_factory.pipeline import build_pipeline
from examples.software_factory.state import BuildState
from fireflyframework_agentic.pipeline import Checkpointer, FileCheckpointer


def _resolve_checkpointer(default_dir: Path) -> Checkpointer:
    backend = os.environ.get("FIREFLY_CKPT", "file").lower()
    if backend == "postgres":
        import psycopg

        from examples.software_factory.checkpointers.postgres import (
            PostgresCheckpointer,
        )

        dsn = os.environ["PG_DSN"]
        return PostgresCheckpointer(psycopg.connect(dsn, autocommit=True))

    if backend == "redis":
        import redis

        from examples.software_factory.checkpointers.redis import RedisCheckpointer

        url = os.environ["REDIS_URL"]
        return RedisCheckpointer(redis.Redis.from_url(url, decode_responses=True))

    return FileCheckpointer(default_dir)


async def main() -> None:
    with tempfile.TemporaryDirectory() as ckpt_dir:
        checkpointer = _resolve_checkpointer(Path(ckpt_dir))
        pipeline = build_pipeline(checkpointer)

        first = await pipeline.invoke(BuildState(request="payments microservice"))
        print(f"\nfirst run:  success={first.success}  failed_node={first.failed_node}  run_id={first.run_id}\n")

        resumed = await pipeline.invoke(run_id=first.run_id)
        print(
            f"\nresumed:    success={resumed.success}  "
            f"release={resumed.state.release_tag}  iteration={resumed.state.iteration}"
        )
        print(f"qa_feedback: {resumed.state.qa_feedback}")


if __name__ == "__main__":
    asyncio.run(main())
