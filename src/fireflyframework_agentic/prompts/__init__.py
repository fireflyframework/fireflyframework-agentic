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

"""Prompts subpackage -- templates, registry, composition, validation, and loading."""

from fireflyframework_agentic.prompts.composer import (
    ConditionalComposer,
    MergeComposer,
    SequentialComposer,
)
from fireflyframework_agentic.prompts.loader import PromptLoader
from fireflyframework_agentic.prompts.registry import PromptRegistry, prompt_registry
from fireflyframework_agentic.prompts.template import (
    PromptInfo,
    PromptTemplate,
    PromptVariable,
)
from fireflyframework_agentic.prompts.validator import PromptValidator, ValidationResult

__all__ = [
    "ConditionalComposer",
    "MergeComposer",
    "PromptInfo",
    "PromptLoader",
    "PromptRegistry",
    "PromptTemplate",
    "PromptValidator",
    "PromptVariable",
    "SequentialComposer",
    "ValidationResult",
    "prompt_registry",
]
