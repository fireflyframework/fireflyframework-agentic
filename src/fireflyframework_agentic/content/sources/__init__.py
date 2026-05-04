# Copyright 2026 Firefly Software Foundation
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

"""Content sources: external systems that yield files for ingestion.

The :class:`ContentSource` Protocol is the stable contract; concrete
implementations such as :class:`SharePointSource` may live in this package
today and migrate to a dedicated infrastructure repository in the future
without changes to the Protocol or to consumer code.
"""

from __future__ import annotations

from fireflyframework_agentic.content.sources.base import ContentSource, RawFile
from fireflyframework_agentic.content.sources.s3 import S3Source, S3SourceConfig
from fireflyframework_agentic.content.sources.sharepoint import (
    SharePointSource,
    SharePointSourceConfig,
)

__all__ = [
    "ContentSource",
    "RawFile",
    "S3Source",
    "S3SourceConfig",
    "SharePointSource",
    "SharePointSourceConfig",
]
