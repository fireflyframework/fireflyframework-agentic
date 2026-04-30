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

"""Benchmark runner — measures retrieval quality on a synthetic ground-truth corpus.

Two modes:

- ``mechanics`` — deterministic stub embedder + in-memory vector store,
  no API calls, fully reproducible. Useful as a CI smoke test for the
  retrieval pipeline mechanics. Vector signal is essentially noise here;
  metrics primarily reflect BM25 quality.

- ``real`` — real Azure OpenAI embeddings + sqlite-vec vector store.
  Optional Haiku reranker via ``--rerank``. Requires
  ``EMBEDDING_BINDING_HOST`` + ``EMBEDDING_BINDING_API_KEY`` (and
  ``ANTHROPIC_API_KEY`` if reranking). Measures actual semantic quality.

Output: per-query trace + aggregate metrics. ``--json out.json`` dumps
machine-readable results for regression comparison between runs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from fireflyframework_agentic.content.loaders import MarkitdownLoader
from fireflyframework_agentic.content.markdown_chunker import MarkdownChunker
from fireflyframework_agentic.embeddings.types import EmbeddingResult
from fireflyframework_agentic.rag.corpus import ChunkHit, SqliteCorpus
from fireflyframework_agentic.rag.ingest.ledger import IngestLedger
from fireflyframework_agentic.rag.ingest.pipeline import ingest_one
from fireflyframework_agentic.rag.retrieval.expander import ExpandedQuery, QueryExpander
from fireflyframework_agentic.rag.retrieval.hybrid import HybridRetriever
from fireflyframework_agentic.vectorstores.memory_store import InMemoryVectorStore

log = logging.getLogger(__name__)


_BENCH_DIR = Path(__file__).parent
_CORPUS_DIR = _BENCH_DIR / "corpus"
_QUERIES_FILE = _BENCH_DIR / "queries.json"


# --- Stub embedder (mechanics mode) -----------------------------------------


class _DeterministicHashEmbedder:
    """Maps each text to a 64-d vector via SHA-256 hashing.

    Deterministic, language-agnostic, fast — but semantically noisy. Good
    enough to exercise the pipeline mechanics; not good enough to measure
    actual retrieval quality (use --mode real for that).
    """

    DIMS = 64

    async def embed(self, texts: list[str], **kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            embeddings=[self._hash_to_vec(t) for t in texts],
            model="hash-stub",
            usage=None,
            dimensions=self.DIMS,
        )

    async def embed_one(self, text: str, **kwargs: Any) -> list[float]:
        return self._hash_to_vec(text)

    def _hash_to_vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # 32 bytes -> 64 half-bytes -> 64 floats in [0, 1)
        return [((b >> 4) & 0xF) / 16.0 for b in h] + [(b & 0xF) / 16.0 for b in h]


# --- Result types -----------------------------------------------------------


@dataclass(slots=True)
class QueryResult:
    """Per-query metrics + trace."""

    id: str
    query: str
    category: str
    language: str
    difficulty: str
    negative: bool
    expected_doc_basenames: list[str]
    expected_substrings: list[str]

    # Retrieved chunks (top-K) with their source docs
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    retrieved_doc_basenames: list[str] = field(default_factory=list)

    # Queries actually issued to the retriever (populated when --expand is used).
    # Format: "[hybrid] text" or "[vec_only] text".
    expanded_queries: list[str] = field(default_factory=list)

    # Per-query metrics
    hit_at_1: bool = False
    hit_at_5: bool = False
    hit_at_20: bool = False
    doc_match: bool = False  # was at least one expected doc retrieved at all
    substring_match: bool = False  # at least one expected substring appeared in retrieved content
    rank_of_first_match: int | None = None  # 1-indexed; None if not retrieved
    rejected_correctly: bool | None = None  # True/False for negative queries; None for non-negative


@dataclass(slots=True)
class BenchmarkResult:
    """Aggregate benchmark metrics."""

    mode: str
    use_rerank: bool
    use_expansion: bool
    n_queries: int
    n_corpus_docs: int
    n_corpus_chunks: int
    queries: list[QueryResult] = field(default_factory=list)

    # Aggregates
    hit_at_1_rate: float = 0.0
    hit_at_5_rate: float = 0.0
    hit_at_20_rate: float = 0.0
    mean_reciprocal_rank: float = 0.0
    doc_match_rate: float = 0.0
    substring_match_rate: float = 0.0
    correct_rejection_rate: float | None = None  # over negative queries; None if no negatives

    # By-category rollup: {category: {hit_at_5: 0.8, ...}}
    by_category: dict[str, dict[str, float]] = field(default_factory=dict)


# --- Helpers ----------------------------------------------------------------


def _doc_basename(source_path: str) -> str:
    return Path(source_path).name


def _load_queries() -> list[dict[str, Any]]:
    data = json.loads(_QUERIES_FILE.read_text(encoding="utf-8"))
    return data["queries"]


def _expected_substring_present(hits: Sequence[ChunkHit], expected: Sequence[str]) -> bool:
    if not expected:
        return False
    haystack = "\n".join(h.content for h in hits)
    return any(s in haystack for s in expected)


def _rank_of_first_doc_match(hits: Sequence[ChunkHit], expected_basenames: Sequence[str]) -> int | None:
    if not expected_basenames:
        return None
    for i, h in enumerate(hits, start=1):
        if _doc_basename(h.source_path) in expected_basenames:
            return i
    return None


# --- Ingest the synthetic corpus --------------------------------------------


async def _ingest_corpus(
    corpus: SqliteCorpus,
    vector_store: Any,
    embedder: Any,
    ledger: IngestLedger,
) -> int:
    chunker = MarkdownChunker(max_chunk_tokens=200, chunk_overlap=30)
    loader = MarkitdownLoader()
    n_chunks = 0
    for path in sorted(_CORPUS_DIR.iterdir()):
        if path.is_file() and not path.name.startswith("."):
            result = await ingest_one(
                path=path,
                corpus=corpus,
                vector_store=vector_store,
                embedder=embedder,
                ledger=ledger,
                chunker=chunker,
                loader=loader,
            )
            n_chunks += result.n_chunks
    return n_chunks


# --- Build the embedder/vector_store stack for the chosen mode --------------


def _build_embedder(mode: str) -> Any:
    if mode == "mechanics":
        return _DeterministicHashEmbedder()
    if mode == "real":
        from fireflyframework_agentic.embeddings.providers.azure import AzureEmbedder

        endpoint = os.environ.get("EMBEDDING_BINDING_HOST")
        api_key = os.environ.get("EMBEDDING_BINDING_API_KEY")
        if not endpoint or not api_key:
            raise RuntimeError("Real mode requires EMBEDDING_BINDING_HOST and EMBEDDING_BINDING_API_KEY.")
        return AzureEmbedder(
            model="text-embedding-3-small",
            azure_endpoint=endpoint,
            api_key=api_key,
        )
    raise ValueError(f"Unknown mode: {mode!r}")


def _build_vector_store(mode: str, root: Path, embed_dimension: int = 1536) -> Any:
    if mode == "mechanics":
        return InMemoryVectorStore()
    if mode == "real":
        from fireflyframework_agentic.vectorstores.sqlite_vec_store import SqliteVecVectorStore

        return SqliteVecVectorStore(
            db_path=root / "corpus.sqlite",
            dimension=embed_dimension,
            table_name="benchmark_chunks",
        )
    raise ValueError(f"Unknown mode: {mode!r}")


# --- Main runner ------------------------------------------------------------


async def run_benchmark(
    *,
    mode: str = "mechanics",
    embed_dimension: int = 1536,
    use_rerank: bool = False,
    use_expansion: bool = False,
    expansion_model: str = "anthropic:claude-haiku-4-5-20251001",
    top_k: int = 5,
    rerank_pool: int = 20,
    rerank_model: str = "anthropic:claude-haiku-4-5-20251001",
    json_out: Path | None = None,
    print_summary: bool = True,
) -> BenchmarkResult:
    """Ingest the synthetic corpus, run every query, return aggregated metrics."""
    queries = _load_queries()

    with tempfile.TemporaryDirectory(prefix="corpus_bench_") as tdir_str:
        tdir = Path(tdir_str)
        corpus = SqliteCorpus(tdir / "corpus.sqlite")
        await corpus.initialise()
        try:
            embedder = _build_embedder(mode)
            vector_store = _build_vector_store(mode, tdir, embed_dimension)
            ledger = IngestLedger(corpus)

            n_chunks = await _ingest_corpus(corpus, vector_store, embedder, ledger)
            n_docs = sum(1 for p in _CORPUS_DIR.iterdir() if p.is_file())

            retriever = HybridRetriever(
                corpus=corpus,
                vector_store=vector_store,
                embedder=embedder,
            )
            reranker = None
            if use_rerank:
                from fireflyframework_agentic.rag.retrieval.reranker import HaikuReranker

                reranker = HaikuReranker(model=rerank_model)

            expander = None
            if use_expansion:
                expander = QueryExpander(model=expansion_model)

            qr_list: list[QueryResult] = []
            for q in queries:
                qr = await _evaluate_query(
                    q=q,
                    retriever=retriever,
                    reranker=reranker,
                    expander=expander,
                    top_k=top_k,
                    rerank_pool=rerank_pool,
                )
                qr_list.append(qr)

            agg = _aggregate(
                qr_list,
                mode=mode,
                use_rerank=use_rerank,
                use_expansion=use_expansion,
                n_corpus_docs=n_docs,
                n_corpus_chunks=n_chunks,
            )

            if print_summary:
                _print_summary(agg)
            if json_out is not None:
                # Auto-create the parent directory so users don't have to
                # remember `mkdir -p runs/` before passing --json.
                json_out.parent.mkdir(parents=True, exist_ok=True)
                json_out.write_text(json.dumps(asdict(agg), indent=2), encoding="utf-8")
                if print_summary:
                    print(f"\nWrote machine-readable results to {json_out}")

            return agg
        finally:
            await corpus.close()


async def _evaluate_query(
    *,
    q: dict[str, Any],
    retriever: HybridRetriever,
    reranker: Any | None,
    expander: QueryExpander | None,
    top_k: int,
    rerank_pool: int,
) -> QueryResult:
    # Expand when requested; otherwise use the raw query (deterministic baseline).
    if expander is not None:
        expanded = await expander.expand(q["query"])
        queries_for_retrieval: list[str | ExpandedQuery] = list(expanded)
        expanded_query_strs = [f"[{eq.route}] {eq.text}" for eq in expanded]
    else:
        queries_for_retrieval = [q["query"]]
        expanded_query_strs = []

    # Always pull a wider pool so rank metrics like Hit@20 are meaningful even
    # without rerank.
    pool_size = max(20, rerank_pool, top_k)
    candidates = await retriever.retrieve(
        queries_for_retrieval,
        top_k_per_query=30,
        top_k_final=pool_size,
    )

    if reranker is not None:
        # Rerank to top_k for the substring/hit checks.
        top_hits = await reranker.rerank(q["query"], candidates, top_k=top_k)
    else:
        top_hits = candidates[:top_k]

    expected_basenames = q.get("expected_doc_basenames") or []
    expected_substrings = q.get("expected_substrings") or []

    rank_first = _rank_of_first_doc_match(candidates, expected_basenames)

    qr = QueryResult(
        id=q["id"],
        query=q["query"],
        category=q.get("category", "uncategorised"),
        language=q.get("language", "en"),
        difficulty=q.get("difficulty", "medium"),
        negative=bool(q.get("negative", False)),
        expected_doc_basenames=list(expected_basenames),
        expected_substrings=list(expected_substrings),
        retrieved_chunk_ids=[h.chunk_id for h in top_hits],
        retrieved_doc_basenames=[_doc_basename(h.source_path) for h in top_hits],
        expanded_queries=expanded_query_strs,
        hit_at_1=rank_first == 1,
        hit_at_5=rank_first is not None and rank_first <= 5,
        hit_at_20=rank_first is not None and rank_first <= 20,
        doc_match=rank_first is not None,
        substring_match=_expected_substring_present(top_hits, expected_substrings),
        rank_of_first_match=rank_first,
    )

    if qr.negative:
        # Correct rejection: rejection is "correct" if no expected doc ranked
        # anywhere in the candidate pool.
        qr.rejected_correctly = rank_first is None

    return qr


def _aggregate(
    qrs: list[QueryResult],
    *,
    mode: str,
    use_rerank: bool,
    use_expansion: bool,
    n_corpus_docs: int,
    n_corpus_chunks: int,
) -> BenchmarkResult:
    n = len(qrs)
    non_neg = [q for q in qrs if not q.negative]
    neg = [q for q in qrs if q.negative]

    n_non_neg = max(len(non_neg), 1)

    hit1 = sum(1 for q in non_neg if q.hit_at_1) / n_non_neg
    hit5 = sum(1 for q in non_neg if q.hit_at_5) / n_non_neg
    hit20 = sum(1 for q in non_neg if q.hit_at_20) / n_non_neg

    mrr = sum((1.0 / q.rank_of_first_match) if q.rank_of_first_match else 0.0 for q in non_neg) / n_non_neg

    doc_match = sum(1 for q in non_neg if q.doc_match) / n_non_neg
    substr_match = sum(1 for q in non_neg if q.substring_match) / n_non_neg

    correct_rejection = sum(1 for q in neg if q.rejected_correctly) / len(neg) if neg else None

    # By-category rollup
    by_cat: dict[str, dict[str, float]] = {}
    cats = sorted({q.category for q in qrs})
    for c in cats:
        in_cat = [q for q in qrs if q.category == c]
        cn = max(len(in_cat), 1)
        by_cat[c] = {
            "n": float(len(in_cat)),
            "hit_at_5": sum(1 for q in in_cat if q.hit_at_5) / cn,
            "doc_match": sum(1 for q in in_cat if q.doc_match) / cn,
            "substring_match": sum(1 for q in in_cat if q.substring_match) / cn,
        }

    return BenchmarkResult(
        mode=mode,
        use_rerank=use_rerank,
        use_expansion=use_expansion,
        n_queries=n,
        n_corpus_docs=n_corpus_docs,
        n_corpus_chunks=n_corpus_chunks,
        queries=qrs,
        hit_at_1_rate=hit1,
        hit_at_5_rate=hit5,
        hit_at_20_rate=hit20,
        mean_reciprocal_rank=mrr,
        doc_match_rate=doc_match,
        substring_match_rate=substr_match,
        correct_rejection_rate=correct_rejection,
        by_category=by_cat,
    )


def _print_summary(agg: BenchmarkResult) -> None:
    print()
    print("=" * 70)
    print(f" Benchmark summary  mode={agg.mode}  expand={agg.use_expansion}  rerank={agg.use_rerank}")
    print("=" * 70)
    print(f" Corpus:    {agg.n_corpus_docs} docs, {agg.n_corpus_chunks} chunks")
    print(f" Queries:   {agg.n_queries}")
    print()
    print(" --- Per-query traces ---")
    for q in agg.queries:
        marker = "✓" if (q.hit_at_5 or q.rejected_correctly) else "✗"
        rank = q.rank_of_first_match if q.rank_of_first_match is not None else "-"
        substr = "✓" if q.substring_match else ("·" if q.negative else "✗")
        print(f"  {marker} [{q.id:32s}] rank={rank!s:>4} substr={substr}  ({q.category})")
        if not (q.hit_at_5 or q.rejected_correctly):
            print(f"      query: {q.query}")
            if q.expanded_queries:
                print("      issued queries:")
                for eq in q.expanded_queries:
                    print(f"        {eq}")
            print(f"      expected: {q.expected_doc_basenames or '(no docs — negative)'}")
            print(f"      retrieved top-5: {q.retrieved_doc_basenames[:5]}")

    print()
    print(" --- Aggregate retrieval metrics (over non-negative queries) ---")
    print(f"  Hit@1:           {agg.hit_at_1_rate:6.1%}")
    print(f"  Hit@5:           {agg.hit_at_5_rate:6.1%}")
    print(f"  Hit@20:          {agg.hit_at_20_rate:6.1%}")
    print(f"  MRR:             {agg.mean_reciprocal_rank:6.3f}")
    print(f"  Doc-match rate:  {agg.doc_match_rate:6.1%}")
    print(f"  Substring match: {agg.substring_match_rate:6.1%}")
    if agg.correct_rejection_rate is not None:
        print(f"  Correct rejection (negatives): {agg.correct_rejection_rate:6.1%}")

    print()
    print(" --- By category ---")
    for cat, metrics in agg.by_category.items():
        print(
            f"  {cat:24s} n={int(metrics['n']):>2d}  "
            f"hit@5={metrics['hit_at_5']:6.1%}  "
            f"doc-match={metrics['doc_match']:6.1%}  "
            f"substr={metrics['substring_match']:6.1%}"
        )
    print()


_REGRESSION_CHECKS: list[tuple[str, str]] = [
    ("hit_at_5_rate", "Hit@5"),
    ("mean_reciprocal_rank", "MRR"),
    ("doc_match_rate", "Doc-match rate"),
    ("substring_match_rate", "Substring match rate"),
]


def _compare_against_baseline(
    current: BenchmarkResult,
    baseline_path: Path,
    tolerance: float,
) -> list[str] | None:
    """Compare *current* against a previously saved JSON baseline.

    Returns:
        ``None``        — baseline file not found; comparison skipped.
        ``[]``          — no regressions within *tolerance*.
        ``[msg, ...]``  — one message per metric that regressed.
    """
    if not baseline_path.exists():
        print(f"\nBaseline file not found: {baseline_path} — skipping comparison.")
        return None

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    regressions: list[str] = []
    for attr, label in _REGRESSION_CHECKS:
        cur = getattr(current, attr)
        base = baseline.get(attr)
        if base is None:
            continue
        if cur < base - tolerance:
            regressions.append(
                f"  {label}: {cur:.4f} < baseline {base:.4f} (delta {cur - base:+.4f}, tolerance ±{tolerance:.4f})"
            )
    return regressions


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path(__file__).parents[4] / ".env")
    parser = argparse.ArgumentParser(
        prog="python tests/examples/corpus_search/benchmark/runner.py",
        description="Run the corpus_search retrieval benchmark.",
    )
    parser.add_argument(
        "--mode",
        choices=("mechanics", "real"),
        default="mechanics",
        help="mechanics: stub embedder, no API. real: Azure OpenAI embeddings.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Add the Haiku listwise reranker between retrieval and metrics.",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help=(
            "Run query expansion (paraphrase variants + HyDE passage) before "
            "retrieval. Measures the full pipeline including the expander. "
            "Requires ANTHROPIC_API_KEY."
        ),
    )
    parser.add_argument(
        "--embed-dimension",
        type=int,
        default=1536,
        help="Embedding dimension for real mode (default: 1536 for text-embedding-3-small).",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--rerank-pool", type=int, default=20)
    parser.add_argument(
        "--rerank-model",
        default="anthropic:claude-haiku-4-5-20251001",
    )
    parser.add_argument(
        "--expansion-model",
        default="anthropic:claude-haiku-4-5-20251001",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write machine-readable results to this path.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "JSON file produced by a previous run to compare against. "
            "If the file does not exist the comparison is skipped (first-run friendly). "
            "Exits 1 when any tracked metric drops below the baseline minus the tolerance."
        ),
    )
    parser.add_argument(
        "--regression-tolerance",
        type=float,
        default=0.02,
        metavar="DELTA",
        help=(
            "Absolute drop allowed below the baseline before the run is considered a "
            "regression (default: 0.02 = 2 percentage points). Use 0.0 for mechanics "
            "mode where results are fully deterministic."
        ),
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Silence the noisy framework agent middleware — benchmark output is
    # what we actually want to read.
    for noisy in ("fireflyframework_agentic.agents.builtin_middleware", "fireflyframework_agentic.events", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.mode == "real" and not (
        os.environ.get("EMBEDDING_BINDING_HOST") and os.environ.get("EMBEDDING_BINDING_API_KEY")
    ):
        sys.stderr.write("real mode requires EMBEDDING_BINDING_HOST and EMBEDDING_BINDING_API_KEY\n")
        return 2
    if (args.rerank or args.expand) and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("--rerank and --expand require ANTHROPIC_API_KEY\n")
        return 2

    result = asyncio.run(
        run_benchmark(
            mode=args.mode,
            embed_dimension=args.embed_dimension,
            use_rerank=args.rerank,
            use_expansion=args.expand,
            expansion_model=args.expansion_model,
            top_k=args.top_k,
            rerank_pool=args.rerank_pool,
            rerank_model=args.rerank_model,
            json_out=args.json,
            print_summary=not args.quiet,
        )
    )

    if args.baseline is not None:
        regressions = _compare_against_baseline(result, args.baseline, args.regression_tolerance)
        if regressions is None:
            pass  # baseline file absent — skipped
        elif regressions:
            print("\nREGRESSION DETECTED vs", args.baseline)
            for line in regressions:
                print(line)
            return 1
        else:
            print(f"\nNo regressions vs {args.baseline} (tolerance {args.regression_tolerance:.3f}).")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
