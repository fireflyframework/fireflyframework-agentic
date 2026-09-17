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
from pydantic_ai.exceptions import ApprovalRequired, CallDeferred

from fireflyframework_agentic.exceptions import ToolError, ToolGuardError, ToolTimeoutError

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


@runtime_checkable
class ToolCallListener(Protocol):
    """Sees every call a :class:`BaseTool` makes — begin, end, failure, pause.

    The one public seam around ``_execute``. Before this protocol existed the only path every
    call took (guards, timeout, error wrapping) was the private ``_guarded_execute``, so a host
    that needed a record of each call as it happened — a per-turn ledger, an audit trail, a
    metering row, a trace — subclassed a private method and broke on every refactor. A listener
    is registered per tool (``listeners=`` at construction or :meth:`BaseTool.add_listener`) and
    receives, in order:

    * ``before_call`` once the earlier listeners (the guard chain first) have let the call
      through; raising here refuses the call — a ``ModelRetry`` tells the model why, anything
      else becomes a ``ToolError`` — and later listeners never see ``before_call`` for it;
    * exactly one of ``after_call`` (with the result the caller receives), ``on_error`` (with
      the exception the caller receives: ``ToolError``, ``ToolTimeoutError``, ``ToolGuardError``
      or ``ModelRetry``) or ``on_pause`` (with the human-in-the-loop signal, ``ApprovalRequired``
      or ``CallDeferred``: the call is waiting on a person, it has neither succeeded nor failed).

    Every method is optional: a listener defines the hooks it needs. ``kwargs`` are the tool's
    arguments, never ``ctx``. ``ctx`` is the same object the tool receives: the pydantic-ai
    ``RunContext`` when the call came through an agent AND the tool opted in with
    ``takes_ctx=True`` (read ``ctx.tool_call_id`` to correlate the call with the model's
    history), ``None`` otherwise — a tool that did not opt in is never handed the context, by
    the tool contract, and its listeners are not either.
    """

    async def before_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any) -> None:
        """The call is about to run. Raise to refuse it."""
        ...

    async def after_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, result: Any) -> None:
        """The call returned ``result``."""
        ...

    async def on_error(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, exc: BaseException) -> None:
        """The call failed with ``exc`` — the exception the caller will receive."""
        ...

    async def on_pause(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any, signal: BaseException) -> None:
        """The call paused for a person (``ApprovalRequired`` / ``CallDeferred``)."""
        ...


class GuardChainListener:
    """The tool's guard chain, run as the FIRST listener's ``before_call``.

    Guards used to be evaluated by a private loop ahead of the listeners' seam; running them as
    a listener means there is one order every observer can reason about — guards refuse first,
    then each listener's ``before_call`` in registration order — and a refused call reaches
    every listener's ``on_error`` with the ``ToolGuardError`` the caller sees. The listener
    holds the tool's own guard list (not a copy) so ``tool.guards.append(...)`` after
    construction, which the decorators do, still counts.
    """

    def __init__(self, guards: list[GuardProtocol]) -> None:
        self._guards = guards

    @property
    def guards(self) -> list[GuardProtocol]:
        """The live guard list this listener evaluates."""
        return self._guards

    async def before_call(self, tool: BaseTool, kwargs: dict[str, Any], ctx: Any) -> None:
        for guard in self._guards:
            result = await guard.check(tool.name, kwargs)
            if not result.passed:
                raise ToolGuardError(f"Guard rejected execution of tool '{tool.name}': {result.reason}")


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
        requires_approval: When ``True``, the tool is exposed to pydantic-ai as
            an approval-required tool. The agent run pauses before this tool
            executes and surfaces a ``DeferredToolRequests`` for human
            sign-off (resolved natively via ``DeferredToolResults``); the tool
            body runs only once the call is approved. See the agent's
            human-in-the-loop docs. Change it after construction with
            :meth:`require_approval`.
        defers: Declare that this tool may raise ``CallDeferred`` from its body
            (a call the run must pause on and a host completes out of band).
            :class:`~fireflyframework_agentic.agents.base.FireflyAgent` widens
            its output type for a deferring tool exactly as it does for an
            approval-required one, so the pause is planned rather than a
            ``UserError`` from pydantic-ai at the first deferral.
        listeners: :class:`ToolCallListener` objects that see every call
            (after the guard chain, which is always the first listener).
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
        requires_approval: bool = False,
        defers: bool = False,
        listeners: Sequence[ToolCallListener] = (),
    ) -> None:
        self._name = name
        self._description = description
        self._tags = list(tags)
        self._guards = list(guards)
        self._parameters = list(parameters)
        self._timeout = timeout
        self._takes_ctx = takes_ctx
        self._requires_approval = requires_approval
        self._defers = defers
        # The guard chain is the first listener, always: refusing a call is the first thing
        # that can happen to it, and everything that watches calls sees the refusal.
        self._listeners: list[Any] = [GuardChainListener(self._guards), *listeners]

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

    @property
    def requires_approval(self) -> bool:
        """Whether calls to this tool require human-in-the-loop approval."""
        return self._requires_approval

    def require_approval(self, flag: bool = True) -> bool:
        """Set :attr:`requires_approval` after construction; returns whether it changed.

        The supported door for a host that learns which tools must stop for a person only
        once the whole surface is built — a policy that names tools, a room rule, a plan — and
        would otherwise have to rebuild every tool or reach for the private attribute. The flag
        must be final before the tool is handed to a :class:`FireflyAgent`, which copies it
        into the native ``pydantic_ai.Tool`` at construction.
        """
        if self._requires_approval == flag:
            return False
        self._requires_approval = flag
        return True

    @property
    def defers(self) -> bool:
        """Whether this tool declares that it may raise ``CallDeferred``."""
        return self._defers

    @property
    def listeners(self) -> list[Any]:
        """The call listeners, guard chain first."""
        return self._listeners

    def add_listener(self, listener: ToolCallListener) -> None:
        """Append a :class:`ToolCallListener`; adding the same object twice is a no-op."""
        if any(existing is listener for existing in self._listeners):
            return
        self._listeners.append(listener)

    # -- Execution -----------------------------------------------------------

    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool after evaluating all guards.

        If any guard rejects, a :class:`ToolGuardError` (a ``ToolError``
        subclass) is raised immediately.
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
        """The one path every call takes: listeners (guards first), timeout, error wrapping.

        Kept private on purpose — :class:`ToolCallListener` is the extension point. A subclass
        that overrides this bypasses every listener the host registered, silently.
        """
        try:
            await self._notify_before(kwargs, ctx)
        except (ApprovalRequired, CallDeferred) as signal:
            await self._notify("on_pause", kwargs, ctx, signal)
            raise
        except BaseException as exc:
            failure = (
                exc
                if isinstance(exc, ToolError) or _is_model_retry(exc)
                else ToolError(f"Tool '{self._name}' refused: {exc}")
            )
            if failure is not exc:
                failure.__cause__ = exc
            await self._notify("on_error", kwargs, ctx, failure)
            raise failure from (None if failure is exc else exc)

        logger.debug("Executing tool '%s' with kwargs=%s", self._name, list(kwargs.keys()))
        # ``_ctx`` reaches ``_execute`` only for ctx-aware tools; it is never in
        # the guard-checked / cache-hashed ``kwargs``.
        exec_kwargs = {**kwargs, "_ctx": ctx} if self._takes_ctx else kwargs
        try:
            coro = self._execute(**exec_kwargs)
            if self._timeout is not None:
                result = await asyncio.wait_for(coro, timeout=self._timeout)
            else:
                result = await coro
        except TimeoutError:
            failure = ToolTimeoutError(f"Tool '{self._name}' timed out after {self._timeout}s")
            await self._notify("on_error", kwargs, ctx, failure)
            raise failure from None
        except (ApprovalRequired, CallDeferred) as signal:
            # pydantic-ai human-in-the-loop / deferral control signals. Like
            # ``ModelRetry`` these are NOT errors: they must reach the agent graph
            # untouched so the run pauses and surfaces a ``DeferredToolRequests``.
            # Wrapping them as ``ToolError`` would break dynamic tool approval.
            await self._notify("on_pause", kwargs, ctx, signal)
            raise
        except ToolError as exc:
            await self._notify("on_error", kwargs, ctx, exc)
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
                await self._notify("on_error", kwargs, ctx, exc)
                raise
            failure = ToolError(f"Tool '{self._name}' failed: {exc}")
            failure.__cause__ = exc
            await self._notify("on_error", kwargs, ctx, failure)
            raise failure from exc

        try:
            await self._notify("after_call", kwargs, ctx, result)
        except Exception as exc:
            # A listener that cannot record the outcome is a failed call, not a successful one
            # with a hole in the record: a ledger that silently missed a row is worse than a
            # turn that failed loudly, and every listener before it already heard ``after_call``.
            raise ToolError(f"Tool '{self._name}' succeeded but a call listener failed: {exc}") from exc
        return result

    async def _notify_before(self, kwargs: dict[str, Any], ctx: Any) -> None:
        for listener in self._listeners:
            hook = getattr(listener, "before_call", None)
            if hook is not None:
                await hook(self, kwargs, ctx)

    async def _notify(self, event: str, kwargs: dict[str, Any], ctx: Any, payload: Any) -> None:
        for listener in self._listeners:
            hook = getattr(listener, event, None)
            if hook is not None:
                await hook(self, kwargs, ctx, payload)

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
