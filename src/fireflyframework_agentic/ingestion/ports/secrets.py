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

"""SecretsProvider: protocol for resolving secrets at runtime."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretsProvider(Protocol):
    """Resolves secret values by symbolic name.

    Implementations may read from environment variables, a cloud key vault,
    a dotenv file, or any other source. The framework only requires that
    :meth:`get` returns a string for every key referenced by configuration
    and raises :class:`KeyError` (or a subclass) for missing keys.
    """

    def get(self, key: str) -> str:
        """Return the secret value associated with *key*."""
        ...
