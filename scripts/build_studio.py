#!/usr/bin/env python3
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

"""Build and bundle the Firefly Studio frontend into the Python package.

Usage::

    python scripts/build_studio.py

This script:
1. Runs ``npm run build`` in ``studio-frontend/``
2. Copies the build output to ``src/fireflyframework_genai/studio/static/``
3. The server then serves these files via FastAPI's StaticFiles mount.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# Resolve paths relative to the repository root.
REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = REPO_ROOT / "studio-frontend"
BUILD_DIR = FRONTEND_DIR / "build"
STATIC_DIR = REPO_ROOT / "src" / "fireflyframework_genai" / "studio" / "static"


def main() -> None:
    """Build the frontend and copy to the static directory."""
    # 1. Install dependencies if needed
    if not (FRONTEND_DIR / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run(
            ["npm", "install"],
            cwd=FRONTEND_DIR,
            check=True,
        )

    # 2. Build the frontend
    print("Building Studio frontend...")
    subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND_DIR,
        check=True,
    )

    if not BUILD_DIR.exists():
        print("ERROR: Build directory not found at", BUILD_DIR, file=sys.stderr)
        sys.exit(1)

    # 3. Clear existing static files (except .gitkeep)
    if STATIC_DIR.exists():
        for item in STATIC_DIR.iterdir():
            if item.name == ".gitkeep":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # 4. Copy build output to static directory
    print(f"Copying build output to {STATIC_DIR}...")
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    for item in BUILD_DIR.iterdir():
        dest = STATIC_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    # Count files
    file_count = sum(1 for _ in STATIC_DIR.rglob("*") if _.is_file() and _.name != ".gitkeep")
    print(f"Bundled {file_count} files into {STATIC_DIR}")
    print("Done! The Studio frontend is now bundled into the Python package.")


if __name__ == "__main__":
    main()
