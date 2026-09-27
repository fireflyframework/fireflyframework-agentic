# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.

"""Plug-and-play Redis :class:`Checkpointer` for fireflyframework-agentic.

This is **example code**, not framework code. Copy this file into your
project and adapt as needed:

* Pass your own ``redis.Redis`` client. The template does not own it.
* Tune ``ttl_seconds`` to match your workflow's longest expected wall-clock.
* The ``firefly:ckpt:<pipeline>:runs`` ZSET indexes runs; :meth:`list_runs`
  removes entries whose checkpoints have expired.
"""

from __future__ import annotations

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
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
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
        latest: CheckpointRecord | None = None
        for key in self._client.scan_iter(match=pattern):
            payload = self._client.get(key)
            if payload is None:
                continue  # An entry can expire between SCAN and GET.
            record = CheckpointRecord.model_validate_json(payload)
            if record.pipeline_name != pipeline_name or record.run_id != run_id:
                continue
            if latest is None or record.sequence > latest.sequence:
                latest = record
        return latest

    def list_runs(self, pipeline_name: str) -> list[str]:
        index = f"{self._PREFIX}:{pipeline_name}:runs"
        runs = []
        for member in self._client.zrange(index, 0, -1):
            run_id = member.decode("utf-8") if isinstance(member, bytes) else member
            if self.load_latest(pipeline_name, run_id) is not None:
                runs.append(run_id)
            else:
                self._client.zrem(index, member)
        return runs
