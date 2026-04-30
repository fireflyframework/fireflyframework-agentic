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

"""Structured explainability reports.

:class:`ExplainabilityReport` generates Markdown or JSON reports that
summarise an agent's decision-making process with all supporting evidence.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from fireflyframework_agentic.explainability.explanation import ExplanationGenerator
from fireflyframework_agentic.explainability.trace_recorder import DecisionRecord


class ReportSection(BaseModel):
    """A section within an explainability report."""

    title: str
    content: str


class ExplainabilityReport(BaseModel):
    """A complete explainability report."""

    title: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str = ""
    sections: list[ReportSection] = []
    raw_records: list[DecisionRecord] = []


class ReportBuilder:
    """Builds :class:`ExplainabilityReport` from decision records.

    Parameters:
        title: Report title.
    """

    def __init__(self, title: str = "Explainability Report") -> None:
        self._title = title
        self._generator = ExplanationGenerator()

    def build(self, records: Sequence[DecisionRecord]) -> ExplainabilityReport:
        """Build a report from the given decision records."""
        narrative = self._generator.generate(records)

        sections = [
            ReportSection(title="Narrative Explanation", content=narrative),
            ReportSection(
                title="Statistics",
                content=self._build_stats(records),
            ),
        ]

        return ExplainabilityReport(
            title=self._title,
            summary=f"Report covering {len(records)} decision points.",
            sections=sections,
            raw_records=list(records),
        )

    def _build_stats(self, records: Sequence[DecisionRecord]) -> str:
        """Build a statistics summary."""
        categories: dict[str, int] = {}
        for r in records:
            categories[r.category] = categories.get(r.category, 0) + 1
        lines = [f"Total decisions: {len(records)}"]
        for cat, count in sorted(categories.items()):
            lines.append(f"  {cat}: {count}")
        return "\n".join(lines)

    @staticmethod
    def to_markdown(report: ExplainabilityReport) -> str:
        """Render the report as Markdown."""
        lines = [f"# {report.title}", ""]
        lines.append(f"Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("")
        if report.summary:
            lines.append(report.summary)
            lines.append("")
        for section in report.sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def to_json(report: ExplainabilityReport) -> str:
        """Render the report as JSON."""
        return json.dumps(report.model_dump(mode="json"), indent=2, default=str)
