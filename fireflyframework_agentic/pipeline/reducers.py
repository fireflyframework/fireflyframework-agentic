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

"""State-merge reducers for typed pipeline state.

Reducers are functions ``(current, update) -> merged`` declared on a state
field via :class:`typing.Annotated`. The pipeline engine inspects
``typing.get_type_hints(state_schema, include_extras=True)`` for each field
and applies the relevant reducer when a node returns a partial state dict.

Fields without an annotated reducer use :func:`replace` (last-write-wins).

Example::

    class AgentState(BaseModel):
        messages: Annotated[list[str], append] = []
        intent: str | None = None  # uses replace by default
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, get_type_hints

from pydantic import BaseModel

logger = logging.getLogger(__name__)

Reducer = Callable[[Any, Any], Any]


def replace(current: Any, update: Any) -> Any:  # noqa: ARG001
    """Last-write-wins: the update value replaces the current value."""
    return update


def append(current: Any, update: Any) -> list[Any]:
    """Append a single item to a list. ``current`` is treated as ``[]`` if ``None``."""
    base = list(current) if current else []
    base.append(update)
    return base


def extend(current: Any, update: Any) -> list[Any]:
    """Concatenate two iterables. ``update`` must be iterable."""
    base = list(current) if current else []
    base.extend(update)
    return base


def merge_dict(current: Any, update: Any) -> dict[Any, Any]:
    """Shallow-merge two dicts; keys in ``update`` win."""
    base = dict(current) if current else {}
    base.update(update or {})
    return base


def discover_reducers(state_schema: type) -> dict[str, Reducer]:
    """Inspect ``Annotated[T, reducer_fn]`` annotations on the schema.

    Only ``Annotated[...]`` metadata is consulted — not generic origins like
    ``list[...]`` or unions. Fields without an annotated reducer are absent
    from the returned dict; callers should treat absence as :func:`replace`.
    """
    out: dict[str, Reducer] = {}
    try:
        hints = get_type_hints(state_schema, include_extras=True)
    except Exception:
        return out
    for field_name, hint in hints.items():
        metadata = getattr(hint, "__metadata__", None)
        if not metadata:
            continue
        for meta in metadata:
            if callable(meta):
                out[field_name] = meta
                break
    return out


def apply_update(state: BaseModel, update: dict[str, Any], reducers: dict[str, Reducer]) -> BaseModel:
    """Return a new state object with ``update`` merged into ``state`` via reducers.

    Keys present in ``update`` but missing from the schema are logged and
    ignored — incremental schema evolution stays painless.
    """
    if not update:
        return state
    new_values = state.model_dump()
    for key, value in update.items():
        if key not in new_values:
            logger.warning("State update key '%s' not in schema %s; ignored.", key, type(state).__name__)
            continue
        reducer = reducers.get(key, replace)
        new_values[key] = reducer(new_values[key], value)
    return type(state).model_validate(new_values)
