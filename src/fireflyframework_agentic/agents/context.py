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

"""Extended agent context carrying correlation IDs, experiment references, and metadata.

:class:`AgentContext` is designed to be passed as part of an agent's
dependencies so that observability, explainability, and experiment modules
can correlate events back to a single logical request.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """Contextual metadata that flows through an agent run.

    Typically created once per request and passed as (or embedded in) the
    agent's ``deps`` parameter.

    Attributes:
        correlation_id: A unique identifier tying together all events produced
            during a single logical request.  Generated automatically if not
            provided.
        experiment_id: When the run is part of an experiment, the experiment
            identifier is stored here so that results can be attributed.
        trace_id: An OpenTelemetry-compatible trace ID for distributed tracing.
        metadata: Arbitrary key-value pairs that travel with the request.
    """

    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    experiment_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
