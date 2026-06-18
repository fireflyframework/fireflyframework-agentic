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

"""Unit tests for evaluation.matcher: anchored, source_stem, tokens, matches."""

from __future__ import annotations

import pytest

from fireflyframework_agentic.evaluation.matcher import (
    anchored,
    matches,
    source_stem,
    tokens,
)
from fireflyframework_agentic.evaluation.registry import RegistryItem


# ── tokens ───────────────────────────────────────────────────────────────────


def test_tokens_basic():
    result = tokens("Hello World")
    assert result == ["hello", "world"]


def test_tokens_lowercases():
    result = tokens("KYC AML PEP")
    assert result == ["kyc", "aml", "pep"]


def test_tokens_strips_punctuation():
    result = tokens("risk-management: cost (FTE).")
    assert "risk" in result
    assert "management" in result
    assert "cost" in result
    assert "fte" in result


def test_tokens_empty_string():
    assert tokens("") == []


def test_tokens_numbers_included():
    result = tokens("case-id CU-2026-1003")
    assert "2026" in result or "cu" in result


def test_tokens_unicode():
    result = tokens("análisis de crédito")
    assert "análisis" in result or "an" in result


# ── anchored ─────────────────────────────────────────────────────────────────


def test_anchored_overlapping_long_token():
    # "underwriting" is 12 chars — well above the 5-char floor.
    assert anchored("credit underwriting risk", "underwriting process steps") is True


def test_anchored_no_overlap():
    # No token >= 5 chars shared between claim and evidence.
    assert anchored("cat sat", "dog ran") is False


def test_anchored_short_tokens_ignored():
    # All tokens in both strings are < 5 chars; no overlap counts.
    assert anchored("a big cat", "a big dog") is False


def test_anchored_mixed_lengths_match():
    # "kyc" is < 5, but "compliance" is long enough.
    assert anchored("kyc compliance review", "compliance framework") is True


def test_anchored_custom_min_token():
    # Lower the floor so short tokens can anchor.
    assert anchored("kyc check", "kyc process", min_token=3) is True


def test_anchored_both_empty():
    assert anchored("", "") is False


def test_anchored_partial_token_no_match():
    # "risk" (4 chars) is below the default 5-char floor.
    assert anchored("risk alert", "risk factor") is False


def test_anchored_returns_bool():
    result = anchored("credit underwriting", "underwriting model")
    assert isinstance(result, bool)


# ── source_stem ───────────────────────────────────────────────────────────────


def test_source_stem_bare_filename_with_extension():
    assert source_stem("SOP-002-kyc-edd.md") == "sop-002-kyc-edd"


def test_source_stem_directory_prefixed():
    assert source_stem("sops/SOP-002-kyc-edd.md") == "sop-002-kyc-edd"


def test_source_stem_deep_path_prefix():
    assert source_stem("docs/policies/SOP-002-kyc-edd.md") == "sop-002-kyc-edd"


def test_source_stem_lowercase():
    # Stems are always lowercased.
    assert source_stem("REPORT-FINAL.pdf") == "report-final"


def test_source_stem_event_log_row_id():
    # src-<process>:<case> → process stem.
    assert source_stem("src-credit-underwriting:CU-2026-1003") == "credit-underwriting"


def test_source_stem_event_log_row_id_preserves_hyphens():
    assert source_stem("src-kyc-onboarding:KYC-001") == "kyc-onboarding"


def test_source_stem_strips_fragment():
    # #page=N should be removed before stemming.
    assert source_stem("docs/report.pdf#page=5") == "report"


def test_source_stem_strips_anchor():
    assert source_stem("sops/SOP-001.md#section-3") == "sop-001"


def test_source_stem_bare_no_extension():
    # No extension, no directory — stem is just the lowercase name.
    assert source_stem("my-document") == "my-document"


def test_source_stem_no_directory_no_extension_lowercase():
    assert source_stem("Signal") == "signal"


def test_source_stem_csv_extension():
    assert source_stem("activity-cost-fte.csv") == "activity-cost-fte"


# ── matches ───────────────────────────────────────────────────────────────────


def _make_item(description: str, evidence: list[str], keywords: list[str] | None = None) -> RegistryItem:
    """Construct a minimal RegistryItem for matching tests."""
    return RegistryItem(
        id="test-item",
        tier="L1",
        description=description,
        evidence=evidence,
        scope="finding",
        keywords=keywords or [],
    )


def _make_finding(title: str, description: str, evidence_id: str) -> dict:
    return {
        "title": title,
        "description": description,
        "evidence_refs": [{"evidence_id": evidence_id}],
    }


def _make_evidence_index(evidence_id: str, locator: str, excerpt: str = "") -> dict:
    return {evidence_id: {"id": evidence_id, "locator": locator, "excerpt": excerpt}}


def test_matches_true_when_source_and_topic_match():
    # Finding title shares a long token with item description and cites the same source.
    item = _make_item("credit underwriting process", ["sop-kyc-credit.md"])
    finding = _make_finding("credit underwriting review", "credit underwriting risk assessment", "ev-1")
    evidence_index = _make_evidence_index("ev-1", "sop-kyc-credit.md")
    assert matches(finding, item, evidence_index, scope="finding") is True


def test_matches_false_when_source_differs():
    # Token match exists but sources don't overlap — anti-gaming guard fires.
    item = _make_item("credit underwriting process", ["sop-credit.md"])
    finding = _make_finding("credit underwriting review", "credit underwriting details", "ev-1")
    evidence_index = _make_evidence_index("ev-1", "other-document.md")
    assert matches(finding, item, evidence_index, scope="finding") is False


def test_matches_false_when_no_token_overlap():
    # Same source, but no shared long token between finding text and item description.
    item = _make_item("regulatory capital requirement", ["sop-capital.md"])
    finding = _make_finding("kyc identity check", "client onboarding steps", "ev-1")
    evidence_index = _make_evidence_index("ev-1", "sop-capital.md")
    assert matches(finding, item, evidence_index, scope="finding") is False


def test_matches_keyword_rail_short_token():
    # "KYC" is 3 chars — below the 5-char token floor but valid as a keyword.
    item = _make_item("some description about identity", ["sop-kyc.md"], keywords=["KYC"])
    finding = _make_finding("KYC onboarding", "KYC onboarding process", "ev-1")
    evidence_index = _make_evidence_index("ev-1", "sop-kyc.md")
    assert matches(finding, item, evidence_index, scope="finding") is True


def test_matches_empty_evidence_refs_returns_false():
    # Finding with no evidence refs cannot share a source with any item.
    item = _make_item("credit underwriting", ["sop-credit.md"])
    finding = {"title": "credit underwriting", "description": "credit underwriting risk", "evidence_refs": []}
    assert matches(finding, item, {}, scope="finding") is False
