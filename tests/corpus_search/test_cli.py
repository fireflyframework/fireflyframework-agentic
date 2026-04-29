from __future__ import annotations

from pathlib import Path

import pytest

from examples.corpus_search.cli import build_arg_parser


def test_ingest_subcommand_parses_required_folder():
    parser = build_arg_parser()
    ns = parser.parse_args(["ingest", "--folder", "./drop"])
    assert ns.command == "ingest"
    assert ns.folder == Path("./drop")
    assert ns.root == Path("./kg")
    assert ns.watch is False
    assert ns.embed_model.startswith("azure:text-embedding")


def test_ingest_subcommand_with_watch_and_custom_root():
    parser = build_arg_parser()
    ns = parser.parse_args(["ingest", "--folder", "./drop", "--root", "./mykg", "--watch"])
    assert ns.watch is True
    assert ns.root == Path("./mykg")


def test_query_subcommand_parses_question():
    parser = build_arg_parser()
    ns = parser.parse_args(["query", "Who is the CEO of OpenAI?"])
    assert ns.command == "query"
    assert ns.question == "Who is the CEO of OpenAI?"
    assert ns.root == Path("./kg")
    assert ns.embed_model.startswith("azure:text-embedding")
    assert ns.expansion_model.startswith("anthropic:claude-haiku")
    assert ns.answer_model.startswith("anthropic:claude-sonnet")
    assert ns.rerank_model.startswith("anthropic:claude-haiku")
    assert ns.rerank_pool == 20
    # Default top_k is 5 — the *post-rerank* count fed to the answer agent.
    assert ns.top_k == 5


def test_query_subcommand_with_overrides():
    parser = build_arg_parser()
    ns = parser.parse_args([
        "query", "what?",
        "--root", "./mykg",
        "--top-k", "20",
        "--rerank-pool", "40",
        "--rerank-model", "anthropic:claude-haiku-4-5-20251001",
        "--embed-model", "openai:text-embedding-3-large",
        "--answer-model", "anthropic:claude-opus-4-7",
    ])
    assert ns.top_k == 20
    assert ns.rerank_pool == 40
    assert ns.embed_model == "openai:text-embedding-3-large"
    assert ns.answer_model == "anthropic:claude-opus-4-7"


def test_no_subcommand_errors():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_show_chunk_subcommand_parses_required_id():
    parser = build_arg_parser()
    ns = parser.parse_args(["show-chunk", "abc123-0"])
    assert ns.command == "show-chunk"
    assert ns.chunk_id == "abc123-0"
    assert ns.root == Path("./kg")


def test_show_chunk_requires_chunk_id():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["show-chunk"])
