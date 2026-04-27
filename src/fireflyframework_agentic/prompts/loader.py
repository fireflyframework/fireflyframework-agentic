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

"""Load prompt templates from the filesystem or inline strings.

:class:`PromptLoader` provides factory methods for creating
:class:`PromptTemplate` instances from various sources.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from fireflyframework_agentic.prompts.template import PromptTemplate, PromptVariable

logger = logging.getLogger(__name__)


class PromptLoader:
    """Utility for loading prompt templates from different sources."""

    @staticmethod
    def from_string(
        name: str,
        template_str: str,
        *,
        version: str = "1.0.0",
        description: str = "",
        variables: Sequence[PromptVariable] = (),
    ) -> PromptTemplate:
        """Create a :class:`PromptTemplate` from an inline string."""
        return PromptTemplate(
            name,
            template_str,
            version=version,
            description=description,
            variables=variables,
        )

    @staticmethod
    def from_file(
        path: str | Path,
        *,
        name: str | None = None,
        version: str = "1.0.0",
        description: str = "",
        variables: Sequence[PromptVariable] = (),
    ) -> PromptTemplate:
        """Create a :class:`PromptTemplate` by reading a file.

        The template name defaults to the file stem (filename without
        extension).
        """
        file_path = Path(path)
        template_str = file_path.read_text(encoding="utf-8")
        resolved_name = name or file_path.stem
        return PromptTemplate(
            resolved_name,
            template_str,
            version=version,
            description=description,
            variables=variables,
        )

    @staticmethod
    def from_directory(
        directory: str | Path,
        *,
        glob_pattern: str = "*.j2",
        version: str = "1.0.0",
    ) -> list[PromptTemplate]:
        """Load all templates matching *glob_pattern* from *directory*.

        Each file becomes a template whose name is the file stem.
        """
        dir_path = Path(directory)
        templates: list[PromptTemplate] = []
        for file_path in sorted(dir_path.glob(glob_pattern)):
            if file_path.is_file():
                template = PromptLoader.from_file(file_path, version=version)
                templates.append(template)
                logger.debug("Loaded prompt template '%s' from %s", template.name, file_path)
        return templates
