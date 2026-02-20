#!/usr/bin/env python3
"""PyInstaller entry point for Firefly Studio desktop app.

Thin wrapper that invokes the Studio CLI with arguments suitable
for desktop sidecar operation (host, port, no-browser).
"""

import sys


def main() -> None:
    """Launch Firefly Studio as a desktop sidecar process."""
    from fireflyframework_genai.studio.cli import main as studio_main

    studio_main(sys.argv[1:])


if __name__ == "__main__":
    main()
