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

"""Hexagonal ports for the ingestion module."""

from fireflyframework_agentic.ingestion.ports.mapper import MapperPort
from fireflyframework_agentic.ingestion.ports.secrets import SecretsProvider
from fireflyframework_agentic.ingestion.ports.sink import StructuredSinkPort
from fireflyframework_agentic.ingestion.ports.source import DataSourcePort

__all__ = [
    "DataSourcePort",
    "MapperPort",
    "SecretsProvider",
    "StructuredSinkPort",
]
