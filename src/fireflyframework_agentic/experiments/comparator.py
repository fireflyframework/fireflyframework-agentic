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

"""Statistical comparison of experiment variants."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from fireflyframework_agentic.experiments.tracker import VariantResult


class ComparisonMetrics(BaseModel):
    """Comparison metrics for a single variant."""

    variant_name: str
    avg_latency_ms: float = 0.0
    total_runs: int = 0
    avg_output_length: float = 0.0


class VariantComparator:
    """Computes comparison metrics across experiment variants."""

    def compare(self, results: Sequence[VariantResult]) -> list[ComparisonMetrics]:
        """Generate comparison metrics for each variant result."""
        metrics: list[ComparisonMetrics] = []
        for r in results:
            avg_len = sum(len(o) for o in r.outputs) / len(r.outputs) if r.outputs else 0
            metrics.append(
                ComparisonMetrics(
                    variant_name=r.variant_name,
                    avg_latency_ms=r.avg_latency_ms,
                    total_runs=r.total_runs,
                    avg_output_length=avg_len,
                )
            )
        return metrics

    def summary(self, results: Sequence[VariantResult]) -> str:
        """Generate a human-readable comparison summary."""
        comparisons = self.compare(results)
        lines = ["Variant Comparison", "=" * 18, ""]
        for m in comparisons:
            lines.append(f"Variant: {m.variant_name}")
            lines.append(f"  Avg latency: {m.avg_latency_ms:.1f} ms")
            lines.append(f"  Total runs: {m.total_runs}")
            lines.append(f"  Avg output length: {m.avg_output_length:.0f} chars")
            lines.append("")
        return "\n".join(lines)
