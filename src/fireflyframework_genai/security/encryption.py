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

"""Encryption providers for sensitive data at rest.

This module provides encryption capabilities for protecting sensitive data
stored in memory backends, configuration files, and logs.

Features:
- AES-256-GCM encryption (authenticated encryption)
- Base64 encoding for safe storage
- Key derivation from passwords
- Memory store wrapper for transparent encryption

Example:
    Basic encryption::

        from fireflyframework_genai.security.encryption import AESEncryptionProvider

        provider = AESEncryptionProvider(key="my-secret-key-32-bytes-long!!")

        # Encrypt
        encrypted = provider.encrypt("sensitive data")

        # Decrypt
        decrypted = provider.decrypt(encrypted)

    Encrypted memory store::

        from fireflyframework_genai.security.encryption import EncryptedMemoryStore
        from fireflyframework_genai.memory.store import InMemoryStore

        # Wrap any memory store with encryption
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        # Use like a normal store - encryption is transparent
        encrypted_store.save("namespace", entry)
        loaded = encrypted_store.load("namespace")
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Protocol, runtime_checkable

from fireflyframework_genai.memory.types import MemoryEntry

logger = logging.getLogger(__name__)


@runtime_checkable
class EncryptionProvider(Protocol):
    """Protocol for encryption/decryption providers.

    Implementations must provide symmetric encryption with authentication
    (e.g., AES-GCM) to ensure both confidentiality and integrity.
    """

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext and return base64-encoded ciphertext.

        Args:
            plaintext: String to encrypt.

        Returns:
            Base64-encoded encrypted data (safe for storage).
        """
        ...

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt base64-encoded ciphertext and return plaintext.

        Args:
            ciphertext: Base64-encoded encrypted data.

        Returns:
            Decrypted plaintext string.

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data).
        """
        ...


class AESEncryptionProvider:
    """AES-256-GCM encryption provider.

    Provides authenticated encryption using AES-256 in GCM mode, which ensures
    both confidentiality and integrity. Each encryption operation uses a
    random nonce to ensure uniqueness.

    Parameters:
        key: 32-byte encryption key (for AES-256). If a string is provided
            and it's not 32 bytes, it will be derived using PBKDF2.

    Example::

        # With explicit 32-byte key
        provider = AESEncryptionProvider(key=b"12345678901234567890123456789012")

        # With password (auto-derives 32-byte key)
        provider = AESEncryptionProvider(key="my-password")

        encrypted = provider.encrypt("sensitive data")
        decrypted = provider.decrypt(encrypted)

    Note:
        Requires the optional ``security`` dependency group:
        ``pip install fireflyframework-genai[security]``
    """

    def __init__(self, key: str | bytes) -> None:
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        except ImportError as exc:
            raise ImportError(
                "Encryption support requires 'cryptography'. Install with: pip install fireflyframework-genai[security]"
            ) from exc

        # Derive 32-byte key if needed
        key_bytes = key.encode("utf-8") if isinstance(key, str) else key

        if len(key_bytes) != 32:
            # Use PBKDF2 to derive a 32-byte key from the password
            logger.debug("Deriving 32-byte key from provided key using PBKDF2")
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"firefly_genai_salt",  # Fixed salt (not ideal for high security)
                iterations=100_000,
            )
            key_bytes = kdf.derive(key_bytes)

        self._cipher = AESGCM(key_bytes)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext using AES-256-GCM.

        Args:
            plaintext: String to encrypt.

        Returns:
            Base64-encoded string containing: nonce + ciphertext + tag
        """
        import os

        # Generate random 12-byte nonce (recommended for GCM)
        nonce = os.urandom(12)

        # Encrypt (returns ciphertext + 16-byte authentication tag)
        plaintext_bytes = plaintext.encode("utf-8")
        ciphertext = self._cipher.encrypt(nonce, plaintext_bytes, None)

        # Combine nonce + ciphertext for storage
        encrypted_data = nonce + ciphertext

        # Base64 encode for safe storage
        return base64.b64encode(encrypted_data).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt AES-256-GCM ciphertext.

        Args:
            ciphertext: Base64-encoded encrypted data.

        Returns:
            Decrypted plaintext string.

        Raises:
            ValueError: If decryption fails (wrong key, corrupted data, tampered data).
        """
        try:
            # Base64 decode
            encrypted_data = base64.b64decode(ciphertext.encode("ascii"))

            # Split nonce and ciphertext
            nonce = encrypted_data[:12]
            ciphertext_bytes = encrypted_data[12:]

            # Decrypt (automatically verifies authentication tag)
            plaintext_bytes = self._cipher.decrypt(nonce, ciphertext_bytes, None)

            return plaintext_bytes.decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Decryption failed: {exc}") from exc


class EncryptedMemoryStore:
    """Transparent encryption wrapper for any MemoryStore.

    Wraps any memory store implementation and automatically encrypts/decrypts
    the content field of MemoryEntry objects. All other fields (metadata, keys,
    etc.) remain unencrypted for indexing and querying.

    Parameters:
        store: Underlying MemoryStore to wrap.
        encryption_key: Encryption key (32 bytes for AES-256, or password).
        provider: Optional custom EncryptionProvider. If None, uses AESEncryptionProvider.

    Example::

        from fireflyframework_genai.memory.store import InMemoryStore
        from fireflyframework_genai.security.encryption import EncryptedMemoryStore

        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(
            base_store,
            encryption_key="my-secret-key"
        )

        # Use normally - encryption is transparent
        entry = MemoryEntry(key="api_key", content="sk-secret123")
        encrypted_store.save("namespace", entry)

        # Content is encrypted in base_store, but decrypted when loaded
        loaded = encrypted_store.load_by_key("namespace", "api_key")
        assert loaded.content == "sk-secret123"

    Note:
        Only the ``content`` field is encrypted. Metadata, keys, timestamps,
        and other fields remain plaintext for efficient querying.
    """

    def __init__(
        self,
        store: Any,
        encryption_key: str | bytes,
        provider: EncryptionProvider | None = None,
    ) -> None:
        self._store = store
        self._provider = provider or AESEncryptionProvider(encryption_key)

    def save(self, namespace: str, entry: MemoryEntry) -> None:
        """Save entry with encrypted content."""
        # Create a copy with encrypted content
        encrypted_entry = entry.model_copy()

        if encrypted_entry.content is not None:
            # Convert content to string if needed
            content_str = (
                str(encrypted_entry.content)
                if not isinstance(encrypted_entry.content, str)
                else encrypted_entry.content
            )

            # Encrypt
            encrypted_entry.content = self._provider.encrypt(content_str)

        # Save encrypted entry
        self._store.save(namespace, encrypted_entry)

    def load(self, namespace: str) -> list[MemoryEntry]:
        """Load entries and decrypt content."""
        encrypted_entries = self._store.load(namespace)
        return [self._decrypt_entry(entry) for entry in encrypted_entries]

    def load_by_key(self, namespace: str, key: str) -> MemoryEntry | None:
        """Load entry by key and decrypt content."""
        encrypted_entry = self._store.load_by_key(namespace, key)

        if encrypted_entry is None:
            return None

        return self._decrypt_entry(encrypted_entry)

    def delete(self, namespace: str, entry_id: str) -> None:
        """Delete entry (no encryption needed)."""
        self._store.delete(namespace, entry_id)

    def clear(self, namespace: str) -> None:
        """Clear namespace (no encryption needed)."""
        self._store.clear(namespace)

    def _decrypt_entry(self, entry: MemoryEntry) -> MemoryEntry:
        """Decrypt the content field of an entry."""
        if entry.content is None:
            return entry

        # Create a copy
        decrypted_entry = entry.model_copy()

        try:
            # Decrypt content
            decrypted_entry.content = self._provider.decrypt(str(entry.content))
        except ValueError as exc:
            logger.error(
                "Failed to decrypt entry %s: %s. Returning encrypted content.",
                entry.entry_id,
                exc,
            )
            # Return entry with encrypted content as-is
            # (better than failing completely)

        return decrypted_entry


def create_encryption_provider_from_config() -> EncryptionProvider | None:
    """Create an encryption provider from framework configuration.

    Returns:
        EncryptionProvider instance if encryption is enabled, None otherwise.
    """
    from fireflyframework_genai.config import get_config

    cfg = get_config()

    if not cfg.encryption_enabled or not cfg.encryption_key:
        return None

    return AESEncryptionProvider(key=cfg.encryption_key)


# Module-level default instance
default_encryption_provider: EncryptionProvider | None = create_encryption_provider_from_config()
