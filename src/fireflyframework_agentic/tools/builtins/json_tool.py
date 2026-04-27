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

"""Built-in JSON processing tool.

Provides parse, validate, extract (dot-path), and format operations so
that agents can work with JSON data without custom tools.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec


class JsonTool(BaseTool):
    """Parse, validate, extract fields, and format JSON data.

    Supported actions:

    * ``"parse"`` -- parse a JSON string into a Python object.
    * ``"validate"`` -- check whether a string is valid JSON.
    * ``"extract"`` -- extract a value at a dot-separated path
      (e.g. ``"address.city"``).
    * ``"format"`` -- pretty-print a JSON string.
    * ``"keys"`` -- list top-level keys of a JSON object.

    Parameters:
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "json",
            description="Parse, validate, extract fields from, and format JSON data",
            tags=["json", "utility"],
            guards=guards,
            parameters=[
                ParameterSpec(
                    name="action",
                    type_annotation="str",
                    description="One of: parse, validate, extract, format, keys",
                    required=True,
                ),
                ParameterSpec(
                    name="data",
                    type_annotation="str",
                    description="JSON string to operate on",
                    required=True,
                ),
                ParameterSpec(
                    name="path",
                    type_annotation="str | None",
                    description="Dot-separated path for extract action (e.g. 'address.city')",
                    required=False,
                    default=None,
                ),
            ],
        )

    async def _execute(self, **kwargs: Any) -> Any:
        action: str = kwargs["action"]
        data: str = kwargs["data"]

        if action == "validate":
            return self._validate(data)
        if action == "parse":
            return self._parse(data)
        if action == "extract":
            path: str | None = kwargs.get("path")
            if not path:
                raise ValueError("'path' is required for the extract action")
            return self._extract(data, path)
        if action == "format":
            return self._format(data)
        if action == "keys":
            return self._keys(data)

        raise ValueError(f"Unknown action '{action}'; expected parse, validate, extract, format, or keys")

    @staticmethod
    def _validate(data: str) -> dict[str, Any]:
        """Return validation result."""
        try:
            json.loads(data)
            return {"valid": True}
        except json.JSONDecodeError as exc:
            return {"valid": False, "error": str(exc)}

    @staticmethod
    def _parse(data: str) -> Any:
        """Parse JSON string into a Python object."""
        return json.loads(data)

    @staticmethod
    def _extract(data: str, path: str) -> Any:
        """Extract a value at a dot-separated path."""
        obj = json.loads(data)
        for key in path.split("."):
            if isinstance(obj, dict):
                if key not in obj:
                    raise KeyError(f"Key '{key}' not found at path '{path}'")
                obj = obj[key]
            elif isinstance(obj, list):
                try:
                    obj = obj[int(key)]
                except (ValueError, IndexError) as exc:
                    raise KeyError(f"Invalid list index '{key}' at path '{path}'") from exc
            else:
                raise KeyError(f"Cannot traverse into {type(obj).__name__} at key '{key}'")
        return obj

    @staticmethod
    def _format(data: str) -> str:
        """Pretty-print JSON."""
        return json.dumps(json.loads(data), indent=2, ensure_ascii=False)

    @staticmethod
    def _keys(data: str) -> list[str]:
        """Return top-level keys of a JSON object."""
        obj = json.loads(data)
        if not isinstance(obj, dict):
            raise TypeError(f"Expected a JSON object, got {type(obj).__name__}")
        return list(obj.keys())
