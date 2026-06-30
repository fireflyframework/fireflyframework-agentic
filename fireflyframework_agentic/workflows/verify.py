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

import contextlib
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from fireflyframework_agentic.model_utils import get_model_identifier
from fireflyframework_agentic.workflows.context import current_workflow
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


# ---------------------------------------------------------------------------
# Judge panel — heterogeneous-model verification with a structured verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """The structured result of a judge panel.

    Attributes:
        survived: ``True`` when ``support`` meets the threshold.
        support: fraction of judges that affirmed the claim (0.0–1.0).
        votes: ``(model_id, affirmed)`` per judge.
    """

    survived: bool
    support: float
    votes: tuple[tuple[str, bool], ...]


_AFFIRM = "Reply with exactly one word: YES or NO."


async def judge_panel(
    claim: str,
    *,
    judges: list[Any],
    rubric: str | None = None,
    threshold: float = 0.5,
) -> Verdict:
    """Score ``claim`` with a panel of (heterogeneous) judge models.

    Each model in ``judges`` votes YES/NO; the claim *survives* when the YES
    fraction is at least ``threshold``. Using different models is a stronger
    signal than asking one model repeatedly. Returns a structured :class:`Verdict`.
    """
    if not judges:
        raise ValueError("judge_panel requires at least one judge model")
    question = (rubric or "Is the following claim true and well-supported?") + "\n\n" + _AFFIRM + "\n\nClaim: {claim}"

    async def _vote(model: Any, i: int) -> tuple[str, bool]:
        out = await agent(question.format(claim=claim), model=model, label=f"judge#{i}")
        affirmed = str(out).strip().lower().startswith("y")
        return (get_model_identifier(model), affirmed)

    raw = await parallel([(lambda m=m, i=i: _vote(m, i)) for i, m in enumerate(judges)])
    votes = tuple(v for v in raw if v is not None)
    support = (sum(1 for _, yes in votes if yes) / len(votes)) if votes else 0.0
    return Verdict(survived=support >= threshold, support=support, votes=votes)


# ---------------------------------------------------------------------------
# Model cascade — cheap-first, escalate on low confidence (FrugalGPT-style)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CascadeResult:
    """The outcome of a :func:`cascade`.

    Attributes:
        output: the accepted answer.
        tier: index of the tier that produced it (0 = cheapest).
        model: the model that produced it.
        confidence: the confidence score of the accepted answer (0.0–1.0).
        escalations: how many tiers were skipped to reach it.
    """

    output: Any
    tier: int
    model: Any
    confidence: float
    escalations: int


class _Confidence(BaseModel):
    score: float


async def _judge_confidence(prompt: Any, output: Any, *, model: Any) -> float:
    res = await agent(
        "Rate from 0.0 to 1.0 how well the ANSWER satisfies the TASK "
        "(1.0 = fully correct and complete). Reply with the score only.\n\n"
        f"TASK: {prompt}\n\nANSWER: {output}",
        model=model,
        output_type=_Confidence,
        label="cascade.judge",
    )
    return max(0.0, min(1.0, float(res.score)))


async def cascade(
    prompt: Any,
    *,
    tiers: list[Any],
    confidence: Callable[[Any], Awaitable[float]] | None = None,
    judge_model: Any | None = None,
    threshold: float = 0.7,
    output_type: Any | None = None,
    instructions: str | None = None,
    max_escalations: int | None = None,
) -> CascadeResult:
    """Run the cheapest tier first; escalate only when confidence is low.

    The classic cost/quality trade-off: ``tiers`` are models ordered cheap →
    expensive. Each tier's answer is scored by ``confidence`` (an async
    ``callable(output) -> float`` in 0.0–1.0); when no ``confidence`` is given a
    judge model rates it (defaults to the cheapest tier as judge, overridable via
    ``judge_model``). The first answer at or above ``threshold`` (or the last tier)
    is returned. Every tier emits a ``cascade.tier`` event.
    """
    if not tiers:
        raise ValueError("cascade requires at least one tier")
    judge = judge_model if judge_model is not None else tiers[0]
    conf_fn = confidence or (lambda out: _judge_confidence(prompt, out, model=judge))
    limit = len(tiers) - 1 if max_escalations is None else min(max_escalations, len(tiers) - 1)

    result: CascadeResult | None = None
    for i, model in enumerate(tiers):
        out = await agent(
            prompt, model=model, output_type=output_type, instructions=instructions, label=f"cascade.tier{i}"
        )
        score = float(await conf_fn(out))
        _emit_cascade(i, model, score)
        result = CascadeResult(output=out, tier=i, model=model, confidence=score, escalations=i)
        if score >= threshold or i >= limit:
            return result
    assert result is not None  # tiers is non-empty
    return result


def _emit_cascade(tier: int, model: Any, confidence: float) -> None:
    with contextlib.suppress(Exception):  # emit is best-effort
        current_workflow().emit(
            "cascade.tier", {"tier": tier, "model": get_model_identifier(model), "confidence": confidence}
        )
