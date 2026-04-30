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

"""Experiment variant configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Variant(BaseModel):
    """A specific configuration to test within an experiment.

    Each variant encapsulates a model, temperature, prompt template, and
    any extra parameters that distinguish it from other variants.

    Parameters:
        name: Variant identifier (e.g. "baseline", "candidate_a").
        model: LLM model string.
        temperature: Sampling temperature.
        prompt_template: Name of the prompt template to use.
        parameters: Additional parameters passed to the agent.
    """

    name: str
    model: str = "openai:gpt-4o"
    temperature: float = 0.7
    prompt_template: str = ""
    parameters: dict[str, Any] = {}
