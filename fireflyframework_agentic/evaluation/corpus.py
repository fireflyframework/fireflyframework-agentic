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
"""Corpus loading and evidence verification (EVALUATION_FRAMEWORK.md §6.3).

The corpus is the third pinned evaluation input, next to the DiscoveryResult
and the registry: the raw document bundle (input.json) the discovery pipeline
read.  It is the trusted side of every evidence anchor — the registry tells
the evaluator what *should* be found; only the corpus can tell it whether what
a run cited is *real*.

verify_entry() closes the fabricated-evidence channel: a run controls every
byte of its own evidence_index, so any check computable from (result, registry)
alone can be satisfied by self-reported evidence.  Checking each excerpt
against the actual corpus text is the only deterministic counter.

Excerpt contract: excerpts are verbatim quotes from the source document.
Spliced quotes (fragments joined with '...' or '…') are supported — each
fragment is verified independently.  Paraphrase belongs in the finding
description, never in an excerpt.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fireflyframework_agentic.evaluation.matcher import source_stem

# Verification statuses for one evidence_index entry.
VERIFIED = "verified"  # excerpt found (verbatim or spliced) in the cited source
EMPTY = "empty"  # entry carries no excerpt text — nothing to verify
SOURCE_UNKNOWN = "source_unknown"  # locator resolves to no corpus document
FABRICATED = "fabricated"  # populated excerpt not found in the cited source

# A spliced excerpt is split on these joiners; fragments shorter than
# _MIN_FRAGMENT_CHARS are too generic to verify and are skipped.
_SPLICE_PATTERN = re.compile(r"\.\.\.|…| -- ")
_MIN_FRAGMENT_CHARS = 15

# A fragment passes fuzzily when matching blocks (>= _MIN_BLOCK_CHARS chars)
# cover at least _COVERAGE_THRESHOLD of it — tolerates punctuation/whitespace
# drift while rejecting invented text (measured ~0.10-0.32 coverage).
_COVERAGE_THRESHOLD = 0.85
_MIN_BLOCK_CHARS = 4


@dataclass
class Corpus:
    """The decoded, normalized corpus: {source stem: normalized text}.

    sha256 pins the corpus file exactly like the registry pin (§4.6): the
    champion record stores it, and G1 re-hashes the file at scoring time to
    flag CORPUS_DRIFT.
    """

    texts: dict[str, str]
    sha256: str
    path: str


def normalize(text: str) -> str:
    """Normalize text for excerpt matching: NFKC, strip markdown emphasis and
    smart quotes, collapse whitespace, casefold."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("**", "").replace("*", "")
    text = re.sub(r"[\"""''']", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def corpus_sha256(path: str | Path) -> str:
    """SHA-256 of the corpus file on disk (the CORPUS_DRIFT re-hash)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_corpus(path: str | Path) -> Corpus:
    """Load a FlyRadar input.json bundle into a stem-indexed normalized Corpus.

    Decodes every artifacts[] file and signals[] event log (base64), normalizes
    the text, and keys each by the same source_stem the matcher uses — so a
    locator in any convention resolves to its document.

    Raises:
        ValueError: when the bundle contains no documents, or two documents
            reduce to the same stem (a collision would let a fabricated
            citation resolve against the wrong real file).
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    named_contents: list[tuple[str, str]] = []
    for artifact in raw.get("artifacts", []):
        named_contents.append((artifact["filename"], artifact["content_base64"]))
    for signal in raw.get("signals", []):
        named_contents.append((signal["name"], signal["content_base64"]))

    if not named_contents:
        raise ValueError(f"corpus bundle {path} contains no artifacts or signals")

    texts: dict[str, str] = {}
    for name, content_b64 in named_contents:
        stem = source_stem(name)
        if stem in texts:
            raise ValueError(
                f"corpus stem collision: two documents reduce to {stem!r} — "
                "rename one; a collision would verify citations against the wrong file"
            )
        decoded = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        texts[stem] = normalize(decoded)

    return Corpus(texts=texts, sha256=corpus_sha256(path), path=str(path))


def _fragment_coverage(fragment: str, source: str) -> float:
    """Fraction of fragment covered by matching blocks of >= _MIN_BLOCK_CHARS chars."""
    blocks = difflib.SequenceMatcher(
        None, fragment, source, autojunk=False
    ).get_matching_blocks()
    covered = sum(b.size for b in blocks if b.size >= _MIN_BLOCK_CHARS)
    return covered / len(fragment)


def verify_entry(corpus: Corpus, entry: dict) -> str:
    """Verify one evidence_index entry against the corpus.

    Returns one of VERIFIED / EMPTY / SOURCE_UNKNOWN / FABRICATED:
    - the locator must resolve (by source stem) to a corpus document, and
    - every fragment of the excerpt must appear in that document's text,
      verbatim after normalization or with matching-block coverage >=
      _COVERAGE_THRESHOLD.

    The score is the minimum over fragments, so one invented fragment sinks a
    spliced excerpt.

    """
    stem = source_stem(entry.get("locator", ""))
    source = corpus.texts.get(stem)
    if source is None:
        return SOURCE_UNKNOWN

    excerpt = normalize(entry.get("excerpt") or "")
    if not excerpt:
        return EMPTY

    fragments = [
        f.strip()
        for f in _SPLICE_PATTERN.split(excerpt)
        if len(f.strip()) >= _MIN_FRAGMENT_CHARS
    ] or [excerpt]

    for fragment in fragments:
        if fragment in source:
            continue
        if _fragment_coverage(fragment, source) < _COVERAGE_THRESHOLD:
            return FABRICATED
    return VERIFIED


def verify_evidence_index(corpus: Corpus, result: dict) -> dict[str, str]:
    """Verify every evidence_index entry of a DiscoveryResult.

    Returns {evidence_id: status} over all entries — referenced or not — so
    the gates share one verification pass.
    """
    return {
        ev["id"]: verify_entry(corpus, ev)
        for ev in result.get("evidence_index", [])
        if ev.get("id")
    }
