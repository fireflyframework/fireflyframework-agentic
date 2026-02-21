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

"""DAG-based pipeline orchestrator for enterprise workflows.

This package provides a Directed Acyclic Graph (DAG) execution engine that
wires agents, reasoning patterns, validation, and tools into production
pipelines where independent stages execute concurrently.
"""

from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.context import PipelineContext
from fireflyframework_genai.pipeline.dag import DAG, DAGEdge, DAGNode, FailureStrategy
from fireflyframework_genai.pipeline.engine import PipelineEngine, PipelineEventHandler
from fireflyframework_genai.pipeline.result import ExecutionTraceEntry, NodeResult, PipelineResult
from fireflyframework_genai.pipeline.steps import (
    AgentStep,
    BatchLLMStep,
    BranchStep,
    CallableStep,
    FanInStep,
    FanOutStep,
    ReasoningStep,
    StepExecutor,
)

__all__ = [
    "AgentStep",
    "BatchLLMStep",
    "BranchStep",
    "CallableStep",
    "DAG",
    "DAGEdge",
    "DAGNode",
    "ExecutionTraceEntry",
    "FailureStrategy",
    "FanInStep",
    "FanOutStep",
    "NodeResult",
    "PipelineBuilder",
    "PipelineContext",
    "PipelineEngine",
    "PipelineEventHandler",
    "PipelineResult",
    "ReasoningStep",
    "StepExecutor",
]
