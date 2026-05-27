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

"""DAG-based pipeline orchestrator for enterprise workflows.

This package provides a Directed Acyclic Graph (DAG) execution engine that
wires agents, reasoning patterns, validation, and tools into production
pipelines where independent stages execute concurrently.

Two builder modes exist:

* **Port-based** (legacy, parallel): :class:`PipelineEngine` executes a DAG
  whose nodes communicate via ``output_key``/``input_key`` edge ports.
* **State-based**: configure ``PipelineBuilder(state=SomeModel)`` and nodes
  become ``async (state) -> dict`` functions over a typed shared state.
  Branching is one ``.branch(source, router)`` call. Optional checkpointing
  via :class:`Checkpointer` enables resume after failure and mid-pipeline start.
"""

from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.checkpoint import (
    Checkpointer,
    CheckpointRecord,
    FileCheckpointer,
)
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_agentic.pipeline.engine import PipelineEngine, PipelineEventHandler
from fireflyframework_agentic.pipeline.reducers import append, extend, merge_dict, replace
from fireflyframework_agentic.pipeline.result import ExecutionTraceEntry, NodeResult, PipelineResult
from fireflyframework_agentic.pipeline.state_pipeline import StatePipeline, StatePipelineResult
from fireflyframework_agentic.pipeline.steps import (
    AgentStep,
    BatchLLMStep,
    BranchStep,
    CallableStep,
    EmbeddingStep,
    FanInStep,
    FanOutStep,
    ReasoningStep,
    RetrievalStep,
    StepExecutor,
)

__all__ = [
    "DAG",
    "AgentStep",
    "BatchLLMStep",
    "BranchStep",
    "CallableStep",
    "CheckpointRecord",
    "Checkpointer",
    "DAGEdge",
    "DAGNode",
    "EmbeddingStep",
    "ExecutionTraceEntry",
    "FailureStrategy",
    "FanInStep",
    "FanOutStep",
    "FileCheckpointer",
    "NodeResult",
    "PipelineBuilder",
    "PipelineContext",
    "PipelineEngine",
    "PipelineEventHandler",
    "PipelineResult",
    "ReasoningStep",
    "RetrievalStep",
    "StatePipeline",
    "StatePipelineResult",
    "StepExecutor",
    "append",
    "extend",
    "merge_dict",
    "replace",
]
