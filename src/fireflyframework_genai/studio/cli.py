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

"""CLI entry point for Firefly Studio.

Usage::

    firefly studio
    firefly studio --port 9000 --host 0.0.0.0 --no-browser
    firefly --port 9000          # implicit "studio" subcommand
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Supports both explicit subcommand form (``firefly studio --port 9000``)
    and the convenience form (``firefly --port 9000``), which defaults to
    the ``studio`` subcommand.
    """
    parser = argparse.ArgumentParser(
        prog="firefly",
        description="Firefly GenAI Framework CLI",
    )

    subparsers = parser.add_subparsers(dest="command")

    # "studio" subcommand
    studio_parser = subparsers.add_parser("studio", help="Launch Firefly Studio")
    _add_studio_args(studio_parser)

    # Also add studio args to the top-level parser for convenience
    _add_studio_args(parser)

    args = parser.parse_args(argv)

    # Default to "studio" when no subcommand is given
    if args.command is None:
        args.command = "studio"

    return args


def _add_studio_args(parser: argparse.ArgumentParser) -> None:
    """Add Studio-specific arguments to a parser."""
    parser.add_argument(
        "--port",
        type=int,
        default=8470,
        help="Port to serve on (default: 8470)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Do not open browser automatically",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        default=False,
        help="Enable development mode (verbose logging)",
    )


def _open_browser_after_delay(url: str, delay: float = 1.5) -> None:
    """Open the browser after a short delay, running in a daemon thread."""

    def _open() -> None:
        import time

        time.sleep(delay)
        webbrowser.open(url)

    thread = threading.Thread(target=_open, daemon=True)
    thread.start()


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``firefly`` command."""
    args = parse_args(argv)

    if args.command == "studio":
        _run_studio(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)


def _run_studio(args: argparse.Namespace) -> None:
    """Launch the Firefly Studio server."""
    import uvicorn  # type: ignore[import-not-found]

    from fireflyframework_genai.studio.config import StudioConfig
    from fireflyframework_genai.studio.server import create_studio_app

    config = StudioConfig(
        _env_file=None,  # type: ignore[call-arg]  # pydantic-settings init kwarg
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        dev_mode=args.dev,
        log_level="debug" if args.dev else "info",
    )

    app = create_studio_app(config=config)

    url = f"http://{config.host}:{config.port}"
    print(f"Firefly Studio running at {url}")

    if config.open_browser:
        _open_browser_after_delay(url)

    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level,
    )
