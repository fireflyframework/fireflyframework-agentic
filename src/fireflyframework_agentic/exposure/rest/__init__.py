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

"""REST exposure subpackage -- FastAPI app factory, router, middleware, streaming."""

from fireflyframework_agentic.exposure.rest.app import create_agentic_app
from fireflyframework_agentic.exposure.rest.schemas import AgentRequest, AgentResponse, HealthResponse

__all__ = [
    "AgentRequest",
    "AgentResponse",
    "HealthResponse",
    "create_agentic_app",
]
