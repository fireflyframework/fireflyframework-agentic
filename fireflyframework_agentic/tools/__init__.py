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

"""Tools subpackage -- protocol, base class, registry, guards, composition, and built-ins.

Firefly tools layer guards, composition, caching and a capability registry on top
of pydantic-ai's tooling, while delegating JSON-schema generation and tool
invocation to pydantic-ai itself. For convenience this package also re-exports
pydantic-ai's native ``RunContext`` and toolset combinators so a ``ToolKit``'s
``as_toolset()`` output can be wrapped/filtered/combined without importing from
``pydantic_ai`` directly.
"""

# Native pydantic-ai surface, re-exported so callers compose toolsets, request
# human approval, and resume deferred runs in one import.
from pydantic_ai import (
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.exceptions import ApprovalRequired
from pydantic_ai.toolsets import (
    ApprovalRequiredToolset,
    CombinedToolset,
    FilteredToolset,
    FunctionToolset,
    PrefixedToolset,
    PreparedToolset,
    RenamedToolset,
    WrapperToolset,
)

from fireflyframework_agentic.tools.base import (
    BaseTool,
    GuardProtocol,
    GuardResult,
    ParameterSpec,
    ToolInfo,
    ToolProtocol,
)
from fireflyframework_agentic.tools.builder import ToolBuilder
from fireflyframework_agentic.tools.cached import CachedTool
from fireflyframework_agentic.tools.composer import (
    ConditionalComposer,
    FallbackComposer,
    SequentialComposer,
)
from fireflyframework_agentic.tools.decorators import firefly_tool, guarded, retryable
from fireflyframework_agentic.tools.guards import (
    CompositeGuard,
    RateLimitGuard,
    SandboxGuard,
    ValidationGuard,
)
from fireflyframework_agentic.tools.registry import ToolRegistry, tool_registry
from fireflyframework_agentic.tools.toolkit import ToolKit, to_pydantic_handler

__all__ = [
    "ApprovalRequired",
    "ApprovalRequiredToolset",
    "BaseTool",
    "CachedTool",
    "CombinedToolset",
    "CompositeGuard",
    "ConditionalComposer",
    "DeferredToolRequests",
    "DeferredToolResults",
    "FallbackComposer",
    "FilteredToolset",
    "FunctionToolset",
    "GuardProtocol",
    "GuardResult",
    "ParameterSpec",
    "PrefixedToolset",
    "PreparedToolset",
    "RateLimitGuard",
    "RenamedToolset",
    "RunContext",
    "SandboxGuard",
    "SequentialComposer",
    "ToolApproved",
    "ToolBuilder",
    "ToolDenied",
    "ToolInfo",
    "ToolKit",
    "ToolProtocol",
    "ToolRegistry",
    "ValidationGuard",
    "WrapperToolset",
    "firefly_tool",
    "guarded",
    "retryable",
    "to_pydantic_handler",
    "tool_registry",
]
