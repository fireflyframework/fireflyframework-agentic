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

"""SP-1 regression: nullable/generic tool parameter schema resolution.

Previously any ``type_annotation`` not in ``_TYPE_MAP`` (including every
``... | None`` and generic ``dict[...]`` form) fell back to ``str``, producing
incorrect non-nullable JSON schemas for the LLM.
"""

from __future__ import annotations

import typing

from fireflyframework_agentic.tools.base import (
    BaseTool,
    ParameterSpec,
    _build_typed_handler,
    _resolve_param_type,
)


class TestResolveParamType:
    def test_plain_scalar(self):
        assert _resolve_param_type("str") is str
        assert _resolve_param_type("int") is int
        assert _resolve_param_type("bool") is bool

    def test_optional_pipe_form(self):
        assert _resolve_param_type("str | None") == (str | None)

    def test_optional_bracket_form(self):
        assert _resolve_param_type("Optional[int]") == (int | None)

    def test_generic_subscript_stripped(self):
        assert _resolve_param_type("list[str]") is list
        assert _resolve_param_type("dict[str, Any]") is dict

    def test_optional_generic(self):
        # The reported bug: HttpTool.body / DatabaseTool.params were "dict | None".
        assert _resolve_param_type("dict[str, Any] | None") == (dict | None)

    def test_unknown_falls_back_to_any_not_str(self):
        assert _resolve_param_type("SomeCustomType") is typing.Any


class _ParamTool(BaseTool):
    async def _execute(self, **kwargs: object) -> object:
        return kwargs


class TestBuildTypedHandlerNullable:
    def test_optional_param_annotation_is_nullable(self):
        tool = _ParamTool(
            "demo",
            parameters=[
                ParameterSpec(
                    name="body",
                    type_annotation="dict[str, Any] | None",
                    required=False,
                    default=None,
                ),
            ],
        )
        handler = _build_typed_handler(tool)
        annotated = handler.__annotations__["body"]
        # Annotated[dict | None, Field(...)] — first arg is the resolved type.
        assert typing.get_args(annotated)[0] == (dict | None)

    def test_required_scalar_unchanged(self):
        tool = _ParamTool(
            "demo2",
            parameters=[ParameterSpec(name="q", type_annotation="str", required=True)],
        )
        handler = _build_typed_handler(tool)
        annotated = handler.__annotations__["q"]
        assert typing.get_args(annotated)[0] is str
