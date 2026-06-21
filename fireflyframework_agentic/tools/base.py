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

"""Tool abstraction layer: protocol, base class, and data models.

The tools system uses a three-layer extensibility model:

1. :class:`ToolProtocol` -- a ``typing.Protocol`` that any object can satisfy
   via duck typing.
2. :class:`BaseTool` -- an abstract base class that provides guard execution,
   validation, error handling, and logging out of the box.
3. Concrete implementations (built-in tools, user-defined subclasses).

Users who prefer composition can implement :class:`ToolProtocol` directly.
Users who prefer inheritance can subclass :class:`BaseTool` and override
:meth:`~BaseTool._execute`.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Annotated, Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from fireflyframework_agentic.exceptions import ToolError, ToolTimeoutError

logger = logging.getLogger(__name__)


def _is_model_retry(exc: BaseException) -> bool:
    """Return True when ``exc`` is a ``pydantic_ai.ModelRetry`` instance.

    ``ModelRetry`` is re-raised (not wrapped) so pydantic-ai's retry
    machinery sees it; every other exception is wrapped as ``ToolError``.
    """
    return isinstance(exc, ModelRetry)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ParameterSpec(BaseModel):
    """Describes a single parameter accepted by a tool.

    ``python_type`` is a **real** Python type object — ``str``, ``int``,
    ``list[str]``, ``Literal["a", "b"]``, a nested ``BaseModel``,
    ``dict[str, Any] | None``, … pydantic-ai introspects it directly, so the LLM
    receives a correct, full-fidelity JSON schema (nested models, enums and
    element types are all preserved).
    """

    name: str
    python_type: Any = str
    description: str = ""
    required: bool = True
    default: Any = None


class ToolInfo(BaseModel):
    """Lightweight, serialisable summary of a registered tool."""

    name: str
    description: str
    tags: list[str] = []
    parameter_count: int = 0


class GuardResult(BaseModel):
    """Outcome of a :class:`GuardProtocol` check.

    When *passed* is ``False``, *reason* explains why the guard rejected
    the execution.
    """

    passed: bool
    reason: str | None = None


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class ToolProtocol(Protocol):
    """Minimal contract that any tool must satisfy.

    Implement this protocol to create tools that integrate with the
    Firefly tool registry and composition system without inheriting from
    any framework class.
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool with the given keyword arguments."""
        ...


@runtime_checkable
class GuardProtocol(Protocol):
    """Pre-execution guard that can accept or reject a tool invocation."""

    async def check(self, tool_name: str, kwargs: dict[str, Any]) -> GuardResult:
        """Evaluate whether execution should proceed."""
        ...


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """Abstract base class for Firefly tools.

    Subclasses must implement :meth:`_execute`.  The public :meth:`execute`
    method wraps it with guard evaluation, logging, and error handling.

    Parameters:
        name: Unique tool name.
        description: Human-readable explanation of what the tool does.
        tags: Tags for capability-based discovery in the registry.
        guards: Ordered sequence of guards evaluated before execution.
        parameters: Declared parameter specifications (used by builder /
            schema generation).
        takes_ctx: When ``True``, the tool opts into receiving a pydantic-ai
            ``RunContext`` (agent deps, usage, retry count, messages). The
            generated handler injects it; ``_execute`` then receives it as the
            keyword-only ``_ctx``. Guards and caching never see ``ctx``.
    """

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        tags: Sequence[str] = (),
        guards: Sequence[GuardProtocol] = (),
        parameters: Sequence[ParameterSpec] = (),
        timeout: float | None = None,
        takes_ctx: bool = False,
    ) -> None:
        self._name = name
        self._description = description
        self._tags = list(tags)
        self._guards = list(guards)
        self._parameters = list(parameters)
        self._timeout = timeout
        self._takes_ctx = takes_ctx

    # -- Properties ----------------------------------------------------------

    @property
    def name(self) -> str:
        """Unique tool name."""
        return self._name

    @property
    def description(self) -> str:
        """Human-readable description."""
        return self._description

    @property
    def tags(self) -> list[str]:
        """Tags for capability-based discovery."""
        return self._tags

    @property
    def guards(self) -> list[GuardProtocol]:
        """Ordered guard chain evaluated before execution."""
        return self._guards

    @property
    def parameters(self) -> list[ParameterSpec]:
        """Declared parameter specifications."""
        return self._parameters

    @property
    def takes_ctx(self) -> bool:
        """Whether this tool opts into a pydantic-ai ``RunContext``."""
        return self._takes_ctx

    # -- Execution -----------------------------------------------------------

    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool after evaluating all guards.

        If any guard rejects, a :class:`ToolError` is raised immediately.
        When a *timeout* is configured, wraps the execution in
        :func:`asyncio.wait_for` and raises :class:`ToolTimeoutError`
        on expiry.
        """
        return await self._guarded_execute(kwargs, ctx=None)

    async def execute_with_ctx(self, ctx: Any, /, **kwargs: Any) -> Any:
        """Run the tool with a pydantic-ai ``RunContext`` delivered to ``_execute``.

        Used by the generated handler for ``takes_ctx`` tools. Guards and any
        caching see only the tool arguments — ``ctx`` is never guard-checked or
        hashed, so it cannot poison a cache key. When ``takes_ctx`` is ``False``
        the ``ctx`` is ignored and behaviour is identical to :meth:`execute`.
        """
        return await self._guarded_execute(kwargs, ctx=ctx)

    async def _guarded_execute(self, kwargs: dict[str, Any], *, ctx: Any) -> Any:
        for guard in self._guards:
            result = await guard.check(self._name, kwargs)
            if not result.passed:
                raise ToolError(f"Guard rejected execution of tool '{self._name}': {result.reason}")

        logger.debug("Executing tool '%s' with kwargs=%s", self._name, list(kwargs.keys()))
        # ``_ctx`` reaches ``_execute`` only for ctx-aware tools; it is never in
        # the guard-checked / cache-hashed ``kwargs``.
        exec_kwargs = {**kwargs, "_ctx": ctx} if self._takes_ctx else kwargs
        try:
            coro = self._execute(**exec_kwargs)
            if self._timeout is not None:
                return await asyncio.wait_for(coro, timeout=self._timeout)
            return await coro
        except TimeoutError:
            raise ToolTimeoutError(f"Tool '{self._name}' timed out after {self._timeout}s") from None
        except ToolError:
            raise
        except Exception as exc:
            # ``ModelRetry`` is Pydantic-AI's way of telling the agent
            # runtime "the tool didn't succeed; tell the model so it
            # can try again or report it to the user". Catching it as
            # a plain ``Exception`` and re-raising as ``ToolError``
            # hid that signal: pydantic-ai never saw the
            # ``RetryPromptPart`` it would otherwise emit, the LLM
            # never got a chance to react, and the entire
            # ``agent.run()`` turn crashed instead. Operators reported
            # "the agent says HTTP 401 but doesn't show the call in
            # the audit panel" -- because the call never reached the
            # model history at all. Letting it propagate untouched
            # restores the documented contract.
            if _is_model_retry(exc):
                raise
            raise ToolError(f"Tool '{self._name}' failed: {exc}") from exc

    def pydantic_handler(self) -> Any:
        """Return a callable suitable for :class:`pydantic_ai.Tool`.

        When :attr:`parameters` is non-empty, builds a wrapper whose
        signature mirrors the declared :class:`ParameterSpec` entries so
        that Pydantic AI can generate a correct JSON schema for the LLM.

        Subclasses that wrap a typed handler (e.g. decorated tools) may
        override this to return a wrapper preserving the original
        function's signature instead.
        """
        # A ctx-aware tool always needs the generated handler so the
        # ``RunContext``-first parameter is present even with no declared params.
        if not self._parameters and not self._takes_ctx:
            return self.execute

        return _build_typed_handler(self)

    @abstractmethod
    async def _execute(self, **kwargs: Any) -> Any:
        """Subclass hook -- implement the actual tool logic here."""
        ...

    # -- Info ----------------------------------------------------------------

    def info(self) -> ToolInfo:
        """Return a serialisable summary of this tool."""
        return ToolInfo(
            name=self._name,
            description=self._description,
            tags=self._tags,
            parameter_count=len(self._parameters),
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self._name!r})"


# ---------------------------------------------------------------------------
# Typed handler builder
# ---------------------------------------------------------------------------


def _build_typed_handler(tool: BaseTool) -> Any:
    """Create a wrapper with a proper signature from *tool.parameters*.

    Pydantic AI introspects the handler's signature to build a JSON schema
    for the LLM.  The default ``execute(**kwargs)`` gives an empty schema.
    This helper constructs a wrapper whose ``inspect.Signature`` and
    ``__annotations__`` reflect the declared :class:`ParameterSpec` entries,
    so the LLM receives correct parameter names, types, and descriptions.

    Each parameter's type is ``ParameterSpec.python_type`` — a real type object,
    so nested models, enums and element types reach the schema intact. When
    ``tool.takes_ctx`` is set, a ``RunContext``-first parameter is prepended —
    annotated with the **bare** ``RunContext`` form pydantic-ai detects (not
    ``Annotated`` / not ``| None``) — and the handler delegates to
    :meth:`BaseTool.execute_with_ctx`, which keeps ``ctx`` out of guards/cache.
    """
    params: list[inspect.Parameter] = []
    annotations: dict[str, Any] = {}
    takes_ctx = getattr(tool, "takes_ctx", False)

    if takes_ctx:
        # Bare ``RunContext[Any]`` so pydantic-ai detects it and injects it
        # positionally; it is excluded from the tool's JSON schema.
        ctx_type = RunContext[Any]
        params.append(inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=ctx_type))
        annotations["ctx"] = ctx_type

    for spec in tool.parameters:
        annotated_type = Annotated[spec.python_type, Field(description=spec.description)]  # type: ignore[valid-type]

        if spec.required:
            param = inspect.Parameter(
                spec.name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=annotated_type,
            )
        else:
            param = inspect.Parameter(
                spec.name,
                inspect.Parameter.KEYWORD_ONLY,
                default=spec.default,
                annotation=annotated_type,
            )
        params.append(param)
        annotations[spec.name] = annotated_type

    sig = inspect.Signature(params)

    if takes_ctx:

        async def _ctx_handler(ctx: Any, **kwargs: Any) -> Any:
            return await tool.execute_with_ctx(ctx, **kwargs)

        handler: Any = _ctx_handler
    else:

        async def _plain_handler(**kwargs: Any) -> Any:
            return await tool.execute(**kwargs)

        handler = _plain_handler

    handler.__signature__ = sig  # type: ignore[attr-defined]
    handler.__annotations__ = annotations
    handler.__name__ = tool.name
    handler.__qualname__ = tool.name
    handler.__doc__ = tool.description
    return handler
