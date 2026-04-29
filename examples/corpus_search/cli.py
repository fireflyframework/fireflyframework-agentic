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

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_EMBED_MODEL = "azure:text-embedding-3-small"
_DEFAULT_EXPANSION_MODEL = "anthropic:claude-haiku-4-5-20251001"
_DEFAULT_ANSWER_MODEL = "anthropic:claude-sonnet-4-6"
_DEFAULT_ROOT = Path("./kg")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m examples.corpus_search",
        description="Ingest documents and query them via hybrid (BM25 + vector) search.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest a folder of documents.")
    p_ingest.add_argument("--folder", type=Path, required=True,
                          help="Folder of source documents to ingest.")
    p_ingest.add_argument("--root", type=Path, default=_DEFAULT_ROOT,
                          help="Output root for corpus.sqlite + chroma/.")
    p_ingest.add_argument("--embed-model", default=_DEFAULT_EMBED_MODEL,
                          help="Embedding model.")
    p_ingest.add_argument("--watch", action="store_true",
                          help="After processing existing files, watch for new ones.")
    p_ingest.add_argument("--verbose", action="store_true")

    p_query = sub.add_parser("query", help="Query the corpus.")
    p_query.add_argument("question", help="Natural-language question.")
    p_query.add_argument("--root", type=Path, default=_DEFAULT_ROOT,
                         help="Corpus root (must contain corpus.sqlite + chroma/).")
    p_query.add_argument("--embed-model", default=_DEFAULT_EMBED_MODEL,
                         help="Embedding model — must match the model used at ingest time.")
    p_query.add_argument("--expansion-model", default=_DEFAULT_EXPANSION_MODEL,
                         help="LLM for query expansion.")
    p_query.add_argument("--answer-model", default=_DEFAULT_ANSWER_MODEL,
                         help="LLM for answer synthesis.")
    p_query.add_argument("--top-k", type=int, default=10,
                         help="Number of fused chunks to feed the answer agent.")
    p_query.add_argument("--verbose", action="store_true")

    return parser


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
    from examples.corpus_search.agent import CorpusAgent

    agent = CorpusAgent(
        root=args.root,
        embed_model=args.embed_model,
        expansion_model=_DEFAULT_EXPANSION_MODEL,
        answer_model=_DEFAULT_ANSWER_MODEL,
    )
    try:
        if args.watch:
            async for result in agent.watch(args.folder):
                _print_ingest_result(result)
        else:
            results = await agent.ingest_folder(args.folder)
            for r in results:
                _print_ingest_result(r)
    finally:
        await agent.close()
    return 0


async def _run_query(args: argparse.Namespace) -> int:
    from examples.corpus_search.agent import CorpusAgent

    agent = CorpusAgent(
        root=args.root,
        embed_model=args.embed_model,
        expansion_model=args.expansion_model,
        answer_model=args.answer_model,
    )
    try:
        result = await agent.query(args.question, top_k=args.top_k)
        print(result.text)
        if result.citations:
            print()
            print("Citations:", ", ".join(result.citations))
    finally:
        await agent.close()
    return 0


def _print_ingest_result(result) -> None:
    print(f"[{result.status}] {result.source_path} (doc_id={result.doc_id}, chunks={result.n_chunks})")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

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

    return 2  # unreachable thanks to required=True


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
