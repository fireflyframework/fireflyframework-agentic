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

"""``firefly-ingest`` command-line entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from fireflyframework_agentic.ingestion.config import IngestionConfig, build_service
from fireflyframework_agentic.ingestion.exceptions import IngestionError

logger = logging.getLogger("firefly_ingest")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firefly-ingest",
        description="Run an ingestion pipeline against a structured target schema.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable DEBUG logging")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="execute an ingestion run")
    run.add_argument("--config", type=Path, required=True, help="path to ingestion.yaml")
    run.add_argument(
        "--full",
        action="store_true",
        help="ignore the persisted delta cursor and re-list everything",
    )

    status = sub.add_parser("status", help="show cache + script coverage")
    status.add_argument("--config", type=Path, required=True)

    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run_command(config_path: Path, full: bool) -> int:
    config = IngestionConfig.from_yaml(config_path)
    service = build_service(config)
    if full:
        result = await service.run_full_rebuild()
    else:
        result = await service.run_incremental()
    print(f"files_processed: {result.files_processed}")
    print(f"records_written: {dict(result.records_written)}")
    print(f"errors: {len(result.errors)}")
    for err in result.errors:
        print(f"  - [{err.kind}] {err.message}")
    return 0 if not result.errors else 2


async def _status_command(config_path: Path) -> int:
    config = IngestionConfig.from_yaml(config_path)
    cache = config.state.cache_dir
    delta = config.state.delta_file
    scripts = config.mapper.scripts_dir
    n_files = sum(1 for _ in cache.rglob("*")) if cache.exists() else 0
    n_scripts = sum(1 for p in scripts.glob("*.py") if not p.name.startswith("_")) if scripts.exists() else 0
    has_delta = delta.exists()
    print(f"cache_dir: {cache} ({n_files} entries)")
    print(f"scripts_dir: {scripts} ({n_scripts} mapping scripts)")
    print(f"delta_file: {delta} ({'present' if has_delta else 'missing'})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    try:
        if args.command == "run":
            return asyncio.run(_run_command(args.config, args.full))
        if args.command == "status":
            return asyncio.run(_status_command(args.config))
    except IngestionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
