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

"""Provider-aware reasoning-token pricing.

Only Gemini's ``thoughts_tokens`` are excluded from ``output_tokens`` and must
be priced separately. OpenAI's ``reasoning_tokens`` are already in
``output_tokens`` (adding them double-counts) and Anthropic folds thinking into
``output_tokens``. ``reasoning_tokens_not_in_output`` reads the Gemini-specific
key so every other provider contributes 0.
"""

from __future__ import annotations

from typing import Any

from fireflyframework_agentic.observability.cost_resolvers import CostContext, resolve_cost
from fireflyframework_agentic.observability.usage import reasoning_tokens_not_in_output


class _Usage:
    def __init__(self, details: dict[str, Any]) -> None:
        self.details = details


def test_helper_counts_only_gemini_thoughts():
    assert reasoning_tokens_not_in_output(_Usage({"thoughts_tokens": 1000})) == 1000
    # OpenAI's reasoning is already in output_tokens — must NOT be re-counted.
    assert reasoning_tokens_not_in_output(_Usage({"reasoning_tokens": 400})) == 0
    # Anthropic reports no reasoning detail key.
    assert reasoning_tokens_not_in_output(_Usage({})) == 0
    assert reasoning_tokens_not_in_output(object()) == 0  # no details attr at all


def test_gemini_thinking_raises_cost():
    base = resolve_cost(CostContext("google:gemini-2.5-pro", input_tokens=100, output_tokens=200, reasoning_tokens=0))
    with_thoughts = resolve_cost(
        CostContext("google:gemini-2.5-pro", input_tokens=100, output_tokens=200, reasoning_tokens=1000)
    )
    assert base is not None and with_thoughts is not None
    assert with_thoughts > base  # thoughts now priced at the output rate


def test_openai_o_series_not_double_counted():
    # The caller passes reasoning_tokens=0 for OpenAI (helper reads thoughts_tokens,
    # which OpenAI does not set), so o-series cost is unchanged / not inflated.
    usage = _Usage({"reasoning_tokens": 400})
    assert reasoning_tokens_not_in_output(usage) == 0
    cost = resolve_cost(
        CostContext(
            "openai:o3", input_tokens=100, output_tokens=500, reasoning_tokens=reasoning_tokens_not_in_output(usage)
        )
    )
    assert cost is not None and cost > 0
