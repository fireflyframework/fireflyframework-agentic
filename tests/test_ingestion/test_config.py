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

"""Tests for ingestion.yaml parsing and adapter assembly."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.adapters.sources import SharePointSource
from fireflyframework_agentic.ingestion.config import (
    IngestionConfig,
    SecretsSection,
    SinkSection,
    StateSection,
    build_mapper,
    build_secrets_provider,
    build_service,
    build_sink,
    build_source,
)
from fireflyframework_agentic.ingestion.exceptions import IngestionConfigError


def _write_minimal_setup(tmp_path: Path) -> Path:
    schema = {
        "tables": [
            {
                "name": "customers",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True, "nullable": False},
                    {"name": "name", "type": "string"},
                    {"name": "tier", "type": "string"},
                ],
            }
        ]
    }
    (tmp_path / "schema.yaml").write_text(yaml.safe_dump(schema))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "customers.py").write_text(
        "import re\n"
        "from collections.abc import Iterator\n"
        "from fireflyframework_agentic.ingestion.domain import "
        "RawFile, TargetSchema, TypedRecord\n"
        "PATTERN = re.compile(r'.*')\n"
        "def map(file, schema): yield from []\n"
    )
    config = {
        "source": {
            "type": "sharepoint",
            "config": {
                "tenant_id_secret": "T",
                "client_id_secret": "C",
                "client_secret_secret": "S",
                "drive_id": "drive-1",
            },
        },
        "mapper": {"type": "script", "scripts_dir": str(tmp_path / "scripts")},
        "sink": {"type": "sqlite", "mode": "in-memory"},
        "schema": str(tmp_path / "schema.yaml"),
        "state": {
            "cache_dir": str(tmp_path / "cache"),
            "delta_file": str(tmp_path / "delta.json"),
        },
        "secrets": {"type": "env"},
    }
    p = tmp_path / "ingestion.yaml"
    p.write_text(yaml.safe_dump(config))
    return p


def test_parses_full_config(tmp_path: Path):
    p = _write_minimal_setup(tmp_path)
    cfg = IngestionConfig.from_yaml(p)
    assert cfg.source.type == "sharepoint"
    assert cfg.source.config["drive_id"] == "drive-1"
    assert cfg.mapper.type == "script"
    assert cfg.sink.type == "sqlite"
    assert cfg.secrets.type == "env"


def test_from_yaml_raises_when_file_missing(tmp_path: Path):
    with pytest.raises(IngestionConfigError, match="could not read"):
        IngestionConfig.from_yaml(tmp_path / "nope.yaml")


def test_from_yaml_raises_when_top_level_not_a_mapping(tmp_path: Path):
    p = tmp_path / "ingestion.yaml"
    p.write_text("- a list at the top\n")
    with pytest.raises(IngestionConfigError, match="must be a mapping"):
        IngestionConfig.from_yaml(p)


def test_build_secrets_provider_env():
    p = build_secrets_provider(SecretsSection(type="env"))
    assert isinstance(p, EnvSecretsProvider)


def test_build_secrets_provider_keyvault_requires_vault_url():
    with pytest.raises(IngestionConfigError, match="vault_url"):
        build_secrets_provider(SecretsSection(type="azure-keyvault"))


def test_build_source_returns_sharepoint_adapter(tmp_path: Path):
    cfg = IngestionConfig.from_yaml(_write_minimal_setup(tmp_path))
    secrets = build_secrets_provider(cfg.secrets)
    src = build_source(cfg.source, cfg.state, secrets)
    assert isinstance(src, SharePointSource)


def test_build_mapper_returns_script_mapper(tmp_path: Path):
    cfg = IngestionConfig.from_yaml(_write_minimal_setup(tmp_path))
    mapper = build_mapper(cfg.mapper)
    assert isinstance(mapper, ScriptMapper)


def test_build_sink_in_memory_returns_sqlite(tmp_path: Path):
    sink = build_sink(SinkSection(type="sqlite", mode="in-memory"))
    assert isinstance(sink, SQLiteSink)
    sink.close()


def test_build_service_full_pipeline(tmp_path: Path):
    cfg = IngestionConfig.from_yaml(_write_minimal_setup(tmp_path))
    svc = build_service(cfg)
    assert svc is not None


def test_state_defaults_under_home(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    state = StateSection()
    assert "fireflyframework" in str(state.cache_dir)
    assert "fireflyframework" in str(state.delta_file)
