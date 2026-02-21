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

"""Agents subpackage -- creation, registration, lifecycle, and delegation."""

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.agents.builtin_middleware import (
    BudgetExceededError,
    CacheMiddleware,
    CostGuardMiddleware,
    ExplainabilityMiddleware,
    LoggingMiddleware,
    ObservabilityMiddleware,
    OutputGuardError,
    OutputGuardMiddleware,
    PromptGuardError,
    PromptGuardMiddleware,
    RetryMiddleware,
    ValidationMiddleware,
)
from fireflyframework_genai.agents.prompt_cache import CacheStatistics, PromptCacheMiddleware
from fireflyframework_genai.agents.cache import ResultCache
from fireflyframework_genai.agents.context import AgentContext
from fireflyframework_genai.agents.decorators import firefly_agent
from fireflyframework_genai.agents.delegation import (
    CapabilityStrategy,
    ContentBasedStrategy,
    CostAwareStrategy,
    DelegationRouter,
    DelegationStrategy,
    RoundRobinStrategy,
)
from fireflyframework_genai.agents.fallback import FallbackModelWrapper, run_with_fallback
from fireflyframework_genai.agents.lifecycle import AgentLifecycle, agent_lifecycle
from fireflyframework_genai.agents.middleware import (
    AgentMiddleware,
    MiddlewareChain,
    MiddlewareContext,
)
from fireflyframework_genai.agents.registry import AgentInfo, AgentRegistry, agent_registry
from fireflyframework_genai.agents.templates import (
    create_classifier_agent,
    create_conversational_agent,
    create_extractor_agent,
    create_router_agent,
    create_summarizer_agent,
)

__all__ = [
    "AgentContext",
    "AgentInfo",
    "AgentLifecycle",
    "agent_lifecycle",
    "AgentMiddleware",
    "AgentRegistry",
    "BudgetExceededError",
    "CacheMiddleware",
    "CacheStatistics",
    "CapabilityStrategy",
    "ContentBasedStrategy",
    "CostAwareStrategy",
    "CostGuardMiddleware",
    "DelegationRouter",
    "DelegationStrategy",
    "ExplainabilityMiddleware",
    "FallbackModelWrapper",
    "FireflyAgent",
    "LoggingMiddleware",
    "MiddlewareChain",
    "MiddlewareContext",
    "ObservabilityMiddleware",
    "OutputGuardError",
    "OutputGuardMiddleware",
    "PromptGuardError",
    "PromptCacheMiddleware",
    "PromptGuardMiddleware",
    "ResultCache",
    "RetryMiddleware",
    "RoundRobinStrategy",
    "ValidationMiddleware",
    "agent_registry",
    "create_classifier_agent",
    "create_conversational_agent",
    "create_extractor_agent",
    "create_router_agent",
    "create_summarizer_agent",
    "firefly_agent",
    "run_with_fallback",
]
