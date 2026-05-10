# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Unit tests for CorpusNotFoundError."""

from __future__ import annotations

from fireflyframework_agentic.rag import CorpusNotFoundError


def test_message_includes_corpus_id() -> None:
    err = CorpusNotFoundError("my-corpus", "/tmp/firefly/corpora/my-corpus/corpus.sqlite")
    msg = str(err)
    assert "my-corpus" in msg
    assert "/tmp/firefly/corpora/my-corpus/corpus.sqlite" in msg
