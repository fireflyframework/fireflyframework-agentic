# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Re-export shim. The canonical home is
``fireflyframework_agentic.rag.agent``. New code should import from there.
"""

from __future__ import annotations

from fireflyframework_agentic.rag.agent import CorpusAgent

__all__ = ["CorpusAgent"]
