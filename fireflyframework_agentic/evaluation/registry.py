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
"""lean-1 registry loader — one schema for all four corpora.

Replaces the four mutually incompatible schemes in use today (L1-L5,
documented/observed/pain-point, critical/important, and no tiers).
Loader enforces all invariants; they are not documentation.

Invariants (EVALUATION_FRAMEWORK.md, the must-find registry):
- schema_version == "lean-1"
- every tier is one of L0 L1 L2 L3 NC
- negative_control_count >= ceil(real_items / 10)
- kappa present (0.0 placeholder allowed; G2 advisory until >= 0.70)
- ABANCA DILO items must target a single measured sub-population
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VALID_TIERS = ("L0", "L1", "L2", "L3", "NC")
VALID_SCOPES = (
    "process", "activity", "decision", "finding", "action",
    "persona", "system", "informal_channel", "dependency_graph",
)
SCHEMA_VERSION = "lean-1"
KAPPA_ADVISORY_THRESHOLD = 0.70


@dataclass(frozen=True)
class RegistryItem:
    id: str
    tier: Literal["L0", "L1", "L2", "L3", "NC"]
    description: str
    evidence: list[str]          # source file paths (path portion of locator, no #page=N)
    scope: str = "finding"       # which DiscoveryResult surface to match against (§4.3)
    keywords: list[str] = field(default_factory=list)
    weight: float = 1.0
    from_node: str = ""   # dependency_graph relation items only
    to_node: str = ""     # dependency_graph relation items only
    relation: str = ""    # defaults to "precedes" when from/to present


@dataclass(frozen=True)
class Registry:
    schema_version: str
    corpus: str
    author: str
    date: str
    kappa: float
    items: list[RegistryItem]
    _sha256: str = field(default="", compare=False)

    @property
    def real_items(self) -> list[RegistryItem]:
        return [i for i in self.items if i.tier != "NC"]

    @property
    def nc_items(self) -> list[RegistryItem]:
        return [i for i in self.items if i.tier == "NC"]

    @property
    def l0_items(self) -> list[RegistryItem]:
        return [i for i in self.items if i.tier == "L0"]

    def is_kappa_advisory(self) -> bool:
        return self.kappa < KAPPA_ADVISORY_THRESHOLD

    def sha256(self) -> str:
        return self._sha256


def _validate(raw: dict, path: Path) -> None:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"{path.name}: schema_version must be '{SCHEMA_VERSION}', "
            f"got {raw.get('schema_version')!r}"
        )
    for fname in ("corpus", "author", "date"):
        if not raw.get(fname):
            raise ValueError(f"{path.name}: missing required field '{fname}'")
    if "kappa" not in raw:
        raise ValueError(f"{path.name}: missing 'kappa' field (use 0.0 as placeholder)")

    items = raw.get("items", [])

    # EMPTY_MUST_FIND guard — must be first; kills fake-champion bug
    if not items:
        raise ValueError(
            f"{path.name}: EMPTY_MUST_FIND — items list is empty; "
            "cannot evaluate recall.  This guard exists to prevent the "
            "fake-100%-champion failure."
        )

    ids = [it.get("id") for it in items]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"{path.name}: duplicate item ids: {dupes}")

    for it in items:
        tier = it.get("tier")
        if tier not in VALID_TIERS:
            raise ValueError(
                f"{path.name}: item '{it.get('id')}' has invalid tier '{tier}'; "
                f"must be one of {VALID_TIERS}"
            )
        scope = it.get("scope", "finding")
        if scope not in VALID_SCOPES:
            raise ValueError(
                f"{path.name}: item '{it.get('id')}' has invalid scope '{scope}'; "
                f"must be one of {VALID_SCOPES}"
            )
        if scope == "dependency_graph":
            if not it.get("from") or not it.get("to"):
                raise ValueError(
                    f"{path.name}: dependency_graph item '{it.get('id')}' must have "
                    "non-empty 'from' and 'to'"
                )
        else:
            if "from" in it or "to" in it or "relation" in it:
                raise ValueError(
                    f"{path.name}: item '{it.get('id')}' has 'from'/'to'/'relation' "
                    f"but scope is '{scope}'; these fields are only valid on "
                    "dependency_graph-scoped items"
                )

    real_count = sum(1 for it in items if it.get("tier") != "NC")
    nc_count = sum(1 for it in items if it.get("tier") == "NC")
    required_nc = max(1, math.ceil(real_count / 10))
    if nc_count < required_nc:
        raise ValueError(
            f"{path.name}: NC density too low — {nc_count} NC item(s) for "
            f"{real_count} real items; need >= {required_nc} (ceil(real/10)).  "
            "Without NC items the eval measures recall only; a verbose hallucinator "
            "scores perfectly."
        )

    # ABANCA DILO blend guard: items must assert a single sub-population target.
    # Checks for phrases that would indicate a blended numeric target is asserted.
    # "blend" alone is too broad (items may reference it negatively).
    BLEND_PHRASES = ("combined distribution", "across all offices regardless of segment")
    for it in items:
        if it.get("tier") == "NC":
            continue
        desc = it.get("description", "").lower()
        iid = it.get("id", "")
        if any(phrase in desc for phrase in BLEND_PHRASES):
            raise ValueError(
                f"{path.name}: item '{iid}' description targets a blended distribution; "
                "ABANCA DILO items must target a single measured sub-population "
                "(Empresas or PyMEs).  Use segment-keyed items: "
                "dilo-empresas-operativa-42pct AND dilo-pymes-operativa-29pct separately."
            )


def _compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(path: str | Path) -> Registry:
    """Load and validate a lean-1 registry file.

    Raises ValueError with a descriptive message on any invariant violation.
    The EMPTY_MUST_FIND check runs first — it is the fake-champion guard.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    _validate(raw, path)
    sha = _compute_sha256(path)

    items = [
        RegistryItem(
            id=it["id"],
            tier=it["tier"],
            scope=it.get("scope", "finding"),
            description=it.get("description", ""),
            evidence=it.get("evidence", []),
            keywords=it.get("keywords", []),
            weight=float(it.get("weight", 1.0)),
            from_node=it.get("from", "") if it.get("scope") == "dependency_graph" else "",
            to_node=it.get("to", "") if it.get("scope") == "dependency_graph" else "",
            relation=it.get("relation", "precedes") if it.get("scope") == "dependency_graph" else "",
        )
        for it in raw["items"]
    ]

    return Registry(
        schema_version=raw["schema_version"],
        corpus=raw["corpus"],
        author=raw["author"],
        date=raw["date"],
        kappa=float(raw["kappa"] or 0.0),
        items=items,
        _sha256=sha,
    )


def registry_sha256(path: str | Path) -> str:
    return _compute_sha256(Path(path))
