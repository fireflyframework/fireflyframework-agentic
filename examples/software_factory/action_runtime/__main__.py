# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0
"""CLI entry point: `python -m software_factory.action_runtime`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from fireflyframework_agentic.exceptions import AgentNotFoundError

from .exceptions import ActionRuntimeError
from .runner import run_agent

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="factory-action-runtime")
    parser.add_argument("--agent", required=True, help="Registered agent name to run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _parse_args(argv)
    try:
        asyncio.run(run_agent(args.agent))
        return 0
    except ActionRuntimeError as e:
        sys.stderr.write(f"::error::{type(e).__name__}: {e}\n")
        return e.exit_code
    except AgentNotFoundError as e:
        sys.stderr.write(f"::error::AgentNotFoundError: {e}\n")
        return 1
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"::error::{type(e).__name__}: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
