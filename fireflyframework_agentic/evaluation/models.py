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

"""Shared config and model classes for the evaluation framework.

EvalConfig captures the parameters of a single evaluation run: which model
is being tested, which corpus it runs against, and where the supporting
artefacts (registry, baseline, judge config) live.

GateVerdict constants define the two possible outcomes of the promotion gate:
PROMOTE (the challenger beats or ties the champion and is safe to deploy)
or HOLD (the challenger does not meet the bar and must be iterated on).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EvalConfig(BaseModel):
    """Configuration for a single evaluation run.

    Parameters:
        model_id: Identifier of the model under evaluation.
        corpus: Name of the evaluation corpus (e.g. "ms_marco_mini", "finance_bench").
        run_id: Unique identifier for this run (e.g. a timestamp or git SHA).
        registry_path: Path to the must-find / golden registry JSON file.
        corpus_path: Path to the corpus directory or bundle.
        baseline_path: Path to a baseline results file for regression comparison.
        judge_model: Model identifier used for the LLM-as-judge advisory pass.
        judge_runs: Number of independent judge calls to aggregate (majority vote).
        embed_model: Model identifier used for embedding-based retrieval metrics.
        metadata: Arbitrary key/value pairs for run bookkeeping.
    """

    model_id: str
    corpus: str
    run_id: str
    registry_path: str = ""
    corpus_path: str = ""
    baseline_path: str = ""
    judge_model: str = ""
    judge_runs: int = 3
    embed_model: str = ""
    metadata: dict[str, Any] = {}


class GateVerdict:
    """Promotion gate verdict constants.

    Use ``GateVerdict.PROMOTE`` when the challenger meets the quality bar and
    is safe to become the new champion.  Use ``GateVerdict.HOLD`` when the
    challenger does not meet the bar and must be iterated on.
    """

    PROMOTE: str = "PROMOTE"
    HOLD: str = "HOLD"
