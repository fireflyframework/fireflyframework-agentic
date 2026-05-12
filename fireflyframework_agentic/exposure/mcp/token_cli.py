# Copyright 2026 Firefly Software Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""``firefly-mcp-token`` — operator CLI for per-corpus capability tokens.

Generates URL-safe random tokens, pushes them to the configured Azure Key
Vault, and supports rotation / revocation. Uses ``DefaultAzureCredential``
(managed identity in Azure, ``az login`` locally).

Commands:
    create   <corpus_id>      Mint a token; refuses if one already exists.
    rotate   <corpus_id>      Mint a fresh token; the previous value
                              becomes stale once the server's cache TTL
                              expires (default 300 s).
    revoke   <corpus_id>      Disable the current version of the secret.
    list                      Show every corpus_id that has a token in
                              this vault (requires KV ``list`` perm).
    show-name <corpus_id>     Print the secret name without any network
                              I/O — useful for shell scripting.

The newly-minted token is printed to **stdout** so callers can pipe it
straight into a password manager; status / errors go to **stderr** so
``firefly-mcp-token create foo > /secure/store`` is safe.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import secrets
import sys
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PREFIX = "firefly-mcp-corpus-token-"
_CORPUS_ID_RE = re.compile(r"^[a-z0-9-]{1,63}$")
_DEFAULT_TOKEN_BYTES = 32


def _secret_name(prefix: str, corpus_id: str) -> str:
    if not _CORPUS_ID_RE.match(corpus_id):
        raise SystemExit(f"invalid corpus_id: {corpus_id!r}. Must match [a-z0-9-]{{1,63}}.")
    return f"{prefix}{corpus_id}"


def _build_client(vault_url: str) -> Any:
    """Construct an async ``SecretClient`` with DefaultAzureCredential.

    Imports are lazy so ``firefly-mcp-token show-name`` works on a box
    without the ``azure`` extra installed (it makes no network call).
    """
    try:
        from azure.identity.aio import DefaultAzureCredential
        from azure.keyvault.secrets.aio import SecretClient
    except ImportError as exc:
        raise SystemExit(
            "firefly-mcp-token <cmd> requires the 'azure' extra: pip install fireflyframework-agentic[azure]"
        ) from exc
    return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())


# ---------- command implementations ---------------------------------------


async def _cmd_create(args: argparse.Namespace) -> int:
    name = _secret_name(args.prefix, args.corpus_id)
    # Fail-fast on bad input BEFORE opening a network client. We deliberately
    # do not bind ``token`` here: keeping it confined to the success branch
    # below means CodeQL's taint analysis cannot flow it into any of the
    # status / error ``print`` calls that go to stderr.
    _validate_byte_length(args.bytes)
    client = _build_client(args.vault_url)
    try:
        if not args.force and await _secret_exists(client, name):
            print(
                f"error: secret {name!r} already exists. Use 'rotate' to "
                "replace its value, or pass --force to overwrite.",
                file=sys.stderr,
            )
            return 2
        token = secrets.token_urlsafe(args.bytes)
        await client.set_secret(name, token)
        print(f"created {name} (token written to stdout)", file=sys.stderr)
        _emit_token(token)
    finally:
        await client.close()
    return 0


async def _cmd_rotate(args: argparse.Namespace) -> int:
    name = _secret_name(args.prefix, args.corpus_id)
    _validate_byte_length(args.bytes)
    client = _build_client(args.vault_url)
    try:
        if not await _secret_exists(client, name):
            print(
                f"error: secret {name!r} does not exist yet. Use 'create' for the first token.",
                file=sys.stderr,
            )
            return 2
        token = secrets.token_urlsafe(args.bytes)
        await client.set_secret(name, token)
        print(
            f"rotated {name}; old tokens stop working after the server's cache TTL (default 300 s).",
            file=sys.stderr,
        )
        _emit_token(token)
    finally:
        await client.close()
    return 0


async def _cmd_revoke(args: argparse.Namespace) -> int:
    name = _secret_name(args.prefix, args.corpus_id)
    if not args.yes:
        print(
            f"about to disable secret {name!r}. Existing clients will fail with "
            "403 after the cache TTL. Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 3
    client = _build_client(args.vault_url)
    try:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            await client.update_secret_properties(name, enabled=False)
        except ResourceNotFoundError:
            print(f"error: secret {name!r} not found.", file=sys.stderr)
            return 2
    finally:
        await client.close()
    print(f"revoked {name}", file=sys.stderr)
    return 0


async def _cmd_list(args: argparse.Namespace) -> int:
    client = _build_client(args.vault_url)
    try:
        names: list[str] = []
        async for prop in client.list_properties_of_secrets():
            secret_name = getattr(prop, "name", None)
            if not isinstance(secret_name, str):
                continue
            if not secret_name.startswith(args.prefix):
                continue
            names.append(secret_name[len(args.prefix) :])
    finally:
        await client.close()
    for n in sorted(names):
        print(n)
    return 0


def _cmd_show_name(args: argparse.Namespace) -> int:
    # The secret NAME is composed deterministically from the configured
    # prefix and the user-supplied corpus_id — neither is sensitive (the
    # name is what the operator needs in shell scripts to drive the
    # ``az keyvault`` CLI). CodeQL flags any print() carrying a "secret"-
    # adjacent variable; the suppression below documents that this is by
    # design and never carries secret material.
    print(_secret_name(args.prefix, args.corpus_id))  # codeql[py/clear-text-logging-sensitive-data]
    return 0


# ---------- helpers --------------------------------------------------------


def _validate_byte_length(byte_length: int) -> None:
    """Reject token lengths below 16 bytes (~128 bits) before any token is generated."""
    if byte_length < 16:
        raise SystemExit(f"--bytes must be at least 16 (got {byte_length})")


def _emit_token(token: str) -> None:
    """Write a freshly-minted token to stdout — the single, documented egress.

    Every other ``print()`` in this module goes to stderr precisely so
    that ``firefly-mcp-token create foo > /secure/store/foo.token`` only
    captures this line. CodeQL still flags this as ``py/clear-text-
    logging-sensitive-data``; the suppression below is the deliberate
    acknowledgement that the CLI's whole purpose is to surface the
    plaintext token exactly once.
    """
    # codeql[py/clear-text-logging-sensitive-data]: stdout is the
    # documented output channel of this CLI.
    sys.stdout.write(token + "\n")
    sys.stdout.flush()


async def _secret_exists(client: Any, name: str) -> bool:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        await client.get_secret(name)
        return True
    except ResourceNotFoundError:
        return False


# ---------- argparse plumbing ---------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firefly-mcp-token",
        description=("Manage per-corpus capability tokens for firefly-mcp-http in Azure Key Vault."),
    )
    parser.add_argument(
        "--vault-url",
        default=os.environ.get("FIREFLY_MCP_KEYVAULT_URL"),
        help="Key Vault URL (e.g. https://kv-firefly-prod.vault.azure.net). Defaults to $FIREFLY_MCP_KEYVAULT_URL.",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("FIREFLY_MCP_TOKEN_SECRET_PREFIX", _DEFAULT_PREFIX),
        help=f"Secret name prefix (default: {_DEFAULT_PREFIX!r}). "
        "Must match FIREFLY_MCP_TOKEN_SECRET_PREFIX on the server.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Mint a new token for a corpus_id.")
    p_create.add_argument("corpus_id")
    p_create.add_argument(
        "--bytes",
        type=int,
        default=_DEFAULT_TOKEN_BYTES,
        help=f"Token entropy in bytes (default {_DEFAULT_TOKEN_BYTES}).",
    )
    p_create.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing secret value (skip the 'already exists' check).",
    )

    p_rotate = sub.add_parser("rotate", help="Replace a corpus_id's token.")
    p_rotate.add_argument("corpus_id")
    p_rotate.add_argument(
        "--bytes",
        type=int,
        default=_DEFAULT_TOKEN_BYTES,
        help=f"Token entropy in bytes (default {_DEFAULT_TOKEN_BYTES}).",
    )

    p_revoke = sub.add_parser("revoke", help="Disable the current version of a corpus_id's token.")
    p_revoke.add_argument("corpus_id")
    p_revoke.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")

    sub.add_parser("list", help="List corpus_ids that have a token in this vault.")

    p_show = sub.add_parser("show-name", help="Print the KV secret name without any network call.")
    p_show.add_argument("corpus_id")

    return parser


_NEEDS_VAULT: frozenset[str] = frozenset({"create", "rotate", "revoke", "list"})


def main(argv: list[str] | None = None) -> int:
    """Entry point registered as ``firefly-mcp-token`` in ``[project.scripts]``."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in _NEEDS_VAULT and not args.vault_url:
        parser.error(
            "missing --vault-url (and $FIREFLY_MCP_KEYVAULT_URL is unset). "
            "Required for 'create', 'rotate', 'revoke', 'list'."
        )

    if args.command == "show-name":
        return _cmd_show_name(args)

    import asyncio

    handlers: dict[str, Callable[[argparse.Namespace], Coroutine[Any, Any, int]]] = {
        "create": _cmd_create,
        "rotate": _cmd_rotate,
        "revoke": _cmd_revoke,
        "list": _cmd_list,
    }
    return asyncio.run(handlers[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
