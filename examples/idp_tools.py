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

"""IDP tools, schemas, prompt templates, and validators.

Shared module used by ``idp_pipeline.py``.  Defines:

- Pydantic output models for classification and extraction.
- ``@firefly_tool`` tools: page-aware PDF-to-text, section finder, date normaliser.
- A ``ToolKit`` that bundles the tools for agent injection.
- ``PromptTemplate`` instances for classification and extraction prompts.
- An ``OutputValidator`` with field-level and cross-field rules.
"""

from __future__ import annotations

import io
import re
from typing import Any

from pydantic import BaseModel, Field

from fireflyframework_agentic.prompts.template import PromptTemplate, PromptVariable
from fireflyframework_agentic.tools import ToolKit, firefly_tool
from fireflyframework_agentic.validation.rules import (
    CustomRule,
    EnumRule,
    OutputValidator,
    RegexRule,
    ValidationRuleResult,
)

# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------

DOCUMENT_TYPES = [
    "certificate_of_incorporation",
    "bylaws",
    "corporate_filing",
    "amendment",
    "legal_agreement",
    "state_certification",
    "stockholder_consent",
    "other",
]

DOCUMENT_TYPE_DESCRIPTIONS: dict[str, str] = {
    "certificate_of_incorporation": (
        "A state-filed charter that legally creates a corporation, specifying name, "
        "purpose, registered agent, authorized capital/shares, and governance framework. "
        "Often titled 'Certificate of Incorporation', 'Restated Certificate', or 'Charter'."
    ),
    "bylaws": (
        "Internal governance rules adopted by the corporation, covering meetings of "
        "stockholders, board of directors, committees, officers, indemnification, "
        "and amendment procedures. Usually titled 'By-Laws' or 'Bylaws'."
    ),
    "corporate_filing": (
        "Any document filed with a state agency related to corporate status, such as "
        "annual reports, certificates of good standing, or foreign qualification."
    ),
    "amendment": (
        "A modification to an existing corporate document, such as a certificate of "
        "amendment changing the company name, capital structure, or registered agent."
    ),
    "legal_agreement": (
        "A binding contract between two or more parties, including merger agreements, "
        "shareholder agreements, or operating agreements."
    ),
    "state_certification": (
        "A certification or authenticated copy issued by a state authority (e.g. "
        "Secretary of State) attesting to the filing, existence, or good standing "
        "of a corporation. Often a cover page certifying an attached document."
    ),
    "stockholder_consent": (
        "A written consent or resolution by the stockholders (or sole stockholder) "
        "of a corporation, taken in lieu of a formal meeting. Typically used to "
        "approve director elections, officer appointments, or corporate actions."
    ),
    "other": "Any corporate/legal document that does not fit the above categories.",
}


class SubDocument(BaseModel):
    """A sub-document identified within a larger PDF after boundary detection."""

    doc_id: str = Field(description="Unique identifier, e.g. 'sub_1'")
    title: str = Field(description="Human-readable title of the sub-document")
    page_start: int = Field(description="First page (1-based) of this sub-document")
    page_end: int = Field(description="Last page (1-based, inclusive) of this sub-document")
    text: str = Field(default="", description="Extracted text for this sub-document only")


class DocumentClassification(BaseModel):
    """Result of document classification."""

    doc_type: str = Field(description="Document type category")
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence 0-1")
    language: str = Field(default="en", description="ISO-639-1 language code")
    summary: str = Field(default="", description="One-sentence summary of the document")


class DocumentSection(BaseModel):
    """A section/article found in the document with its page location."""

    title: str = Field(description="Section or article title")
    page_number: int = Field(default=0, description="Page number where the section starts (1-based)")
    content_summary: str = Field(default="", description="Brief summary of the section content")


class PersonReference(BaseModel):
    """A person mentioned in the document."""

    name: str = Field(description="Full name of the person")
    role: str = Field(default="", description="Role or title (e.g. 'President', 'Secretary of State')")
    affiliation: str = Field(
        default="company",
        description=(
            "Who this person represents: 'company' for officers/directors, "
            "'state' for government officials (Secretary of State, etc.), "
            "'notary' for notaries public, 'witness' for witnesses"
        ),
    )


class AuthorizedShares(BaseModel):
    """Capital / authorized share structure."""

    total_shares: int = Field(default=0, description="Total number of authorized shares")
    common_shares: int = Field(default=0, description="Number of common shares")
    common_par_value: str = Field(default="", description="Par value per common share")
    preferred_shares: int = Field(default=0, description="Number of preferred shares")
    preferred_par_value: str = Field(default="", description="Par value per preferred share (if any)")


class CorporateDocumentData(BaseModel):
    """Structured data extracted from a corporate/legal document."""

    company_name: str = Field(description="Full legal name of the company")
    doc_type: str = Field(description="Type of corporate document")
    incorporation_state: str = Field(default="", description="State/jurisdiction of incorporation")
    incorporation_date: str = Field(default="", description="Date of incorporation (ISO 8601)")
    effective_date: str = Field(default="", description="Effective date of the document (ISO 8601)")
    filing_number: str = Field(default="", description="State filing or document number")
    registered_agent: str = Field(default="", description="Name of the registered agent")
    registered_agent_address: str = Field(default="", description="Full address of the registered agent")
    principal_address: str = Field(default="", description="Principal office address of the company")
    sections: list[DocumentSection] = Field(
        default_factory=list,
        description="Major sections/articles found, each with title, page number, and content summary",
    )
    key_provisions: list[str] = Field(default_factory=list, description="Key provisions or articles")
    officers_mentioned: list[PersonReference] = Field(
        default_factory=list,
        description=(
            "Company officers and directors ONLY (NOT state officials or notaries). "
            "Each entry has name, role, and affiliation='company'."
        ),
    )
    signatories: list[PersonReference] = Field(
        default_factory=list,
        description=(
            "ALL people who signed the document, including state officials and notaries. "
            "Each entry has name, role, and affiliation ('company', 'state', or 'notary')."
        ),
    )
    authorized_shares: AuthorizedShares | None = Field(
        default=None, description="Authorized share/capital structure if described in the document"
    )


# ---------------------------------------------------------------------------
# PDF URL
# ---------------------------------------------------------------------------

PDF_URL = (
    "https://www.unilever.com/files/4760bbbe-456d-4c37-82be-176054088e3e/"
    "certificate-of-incorporation-and-bylaws-of-unilever-united-states.pdf"
)

# ---------------------------------------------------------------------------
# @firefly_tool definitions
# ---------------------------------------------------------------------------


@firefly_tool(
    name="pdf_to_text",
    description="Download a PDF from a URL and extract page-aware text with [PAGE N] markers.",
    tags=["idp", "ocr"],
)
async def pdf_to_text(url: str) -> str:
    """Download a PDF and extract text with page markers using pdfplumber.

    Each page is prefixed with ``[PAGE N]`` so downstream tools can track
    which page a piece of text appears on.

    Requires ``httpx`` and ``pdfplumber`` (both in dev dependencies).
    """
    import httpx
    import pdfplumber

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=60.0,
        headers={"User-Agent": "Mozilla/5.0"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[PAGE {idx}]\n{text}")
    return "\n\n".join(pages)


@firefly_tool(
    name="section_finder",
    description="Split document text into titled sections with page offsets using [PAGE N] markers.",
    tags=["idp", "parsing"],
)
async def section_finder(text: str) -> str:
    """Identify section headings and return them with page numbers.

    Expects the text to contain ``[PAGE N]`` markers (as produced by
    ``pdf_to_text``).  Returns a numbered list like::

        1. ARTICLE FIRST — Name of Corporation (page 3)
        2. ARTICLE SECOND — Registered Office (page 3)
    """
    # Track current page as we scan through the text
    page_re = re.compile(r"\[PAGE (\d+)\]")
    heading_re = re.compile(
        r"^(?:ARTICLE\s+[IVXLC\d]+[.:]*\s*.*"
        r"|SECTION\s+\d+[.:]*\s*.*"
        r"|CHAPTER\s+\d+[.:]*\s*.*"
        r"|(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)[.:]+\s*.*"
        r"|[A-Z][A-Z\s]{5,})$",
        re.MULTILINE,
    )

    # Build a list of (position, page_number) from page markers
    page_positions: list[tuple[int, int]] = []
    for m in page_re.finditer(text):
        page_positions.append((m.start(), int(m.group(1))))

    def _page_for(pos: int) -> int:
        """Return the page number for a character position."""
        page = 1
        for pp, pn in page_positions:
            if pp > pos:
                break
            page = pn
        return page

    headings: list[tuple[str, int]] = []
    for m in heading_re.finditer(text):
        heading_text = m.group().strip()
        page = _page_for(m.start())
        headings.append((heading_text, page))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[tuple[str, int]] = []
    for h, p in headings:
        key = h.lower()
        if key not in seen:
            seen.add(key)
            unique.append((h, p))

    if not unique:
        return "No section headings found."
    return "\n".join(f"{i + 1}. {h} (page {p})" for i, (h, p) in enumerate(unique[:50]))


@firefly_tool(
    name="date_normalizer",
    description="Parse a date string in various formats and return ISO 8601 (YYYY-MM-DD).",
    tags=["idp", "parsing"],
)
async def date_normalizer(date_string: str) -> str:
    """Attempt to normalise a date string to ISO 8601 format."""
    import datetime

    # Try common formats
    formats = [
        "%B %d, %Y",  # January 15, 2026
        "%b %d, %Y",  # Jan 15, 2026
        "%m/%d/%Y",  # 01/15/2026
        "%d/%m/%Y",  # 15/01/2026
        "%Y-%m-%d",  # 2026-01-15
        "%B %Y",  # January 2026
        "%d %B %Y",  # 15 January 2026
        "%Y",  # 2026
    ]
    cleaned = date_string.strip()
    # Remove ordinal suffixes: 1st, 2nd, 3rd, 4th, etc.
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", cleaned)

    for fmt in formats:
        try:
            dt = datetime.datetime.strptime(cleaned, fmt)  # noqa: DTZ007
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return f"UNPARSEABLE: {date_string}"


# ---------------------------------------------------------------------------
# ToolKit
# ---------------------------------------------------------------------------

idp_toolkit = ToolKit(
    "idp-tools",
    [pdf_to_text, section_finder, date_normalizer],
    description="Tools for Intelligent Document Processing (PDF extraction, section parsing, date normalisation)",
    tags=["idp"],
)

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

classification_prompt = PromptTemplate(
    "idp_classification",
    (
        "Classify the following corporate document text into the appropriate "
        "category. Pay close attention to the document title and opening lines "
        "to determine the document type.\n\n"
        "Document text (first {{ max_chars }} characters):\n"
        "---\n{{ document_text }}\n---"
    ),
    version="4.0.0",
    description=(
        "Provides document text for classification. Categories, descriptions, "
        "and disambiguation rules are in the classifier agent's system prompt "
        "(via create_classifier_agent + extra_instructions), so this template "
        "only needs to supply the document content."
    ),
    variables=[
        PromptVariable(name="max_chars", description="How many characters of document text are included"),
        PromptVariable(name="document_text", description="The document text to classify"),
    ],
)

split_prompt = PromptTemplate(
    "idp_split",
    (
        "You are an expert at analysing corporate/legal PDF documents.\n\n"
        "The following text was extracted from a PDF and contains [PAGE N] markers "
        "indicating page boundaries. Your task is to identify DISTINCT DOCUMENTS "
        "within this single PDF file.\n\n"
        "Common patterns:\n"
        "- A PDF may contain a Certificate of Incorporation followed by Bylaws\n"
        "- There may be cover sheets, certifications, or exhibits\n"
        "- Look for clear title pages, new document headers, or 'BY-LAWS' headings\n\n"
        "Page markers found in the document:\n{{ page_markers }}\n\n"
        "Document text (first {{ max_chars }} chars):\n"
        "---\n{{ document_text }}\n---\n\n"
        "Identify each distinct document and return a JSON array of objects, each with:\n"
        "- title: descriptive title of the sub-document\n"
        "- page_start: first page number (integer)\n"
        "- page_end: last page number (integer, inclusive)\n\n"
        'Example: [{"title": "Certificate of Incorporation", "page_start": 1, '
        '"page_end": 6}, {"title": "By-Laws", "page_start": 7, "page_end": 33}]'
    ),
    version="1.0.0",
    description="Identifies document boundaries within a multi-document PDF.",
    variables=[
        PromptVariable(name="page_markers", description="List of [PAGE N] positions found"),
        PromptVariable(name="max_chars", description="Character count of text provided"),
        PromptVariable(name="document_text", description="The document text to analyse"),
    ],
)

explainability_prompt = PromptTemplate(
    "idp_explainability",
    (
        "You are an expert technical writer producing an explainability report for an "
        "AI-powered Intelligent Document Processing pipeline.\n\n"
        "The pipeline processed a PDF document through these stages:\n"
        "  ingest → split → classify → extract → validate → assemble\n\n"
        "Below is the complete execution trace (JSON), audit trail (JSON), and the "
        "assembled output (JSON).\n\n"
        "=== EXECUTION TRACE ===\n{{ trace_json }}\n\n"
        "=== AUDIT TRAIL ===\n{{ audit_json }}\n\n"
        "=== ASSEMBLED OUTPUT ===\n{{ assembled_json }}\n\n"
        "Write a clear, professional narrative report that covers:\n"
        "1. **Pipeline Overview**: What the pipeline did, how many documents were found.\n"
        "2. **Document Splitting**: How the PDF was split, page ranges, rationale.\n"
        "3. **Per-Document Findings**: For each sub-document, summarise the classification, "
        "   key extracted fields (company name, officers, shares, etc.), and validation status.\n"
        "4. **Key Decisions**: Any notable reasoning steps, retries, or self-corrections.\n"
        "5. **Validation & Grounding**: Overall validation outcome, grounding scores, "
        "   any ungrounded fields and why.\n"
        "6. **Recommendations**: Potential improvements or areas where extraction confidence "
        "   could be improved.\n\n"
        "Use Markdown formatting. Be thorough but concise. Write for a technical audience "
        "who needs to audit and trust the pipeline's output."
    ),
    version="1.0.0",
    description="LLM-powered narrative explainability report for the IDP pipeline.",
    variables=[
        PromptVariable(name="trace_json", description="JSON-serialized execution trace records"),
        PromptVariable(name="audit_json", description="JSON-serialized audit trail"),
        PromptVariable(name="assembled_json", description="JSON-serialized assembled pipeline output"),
    ],
)

extraction_prompt = PromptTemplate(
    "idp_extraction",
    (
        "You are an expert data extractor for corporate legal documents.\n\n"
        "Extract structured data from the following {{ doc_type }} document.\n"
        "The text contains [PAGE N] markers indicating page boundaries.\n\n"
        "Document text:\n---\n{{ document_text }}\n---\n\n"
        "Extract ALL of the following fields precisely:\n\n"
        "BASIC INFO:\n"
        "- company_name: Full legal company name\n"
        "- doc_type: Type of document ({{ doc_type }})\n"
        "- incorporation_state: State or jurisdiction of incorporation\n"
        "- incorporation_date: Date of incorporation (ISO 8601 YYYY-MM-DD)\n"
        "- effective_date: Effective date of the document (ISO 8601 YYYY-MM-DD)\n"
        "- filing_number: State filing or document number if present\n\n"
        "REGISTERED AGENT & ADDRESSES:\n"
        "- registered_agent: Name of the registered agent\n"
        "- registered_agent_address: FULL street address of the registered agent "
        "(street, city, county, state, zip)\n"
        "- principal_address: Principal office address of the company if mentioned\n\n"
        "SECTIONS (with page offsets):\n"
        "- sections: List of major sections/articles. For EACH section provide:\n"
        "  - title: The full section/article title\n"
        "  - page_number: The page number from the [PAGE N] marker where it appears\n"
        "  - content_summary: A one-sentence summary of that section's content\n\n"
        "KEY PROVISIONS:\n"
        "- key_provisions: Up to 10 key provisions or noteworthy clauses\n\n"
        "AUTHORIZED SHARES (if applicable):\n"
        "- authorized_shares: Share structure including total_shares, common_shares, "
        "common_par_value, preferred_shares, preferred_par_value\n\n"
        "PEOPLE — IMPORTANT DISTINCTION:\n"
        "- officers_mentioned: ONLY company officers and directors (President, VP, "
        "Secretary, Treasurer, directors). Each with name, role, affiliation='company'.\n"
        "  ⚠ Do NOT include government officials (Secretary of State, Deputy Secretary, "
        "etc.) or notaries here.\n"
        "- signatories: ALL people who signed or authenticated the document, including "
        "state officials and notaries. Each with name, role, and correct affiliation:\n"
        "  - affiliation='company' for company officers/directors\n"
        "  - affiliation='state' for government officials (Secretary of State, etc.)\n"
        "  - affiliation='notary' for notaries public\n"
        "  - affiliation='witness' for witnesses\n\n"
        "If a field cannot be determined, use an empty string, empty list, or null."
    ),
    version="2.0.0",
    description="Extracts structured data from a corporate document (page-aware, role-aware).",
    variables=[
        PromptVariable(name="doc_type", description="The classified document type"),
        PromptVariable(name="document_text", description="The full document text to extract from"),
    ],
)

# ---------------------------------------------------------------------------
# Output validators
# ---------------------------------------------------------------------------


def _sections_non_empty(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: sections list should not be empty for corporate documents."""
    sections = data.get("sections", [])
    passed = isinstance(sections, list) and len(sections) > 0
    return ValidationRuleResult(
        rule_name="cross:sections_non_empty",
        field_name="sections",
        passed=passed,
        message="" if passed else "Corporate documents should have at least one section heading.",
        value=sections,
    )


def _sections_have_pages(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: sections should include page numbers."""
    sections = data.get("sections", [])
    if not sections:
        return ValidationRuleResult(
            rule_name="cross:sections_have_pages",
            field_name="sections",
            passed=True,
            message="",
            value=sections,
        )
    has_pages = all(isinstance(s, dict) and s.get("page_number", 0) > 0 for s in sections if isinstance(s, dict))
    return ValidationRuleResult(
        rule_name="cross:sections_have_pages",
        field_name="sections",
        passed=has_pages,
        message="" if has_pages else "All sections should have a page_number > 0.",
        value=sections,
    )


def _no_state_officials_in_officers(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: officers_mentioned should not include state officials."""
    officers = data.get("officers_mentioned", [])
    bad = [
        o.get("name", "?") if isinstance(o, dict) else str(o)
        for o in officers
        if isinstance(o, dict) and o.get("affiliation") in ("state", "notary", "witness")
    ]
    passed = len(bad) == 0
    return ValidationRuleResult(
        rule_name="cross:no_state_officials_in_officers",
        field_name="officers_mentioned",
        passed=passed,
        message=(
            "" if passed else f"officers_mentioned should only contain company officers, but found: {', '.join(bad)}"
        ),
        value=officers,
    )


# Valid affiliations for PersonReference
VALID_AFFILIATIONS = ["company", "state", "notary", "witness"]

# ISO 8601 date pattern (YYYY-MM-DD) or empty string
_ISO_DATE_OR_EMPTY = r"^$|^\d{4}-\d{2}-\d{2}$"

# US state names / abbreviations (non-exhaustive but covers common cases)
_US_STATES = [
    "Alabama",
    "Alaska",
    "Arizona",
    "Arkansas",
    "California",
    "Colorado",
    "Connecticut",
    "Delaware",
    "Florida",
    "Georgia",
    "Hawaii",
    "Idaho",
    "Illinois",
    "Indiana",
    "Iowa",
    "Kansas",
    "Kentucky",
    "Louisiana",
    "Maine",
    "Maryland",
    "Massachusetts",
    "Michigan",
    "Minnesota",
    "Mississippi",
    "Missouri",
    "Montana",
    "Nebraska",
    "Nevada",
    "New Hampshire",
    "New Jersey",
    "New Mexico",
    "New York",
    "North Carolina",
    "North Dakota",
    "Ohio",
    "Oklahoma",
    "Oregon",
    "Pennsylvania",
    "Rhode Island",
    "South Carolina",
    "South Dakota",
    "Tennessee",
    "Texas",
    "Utah",
    "Vermont",
    "Virginia",
    "Washington",
    "West Virginia",
    "Wisconsin",
    "Wyoming",
    "District of Columbia",
]


def _valid_signatories_affiliations(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: all signatories must have valid affiliations."""
    signatories = data.get("signatories", [])
    bad = [
        f"{s.get('name', '?')} (affiliation={s.get('affiliation', '?')})"
        for s in signatories
        if isinstance(s, dict) and s.get("affiliation") not in VALID_AFFILIATIONS
    ]
    passed = len(bad) == 0
    return ValidationRuleResult(
        rule_name="cross:signatories_valid_affiliations",
        field_name="signatories",
        passed=passed,
        message=("" if passed else f"Invalid affiliations in signatories: {', '.join(bad)}"),
        value=signatories,
    )


def _valid_officers_affiliations(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: all officers must have affiliation='company'."""
    officers = data.get("officers_mentioned", [])
    bad = [
        f"{o.get('name', '?')} (affiliation={o.get('affiliation', '?')})"
        for o in officers
        if isinstance(o, dict) and o.get("affiliation") != "company"
    ]
    passed = len(bad) == 0
    return ValidationRuleResult(
        rule_name="cross:officers_affiliation_company",
        field_name="officers_mentioned",
        passed=passed,
        message=("" if passed else f"officers_mentioned must all have affiliation='company': {', '.join(bad)}"),
        value=officers,
    )


def _authorized_shares_valid(data: dict[str, Any]) -> ValidationRuleResult:
    """Cross-field rule: if authorized_shares present, total >= common + preferred."""
    shares = data.get("authorized_shares")
    if not shares or not isinstance(shares, dict):
        return ValidationRuleResult(
            rule_name="cross:authorized_shares_valid",
            field_name="authorized_shares",
            passed=True,
            message="",
            value=shares,
        )
    total = shares.get("total_shares", 0)
    common = shares.get("common_shares", 0)
    preferred = shares.get("preferred_shares", 0)
    passed = total >= common + preferred
    return ValidationRuleResult(
        rule_name="cross:authorized_shares_valid",
        field_name="authorized_shares",
        passed=passed,
        message=("" if passed else f"total_shares ({total}) < common ({common}) + preferred ({preferred})"),
        value=shares,
    )


document_validator = OutputValidator(
    {
        "company_name": [
            RegexRule(
                "company_name",
                r".{2,}",
                description="Company name must be at least 2 characters",
            ),
        ],
        "doc_type": [
            EnumRule("doc_type", DOCUMENT_TYPES, case_sensitive=False),
        ],
        "incorporation_state": [
            RegexRule(
                "incorporation_state",
                r".{2,}",
                description="Incorporation state must be at least 2 characters",
            ),
            EnumRule(
                "incorporation_state",
                _US_STATES,
                case_sensitive=False,
            ),
        ],
        "incorporation_date": [
            RegexRule(
                "incorporation_date",
                _ISO_DATE_OR_EMPTY,
                description="incorporation_date must be ISO 8601 (YYYY-MM-DD) or empty",
            ),
        ],
        "effective_date": [
            RegexRule(
                "effective_date",
                _ISO_DATE_OR_EMPTY,
                description="effective_date must be ISO 8601 (YYYY-MM-DD) or empty",
            ),
        ],
        "filing_number": [
            RegexRule(
                "filing_number",
                r"^$|^[A-Za-z0-9\-\s./]+$",
                description="filing_number must be alphanumeric (dashes, spaces, dots, slashes allowed) or empty",
            ),
        ],
        "registered_agent": [
            RegexRule(
                "registered_agent",
                r"^$|.{2,}",
                description="Registered agent name must be empty or at least 2 characters",
            ),
        ],
        "registered_agent_address": [
            CustomRule(
                "registered_agent_address",
                lambda v: isinstance(v, str) and (v == "" or ("," in v and len(v) >= 10)),
                description=(
                    "registered_agent_address must be empty or a full address (at least 10 chars with a comma)"
                ),
            ),
        ],
    },
    cross_field_rules=[
        _sections_non_empty,
        _sections_have_pages,
        _no_state_officials_in_officers,
        _valid_signatories_affiliations,
        _valid_officers_affiliations,
        _authorized_shares_valid,
    ],
)
