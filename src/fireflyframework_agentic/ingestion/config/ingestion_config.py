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

"""Pydantic config model for ingestion.yaml + factory helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
from fireflyframework_agentic.ingestion.adapters.mappers import ScriptMapper
from fireflyframework_agentic.ingestion.adapters.sinks import SQLiteSink
from fireflyframework_agentic.ingestion.adapters.sources import (
    SharePointSource,
    SharePointSourceConfig,
)
from fireflyframework_agentic.ingestion.domain import TargetSchema
from fireflyframework_agentic.ingestion.exceptions import IngestionConfigError
from fireflyframework_agentic.ingestion.ports import (
    DataSourcePort,
    MapperPort,
    SecretsProvider,
    StructuredSinkPort,
)
from fireflyframework_agentic.ingestion.services import IngestionService


class SourceSection(BaseModel):
    type: Literal["sharepoint"]
    config: dict[str, Any]


class MapperSection(BaseModel):
    type: Literal["script"]
    scripts_dir: Path


class SinkSection(BaseModel):
    type: Literal["sqlite"]
    mode: Literal["in-memory", "file"] = "in-memory"
    path: Path | None = None


class StateSection(BaseModel):
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".fireflyframework/ingestion/cache")
    delta_file: Path = Field(default_factory=lambda: Path.home() / ".fireflyframework/ingestion/delta.json")


class SecretsSection(BaseModel):
    type: Literal["env", "azure-keyvault"] = "env"
    vault_url: str | None = None


class IngestionConfig(BaseModel):
    """Top-level :file:`ingestion.yaml` schema."""

    source: SourceSection
    mapper: MapperSection
    sink: SinkSection
    schema_path: Path = Field(alias="schema")
    state: StateSection = Field(default_factory=StateSection)
    secrets: SecretsSection = Field(default_factory=SecretsSection)

    model_config = {"populate_by_name": True}

    @classmethod
    def from_yaml(cls, path: str | Path) -> IngestionConfig:
        try:
            data = yaml.safe_load(Path(path).read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise IngestionConfigError(f"could not read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise IngestionConfigError(f"{path}: top-level must be a mapping")
        return cls.model_validate(data)


def build_secrets_provider(section: SecretsSection) -> SecretsProvider:
    if section.type == "env":
        return EnvSecretsProvider()
    if section.type == "azure-keyvault":
        if not section.vault_url:
            raise IngestionConfigError("secrets.type=azure-keyvault requires secrets.vault_url")
        # Lazy import: this code path requires the optional extra.
        from fireflyframework_agentic.ingestion.adapters.keyvault_provider import (
            AzureKeyVaultSecretsProvider,
        )

        return AzureKeyVaultSecretsProvider(section.vault_url)
    raise IngestionConfigError(f"unknown secrets type: {section.type!r}")


def build_source(
    section: SourceSection,
    state: StateSection,
    secrets: SecretsProvider,
) -> DataSourcePort:
    if section.type == "sharepoint":
        merged = {
            **section.config,
            "cache_dir": state.cache_dir,
            "delta_file": state.delta_file,
        }
        sp_config = SharePointSourceConfig.model_validate(merged)
        return SharePointSource(sp_config, secrets)
    raise IngestionConfigError(f"unknown source type: {section.type!r}")


def build_mapper(section: MapperSection) -> MapperPort:
    if section.type == "script":
        return ScriptMapper(section.scripts_dir)
    raise IngestionConfigError(f"unknown mapper type: {section.type!r}")


def build_sink(section: SinkSection) -> StructuredSinkPort:
    if section.type == "sqlite":
        if section.mode == "in-memory":
            return SQLiteSink(":memory:")
        if section.path is None:
            raise IngestionConfigError(f"sqlite sink mode={section.mode!r} requires sink.path")
        return SQLiteSink(str(section.path))
    raise IngestionConfigError(f"unknown sink type: {section.type!r}")


def build_service(config: IngestionConfig) -> IngestionService:
    schema = TargetSchema.from_yaml(config.schema_path)
    secrets = build_secrets_provider(config.secrets)
    source = build_source(config.source, config.state, secrets)
    mapper = build_mapper(config.mapper)
    sink = build_sink(config.sink)
    return IngestionService(source, mapper, sink, schema)


def expand_env_vars(value: str) -> str:
    """Expand ``${VAR}`` references in *value* using ``os.environ``."""
    return os.path.expandvars(value)
