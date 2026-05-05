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

"""Environment-variable based secrets provider (default implementation)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from fireflyframework_agentic.ingestion.exceptions import SecretNotFoundError


class EnvSecretsProvider:
    """Resolves secrets from environment variables.

    The provider can be created against an explicit mapping (useful for
    tests) or against the live ``os.environ`` (default).
    """

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: Mapping[str, str] = env if env is not None else os.environ

    def get(self, key: str) -> str:
        try:
            return self._env[key]
        except KeyError as exc:
            raise SecretNotFoundError(f"environment variable {key!r} is not set") from exc
