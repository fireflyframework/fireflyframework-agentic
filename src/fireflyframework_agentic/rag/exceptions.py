# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""RAG-specific exceptions."""

from __future__ import annotations


class CorpusNotFoundError(LookupError):
    """Raised when a requested corpus has no on-disk SQLite file.

    The MCP retrieval / query tools raise this rather than returning empty
    hits with a warning, so a typo'd corpus_id never silently looks like
    "no relevant chunks".
    """

    def __init__(self, corpus_id: str, expected_path: str) -> None:
        super().__init__(
            f"Corpus {corpus_id!r} not found — no SQLite file at {expected_path!r}. "
            f"Ingest at least one document into this corpus before querying."
        )
        self.corpus_id = corpus_id
        self.expected_path = expected_path
