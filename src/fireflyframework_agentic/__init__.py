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

"""Firefly Agentic Framework -- A metaframework built on Pydantic AI.

This package provides production-grade abstractions for building GenAI
applications including agents, reasoning patterns, prompt engineering,
tools, observability, explainability, experimentation, and exposure
via REST APIs and message queues.

Quick start::

    from fireflyframework_agentic import FireflyAgenticConfig, get_config

    config = get_config()
    print(config.default_model)
"""

from importlib.metadata import version

from fireflyframework_agentic.config import FireflyAgenticConfig, get_config, reset_config

__version__ = version("fireflyframework-agentic")

from fireflyframework_agentic.embeddings import BaseEmbedder, EmbedderRegistry, EmbeddingProtocol
from fireflyframework_agentic.exceptions import (
    AgentError,
    AgentNotFoundError,
    BudgetExceededError,
    ChunkingError,
    CompressionError,
    ConfigurationError,
    DatabaseConnectionError,
    DatabaseStoreError,
    DelegationError,
    EmbeddingError,
    EmbeddingProviderError,
    ExperimentError,
    ExplainabilityError,
    ExposureError,
    FireflyAgenticError,
    FireflyMemoryError,
    MemoryError,
    ObservabilityError,
    OutputReviewError,
    OutputValidationError,
    PipelineError,
    PromptError,
    PromptNotFoundError,
    PromptValidationError,
    QoSError,
    QueueConnectionError,
    QuotaError,
    RateLimitError,
    ReasoningError,
    ReasoningPatternNotFoundError,
    ReasoningStepLimitError,
    ToolError,
    ToolGuardError,
    ToolNotFoundError,
    ToolTimeoutError,
    VectorStoreConnectionError,
    VectorStoreError,
)
from fireflyframework_agentic.logging import configure_logging, enable_debug
from fireflyframework_agentic.plugin import PluginDiscovery
from fireflyframework_agentic.types import (
    JSON,
    AgentDepsT,
    AgentLike,
    AudioUrl,
    BinaryContent,
    DocumentUrl,
    Headers,
    ImageUrl,
    Metadata,
    MultiModalContent,
    OutputT,
    ToolInputT,
    ToolOutputT,
    UserContent,
    UserPrompt,
    VideoUrl,
)
from fireflyframework_agentic.vectorstores import BaseVectorStore, InMemoryVectorStore, VectorStoreProtocol

__all__ = [
    "__version__",
    "FireflyAgenticConfig",
    "get_config",
    "reset_config",
    "FireflyAgenticError",
    "FireflyMemoryError",
    "ConfigurationError",
    "AgentError",
    "AgentNotFoundError",
    "DelegationError",
    "ToolError",
    "ToolGuardError",
    "ToolNotFoundError",
    "ToolTimeoutError",
    "PromptError",
    "PromptNotFoundError",
    "PromptValidationError",
    "ReasoningError",
    "ReasoningStepLimitError",
    "ReasoningPatternNotFoundError",
    "ExperimentError",
    "ObservabilityError",
    "ExplainabilityError",
    "ExposureError",
    "QueueConnectionError",
    "ChunkingError",
    "CompressionError",
    "OutputReviewError",
    "OutputValidationError",
    "PipelineError",
    "QoSError",
    "QuotaError",
    "BudgetExceededError",
    "RateLimitError",
    "DatabaseStoreError",
    "DatabaseConnectionError",
    "EmbeddingError",
    "EmbeddingProviderError",
    "VectorStoreError",
    "VectorStoreConnectionError",
    "MemoryError",
    "AgentDepsT",
    "AgentLike",
    "OutputT",
    "ToolInputT",
    "ToolOutputT",
    "JSON",
    "Metadata",
    "Headers",
    "UserContent",
    "MultiModalContent",
    "UserPrompt",
    "ImageUrl",
    "AudioUrl",
    "DocumentUrl",
    "VideoUrl",
    "BinaryContent",
    "BaseEmbedder",
    "EmbedderRegistry",
    "EmbeddingProtocol",
    "BaseVectorStore",
    "InMemoryVectorStore",
    "VectorStoreProtocol",
    "PluginDiscovery",
    "configure_logging",
    "enable_debug",
]
