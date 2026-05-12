# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.

"""Tests for the ``firefly-mcp-token`` operator CLI.

The Azure SDK is stubbed end-to-end so no live vault is required.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import pytest

pytest.importorskip("azure.keyvault.secrets.aio", reason="CLI lazy-imports the azure SDK")

from azure.core.exceptions import ResourceNotFoundError

from fireflyframework_agentic.exposure.mcp import token_cli


class _FakeSecret:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeProp:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSecretClient:
    """Async stand-in for ``SecretClient`` covering the methods the CLI uses."""

    def __init__(self, *, secrets: dict[str, str] | None = None) -> None:
        self.secrets: dict[str, str] = dict(secrets or {})
        self.disabled: set[str] = set()
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str]] = []
        self.update_calls: list[tuple[str, bool]] = []
        self.list_called = False

    async def get_secret(self, name: str) -> _FakeSecret:
        self.get_calls.append(name)
        if name not in self.secrets:
            raise ResourceNotFoundError(message=f"{name} not found")
        return _FakeSecret(self.secrets[name])

    async def set_secret(self, name: str, value: str) -> _FakeSecret:
        self.set_calls.append((name, value))
        self.secrets[name] = value
        return _FakeSecret(value)

    async def update_secret_properties(self, name: str, *, enabled: bool) -> None:
        if name not in self.secrets:
            raise ResourceNotFoundError(message=f"{name} not found")
        self.update_calls.append((name, enabled))
        if not enabled:
            self.disabled.add(name)

    def list_properties_of_secrets(self):
        self.list_called = True
        owner = self

        class _Iter:
            def __init__(self) -> None:
                self._items = [_FakeProp(n) for n in owner.secrets]

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self._items:
                    raise StopAsyncIteration
                return self._items.pop(0)

        return _Iter()

    async def close(self) -> None:
        return None


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch) -> _FakeSecretClient:
    client = _FakeSecretClient()
    monkeypatch.setattr(token_cli, "_build_client", lambda vault_url: client)
    return client


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = token_cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


# ---------- show-name (no network) ----------------------------------------


def test_show_name_composes_default_prefix() -> None:
    rc, out, _ = _run(["show-name", "real-data"])
    assert rc == 0
    assert out.strip() == "firefly-mcp-corpus-token-real-data"


def test_show_name_honours_custom_prefix() -> None:
    rc, out, _ = _run(["--prefix", "tenant-a-", "show-name", "demo"])
    assert rc == 0
    assert out.strip() == "tenant-a-demo"


def test_show_name_rejects_invalid_corpus_id() -> None:
    with pytest.raises(SystemExit, match="invalid corpus_id"):
        _run(["show-name", "Has Spaces"])


# ---------- create ---------------------------------------------------------


def test_create_writes_secret_and_prints_token_to_stdout(
    stub_client: _FakeSecretClient,
) -> None:
    rc, out, err = _run(["--vault-url", "https://kv.example", "create", "demo", "--bytes", "32"])
    assert rc == 0
    # The token lives on stdout (one line, urlsafe).
    token = out.strip()
    assert token and " " not in token and "/" not in token
    # KV write went through.
    assert stub_client.set_calls == [("firefly-mcp-corpus-token-demo", token)]
    # Status message went to stderr (so `> /secure/store` only catches the token).
    # The status line does NOT include the secret name (codeql autofix
    # simplified it to "created secret …") — this is fine: the operator
    # already typed the corpus_id, no need to echo it back.
    assert "created secret" in err
    assert token not in err  # token MUST NOT leak to stderr
    # Belt-and-braces: the customer-derived corpus_id MUST NOT appear in stderr
    # status messages either.
    assert "demo" not in err.split("(token", 1)[0]  # before the token-egress note


def test_create_refuses_if_secret_already_exists(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets["firefly-mcp-corpus-token-demo"] = "old"

    rc, out, err = _run(["--vault-url", "https://kv.example", "create", "demo"])
    assert rc == 2
    assert out == ""
    assert "already exists" in err
    assert stub_client.set_calls == []


def test_create_force_overwrites(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets["firefly-mcp-corpus-token-demo"] = "old"

    rc, out, _ = _run(["--vault-url", "https://kv.example", "create", "demo", "--force"])
    assert rc == 0
    new_token = out.strip()
    assert new_token != "old"
    assert stub_client.secrets["firefly-mcp-corpus-token-demo"] == new_token


def test_create_rejects_short_bytes() -> None:
    with pytest.raises(SystemExit, match="at least 16"):
        _run(["--vault-url", "https://kv.example", "create", "demo", "--bytes", "8"])


# ---------- rotate ---------------------------------------------------------


def test_rotate_replaces_existing(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets["firefly-mcp-corpus-token-demo"] = "old"

    rc, out, err = _run(["--vault-url", "https://kv.example", "rotate", "demo"])
    assert rc == 0
    new_token = out.strip()
    assert new_token != "old"
    assert stub_client.secrets["firefly-mcp-corpus-token-demo"] == new_token
    assert "rotated secret" in err
    assert "demo" not in err  # corpus_id not echoed back


def test_rotate_refuses_if_missing(stub_client: _FakeSecretClient) -> None:
    rc, out, err = _run(["--vault-url", "https://kv.example", "rotate", "demo"])
    assert rc == 2
    assert out == ""
    assert "does not exist" in err


# ---------- revoke ---------------------------------------------------------


def test_revoke_requires_yes(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets["firefly-mcp-corpus-token-demo"] = "tok"

    rc, _, err = _run(["--vault-url", "https://kv.example", "revoke", "demo"])
    assert rc == 3
    assert "Re-run with --yes" in err
    assert stub_client.disabled == set()  # no API call


def test_revoke_with_yes_disables_secret(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets["firefly-mcp-corpus-token-demo"] = "tok"

    rc, _, err = _run(["--vault-url", "https://kv.example", "revoke", "demo", "--yes"])
    assert rc == 0
    assert stub_client.update_calls == [("firefly-mcp-corpus-token-demo", False)]
    assert "firefly-mcp-corpus-token-demo" in stub_client.disabled
    assert "revoked" in err


def test_revoke_returns_2_when_missing(stub_client: _FakeSecretClient) -> None:
    rc, _, err = _run(["--vault-url", "https://kv.example", "revoke", "ghost", "--yes"])
    assert rc == 2
    assert "not found" in err


# ---------- list -----------------------------------------------------------


def test_list_returns_only_our_prefix(stub_client: _FakeSecretClient) -> None:
    stub_client.secrets.update(
        {
            "firefly-mcp-corpus-token-real-data": "x",
            "firefly-mcp-corpus-token-notes": "x",
            "unrelated-secret": "x",
        }
    )

    rc, out, _ = _run(["--vault-url", "https://kv.example", "list"])
    assert rc == 0
    lines = [line for line in out.splitlines() if line]
    assert lines == ["notes", "real-data"]  # sorted, prefix stripped
    assert stub_client.list_called


# ---------- argument parsing ----------------------------------------------


def test_vault_url_required_for_networked_commands() -> None:
    with pytest.raises(SystemExit):
        # argparse calls sys.exit(2) via parser.error
        _run(["create", "demo"])


def test_env_var_provides_default_vault_url(monkeypatch: pytest.MonkeyPatch, stub_client: _FakeSecretClient) -> None:
    monkeypatch.setenv("FIREFLY_MCP_KEYVAULT_URL", "https://from-env.example")
    rc, _, _ = _run(["create", "demo"])
    assert rc == 0


def test_token_never_appears_in_stderr_on_create(stub_client: _FakeSecretClient) -> None:
    """Regression guard: the only place the token may surface is stdout."""
    rc, out, err = _run(["--vault-url", "https://kv.example", "create", "demo"])
    assert rc == 0
    token = out.strip()
    assert token not in err
