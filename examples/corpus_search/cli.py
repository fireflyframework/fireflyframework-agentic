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

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

try:
    import sqlite_vec  # type: ignore[import-not-found]

    _HAS_SQLITE_VEC = True
except ImportError:
    sqlite_vec = None  # type: ignore[assignment]
    _HAS_SQLITE_VEC = False

from fireflyframework_agentic.observability import configure_exporters
from fireflyframework_agentic.pipeline.triggers import FolderWatcher
from fireflyframework_agentic.rag.agent import CorpusAgent
from fireflyframework_agentic.rag.corpus import SqliteCorpus
from fireflyframework_agentic.rag.ingest.structured_schema import SchemaFeedback, TargetSchema

_DEFAULT_EMBED_MODEL = "azure:text-embedding-3-small"
_DEFAULT_EXPANSION_MODEL = "anthropic:claude-haiku-4-5-20251001"
_DEFAULT_ANSWER_MODEL = "anthropic:claude-sonnet-4-6"
_DEFAULT_RERANK_MODEL = "anthropic:claude-haiku-4-5-20251001"
_DEFAULT_RERANK_POOL = 20
_DEFAULT_TOP_K = 5
_DEFAULT_ROOT = Path("./kg")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.corpus_search",
        description="Ingest documents and query them via hybrid (BM25 + vector) search.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a file or folder of documents.")
    p_ingest.add_argument("path", nargs="?", type=Path, default=None, help="Single file to ingest (alternative to --folder).")
    p_ingest.add_argument("--folder", type=Path, default=None, help="Folder of source documents to ingest.")
    p_ingest.add_argument("--root", type=Path, default=_DEFAULT_ROOT, help="Output root for corpus.sqlite.")
    p_ingest.add_argument("--embed-model", default=_DEFAULT_EMBED_MODEL, help="Embedding model.")
    p_ingest.add_argument(
        "--embed-dimension",
        type=int,
        default=1536,
        help="Embedding dimension — must match the chosen model (text-embedding-3-small=1536, text-embedding-3-large=3072).",
    )
    p_ingest.add_argument("--watch", action="store_true", help="After processing existing files, watch for new ones.")
    p_ingest.add_argument(
        "--mode",
        choices=["unstructured", "structured"],
        default="unstructured",
        help="Ingestion mode: unstructured (documents) or structured (CSV/Excel).",
    )
    p_ingest.add_argument(
        "--interactive",
        action="store_true",
        default=False,
        help="Interactively review and correct the inferred schema before ingestion (structured mode only).",
    )
    p_ingest.add_argument("--verbose", action="store_true")

    p_query = sub.add_parser("query", help="Query the corpus.")
    p_query.add_argument("question", help="Natural-language question.")
    p_query.add_argument("--root", type=Path, default=_DEFAULT_ROOT, help="Corpus root (must contain corpus.sqlite).")
    p_query.add_argument(
        "--embed-model",
        default=_DEFAULT_EMBED_MODEL,
        help="Embedding model — must match the model used at ingest time.",
    )
    p_query.add_argument(
        "--embed-dimension",
        type=int,
        default=1536,
        help="Embedding dimension — must match the model used at ingest time.",
    )
    p_query.add_argument("--expansion-model", default=_DEFAULT_EXPANSION_MODEL, help="LLM for query expansion.")
    p_query.add_argument("--answer-model", default=_DEFAULT_ANSWER_MODEL, help="LLM for answer synthesis.")
    p_query.add_argument(
        "--rerank-model", default=_DEFAULT_RERANK_MODEL, help="LLM for listwise reranking of retrieved candidates."
    )
    p_query.add_argument(
        "--rerank-pool",
        type=int,
        default=_DEFAULT_RERANK_POOL,
        help="Number of candidates pulled by hybrid retrieval before reranking.",
    )
    p_query.add_argument(
        "--top-k", type=int, default=_DEFAULT_TOP_K, help="Number of chunks fed to the answer agent after reranking."
    )
    p_query.add_argument("--verbose", action="store_true")

    p_show = sub.add_parser(
        "show-chunk",
        help="Print a single chunk's content + source (no LLM, no embedding).",
    )
    p_show.add_argument("chunk_id", help="The chunk_id to look up (as printed in the Sources block of a query result).")
    p_show.add_argument("--root", type=Path, default=_DEFAULT_ROOT, help="Corpus root (must contain corpus.sqlite).")
    p_show.add_argument("--verbose", action="store_true")

    p_pre = sub.add_parser(
        "preflight",
        help="Validate env, drop folder, and ./kg state before kicking off a real ingestion.",
    )
    p_pre.add_argument("--folder", type=Path, required=True, help="Drop folder that ingest will read from.")
    p_pre.add_argument("--root", type=Path, default=_DEFAULT_ROOT, help="Corpus root (corpus.sqlite location).")
    p_pre.add_argument("--embed-model", default=_DEFAULT_EMBED_MODEL, help="Embedding model.")
    p_pre.add_argument(
        "--force-clean",
        action="store_true",
        help=(
            "Wipe ./kg/ before validating (deletes the directory and recreates it). "
            "Interactive sessions get a 'yes'/abort confirmation prompt; non-interactive "
            "(CI, scripts) skip the prompt because --force-clean itself is the consent."
        ),
    )

    return parser


def _init_telemetry() -> None:
    """Wire OTel providers based on environment variables.

    Reads ``APPLICATIONINSIGHTS_CONNECTION_STRING`` for AppInsights,
    ``FIREFLY_AGENTIC_OTLP_ENDPOINT`` for vendor-neutral OTLP, and
    ``FIREFLY_AGENTIC_CONSOLE_TELEMETRY=1`` to mirror everything to stdout
    for local debugging. Connection strings are not logged.

    Idempotent — repeated calls with the same effective config are a no-op
    via the guard inside :func:`configure_exporters`.
    """
    cs = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    otlp = os.environ.get("FIREFLY_AGENTIC_OTLP_ENDPOINT")
    console = os.environ.get("FIREFLY_AGENTIC_CONSOLE_TELEMETRY") == "1"
    configure_exporters(
        service_name="corpus-search",
        azure_monitor_connection_string=cs,
        otlp_endpoint=otlp,
        console=console,
    )


def _run_preflight(args: argparse.Namespace) -> int:
    """Validate environment, drop folder, and ./kg state without running ingestion.

    Failure conditions:
      - missing AppInsights / embedding / Anthropic keys
      - drop folder missing or empty
      - ./kg already populated and ``--force-clean`` not passed
      - sqlite-vec extension fails to load
    """
    folder: Path = args.folder
    root: Path = args.root
    print("[preflight] validating credentials and environment...")

    rc = _check_keys(embed_model=args.embed_model, need_anthropic=True)
    if rc:
        return rc

    cs = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not cs:
        sys.stderr.write(
            "[preflight] APPLICATIONINSIGHTS_CONNECTION_STRING is not set; telemetry will not reach Azure Monitor.\n"
        )
        return 2
    if len(cs) < 40:  # sanity: real conn strings are ~150+ chars
        sys.stderr.write("[preflight] APPLICATIONINSIGHTS_CONNECTION_STRING looks too short.\n")
        return 2

    if not folder.exists() or not folder.is_dir():
        sys.stderr.write(f"[preflight] drop folder {folder} does not exist or is not a directory.\n")
        return 2
    n_files = sum(1 for p in folder.rglob("*") if p.is_file())
    if n_files == 0:
        sys.stderr.write(f"[preflight] drop folder {folder} contains no files.\n")
        return 2

    db = root / "corpus.sqlite"
    if db.exists():
        if not args.force_clean:
            sys.stderr.write(f"[preflight] {db} already exists. Pass --force-clean to wipe ./kg before ingesting.\n")
            return 2
        # --force-clean is set: wipe ./kg and recreate the directory.
        # Confirmation prompt suppressed when running non-interactively
        # (CI, scripts) — --force-clean itself is the explicit consent.
        if sys.stdin.isatty():
            confirm = input(f"[preflight] About to delete {root} and all its contents. Type 'yes' to proceed: ")
            if confirm.strip().lower() != "yes":
                sys.stderr.write("[preflight] aborted by operator.\n")
                return 2
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)
        print(f"[preflight] wiped {root} (--force-clean)")

    # sqlite-vec smoke test — exercises the same load path the ingest code uses.
    try:
        if not _HAS_SQLITE_VEC:
            raise ImportError("sqlite-vec is not installed")
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[preflight] sqlite-vec extension failed to load: {exc}\n")
        return 2

    print(f"[preflight] OK. drop={folder} files={n_files} kg={root} clean={'yes' if args.force_clean else 'fresh'}")
    return 0


def _check_keys(*, embed_model: str, need_anthropic: bool) -> int:
    """Validate that the env contains the credentials the chosen backends need.

    The embedding provider is parsed from the ``embed_model`` prefix:

    - ``azure:<deployment>`` requires ``EMBEDDING_BINDING_HOST`` and
      ``EMBEDDING_BINDING_API_KEY``.
    - ``openai:<model>`` requires ``OPENAI_API_KEY``.

    ``need_anthropic`` is set by the ``query`` subcommand only — ingest doesn't
    need ``ANTHROPIC_API_KEY``.
    """
    provider = embed_model.split(":", 1)[0] if ":" in embed_model else "openai"
    if provider == "azure":
        if not os.environ.get("EMBEDDING_BINDING_HOST"):
            sys.stderr.write("EMBEDDING_BINDING_HOST missing (set in environment or .env)\n")
            return 2
        if not os.environ.get("EMBEDDING_BINDING_API_KEY"):
            sys.stderr.write("EMBEDDING_BINDING_API_KEY missing (set in environment or .env)\n")
            return 2
    elif provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            sys.stderr.write("OPENAI_API_KEY missing (set in environment or .env)\n")
            return 2
    else:
        sys.stderr.write(f"Unknown embedding provider: {provider!r}\n")
        return 2

    if need_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("ANTHROPIC_API_KEY missing (set in environment or .env)\n")
        return 2
    return 0


async def _run_ingest(args: argparse.Namespace) -> int:
    agent = CorpusAgent(
        root=args.root,
        embed_model=args.embed_model,
        embed_dimension=args.embed_dimension,
        expansion_model=_DEFAULT_EXPANSION_MODEL,
        answer_model=_DEFAULT_ANSWER_MODEL,
        rerank_model=_DEFAULT_RERANK_MODEL,
        rerank_pool=_DEFAULT_RERANK_POOL,
    )
    on_review = _cli_review_schema if getattr(args, "interactive", False) else None
    mode = getattr(args, "mode", "unstructured")
    try:
        single_path: Path | None = getattr(args, "path", None)
        folder: Path | None = getattr(args, "folder", None)
        if single_path is not None and single_path.is_file():
            result = await agent.ingest_one(single_path, mode=mode, on_review=on_review)
            _print_ingest_result(result)
        elif args.watch:
            target = folder or single_path
            if target is None:
                sys.stderr.write("error: --folder or a path argument is required for --watch\n")
                return 1
            async for result in agent.watch(target):
                _print_ingest_result(result)
        else:
            # Walk the folder ourselves so we can stream per-file status
            # to the operator's terminal as each file finishes (rather than
            # buffering the whole batch via agent.ingest_folder). Filtering
            # uses FolderWatcher.is_hidden to stay in sync with the watcher
            # path. The framework-level corpus_search.ingest_folder span
            # is sacrificed in favour of operator UX; per-file
            # rag.ingest.document spans are still emitted as before.
            dir_target = folder or single_path
            if dir_target is None:
                sys.stderr.write("error: --folder or a path argument is required\n")
                return 1
            root = Path(dir_target)
            watcher = FolderWatcher(folder=root)
            candidates = sorted(p for p in root.rglob("*") if p.is_file() and not watcher.is_hidden(p))
            print(f"found {len(candidates)} file(s) under {root}", file=sys.stderr)
            for i, path in enumerate(candidates, 1):
                size_kb = path.stat().st_size / 1024 if path.exists() else 0
                print(
                    f"[{i}/{len(candidates)}] starting {path.relative_to(root)} ({size_kb:.0f} KB)",
                    file=sys.stderr,
                    flush=True,
                )
                result = await agent.ingest_one(path, mode=mode, on_review=on_review)
                _print_ingest_result(result)
    finally:
        await agent.close()
    return 0


async def _run_query(args: argparse.Namespace) -> int:
    agent = CorpusAgent(
        root=args.root,
        embed_model=args.embed_model,
        embed_dimension=args.embed_dimension,
        expansion_model=args.expansion_model,
        answer_model=args.answer_model,
        rerank_model=args.rerank_model,
        rerank_pool=args.rerank_pool,
    )
    try:
        result = await agent.query(args.question, top_k=args.top_k)
        print(result.text)
        if result.cited_sources:
            print()
            print("Sources:")
            for src in result.cited_sources:
                # Show the chunk_id (so the user can match it to the inline
                # [chunk_id] markers in the answer text) plus the filename
                # of the source document.
                print(f"  [{src.chunk_id}] {Path(src.source_path).name}")
        elif result.citations:
            # Fallback: LLM cited chunk_ids that didn't appear in the hits
            # (rare; usually a hallucinated id). Show the raw citations.
            print()
            print("Citations:", ", ".join(result.citations))
    finally:
        await agent.close()
    return 0


def _print_ingest_result(result) -> None:
    print(f"[{result.status}] {result.source_path} (doc_id={result.doc_id}, chunks={result.n_chunks})")


async def _cli_review_schema(schema: TargetSchema) -> SchemaFeedback:
    sys.stdout.write("\n--- Inferred schema ---\n")
    for table in schema.tables:
        sys.stdout.write(f"  Table: {table.name}\n")
        for col in table.columns:
            flags = []
            if col.primary_key:
                flags.append("PK")
            if not col.nullable:
                flags.append("NOT NULL")
            flag_str = f"  [{', '.join(flags)}]" if flags else ""
            sys.stdout.write(f"    {col.name}: {col.type.value}{flag_str}\n")
    sys.stdout.write("-----------------------\n")
    sys.stdout.write("Press Enter to approve, or type corrections: ")
    sys.stdout.flush()
    loop = asyncio.get_running_loop()
    raw = await loop.run_in_executor(None, sys.stdin.readline)
    corrections = raw.strip()
    return SchemaFeedback(approved=not corrections, corrections=corrections)


async def _run_show_chunk(args: argparse.Namespace) -> int:
    corpus_path = args.root / "corpus.sqlite"
    if not corpus_path.exists():
        sys.stderr.write(f"corpus.sqlite not found at {corpus_path}\n")
        return 2
    corpus = SqliteCorpus(corpus_path)
    await corpus.initialise()
    try:
        chunks = await corpus.get_chunks([args.chunk_id])
        if not chunks:
            sys.stderr.write(f"chunk_id {args.chunk_id!r} not found\n")
            return 1
        chunk = chunks[0]
        print(f"chunk_id:    {chunk.chunk_id}")
        print(f"doc_id:      {chunk.doc_id}")
        print(f"source_path: {chunk.source_path}")
        print(f"index:       {chunk.index_in_doc}")
        print()
        print(chunk.content)
    finally:
        await corpus.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_arg_parser().parse_args(argv)
    verbose = bool(getattr(args, "verbose", False))
    # Root stays at INFO. Only our own packages get DEBUG when --verbose
    # is passed; everything else stays at the silenced level so pdfminer
    # doesn't dump every PDF parser token (~10 GB/min for a mid-sized PDF).
    logging.basicConfig(level=logging.INFO)
    if verbose:
        for name in ("examples.corpus_search", "fireflyframework_agentic"):
            logging.getLogger(name).setLevel(logging.DEBUG)
    # Default silenced loggers — operator can override the list via the
    # FIREFLY_AGENTIC_VERBOSE_LOGGERS env var (CSV) when triaging a
    # specific subsystem (e.g. set "azure" to leave Azure SDK at INFO
    # while keeping pdfminer/pdfplumber muted).
    default_silenced = ("pdfminer", "pdfplumber", "markdown_it", "azure", "urllib3", "httpx")
    keep_verbose = {
        name.strip() for name in os.environ.get("FIREFLY_AGENTIC_VERBOSE_LOGGERS", "").split(",") if name.strip()
    }
    for noisy in default_silenced:
        if noisy not in keep_verbose:
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # Telemetry init runs for every subcommand so that even show-chunk and
    # preflight emit spans into AppInsights when a connection string is set.
    # Idempotent across calls within the same process.
    _init_telemetry()

    if args.command == "ingest":
        rc = _check_keys(embed_model=args.embed_model, need_anthropic=False)
        if rc:
            return rc
        return asyncio.run(_run_ingest(args))
    if args.command == "query":
        rc = _check_keys(embed_model=args.embed_model, need_anthropic=True)
        if rc:
            return rc
        return asyncio.run(_run_query(args))
    if args.command == "show-chunk":
        # No API keys needed — we're reading SQLite directly.
        return asyncio.run(_run_show_chunk(args))
    if args.command == "preflight":
        return _run_preflight(args)

    return 2  # unreachable thanks to required=True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
