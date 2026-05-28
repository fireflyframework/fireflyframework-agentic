"""Layer 7 of the unification (#245): StatePipeline deprecation.

Constructing :class:`StatePipeline` now emits a :class:`DeprecationWarning`
pointing at :class:`PipelineEngine` configured with ``state_schema=`` as
the supported replacement.
"""

from __future__ import annotations

import warnings

from pydantic import BaseModel

from fireflyframework_agentic.pipeline.builder import PipelineBuilder


class _S(BaseModel):
    x: int = 0


async def _noop(state):
    return None


def test_state_pipeline_emits_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        PipelineBuilder("p", state=_S).add_node(_noop).build()
    deprec = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert deprec, "expected a DeprecationWarning when constructing StatePipeline"
    assert "PipelineEngine" in str(deprec[0].message)
    assert "#245" in str(deprec[0].message)
