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

"""Evaluation subpackage -- gate-based quality gates, LLM-as-judge advisory, champion/challenger tracking, and retrieval metrics.

Gate pipeline (flags, not vetoes):
    G1 -- Structural & Safe (schema + PII + empty-registry guard)
    G2 -- Must-finds & negative controls (recall + NC precision)
    G3 -- Evidence (grounding / token-anchoring)
    G4 -- LLM-as-a-Judge (advisory, opt-in, never decides promotion)
    G5 -- No-regression / promotion (champion/challenger comparison)

Retrieval metrics:
    Precision@k, Recall@k, MRR, NDCG -- computed over ranked retrieval results.

Champion tracking:
    Persists the best-known run record so that promotion decisions can be made
    against a stable baseline rather than the most recent run.
"""

from importlib.metadata import PackageNotFoundError, version

from fireflyframework_agentic.evaluation.gates import GateResult, Verdict, render_scorecard, run_gates
from fireflyframework_agentic.evaluation.champion import ChampionRecord, invalidate_champion, load_champion, save_champion
from fireflyframework_agentic.evaluation.judge import AdvisoryReport, run_judge
from fireflyframework_agentic.evaluation.retrieval import RetrieverMetrics, compute_retrieval_metrics

try:
    __version__ = version("fireflyframework-agentic")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__all__ = [
    "GateResult",
    "Verdict",
    "run_gates",
    "render_scorecard",
    "ChampionRecord",
    "load_champion",
    "save_champion",
    "invalidate_champion",
    "AdvisoryReport",
    "run_judge",
    "RetrieverMetrics",
    "compute_retrieval_metrics",
]
