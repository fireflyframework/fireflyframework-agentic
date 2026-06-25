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

"""LLM-as-judge evaluation example.

Score a set of Q&A pairs using the evaluation metrics:
  - contains_answer  — does the answer contain the correct information?
  - addresses_question — does the answer directly address what was asked?

Each metric runs ``--runs`` times and reports the median score (default 3).

Usage::

    python examples/llm_eval_example.py --model anthropic:claude-haiku-4-5-20251001

    # Or score from a JSONL file instead of the built-in sample data:
    python examples/llm_eval_example.py \\
        --model anthropic:claude-haiku-4-5-20251001 \\
        --items-file items.jsonl

Items JSONL format — one JSON object per line::

    {"question": "...", "answer": "...", "reference": "..."}
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from fireflyframework_agentic.evaluation import (
    EvalContext,
    JudgeClient,
    addresses_question,
    contains_answer,
)

# Sample data used when no --items-file is provided.
_SAMPLE_ITEMS = [
    {
        "question": "What is the boiling point of water at sea level?",
        "reference": "Water boils at 100 °C at standard atmospheric pressure.",
        "answer": "Water boils at 100 degrees Celsius at sea level.",
    },
    {
        "question": "Who wrote Romeo and Juliet?",
        "reference": "Romeo and Juliet was written by William Shakespeare around 1594–1596.",
        "answer": "It was written by Shakespeare.",
    },
    {
        "question": "What is the capital of France?",
        "reference": "The capital of France is Paris.",
        "answer": "The weather in France is generally mild.",
    },
]


async def score_items(items: list[dict], ctx: EvalContext) -> list[dict]:
    tasks = [(contains_answer(item, ctx), addresses_question(item, ctx)) for item in items]
    pairs = await asyncio.gather(*[asyncio.gather(ca, aq) for ca, aq in tasks])
    return [
        {"question": item["question"], "contains_answer": ca, "addresses_question": aq}
        for item, (ca, aq) in zip(items, pairs)
    ]


async def main(args: argparse.Namespace) -> None:
    if args.items_file:
        lines = Path(args.items_file).read_text(encoding="utf-8").strip().splitlines()
        items = [json.loads(line) for line in lines if line.strip()]
    else:
        items = _SAMPLE_ITEMS

    ctx = EvalContext(client=JudgeClient(args.model), runs=args.runs)
    results = await score_items(items, ctx)

    print(f"\n{'Question':<45} {'contains':>8} {'addresses':>9}")
    print("-" * 63)
    for r in results:
        q = r["question"][:43] + ".." if len(r["question"]) > 45 else r["question"]
        ca = f"{r['contains_answer']:.2f}" if r["contains_answer"] is not None else "  n/a"
        aq = f"{r['addresses_question']:.2f}" if r["addresses_question"] is not None else "    n/a"
        print(f"{q:<45} {ca:>8} {aq:>9}")

    scored = [r for r in results if r["contains_answer"] is not None]
    if scored:
        avg_ca = sum(r["contains_answer"] for r in scored) / len(scored)
        avg_aq = sum(r["addresses_question"] for r in scored) / len(scored)
        print("-" * 63)
        print(f"{'Average':<45} {avg_ca:>8.2f} {avg_aq:>9.2f}")
    print(f"\n{len(items)} items scored ({args.runs} judge run(s) each).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score Q&A pairs with LLM-as-judge metrics.")
    parser.add_argument(
        "--model",
        default="anthropic:claude-haiku-4-5-20251001",
        help="Judge model spec (provider:model).",
    )
    parser.add_argument("--runs", type=int, default=3, help="Judge runs per item (median is reported).")
    parser.add_argument("--items-file", default=None, help="Optional JSONL file of {question, answer, reference} items.")
    asyncio.run(main(parser.parse_args()))
