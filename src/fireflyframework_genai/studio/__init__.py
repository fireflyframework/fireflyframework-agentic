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

"""Firefly Studio -- visual agent IDE for the Firefly GenAI framework."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fireflyframework_genai.studio.config import StudioConfig

__all__ = [
    "StudioConfig",
    "launch_studio",
]


def __getattr__(name: str) -> object:
    if name == "StudioConfig":
        from fireflyframework_genai.studio.config import StudioConfig

        return StudioConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def launch_studio() -> None:
    """Launch the Firefly Studio server.

    Convenience wrapper that delegates to the CLI entry point.
    """
    from fireflyframework_genai.studio.cli import main

    main(["studio"])
