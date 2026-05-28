# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Plug-and-play Redis :class:`Checkpointer` for fireflyframework-agentic.

This is **example code**, not framework code. Copy this file into your
project and adapt as needed:

* Pass your own ``redis.Redis`` client. The template does not own it.
* Tune ``ttl_seconds`` to match your workflow's longest expected wall-clock.
* The ``firefly:ckpt:<pipeline>:runs`` ZSET does not expire — it's tiny and
  serves as the index for :meth:`list_runs`.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fireflyframework_agentic.pipeline import CheckpointRecord


class RedisCheckpointer:
    """Stores checkpoints as TTL'd JSON keys, indexed by a per-pipeline ZSET.

    Key layout:

    * ``firefly:ckpt:<pipeline>:<run_id>:<seq:06d>_<node_id>`` → JSON record (TTL).
    * ``firefly:ckpt:<pipeline>:runs``                         → ZSET of run_ids (no TTL).

    Implements the :class:`fireflyframework_agentic.pipeline.Checkpointer`
    Protocol — three sync methods over a caller-supplied client.
    """

    _PREFIX = "firefly:ckpt"

    def __init__(self, client: Any, *, ttl_seconds: int = 30 * 24 * 3600) -> None:
        self._client = client
        self._ttl = ttl_seconds

    def save(self, record: CheckpointRecord) -> None:
        key = f"{self._PREFIX}:{record.pipeline_name}:{record.run_id}:{record.sequence:06d}_{record.node_id}"
        self._client.set(key, record.model_dump_json(), ex=self._ttl)
        self._client.zadd(
            f"{self._PREFIX}:{record.pipeline_name}:runs",
            {record.run_id: time.time()},
        )

    def load_latest(self, pipeline_name: str, run_id: str) -> CheckpointRecord | None:
        pattern = f"{self._PREFIX}:{pipeline_name}:{run_id}:*"
        keys = self._client.keys(pattern)
        if not keys:
            return None
        # Keys are zero-padded by sequence — lex-sorted last = numerically-latest.
        latest_key = sorted(keys)[-1]
        payload = self._client.get(latest_key)
        if payload is None:
            return None
        return CheckpointRecord.model_validate(json.loads(payload))

    def list_runs(self, pipeline_name: str) -> list[str]:
        return list(self._client.zrange(f"{self._PREFIX}:{pipeline_name}:runs", 0, -1))
