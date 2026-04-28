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

"""Unit tests for encryption."""

from __future__ import annotations

import pytest

# Check if cryptography is available
pytest.importorskip("cryptography", reason="Encryption tests require cryptography")

from fireflyframework_agentic.memory.store import InMemoryStore
from fireflyframework_agentic.memory.types import MemoryEntry, MemoryScope
from fireflyframework_agentic.security.encryption import AESEncryptionProvider, EncryptedMemoryStore


class TestAESEncryptionProvider:
    """Test suite for AESEncryptionProvider."""

    def test_encrypt_decrypt_round_trip(self):
        """Test that encryption/decryption preserves data."""
        provider = AESEncryptionProvider(key="my-secret-key-32-bytes-long!!")

        plaintext = "sensitive data"
        encrypted = provider.encrypt(plaintext)
        decrypted = provider.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_encryption_produces_different_output(self):
        """Test that each encryption produces unique output (due to random nonce)."""
        provider = AESEncryptionProvider(key="my-secret-key-32-bytes-long!!")

        plaintext = "test data"
        encrypted1 = provider.encrypt(plaintext)
        encrypted2 = provider.encrypt(plaintext)

        assert encrypted1 != encrypted2  # Different nonces

    def test_key_derivation(self):
        """Test that short keys are derived to 32 bytes."""
        provider = AESEncryptionProvider(key="short-key")

        plaintext = "test"
        encrypted = provider.encrypt(plaintext)
        decrypted = provider.decrypt(encrypted)

        assert decrypted == plaintext

    def test_wrong_key_fails_decryption(self):
        """Test that decryption with wrong key fails."""
        provider1 = AESEncryptionProvider(key="key1")
        provider2 = AESEncryptionProvider(key="key2")

        encrypted = provider1.encrypt("secret")

        with pytest.raises(ValueError, match="Decryption failed"):
            provider2.decrypt(encrypted)

    def test_tampered_ciphertext_fails(self):
        """Test that tampered ciphertext is detected."""
        provider = AESEncryptionProvider(key="my-secret-key")

        encrypted = provider.encrypt("data")
        # Tamper with the ciphertext
        tampered = encrypted[:-4] + "XXXX"

        with pytest.raises(ValueError, match="Decryption failed"):
            provider.decrypt(tampered)

    def test_unicode_support(self):
        """Test encryption of Unicode strings."""
        provider = AESEncryptionProvider(key="key")

        plaintext = "Hello 世界 🔒"
        encrypted = provider.encrypt(plaintext)
        decrypted = provider.decrypt(encrypted)

        assert decrypted == plaintext


class TestEncryptedMemoryStore:
    """Test suite for EncryptedMemoryStore."""

    def test_save_and_load_with_encryption(self):
        """Test that data is encrypted when saved and decrypted when loaded."""
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        entry = MemoryEntry(
            key="api_key",
            content="sk-secret123",
            scope=MemoryScope.WORKING,
        )

        # Save through encrypted store
        encrypted_store.save("namespace", entry)

        # Verify content is encrypted in base store
        base_entries = base_store.load("namespace")
        assert len(base_entries) == 1
        assert base_entries[0].content != "sk-secret123"  # Should be encrypted

        # Load through encrypted store - should decrypt
        loaded_entries = encrypted_store.load("namespace")
        assert len(loaded_entries) == 1
        assert loaded_entries[0].content == "sk-secret123"  # Should be decrypted

    def test_load_by_key_decrypts(self):
        """Test that load_by_key decrypts content."""
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        entry = MemoryEntry(key="password", content="super-secret")
        encrypted_store.save("namespace", entry)

        loaded = encrypted_store.load_by_key("namespace", "password")
        assert loaded is not None
        assert loaded.content == "super-secret"

    def test_metadata_not_encrypted(self):
        """Test that metadata and other fields are not encrypted."""
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        entry = MemoryEntry(
            key="test_key",
            content="secret",
            metadata={"tag": "important"},
        )

        encrypted_store.save("namespace", entry)

        # Check base store - metadata should be plaintext
        base_entries = base_store.load("namespace")
        assert base_entries[0].key == "test_key"  # Not encrypted
        assert base_entries[0].metadata == {"tag": "important"}  # Not encrypted

    def test_delete_and_clear_work(self):
        """Test that delete and clear operations work."""
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        entry = MemoryEntry(key="test", content="data")
        encrypted_store.save("namespace", entry)

        # Delete specific entry
        encrypted_store.delete("namespace", entry.entry_id)
        assert encrypted_store.load("namespace") == []

        # Clear namespace
        encrypted_store.save("namespace", entry)
        encrypted_store.clear("namespace")
        assert encrypted_store.load("namespace") == []

    def test_none_content_not_encrypted(self):
        """Test that None content is handled gracefully."""
        base_store = InMemoryStore()
        encrypted_store = EncryptedMemoryStore(base_store, encryption_key="secret")

        entry = MemoryEntry(key="test", content=None)
        encrypted_store.save("namespace", entry)

        loaded = encrypted_store.load("namespace")
        assert loaded[0].content is None
