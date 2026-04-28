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

"""Built-in web search tool abstraction.

:class:`SearchTool` defines the interface for web-search integrations.
Users must subclass and provide a concrete :meth:`_search` implementation
that calls their preferred search API (Tavily, SerpAPI, Brave, etc.).
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.tools.base import BaseTool, GuardProtocol, ParameterSpec


class SearchResult(BaseModel):
    """A single result returned by a search query."""

    title: str
    url: str
    snippet: str


class SearchTool(BaseTool):
    """Abstract search tool that users extend with their preferred search backend.

    Subclasses must implement :meth:`_search`.

    Parameters:
        max_results: Maximum number of results to return per query.
        guards: Optional guard chain.
    """

    def __init__(
        self,
        *,
        max_results: int = 5,
        guards: Sequence[GuardProtocol] = (),
    ) -> None:
        super().__init__(
            "search",
            description="Search the web for information",
            tags=["search", "web"],
            guards=guards,
            parameters=[
                ParameterSpec(name="query", type_annotation="str", description="Search query", required=True),
            ],
        )
        self._max_results = max_results

    async def _execute(self, **kwargs: Any) -> list[dict[str, str]]:
        query: str = kwargs["query"]
        results = await self._search(query, self._max_results)
        return [r.model_dump() for r in results]

    @abstractmethod
    async def _search(self, query: str, max_results: int) -> list[SearchResult]:
        """Implement the actual search API call.

        Parameters:
            query: The search query string.
            max_results: Maximum number of results to return.

        Returns:
            A list of :class:`SearchResult` instances.
        """
        ...
