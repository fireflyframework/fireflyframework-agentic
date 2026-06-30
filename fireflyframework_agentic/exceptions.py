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

"""Exception hierarchy for the Firefly Agentic framework.

Every module raises exceptions from this hierarchy so that callers can catch
at the granularity they need -- from the broad :class:`FireflyAgenticError`
base to specific leaf exceptions like :class:`ToolGuardError`.
"""

from __future__ import annotations


class FireflyAgenticError(Exception):
    """Base exception for all errors raised by the Firefly Agentic framework."""


# -- Configuration -----------------------------------------------------------


class ConfigurationError(FireflyAgenticError):
    """Raised when the framework configuration is invalid or missing."""


# -- Agents ------------------------------------------------------------------


class AgentError(FireflyAgenticError):
    """Raised for errors during agent creation, registration, or execution."""


class AgentNotFoundError(AgentError):
    """Raised when a requested agent cannot be found in the registry."""


class DelegationError(AgentError):
    """Raised when multi-agent delegation fails."""


# -- Tools -------------------------------------------------------------------


class ToolError(FireflyAgenticError):
    """Raised for errors during tool execution."""


class ToolGuardError(ToolError):
    """Raised when a tool guard rejects execution (e.g. validation, rate-limit, approval)."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool cannot be found in the registry."""


class ToolTimeoutError(ToolError):
    """Raised when a tool execution exceeds the configured timeout."""


# -- Prompts -----------------------------------------------------------------


class PromptError(FireflyAgenticError):
    """Raised for errors in prompt template rendering, validation, or loading."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt template cannot be found in the registry."""


class PromptValidationError(PromptError):
    """Raised when a prompt fails validation (e.g. missing variables, token limit exceeded)."""


# -- Reasoning ---------------------------------------------------------------


class ReasoningError(FireflyAgenticError):
    """Raised for errors during reasoning pattern execution."""


class ReasoningStepLimitError(ReasoningError):
    """Raised when a reasoning pattern exceeds its maximum step count."""


class ReasoningPatternNotFoundError(ReasoningError):
    """Raised when a requested reasoning pattern cannot be found in the registry."""


# -- Experiments -------------------------------------------------------------


class ExperimentError(FireflyAgenticError):
    """Raised for errors during experiment definition, execution, or tracking."""


# -- Observability -----------------------------------------------------------


class ObservabilityError(FireflyAgenticError):
    """Raised for errors in tracing, metrics, or event emission."""


# -- Explainability ----------------------------------------------------------


class ExplainabilityError(FireflyAgenticError):
    """Raised for errors in trace recording, explanation generation, or audit."""


# -- Content processing ------------------------------------------------------


class ChunkingError(FireflyAgenticError):
    """Raised for errors during document chunking or splitting."""


class CompressionError(FireflyAgenticError):
    """Raised for errors during context compression."""


# -- Validation --------------------------------------------------------------


class OutputValidationError(FireflyAgenticError):
    """Raised when structured output validation fails."""


class QoSError(FireflyAgenticError):
    """Raised when output quality falls below QoS thresholds."""


class OutputReviewError(FireflyAgenticError):
    """Raised when the output reviewer exhausts all retry attempts without producing valid output."""


# -- Pipeline ----------------------------------------------------------------


class PipelineError(FireflyAgenticError):
    """Raised for errors during pipeline construction or execution."""


# -- Memory ------------------------------------------------------------------


class FireflyMemoryError(FireflyAgenticError):
    """Raised for errors during memory storage, retrieval, or management."""


# Deprecated alias for backwards compatibility
MemoryError = FireflyMemoryError


class DatabaseStoreError(FireflyMemoryError):
    """Raised for errors in database-backed memory store operations."""


class DatabaseConnectionError(DatabaseStoreError):
    """Raised when a database connection cannot be established or is lost."""


# -- Quota & Rate Limiting ---------------------------------------------------


class QuotaError(FireflyAgenticError):
    """Base exception for quota and rate limit errors."""


class BudgetExceededError(QuotaError):
    """Raised when a budget rule is exceeded.

    Carries structured fields populated by
    :class:`~fireflyframework_agentic.observability.budget.BudgetGate`.
    """

    rule_name: str
    spend_usd: float
    limit_usd: float

    def __init__(
        self,
        msg: str = "",
        *,
        rule_name: str = "",
        spend_usd: float = 0.0,
        limit_usd: float = 0.0,
    ) -> None:
        super().__init__(msg)
        self.rule_name = rule_name
        self.spend_usd = spend_usd
        self.limit_usd = limit_usd


class RateLimitError(QuotaError):
    """Raised when a rate limit is exceeded."""


# -- Embeddings --------------------------------------------------------


class EmbeddingError(FireflyAgenticError):
    """Raised for errors during embedding generation."""


class EmbeddingProviderError(EmbeddingError):
    """Raised when an embedding provider API call fails."""


# -- Vector Stores -----------------------------------------------------


class VectorStoreError(FireflyAgenticError):
    """Raised for errors during vector store operations."""


class VectorStoreConnectionError(VectorStoreError):
    """Raised when a vector store backend connection fails."""


# -- Workflows ---------------------------------------------------------------


class WorkflowError(FireflyAgenticError):
    """Base exception for the dynamic-workflow orchestration engine."""


class WorkflowNotFoundError(WorkflowError):
    """Raised when no workflow is registered under the requested name."""


class WorkflowBudgetError(WorkflowError):
    """Raised when a workflow exceeds its agent-count or token budget."""


class WorkflowContextError(WorkflowError):
    """Raised when a workflow primitive runs outside an active workflow context."""


class WorkflowInterrupt(WorkflowError):  # noqa: N818 - a control-flow signal, not an error
    """Raised by ``human()`` to pause a run for external input.

    Catch it, call :meth:`provide` with the human's answer, then re-run the
    workflow with the same ``journal`` to resume from where it paused.
    """

    def __init__(self, prompt: str, *, seq: int, journal: object) -> None:
        super().__init__(f"workflow paused for human input: {prompt[:120]}")
        self.prompt = prompt
        self.seq = seq
        self._journal = journal

    def provide(self, answer: object) -> None:
        """Record the human's answer so the next run resumes past the pause."""
        self._journal.record(self.seq, answer)  # type: ignore[attr-defined]


# -- Secure script execution -------------------------------------------------


class ExecutionError(FireflyAgenticError):
    """Base exception for the secure script-execution subsystem."""


class CodeSafetyError(ExecutionError):
    """Raised when generated/guest code fails the static safety pre-screen."""


class SandboxUnavailableError(ExecutionError):
    """Raised when a sandbox backend's dependency is not installed."""
