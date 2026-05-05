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

"""Tests for secret-provider adapters."""

import pytest

from fireflyframework_agentic.ingestion.adapters import EnvSecretsProvider
from fireflyframework_agentic.ingestion.exceptions import SecretNotFoundError
from fireflyframework_agentic.ingestion.ports import SecretsProvider


def test_env_provider_returns_value():
    p = EnvSecretsProvider({"FOO": "bar"})
    assert p.get("FOO") == "bar"


def test_env_provider_missing_key_raises_secret_not_found():
    p = EnvSecretsProvider({})
    with pytest.raises(SecretNotFoundError, match="FOO"):
        p.get("FOO")


def test_env_provider_satisfies_protocol():
    p = EnvSecretsProvider({})
    assert isinstance(p, SecretsProvider)


def test_env_provider_uses_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("INGESTION_TEST_KEY", "from_environ")
    p = EnvSecretsProvider()
    assert p.get("INGESTION_TEST_KEY") == "from_environ"


def test_secret_not_found_is_a_key_error_subclass():
    p = EnvSecretsProvider({})
    with pytest.raises(KeyError):
        p.get("MISSING")
