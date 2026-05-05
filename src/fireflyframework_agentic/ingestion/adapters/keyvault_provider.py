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

"""Azure Key Vault secrets provider (optional, requires extra ``ingestion-keyvault``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fireflyframework_agentic.ingestion.exceptions import SecretNotFoundError

if TYPE_CHECKING:
    from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found]


class AzureKeyVaultSecretsProvider:
    """Resolves secrets from an Azure Key Vault.

    Lazy-imports the Azure SDK so the dependency is required only when the
    provider is actually constructed. Install with::

        pip install fireflyframework-agentic[ingestion-keyvault]
    """

    def __init__(self, vault_url: str, client: SecretClient | None = None) -> None:
        self._vault_url = vault_url
        self._client = client

    def _ensure_client(self) -> SecretClient:
        if self._client is not None:
            return self._client
        try:
            from azure.identity import DefaultAzureCredential  # type: ignore[import-not-found]
            from azure.keyvault.secrets import SecretClient  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "AzureKeyVaultSecretsProvider requires the "
                "'ingestion-keyvault' extra: "
                "pip install fireflyframework-agentic[ingestion-keyvault]"
            ) from exc
        self._client = SecretClient(
            vault_url=self._vault_url,
            credential=DefaultAzureCredential(),
        )
        return self._client

    def get(self, key: str) -> str:
        client = self._ensure_client()
        try:
            secret = client.get_secret(key)
        except Exception as exc:
            raise SecretNotFoundError(f"key vault {self._vault_url!r} does not contain secret {key!r}") from exc
        if secret.value is None:
            raise SecretNotFoundError(f"key vault secret {key!r} has no value")
        return secret.value
