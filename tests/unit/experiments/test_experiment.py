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

"""Tests for experiments."""

from __future__ import annotations

from fireflyframework_agentic.experiments.experiment import Experiment
from fireflyframework_agentic.experiments.variant import Variant


class TestExperiment:
    def test_experiment_creation(self):
        exp = Experiment(
            name="test_exp",
            description="A test experiment",
            variants=[
                Variant(name="v1", model="openai:gpt-4o"),
                Variant(name="v2", model="openai:gpt-4o-mini"),
            ],
        )
        assert exp.name == "test_exp"
        assert len(exp.variants) == 2


class TestVariant:
    def test_variant_creation(self):
        v = Variant(name="v1", model="openai:gpt-4o", temperature=0.5)
        assert v.name == "v1"
        assert v.model == "openai:gpt-4o"
        assert v.temperature == 0.5
