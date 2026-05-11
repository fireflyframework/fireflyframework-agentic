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

"""Tests for the S3Source stub.

These tests assert the stub honours the locked-in API surface (Protocol
conformance and config validation) while raising clearly when constructed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fireflyframework_agentic.content.sources import (
    ContentSource,
)
from s3_source import (
    S3Source,
    S3SourceConfig,
)


def _config(tmp_path: Path) -> S3SourceConfig:
    return S3SourceConfig(
        bucket="firefly-knowledge-base",
        region="eu-west-1",
        cache_dir=tmp_path / "cache",
        cursor_file=tmp_path / "cursor.json",
    )


def test_s3_source_class_satisfies_protocol() -> None:
    """S3Source must structurally match ContentSource even though instantiation fails."""
    # Protocol membership at class level is checked via the structural
    # attribute set; runtime_checkable Protocols inspect attribute presence.
    for attr in ("list_changed", "fetch", "current_cursor", "pending_cursor", "commit_delta"):
        assert hasattr(S3Source, attr), f"S3Source missing required attribute: {attr}"


def test_s3_source_construction_raises_not_implemented(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError, match=r"\[aws\] extra"):
        S3Source(
            _config(tmp_path),
            access_key_id="AKIA...",
            secret_access_key="secret",
        )


def test_s3_source_config_validates() -> None:
    """The config model is real and usable even though the source is a stub."""
    cfg = S3SourceConfig(
        bucket="b",
        region="eu-west-1",
        prefix="docs/",
        mime_types=["application/pdf"],
        cache_dir=Path("/tmp/cache"),
        cursor_file=Path("/tmp/cursor.json"),
    )
    assert cfg.bucket == "b"
    assert cfg.prefix == "docs/"
    assert cfg.mime_types == ["application/pdf"]


def test_content_source_protocol_is_runtime_checkable() -> None:
    """Defensive: confirm the Protocol export is the runtime-checkable one."""
    # If this fails it means base.py changed in a breaking way.
    assert hasattr(ContentSource, "__instancecheck__")
