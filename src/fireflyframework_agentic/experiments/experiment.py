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

"""Experiment definition and configuration."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.experiments.variant import Variant


class Experiment(BaseModel):
    """Defines an A/B or multi-variant experiment.

    Parameters:
        name: Unique experiment name.
        hypothesis: What the experiment aims to prove or disprove.
        variants: The configurations to compare.
        dataset: Optional list of test inputs.
        metadata: Arbitrary key-value pairs.
    """

    name: str
    hypothesis: str = ""
    variants: list[Variant] = []
    dataset: list[str] = []
    metadata: dict[str, Any] = {}
    tags: list[str] = []

    def add_variant(self, variant: Variant) -> None:
        """Append a variant to this experiment."""
        self.variants.append(variant)

    def add_inputs(self, inputs: Sequence[str]) -> None:
        """Add test inputs to the dataset."""
        self.dataset.extend(inputs)
