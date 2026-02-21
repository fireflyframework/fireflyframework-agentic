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

"""Firefly GenAI Framework -- A metaframework built on Pydantic AI.

This package provides production-grade abstractions for building GenAI
applications including agents, reasoning patterns, prompt engineering,
tools, observability, explainability, experimentation, and exposure
via REST APIs and message queues.

Quick start::

    from fireflyframework_genai import FireflyGenAIConfig, get_config

    config = get_config()
    print(config.default_model)
"""

from fireflyframework_genai._version import __version__
from fireflyframework_genai.config import FireflyGenAIConfig, get_config, reset_config
from fireflyframework_genai.exceptions import (
    AgentError,
    AgentNotFoundError,
    BudgetExceededError,
    ChunkingError,
    CompressionError,
    ConfigurationError,
    DatabaseConnectionError,
    DatabaseStoreError,
    DelegationError,
    ExperimentError,
    ExplainabilityError,
    ExposureError,
    FireflyGenAIError,
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
)
from fireflyframework_genai.logging import configure_logging, enable_debug
from fireflyframework_genai.plugin import PluginDiscovery
from fireflyframework_genai.types import (
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

__all__ = [
    "__version__",
    "FireflyGenAIConfig",
    "get_config",
    "reset_config",
    "FireflyGenAIError",
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
    "PluginDiscovery",
    "configure_logging",
    "enable_debug",
]
