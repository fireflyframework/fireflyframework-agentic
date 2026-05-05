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

"""Concrete adapters for the ingestion module.

The two secret-resolution adapters live at the top level of this package
(``env_provider``, ``keyvault_provider``) rather than under a subpackage:
the domain has only two implementations and a flat layout reads more
directly. The other adapter families have their own subpackages
(``sources``, ``mappers``, ``sinks``) because we anticipate multiple
implementations of each.
"""

from fireflyframework_agentic.ingestion.adapters.env_provider import (
    EnvSecretsProvider,
)

__all__ = ["EnvSecretsProvider"]
