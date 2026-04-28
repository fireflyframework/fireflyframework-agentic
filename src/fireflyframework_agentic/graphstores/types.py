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

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Node(BaseModel):
    """A node in the knowledge graph.

    `key` is the within-doc identifier for the entity (e.g. canonical name);
    `(source_doc_id, label, key)` is unique per the SQLite schema.
    """

    label: str
    key: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_doc_id: str
    extractor_name: str
    chunk_ids: list[str] = Field(default_factory=list)


class Edge(BaseModel):
    """A directed edge between two nodes in the knowledge graph."""

    label: str
    source_label: str
    source_key: str
    target_label: str
    target_key: str
    properties: dict[str, Any] = Field(default_factory=dict)
    source_doc_id: str
    extractor_name: str
