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

"""Quality combinators built on the workflow primitives.

These encode the "fan-out → reduce-in-Python → decide" patterns that make
multi-agent runs trustworthy: adversarial verification (refute, don't confirm)
and loop-until-dry discovery.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Hashable
from typing import Any

from fireflyframework_agentic.workflows.primitives import agent, parallel

_REFUTE_PROMPT = (
    "You are a skeptical reviewer. Try hard to REFUTE the claim below. "
    "Default to refuting when uncertain. Reply with exactly one word: "
    "REFUTED or SUPPORTED.\n\nClaim: {claim}"
)


async def adversarial_verify(
    claim: str,
    *,
    model: Any | None = None,
    n: int = 3,
    instructions: str | None = None,
) -> bool:
    """Spawn ``n`` independent skeptics to refute ``claim``; majority rules.

    Returns ``True`` when the claim *survives* — i.e. fewer than a majority of
    the skeptics refute it. Each skeptic is prompted to default to refuting when
    uncertain, so survival is a conservative signal.
    """
    if n < 1:
        raise ValueError("n must be >= 1")

    async def _vote(i: int) -> bool:
        out = await agent(
            _REFUTE_PROMPT.format(claim=claim),
            label=f"refute#{i}",
            model=model,
            instructions=instructions,
        )
        return "refut" in str(out).lower()

    votes = await parallel([lambda i=i: _vote(i) for i in range(n)])
    refuted = sum(1 for v in votes if v)
    majority = n // 2 + 1
    return refuted < majority


async def loop_until_dry(
    produce: Callable[[], Awaitable[list[Any]]],
    *,
    max_rounds: int = 5,
    dry_rounds: int = 2,
    key: Callable[[Any], Hashable] = lambda x: x,
) -> list[Any]:
    """Call ``produce()`` repeatedly, accumulating de-duplicated results.

    Stops after ``dry_rounds`` consecutive rounds that surface nothing new, or
    after ``max_rounds`` total. ``key`` maps an item to its dedup identity.
    Catches the long tail that a fixed ``while count < N`` loop misses.
    """
    if max_rounds < 1 or dry_rounds < 1:
        raise ValueError("max_rounds and dry_rounds must be >= 1")

    seen: set[Hashable] = set()
    collected: list[Any] = []
    consecutive_dry = 0
    rounds = 0
    while consecutive_dry < dry_rounds and rounds < max_rounds:
        rounds += 1
        batch = await produce() or []
        fresh = [item for item in batch if key(item) not in seen]
        if not fresh:
            consecutive_dry += 1
            continue
        consecutive_dry = 0
        for item in fresh:
            seen.add(key(item))
            collected.append(item)
    return collected
