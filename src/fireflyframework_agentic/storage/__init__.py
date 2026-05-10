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
"""Storage layer: managed-SQLite-file abstractions.

See docs/superpowers/specs/2026-05-06-db-storage-backend-design.md.
"""

from fireflyframework_agentic.storage._types import (
    DatabaseStoreError,
    LockToken,
    RetryPolicy,
    StorageDownloadError,
    StorageLeaseError,
    StorageMetadata,
    StorageTransientError,
    StorageUploadError,
    StoreUnavailableError,
    WriteSession,
)
from fireflyframework_agentic.storage.backend import StorageBackend
from fireflyframework_agentic.storage.database_store import DatabaseStore
from fireflyframework_agentic.storage.local_backend import LocalBackend

# AzureBlobBackend lives behind the [storage-azure] extra. We try the
# import eagerly so it is a real symbol when the deps are installed
# (matches static-analyser expectations); when the deps are missing,
# `__getattr__` raises a clear, install-suggesting error instead of
# the bare ImportError seen at this site.
try:
    from fireflyframework_agentic.storage.azure_backend import AzureBlobBackend
except ImportError:  # pragma: no cover — exercised when the extra isn't installed
    _AZURE_BACKEND_IMPORT_ERROR: ImportError | None = ImportError(
        "AzureBlobBackend requires the storage-azure extra; install with "
        "`pip install fireflyframework-agentic[storage-azure]`"
    )
else:
    _AZURE_BACKEND_IMPORT_ERROR = None

__all__ = [
    "AzureBlobBackend",
    "DatabaseStore",
    "DatabaseStoreError",
    "LocalBackend",
    "LockToken",
    "RetryPolicy",
    "StorageBackend",
    "StorageDownloadError",
    "StorageLeaseError",
    "StorageMetadata",
    "StorageTransientError",
    "StorageUploadError",
    "StoreUnavailableError",
    "WriteSession",
]


def __getattr__(name: str):
    if name == "AzureBlobBackend" and _AZURE_BACKEND_IMPORT_ERROR is not None:
        raise _AZURE_BACKEND_IMPORT_ERROR
    raise AttributeError(name)
