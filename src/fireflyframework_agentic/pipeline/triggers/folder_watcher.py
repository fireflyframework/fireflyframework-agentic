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

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FolderWatcher:
    """Yield paths for new / changed files under a folder.

    Uses ``watchfiles.awatch`` for events. Each candidate path is held back until
    its size has been observed unchanged across ``stability_polls`` consecutive
    polls (a heuristic for "the writer has finished"). The ``startup_scan``
    helper enumerates existing files so callers can reconcile against a ledger.
    """

    folder: Path
    debounce_ms: int = 500
    stability_polls: int = 2
    stability_interval_ms: int = 200

    def _is_hidden(self, path: Path) -> bool:
        """True if any path component (relative to ``self.folder``) starts with '.'.

        Catches macOS ``.DS_Store``, editor swap files (``.something.swp``),
        and ``.git`` / similar dotted directories anywhere in the tree.
        """
        try:
            rel_parts = path.relative_to(self.folder).parts
        except ValueError:
            rel_parts = path.parts
        return any(part.startswith(".") for part in rel_parts)

    async def startup_scan(self) -> AsyncIterator[Path]:
        """Yield every existing file under ``folder`` (recursive).

        Hidden files (anything starting with ``.`` in any path component
        relative to ``folder``) are skipped.
        """
        for p in sorted(self.folder.rglob("*")):
            if not p.is_file():
                continue
            if self._is_hidden(p):
                continue
            yield p

    async def wait_for_stability(self, path: Path, *, max_wait_ms: int = 5000) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_wait_ms / 1000.0
        last_size = -1
        stable_count = 0
        while loop.time() < deadline:
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                return False
            if size == last_size:
                stable_count += 1
                if stable_count >= self.stability_polls:
                    return True
            else:
                stable_count = 0
                last_size = size
            await asyncio.sleep(self.stability_interval_ms / 1000.0)
        return False

    async def watch(self) -> AsyncIterator[Path]:
        from watchfiles import Change, awatch

        async for changes in awatch(str(self.folder), debounce=self.debounce_ms):
            for change, raw_path in changes:
                if change is Change.deleted:
                    continue
                path = Path(raw_path)
                if not path.is_file():
                    continue
                if self._is_hidden(path):
                    continue
                if await self.wait_for_stability(path):
                    yield path
