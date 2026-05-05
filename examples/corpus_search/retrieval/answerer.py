# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Re-export shim. The canonical home is
``fireflyframework_agentic.rag.retrieval.answerer``. This shim exists so
the example's CLI and historical test imports keep working unchanged.
New code should import from the library path.
"""

from __future__ import annotations

from fireflyframework_agentic.rag.retrieval.answerer import (
    Answer,
    AnswerAgent,
    CitedSource,
    format_chunks_for_prompt,
)

__all__ = ["Answer", "AnswerAgent", "CitedSource", "format_chunks_for_prompt"]
