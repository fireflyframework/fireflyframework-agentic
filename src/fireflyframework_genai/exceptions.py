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

"""Exception hierarchy for the Firefly GenAI framework.

Every module raises exceptions from this hierarchy so that callers can catch
at the granularity they need -- from the broad :class:`FireflyGenAIError`
base to specific leaf exceptions like :class:`ToolGuardError`.
"""

from __future__ import annotations


class FireflyGenAIError(Exception):
    """Base exception for all errors raised by the Firefly GenAI framework."""


# -- Configuration -----------------------------------------------------------


class ConfigurationError(FireflyGenAIError):
    """Raised when the framework configuration is invalid or missing."""


# -- Agents ------------------------------------------------------------------


class AgentError(FireflyGenAIError):
    """Raised for errors during agent creation, registration, or execution."""


class AgentNotFoundError(AgentError):
    """Raised when a requested agent cannot be found in the registry."""


class DelegationError(AgentError):
    """Raised when multi-agent delegation fails."""


# -- Tools -------------------------------------------------------------------


class ToolError(FireflyGenAIError):
    """Raised for errors during tool execution."""


class ToolGuardError(ToolError):
    """Raised when a tool guard rejects execution (e.g. validation, rate-limit, approval)."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool cannot be found in the registry."""


class ToolTimeoutError(ToolError):
    """Raised when a tool execution exceeds the configured timeout."""


# -- Prompts -----------------------------------------------------------------


class PromptError(FireflyGenAIError):
    """Raised for errors in prompt template rendering, validation, or loading."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt template cannot be found in the registry."""


class PromptValidationError(PromptError):
    """Raised when a prompt fails validation (e.g. missing variables, token limit exceeded)."""


# -- Reasoning ---------------------------------------------------------------


class ReasoningError(FireflyGenAIError):
    """Raised for errors during reasoning pattern execution."""


class ReasoningStepLimitError(ReasoningError):
    """Raised when a reasoning pattern exceeds its maximum step count."""


class ReasoningPatternNotFoundError(ReasoningError):
    """Raised when a requested reasoning pattern cannot be found in the registry."""


# -- Experiments -------------------------------------------------------------


class ExperimentError(FireflyGenAIError):
    """Raised for errors during experiment definition, execution, or tracking."""


# -- Observability -----------------------------------------------------------


class ObservabilityError(FireflyGenAIError):
    """Raised for errors in tracing, metrics, or event emission."""


# -- Explainability ----------------------------------------------------------


class ExplainabilityError(FireflyGenAIError):
    """Raised for errors in trace recording, explanation generation, or audit."""


# -- Exposure ----------------------------------------------------------------


class ExposureError(FireflyGenAIError):
    """Raised for errors in REST API or queue-based agent exposure."""


class QueueConnectionError(ExposureError):
    """Raised when a queue backend connection fails."""


# -- Content processing ------------------------------------------------------


class ChunkingError(FireflyGenAIError):
    """Raised for errors during document chunking or splitting."""


class CompressionError(FireflyGenAIError):
    """Raised for errors during context compression."""


# -- Validation --------------------------------------------------------------


class OutputValidationError(FireflyGenAIError):
    """Raised when structured output validation fails."""


class QoSError(FireflyGenAIError):
    """Raised when output quality falls below QoS thresholds."""


class OutputReviewError(FireflyGenAIError):
    """Raised when the output reviewer exhausts all retry attempts without producing valid output."""


# -- Pipeline ----------------------------------------------------------------


class PipelineError(FireflyGenAIError):
    """Raised for errors during pipeline construction or execution."""


# -- Memory ------------------------------------------------------------------


class FireflyMemoryError(FireflyGenAIError):
    """Raised for errors during memory storage, retrieval, or management."""


# Deprecated alias for backwards compatibility
MemoryError = FireflyMemoryError


class DatabaseStoreError(FireflyMemoryError):
    """Raised for errors in database-backed memory store operations."""


class DatabaseConnectionError(DatabaseStoreError):
    """Raised when a database connection cannot be established or is lost."""


# -- Quota & Rate Limiting ---------------------------------------------------


class QuotaError(FireflyGenAIError):
    """Base exception for quota and rate limit errors."""


class BudgetExceededError(QuotaError):
    """Raised when the daily budget limit is exceeded."""


class RateLimitError(QuotaError):
    """Raised when a rate limit is exceeded."""


# -- Embeddings --------------------------------------------------------


class EmbeddingError(FireflyGenAIError):
    """Raised for errors during embedding generation."""


class EmbeddingProviderError(EmbeddingError):
    """Raised when an embedding provider API call fails."""


# -- Vector Stores -----------------------------------------------------


class VectorStoreError(FireflyGenAIError):
    """Raised for errors during vector store operations."""


class VectorStoreConnectionError(VectorStoreError):
    """Raised when a vector store backend connection fails."""
