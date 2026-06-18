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

from fireflyframework_agentic.evaluation.corpus import EMPTY, FABRICATED, SOURCE_UNKNOWN, VERIFIED, corpus_sha256, load_corpus, verify_evidence_index
from fireflyframework_agentic.evaluation.gates import GateResult, Verdict, g2_recall_precision, run_gates
from fireflyframework_agentic.evaluation.scorecard import render_scorecard, verdict, VERDICT_PROMOTE, VERDICT_HOLD
from fireflyframework_agentic.evaluation.champion import ChampionRecord, invalidate_champion, load_champion, save_champion
from fireflyframework_agentic.evaluation.judge import AdvisoryReport, run_judge
from fireflyframework_agentic.evaluation.judge_client import JudgeClient, OllamaEmbedder, build_embedder, cosine
from fireflyframework_agentic.evaluation.matcher import anchored, matches, source_stem, tokens
from fireflyframework_agentic.evaluation.registry import Registry, RegistryItem, load_registry, registry_sha256
from fireflyframework_agentic.lab.retrieval_metrics import RetrieverMetrics, compute_retrieval_metrics
from fireflyframework_agentic.evaluation.stats import aa_band, aggregate_grounding, left_skew_flag

try:
    __version__ = version("fireflyframework-agentic")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__all__ = [
    "EMPTY",
    "FABRICATED",
    "SOURCE_UNKNOWN",
    "VERIFIED",
    "corpus_sha256",
    "load_corpus",
    "verify_evidence_index",
    "GateResult",
    "Verdict",
    "g2_recall_precision",
    "run_gates",
    "render_scorecard",
    "verdict",
    "VERDICT_PROMOTE",
    "VERDICT_HOLD",
    "ChampionRecord",
    "load_champion",
    "save_champion",
    "invalidate_champion",
    "AdvisoryReport",
    "run_judge",
    "JudgeClient",
    "OllamaEmbedder",
    "build_embedder",
    "cosine",
    "Registry",
    "RegistryItem",
    "load_registry",
    "registry_sha256",
    "RetrieverMetrics",
    "compute_retrieval_metrics",
    "anchored",
    "matches",
    "source_stem",
    "tokens",
    "aa_band",
    "aggregate_grounding",
    "left_skew_flag",
]
