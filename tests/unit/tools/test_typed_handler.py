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

"""Typed tool-parameter handler: a real ``python_type`` reaches the schema intact.

``ParameterSpec.python_type`` is a real type object, so nullable/generic/nested
forms flow straight into the generated handler's annotations — there is no lossy
string resolution step. (Supersedes the old SP-1 ``_resolve_param_type`` test:
``dict[str, Any] | None`` used to collapse to a non-nullable ``str``.)
"""

from __future__ import annotations

import typing
from typing import Any

from fireflyframework_agentic.tools.base import BaseTool, ParameterSpec, _build_typed_handler


class _ParamTool(BaseTool):
    async def _execute(self, **kwargs: object) -> object:
        return kwargs


def test_optional_generic_is_preserved():
    # The historical bug: HttpTool.body / DatabaseTool.params were dict | None.
    tool = _ParamTool(
        "demo",
        parameters=[ParameterSpec(name="body", python_type=dict[str, Any] | None, required=False, default=None)],
    )
    handler = _build_typed_handler(tool)
    annotated = handler.__annotations__["body"]
    # Annotated[dict[str, Any] | None, Field(...)] — first arg is the real type.
    assert typing.get_args(annotated)[0] == (dict[str, Any] | None)


def test_required_scalar_preserved():
    tool = _ParamTool("demo2", parameters=[ParameterSpec(name="q", python_type=str, required=True)])
    handler = _build_typed_handler(tool)
    assert typing.get_args(handler.__annotations__["q"])[0] is str


def test_no_parameters_returns_plain_execute():
    tool = _ParamTool("demo3")
    # No declared params and no ctx -> the plain execute, not a synthesized wrapper.
    assert tool.pydantic_handler() == tool.execute
