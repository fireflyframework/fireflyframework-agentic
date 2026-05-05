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

"""SQL identifier validation for safe interpolation into queries.

Database adapters that need to interpolate identifiers (table names,
column names, schema names) into SQL strings must first validate them
against this regex. Values are always parameterized — only identifiers
go through string interpolation, and only after passing this check.
"""

from __future__ import annotations

import re

_SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_identifier(name: str) -> str:
    """Return *name* unchanged if it is a safe SQL identifier; raise otherwise.

    A safe identifier is a string matching ``[a-zA-Z_][a-zA-Z0-9_]*``.
    This excludes whitespace, punctuation, quotes, and any character that
    could break out of a quoted identifier or alter SQL parsing.

    Raises:
        ValueError: If *name* does not match the safe pattern.
    """
    if not _SAFE_IDENTIFIER.match(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name
