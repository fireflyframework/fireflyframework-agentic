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

"""Benchmark suite for the corpus_search agent.

A small synthetic corpus + a labelled query set with ground-truth chunk
expectations. The runner ingests the corpus into a tmpdir, runs each
query through the retriever (and optionally the reranker), and reports
Hit@K, MRR, doc-match-rate, and correct-rejection on out-of-corpus
queries.

Usage::

    # Mechanics-only (deterministic embeddings, no API): fast CI run.
    python tests/examples/corpus_search/benchmark/runner.py --mode mechanics

    # Real Azure OpenAI embeddings (needs EMBEDDING_BINDING_*) — actual quality.
    python tests/examples/corpus_search/benchmark/runner.py --mode real

    # Real-mode plus Haiku reranker (needs ANTHROPIC_API_KEY too).
    python tests/examples/corpus_search/benchmark/runner.py --mode real --rerank

The benchmark deliberately stops short of the answer agent — measuring
retrieval quality is reproducible; LLM-generated answer quality is not.
"""

from __future__ import annotations
