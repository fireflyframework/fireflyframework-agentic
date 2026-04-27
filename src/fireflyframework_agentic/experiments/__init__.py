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

"""Experiments subpackage -- A/B testing and variant comparison."""

from fireflyframework_agentic.experiments.comparator import ComparisonMetrics, VariantComparator
from fireflyframework_agentic.experiments.experiment import Experiment
from fireflyframework_agentic.experiments.runner import ExperimentRunner
from fireflyframework_agentic.experiments.tracker import ExperimentTracker, VariantResult
from fireflyframework_agentic.experiments.variant import Variant

__all__ = [
    "ComparisonMetrics",
    "Experiment",
    "ExperimentRunner",
    "ExperimentTracker",
    "Variant",
    "VariantComparator",
    "VariantResult",
]
