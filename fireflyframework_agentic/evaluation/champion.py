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
"""Per-corpus champion management.

Champions are per-corpus — mode 2A (conformance) and mode 2B (extraction)
metrics live in incommensurable spaces.  There is no global champion.
See EVALUATION_FRAMEWORK.md (per-corpus champions).

The historical fake-100% incident: banca-cordobesa/baseline.json was populated
with a champion scored against an EMPTY must-find registry.  The EMPTY_MUST_FIND
guard in G1 prevents a recurrence; the invalidate_champion() function provides
the corrective action when it does happen.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChampionRecord:
    """Per-corpus champion, stored as 'champion' key in baseline.json."""

    corpus: str
    run_id: str
    model_id: str
    registry_sha256: str
    scores: dict  # {metric_name: float}
    aa_noise: dict = field(default_factory=dict)  # {metric_name: noise_floor}
    is_day_zero: bool = False
    human_sign_offs: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)  # evaluation config snapshot
    corpus_sha256: str = ""  # pin of the evidence corpus the champion was verified against

    def primary_metric(self) -> str:
        return next(iter(self.scores)) if self.scores else ""

    def primary_score(self) -> float:
        return float(self.scores.get(self.primary_metric(), 0.0))


def load_champion(baseline_path: str | Path) -> ChampionRecord | None:
    """Load the current per-corpus champion from baseline.json.

    Returns None when:
    - The file does not exist (normal Day-Zero state).
    - The file exists but 'champion' is null (post-invalidation state).
    """
    path = Path(baseline_path)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    champ_raw = raw.get("champion")
    if champ_raw is None:
        return None
    return ChampionRecord(
        corpus=champ_raw["corpus"],
        run_id=champ_raw["run_id"],
        model_id=champ_raw["model_id"],
        registry_sha256=champ_raw["registry_sha256"],
        scores=champ_raw.get("scores", {}),
        aa_noise=champ_raw.get("aa_noise", {}),
        is_day_zero=champ_raw.get("is_day_zero", False),
        human_sign_offs=champ_raw.get("human_sign_offs", []),
        config=champ_raw.get("config", {}),
        corpus_sha256=champ_raw.get("corpus_sha256", ""),
    )


def save_champion(
    baseline_path: str | Path,
    champion: ChampionRecord,
    *,
    summary: str = "",
    date: str = "",
) -> None:
    """Persist a new champion and append a promotion log entry.

    Reads the existing file if it exists (to preserve the log), then writes
    the new champion.  The promotion log is append-only.
    """
    path = Path(baseline_path)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        log = raw.get("promotion_log", [])
        prev_run = raw.get("champion", {})
        prev_run_id = prev_run.get("run_id") if isinstance(prev_run, dict) else None
    else:
        log = []
        prev_run_id = None

    log.append(
        {
            "date": date or "unknown",
            "from": prev_run_id,
            "to": champion.run_id,
            "label": "day-zero" if champion.is_day_zero else "promotion",
            "summary": summary,
        }
    )

    payload = {
        "champion": {
            "corpus": champion.corpus,
            "run_id": champion.run_id,
            "model_id": champion.model_id,
            "registry_sha256": champion.registry_sha256,
            "scores": champion.scores,
            "aa_noise": champion.aa_noise,
            "is_day_zero": champion.is_day_zero,
            "human_sign_offs": champion.human_sign_offs,
            "config": champion.config,
            "corpus_sha256": champion.corpus_sha256,
        },
        "promotion_log": log,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def invalidate_champion(
    baseline_path: str | Path,
    *,
    reason: str,
    date: str = "",
) -> None:
    """Null out the current champion and record the invalidation reason.

    Used when a champion was locked in against an empty or tampered registry
    (the banca-cordobesa fake-100% incident).
    """
    path = Path(baseline_path)
    if not path.exists():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    log = raw.get("promotion_log", [])
    prev_run = raw.get("champion", {})
    prev_run_id = prev_run.get("run_id") if isinstance(prev_run, dict) else None
    log.append(
        {
            "date": date or "unknown",
            "from": prev_run_id,
            "to": None,
            "label": "INVALIDATED",
            "summary": reason,
        }
    )
    raw["champion"] = None
    raw["promotion_log"] = log
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


def input_hash(result_dict: dict) -> str:
    """Stable 16-char SHA-256 prefix of the DiscoveryResult for provenance."""
    canonical = json.dumps(result_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
