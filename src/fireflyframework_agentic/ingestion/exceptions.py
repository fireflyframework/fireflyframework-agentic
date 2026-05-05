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

"""Exceptions raised by the ingestion module."""

from __future__ import annotations

from fireflyframework_agentic.exceptions import FireflyAgenticError


class IngestionError(FireflyAgenticError):
    """Base exception for the ingestion module.

    Distinct from :class:`fireflyframework_agentic.ingestion.domain.IngestionError`,
    which is a Pydantic model used to carry recoverable errors back to the
    caller in :class:`IngestionResult`. This exception is raised for fatal,
    non-recoverable conditions.
    """


class IngestionConfigError(IngestionError):
    """Raised when ``ingestion.yaml`` is malformed or references missing assets."""


class MultipleMappersError(IngestionError):
    """Raised when more than one mapping script's PATTERN matches a file."""


class MappingScriptError(IngestionError):
    """Raised when a mapping script cannot be loaded or has an invalid contract."""


class SecretNotFoundError(IngestionError, KeyError):
    """Raised when a :class:`SecretsProvider` cannot resolve a key."""
