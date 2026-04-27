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

"""Generate human-readable explanations from decision traces.

:class:`ExplanationGenerator` takes a list of
:class:`~fireflyframework_agentic.explainability.trace_recorder.DecisionRecord`
objects and produces a narrative description of the agent's decision-making
process.
"""

from __future__ import annotations

from collections.abc import Sequence

from fireflyframework_agentic.explainability.trace_recorder import DecisionRecord


class ExplanationGenerator:
    """Produces human-readable explanations from decision records.

    The generator walks through each record chronologically and builds a
    narrative that describes what the agent did and why.
    """

    def generate(self, records: Sequence[DecisionRecord]) -> str:
        """Create a narrative explanation from *records*.

        Returns a multi-line string suitable for display or inclusion in
        a report.
        """
        if not records:
            return "No decision records available to explain."

        lines: list[str] = ["Decision Explanation", "=" * 21, ""]
        for i, rec in enumerate(records, 1):
            ts = rec.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines.append(f"Step {i} [{ts}] -- {rec.category}")
            if rec.agent:
                lines.append(f"  Agent: {rec.agent}")
            if rec.input_summary:
                lines.append(f"  Input: {rec.input_summary}")
            if rec.output_summary:
                lines.append(f"  Output: {rec.output_summary}")
            if rec.detail:
                for k, v in rec.detail.items():
                    lines.append(f"  {k}: {v}")
            lines.append("")

        return "\n".join(lines)
