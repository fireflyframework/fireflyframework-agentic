# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""Parse `INPUT_*` env vars set by GitHub Actions for Docker actions."""
from __future__ import annotations

import os


def read_action_inputs() -> dict[str, str]:
    """Return a dict of action inputs keyed by lowercase name.

    GitHub sets one env var per declared input, named `INPUT_<NAME>` where
    `<NAME>` is uppercase and any non-alphanumeric characters in the input
    name are replaced with underscores. We strip the prefix and lowercase
    the key so callers can build a Pydantic model from the result.
    """
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith("INPUT_"):
            continue
        out[key[len("INPUT_"):].lower()] = value
    return out
