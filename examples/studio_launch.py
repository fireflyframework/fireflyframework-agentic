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

"""Launch Firefly Studio.

Demonstrates three ways to start the Studio IDE:

1. CLI:            ``firefly studio``
2. Convenience:    ``launch_studio()``
3. Programmatic:   ``create_studio_app()`` + uvicorn

Requirements:
    pip install "fireflyframework-genai[studio]"
"""

from __future__ import annotations


def main() -> None:
    """Launch Studio with custom configuration."""
    import uvicorn

    from fireflyframework_genai.studio.config import StudioConfig
    from fireflyframework_genai.studio.server import create_studio_app

    config = StudioConfig(
        port=8470,
        host="127.0.0.1",
        open_browser=True,
        dev_mode=False,
        # projects_dir="/path/to/custom/projects",  # optional
    )

    app = create_studio_app(config=config)

    print(f"Firefly Studio running at http://{config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
