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

"""Pre-built template agents -- configurable, opinionated, and ready to use.

Each factory function returns a fully-configured :class:`FireflyAgent`
with purpose-built instructions, tags, and optional tools or output types.
Users can customise model, instructions, and behaviour via keyword arguments.
"""

from fireflyframework_agentic.agents.templates.classifier import create_classifier_agent
from fireflyframework_agentic.agents.templates.conversational import create_conversational_agent
from fireflyframework_agentic.agents.templates.extractor import create_extractor_agent
from fireflyframework_agentic.agents.templates.router import create_router_agent
from fireflyframework_agentic.agents.templates.summarizer import create_summarizer_agent

__all__ = [
    "create_classifier_agent",
    "create_conversational_agent",
    "create_extractor_agent",
    "create_router_agent",
    "create_summarizer_agent",
]
