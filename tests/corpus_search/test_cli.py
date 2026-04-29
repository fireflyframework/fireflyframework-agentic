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
    assert ns.embed_model.startswith("openai:text-embedding")


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
    assert ns.expansion_model.startswith("anthropic:claude-haiku")
    assert ns.answer_model.startswith("anthropic:claude-sonnet")
    assert ns.top_k == 10


def test_query_subcommand_with_overrides():
    parser = build_arg_parser()
    ns = parser.parse_args([
        "query", "what?",
        "--root", "./mykg",
        "--top-k", "20",
        "--answer-model", "anthropic:claude-opus-4-7",
    ])
    assert ns.top_k == 20
    assert ns.answer_model == "anthropic:claude-opus-4-7"


def test_no_subcommand_errors():
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
