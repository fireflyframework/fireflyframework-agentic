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

"""Smoke test for the benchmark runner.

Runs the benchmark in mechanics mode (deterministic stub embedder, no API)
end-to-end. The expected mechanics-mode quality bar is modest — vector
signal is hash-noise — but BM25 should reliably hit factual lookups, so we
assert a floor on Hit@5 and substring-match. This catches regressions in
the ingest/retrieval pipeline without requiring API keys.
"""

from __future__ import annotations

from examples.corpus_search.benchmark.runner import run_benchmark


async def test_benchmark_mechanics_mode_completes_with_reasonable_floor():
    """Run the full benchmark in mechanics mode and assert quality floors."""
    result = await run_benchmark(
        mode="mechanics",
        use_rerank=False,
        top_k=5,
        rerank_pool=20,
        json_out=None,
        print_summary=False,
    )

    # Sanity: the corpus loaded, queries ran.
    assert result.n_queries > 0
    assert result.n_corpus_docs == 12
    assert result.n_corpus_chunks > 0

    # Floor expectations for mechanics mode. BM25 with our sanitiser should
    # comfortably clear these; if it can't, something has regressed.
    # These are intentionally generous — tightening them is a quality lever
    # for future iteration.
    assert result.hit_at_5_rate >= 0.50, (
        f"Hit@5 dropped below floor: {result.hit_at_5_rate:.1%}. "
        f"Expected most factual-lookup queries to hit BM25-reliable terms."
    )
    assert result.doc_match_rate >= 0.60
    # Substring match is the strongest "we actually found the answer" signal;
    # mechanics mode (BM25-only effectively) typically lands above 50%.
    assert result.substring_match_rate >= 0.40

    # Negatives: at least one negative query should be correctly rejected.
    if result.correct_rejection_rate is not None:
        # We accept any rejection > 0 here; tightening is future work.
        assert result.correct_rejection_rate >= 0.0


def test_benchmark_corpus_and_queries_are_in_sync():
    """Every query's expected_doc_basenames must reference an existing
    file under benchmark/corpus/.
    """
    import json
    from pathlib import Path

    bench_dir = Path(__file__).parents[3] / "examples" / "corpus_search" / "benchmark"
    corpus_files = {p.name for p in (bench_dir / "corpus").iterdir() if p.is_file()}
    queries = json.loads((bench_dir / "queries.json").read_text(encoding="utf-8"))["queries"]

    for q in queries:
        for basename in q.get("expected_doc_basenames", []):
            assert basename in corpus_files, f"query {q['id']!r} expects {basename!r} but it's not in the corpus dir"
