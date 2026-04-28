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

"""Intelligent Document Processing (IDP) pipeline example.

Demonstrates **all major framework features** working together to process a
real PDF document (Unilever Certificate of Incorporation & Bylaws):

- **Agents**: ``FireflyAgent``, ``create_classifier_agent``, ``create_extractor_agent``
- **Tools**: ``@firefly_tool``, ``ToolKit``, ``CachedTool``, tool-to-agent bridging
- **Security**: ``PromptGuardMiddleware``, ``OutputGuardMiddleware``, ``CostGuardMiddleware``
- **Prompts**: ``PromptTemplate`` with declared variables
- **Reasoning**: ``ReflexionPattern``
- **Content processing**: ``TextChunker``, ``ContextCompressor``, ``TruncationStrategy``
- **Memory**: ``MemoryManager`` with working memory and conversation memory
- **Validation**: ``OutputValidator``, ``GroundingChecker``, ``OutputReviewer``
- **Pipeline**: ``PipelineBuilder``, ``CallableStep``, ``PipelineEventHandler``
- **Explainability**: ``TraceRecorder``, ``AuditTrail``, ``ReportBuilder``, LLM narrative
- **Logging**: ``configure_logging``

Pipeline stages::

    ingest → split → classify → extract → validate → assemble → explain

Usage::

    export OPENAI_API_KEY="sk-..."
    uv run python examples/idp_pipeline.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sys
from typing import Any

from _common import MODEL, ensure_api_key
from idp_tools import (
    DOCUMENT_TYPE_DESCRIPTIONS,
    DOCUMENT_TYPES,
    PDF_URL,
    CorporateDocumentData,
    DocumentClassification,
    SubDocument,
    classification_prompt,
    document_validator,
    explainability_prompt,
    extraction_prompt,
    idp_toolkit,
    split_prompt,
)

from fireflyframework_agentic.agents import FireflyAgent
from fireflyframework_agentic.agents.builtin_middleware import (
    CostGuardMiddleware,
    OutputGuardMiddleware,
    PromptGuardMiddleware,
)
from fireflyframework_agentic.agents.templates import create_classifier_agent, create_extractor_agent
from fireflyframework_agentic.content.chunking import TextChunker
from fireflyframework_agentic.content.compression import ContextCompressor, TruncationStrategy
from fireflyframework_agentic.explainability import AuditTrail, ReportBuilder, TraceRecorder
from fireflyframework_agentic.logging import configure_logging
from fireflyframework_agentic.memory import MemoryManager
from fireflyframework_agentic.pipeline.builder import PipelineBuilder
from fireflyframework_agentic.pipeline.context import PipelineContext
from fireflyframework_agentic.pipeline.engine import PipelineEngine
from fireflyframework_agentic.pipeline.steps import CallableStep
from fireflyframework_agentic.reasoning import ReflexionPattern
from fireflyframework_agentic.tools.cached import CachedTool
from fireflyframework_agentic.validation.qos import GroundingChecker
from fireflyframework_agentic.validation.reviewer import OutputReviewer

# ── ANSI colour helpers ─────────────────────────────────────────────────────
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str) -> str:
    return f"\033[{code}m" if _USE_COLOR else ""


BOLD = _c("1")
DIM = _c("2")
RED = _c("31")
GREEN = _c("32")
YELLOW = _c("33")
CYAN = _c("36")
MAGENTA = _c("35")
BLUE = _c("34")
RESET = _c("0")


def _header(title: str) -> str:
    """Return a bold cyan section header."""
    line = "─" * 70
    return f"\n{CYAN}{line}{RESET}\n{BOLD}{CYAN}  {title}{RESET}\n{CYAN}{line}{RESET}"


def _subheader(title: str) -> str:
    """Return a bold section sub-header."""
    return f"\n{BOLD}{title}{RESET}"


# ── Pretty JSON printer ─────────────────────────────────────────────────────


def _pretty_json(obj: Any, indent: int = 2) -> str:
    """Render *obj* as indented JSON with ANSI-coloured keys and values.

    Colour scheme:
    - Keys: bold cyan
    - Strings: green
    - Numbers: yellow
    - Booleans: magenta
    - Null: dim red
    - Structural chars (braces, brackets, colons, commas): dim
    """
    if not _USE_COLOR:
        return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)

    lines: list[str] = []

    def _val(value: Any) -> str:
        """Return a coloured inline representation of a scalar value."""
        if value is None:
            return f"{DIM}{RED}null{RESET}"
        if isinstance(value, bool):
            return f"{MAGENTA}{json.dumps(value)}{RESET}"
        if isinstance(value, (int, float)):
            return f"{YELLOW}{json.dumps(value)}{RESET}"
        if isinstance(value, str):
            return f"{GREEN}{json.dumps(value, ensure_ascii=False)}{RESET}"
        return f"{GREEN}{json.dumps(str(value), ensure_ascii=False)}{RESET}"

    def _render(value: Any, depth: int, *, trailing_comma: bool = False) -> None:
        pad = " " * (indent * depth)
        comma = "," if trailing_comma else ""

        if isinstance(value, dict):
            if not value:
                lines.append(f"{pad}{DIM}{{}}{RESET}{comma}")
                return
            lines.append(f"{pad}{DIM}{{{RESET}")
            keys = list(value.keys())
            for i, k in enumerate(keys):
                v = value[k]
                kstr = f"{BOLD}{CYAN}{json.dumps(k, ensure_ascii=False)}{RESET}"
                is_last = i == len(keys) - 1
                inner = " " * (indent * (depth + 1))
                c = "" if is_last else ","
                if isinstance(v, (dict, list)) and v:
                    if isinstance(v, dict):
                        lines.append(f"{inner}{kstr}{DIM}:{RESET} {DIM}{{{RESET}")
                        _render_kv(v, depth + 2, parent_last=is_last)
                    else:
                        lines.append(f"{inner}{kstr}{DIM}:{RESET} {DIM}[{RESET}")
                        for j, item in enumerate(v):
                            _render(item, depth + 2, trailing_comma=(j < len(v) - 1))
                        lines.append(f"{inner}{DIM}]{RESET}{c}")
                else:
                    lines.append(f"{inner}{kstr}{DIM}:{RESET} {_val(v)}{c}")
            lines.append(f"{pad}{DIM}}}{RESET}{comma}")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{DIM}[]{RESET}{comma}")
                return
            lines.append(f"{pad}{DIM}[{RESET}")
            for i, item in enumerate(value):
                _render(item, depth + 1, trailing_comma=(i < len(value) - 1))
            lines.append(f"{pad}{DIM}]{RESET}{comma}")
        else:
            lines.append(f"{pad}{_val(value)}{comma}")

    def _render_kv(d: dict, depth: int, *, parent_last: bool) -> None:
        """Render key-value pairs of a nested dict and close the brace."""
        keys = list(d.keys())
        inner = " " * (indent * depth)
        for i, k in enumerate(keys):
            v = d[k]
            kstr = f"{BOLD}{CYAN}{json.dumps(k, ensure_ascii=False)}{RESET}"
            is_last = i == len(keys) - 1
            c = "" if is_last else ","
            if isinstance(v, (dict, list)) and v:
                if isinstance(v, dict):
                    lines.append(f"{inner}{kstr}{DIM}:{RESET} {DIM}{{{RESET}")
                    _render_kv(v, depth + 1, parent_last=is_last)
                else:
                    lines.append(f"{inner}{kstr}{DIM}:{RESET} {DIM}[{RESET}")
                    for j, item in enumerate(v):
                        _render(item, depth + 1, trailing_comma=(j < len(v) - 1))
                    lines.append(f"{inner}{DIM}]{RESET}{c}")
            else:
                lines.append(f"{inner}{kstr}{DIM}:{RESET} {_val(v)}{c}")
        outer = " " * (indent * (depth - 1))
        c = "" if parent_last else ","
        lines.append(f"{outer}{DIM}}}{RESET}{c}")

    _render(obj, 0)
    return "\n".join(lines)


# ── Logging ─────────────────────────────────────────────────────────────────
configure_logging("INFO", format_style="colored")

# ── Shared memory ───────────────────────────────────────────────────────────
memory = MemoryManager(working_scope_id="idp-session")

# ── Content processing ──────────────────────────────────────────────────────
chunker = TextChunker(chunk_size=6000, chunk_overlap=300, strategy="sentence")
compressor = ContextCompressor(TruncationStrategy(), estimator=None)

# ── Grounding checker ──────────────────────────────────────────────────────
grounding_checker = GroundingChecker(case_sensitive=False, min_grounding_ratio=0.6)

# ── Agent middleware ────────────────────────────────────────────────────────
prompt_guard = PromptGuardMiddleware(sanitise=True)
output_guard = OutputGuardMiddleware(sanitise=True)
cost_guard = CostGuardMiddleware(budget_usd=10.0, warn_only=True)
_AGENT_MIDDLEWARE = [prompt_guard, output_guard, cost_guard]

# ── Explainability ──────────────────────────────────────────────────────────
recorder = TraceRecorder()
audit = AuditTrail()


# ═══════════════════════════════════════════════════════════════════════════
# Agent definitions
# ═══════════════════════════════════════════════════════════════════════════


# Disambiguation rules appended to the classifier's system prompt so the
# LLM correctly distinguishes similar-looking corporate document types.
_CLASSIFIER_EXTRA_INSTRUCTIONS = (
    "\n\nIMPORTANT — Corporate document classification rules:\n"
    "• Each sub-document is a SEPARATE logical document extracted from a larger PDF.\n"
    "  Classify THIS sub-document on its own merits, not by what it references.\n"
    "• The DOCUMENT TITLE is the strongest classification signal.\n"
    "• A cover page from a Secretary of State certifying a copy is 'state_certification',\n"
    "  NOT the same type as the document being certified.\n"
    "• A document titled 'By-Laws' or 'Bylaws' containing articles about meetings,\n"
    "  officers, committees, and indemnification is 'bylaws', even if it mentions\n"
    "  the corporation's certificate of incorporation.\n"
    "• A 'Written Consent' or 'Action by the Stockholders' is 'stockholder_consent',\n"
    "  even if it references elections, by-laws, or the corporation charter.\n"
    "• Reserve 'certificate_of_incorporation' for the actual charter that defines\n"
    "  corporate name, purpose, registered agent, share structure, and articles.\n"
)


def _build_classifier() -> FireflyAgent:
    """Build a classifier agent with structured ``ClassificationResult`` output.

    Uses :func:`create_classifier_agent` which sets
    ``output_type=ClassificationResult``, so every ``agent.run()`` call
    returns a typed pydantic object — no JSON parsing required.
    """
    return create_classifier_agent(
        categories=DOCUMENT_TYPES,
        descriptions=DOCUMENT_TYPE_DESCRIPTIONS,
        name="idp_classifier",
        model=MODEL,
        middleware=_AGENT_MIDDLEWARE,
        extra_instructions=_CLASSIFIER_EXTRA_INSTRUCTIONS,
        auto_register=False,
    )


def _build_extractor() -> FireflyAgent:
    """Build an extractor agent with CorporateDocumentData output and IDP tools."""
    return create_extractor_agent(
        CorporateDocumentData,
        field_descriptions={
            "company_name": "Full legal name of the company",
            "doc_type": "Type of corporate document",
            "incorporation_state": "State or jurisdiction of incorporation",
            "incorporation_date": "Date of incorporation (ISO 8601 YYYY-MM-DD)",
            "effective_date": "Effective date of the document (ISO 8601 YYYY-MM-DD)",
            "filing_number": "State filing or document number",
            "registered_agent": "Name of the registered agent",
            "registered_agent_address": "Full street address of the registered agent",
            "principal_address": "Principal office address if mentioned",
            "sections": (
                "List of DocumentSection objects — each with title (str), "
                "page_number (int from [PAGE N] markers), content_summary (str)"
            ),
            "key_provisions": "Key provisions or articles (up to 10)",
            "officers_mentioned": (
                "ONLY company officers/directors — each PersonReference with name, role, "
                "affiliation='company'. Do NOT include Secretary of State or notaries."
            ),
            "signatories": (
                "ALL people who signed/authenticated the document — each PersonReference "
                "with name, role, and affiliation ('company', 'state', or 'notary')"
            ),
            "authorized_shares": (
                "AuthorizedShares with total_shares, common_shares, common_par_value, "
                "preferred_shares, preferred_par_value"
            ),
        },
        name="idp_extractor",
        model=MODEL,
        tools=idp_toolkit.as_pydantic_tools(),
        memory=memory.fork(working_scope_id="extractor"),
        middleware=_AGENT_MIDDLEWARE,
    )


def _build_splitter() -> FireflyAgent:
    """Build a splitter agent that identifies document boundaries in a PDF."""
    return FireflyAgent(
        "idp_splitter",
        model=MODEL,
        instructions=(
            "You are an expert at analysing multi-document PDF files. "
            "Identify distinct document boundaries and return JSON."
        ),
        description="Identifies document boundaries within a multi-document PDF",
        tags=["idp", "splitter"],
        middleware=_AGENT_MIDDLEWARE,
        auto_register=False,
    )


# ── Cached PDF tool ─────────────────────────────────────────────────────────
# Wrap the PDF download tool in CachedTool so repeated runs (or retries)
# reuse the already-downloaded content instead of re-fetching from the web.
_cached_pdf_tool = CachedTool(idp_toolkit.tools[0], ttl_seconds=600.0)


def _build_explainer() -> FireflyAgent:
    """Build an explainer agent that generates human-readable narratives."""
    return FireflyAgent(
        "idp_explainer",
        model=MODEL,
        instructions=(
            "You are an expert technical writer. Produce clear, professional "
            "narrative reports for AI pipeline outputs. Use Markdown formatting."
        ),
        description="Generates human-readable explainability narratives",
        tags=["idp", "explainability"],
        auto_register=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Helper: split raw text by page markers
# ═══════════════════════════════════════════════════════════════════════════

_PAGE_RE = re.compile(r"\[PAGE (\d+)\]")


def _extract_pages(raw_text: str) -> dict[int, str]:
    """Split raw text into {page_number: page_text} using [PAGE N] markers."""
    pages: dict[int, str] = {}
    parts = _PAGE_RE.split(raw_text)
    # parts is: [before_first, page_num_1, text_1, page_num_2, text_2, ...]
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        text = parts[i + 1] if i + 1 < len(parts) else ""
        pages[page_num] = text.strip()
    return pages


def _slice_pages(pages: dict[int, str], start: int, end: int) -> str:
    """Reassemble page text for a page range [start, end] inclusive."""
    result: list[str] = []
    for p in range(start, end + 1):
        if p in pages:
            result.append(f"[PAGE {p}]\n{pages[p]}")
    return "\n\n".join(result)


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline step functions (for CallableStep)
# ═══════════════════════════════════════════════════════════════════════════


async def ingest_step(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Download and extract text from the PDF, chunk it, compress if needed."""
    url = context.inputs or PDF_URL

    print(f"\n{CYAN}📄 Ingesting PDF...{RESET}")
    raw_text = await _cached_pdf_tool.execute(url=url)  # pdf_to_text (cached)
    text_hash = hashlib.sha256(raw_text.encode()).hexdigest()[:12]

    page_count = len(re.findall(r"\[PAGE \d+\]", raw_text))
    chunks = chunker.chunk(raw_text)
    print(f"   {GREEN}Extracted {len(raw_text):,} characters, {page_count} pages → {len(chunks)} chunks{RESET}")

    compressed = await compressor.compress(raw_text, max_tokens=60_000)

    if context.memory is not None:
        context.memory.set_fact("raw_text", raw_text)
        context.memory.set_fact("raw_text_hash", text_hash)
        context.memory.set_fact("chunk_count", len(chunks))
        context.memory.set_fact("page_count", page_count)
        context.memory.set_fact("compressed_text", compressed)

    context.metadata["text_hash"] = text_hash
    context.metadata["chunk_count"] = len(chunks)
    context.metadata["page_count"] = page_count

    recorder.record(
        "tool_invocation",
        agent="ingest",
        input_summary=f"PDF download: {url}",
        output_summary=f"{len(raw_text):,} chars, {page_count} pages, {len(chunks)} chunks",
        detail={"tool": "pdf_to_text", "hash": text_hash},
    )
    audit.append(
        actor="ingest",
        action="pdf_download",
        resource=url,
        detail={"chars": len(raw_text), "pages": page_count, "chunks": len(chunks)},
    )

    return compressed


async def split_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Detect document boundaries and split into sub-documents.

    Demonstrates: FireflyAgent, PromptTemplate, page-aware text slicing.
    """
    raw_text = ""
    if context.memory is not None:
        raw_text = context.memory.get_fact("raw_text", "")
    if not raw_text:
        raw_text = str(inputs.get("input", ""))

    page_count = context.metadata.get("page_count", 0)

    # Build a page-level summary so the splitter can see the ENTIRE document
    # structure, not just the first few thousand characters.
    pages_map = _extract_pages(raw_text)
    page_summaries: list[str] = []
    for pn in sorted(pages_map.keys()):
        first_line = pages_map[pn].split("\n", 1)[0].strip()[:120]
        page_summaries.append(f"[PAGE {pn}] {first_line}")
    markers_str = "\n".join(page_summaries)

    print(f"\n{CYAN}✂️  Splitting document into sub-documents...{RESET}")

    # Give the splitter the first 8K chars of full text PLUS the page summaries
    # so it can detect boundaries across the entire document.
    prompt = split_prompt.render(
        page_markers=markers_str,
        max_chars=str(min(8000, len(raw_text))),
        document_text=raw_text[:8000],
    )

    splitter = _build_splitter()
    result = await splitter.run(prompt)
    raw_output = result.output if hasattr(result, "output") else str(result)

    # Parse the JSON array from the agent's response
    boundaries: list[dict[str, Any]] = []
    try:
        out_str = str(raw_output)
        match = re.search(r"\[.*\]", out_str, re.DOTALL)
        if match:
            boundaries = json.loads(match.group())
    except (json.JSONDecodeError, TypeError):
        pass

    if not boundaries:
        boundaries = [{"title": "Full Document", "page_start": 1, "page_end": page_count}]

    # Build SubDocument objects by slicing the raw text by page ranges
    pages = _extract_pages(raw_text)
    min_subdoc_chars = 200
    raw_sub_docs: list[SubDocument] = []
    for i, b in enumerate(boundaries):
        start = b.get("page_start", 1)
        end = b.get("page_end", page_count)
        text = _slice_pages(pages, start, end)
        raw_sub_docs.append(
            SubDocument(
                doc_id=f"sub_{i + 1}",
                title=b.get("title", f"Sub-document {i + 1}"),
                page_start=start,
                page_end=end,
                text=text,
            )
        )

    # Merge fragments (< min_subdoc_chars) into the preceding sub-document
    # so that tiny counterpart/signature pages don't cause extraction failures.
    sub_docs: list[SubDocument] = []
    for sd in raw_sub_docs:
        if len(sd.text) < min_subdoc_chars and sub_docs:
            prev = sub_docs[-1]
            merged_text = prev.text + "\n\n" + sd.text
            sub_docs[-1] = SubDocument(
                doc_id=prev.doc_id,
                title=prev.title,
                page_start=prev.page_start,
                page_end=sd.page_end,
                text=merged_text,
            )
            print(f"   {DIM}(merged fragment '{sd.title}' [{len(sd.text)} chars] into '{prev.title}'){RESET}")
        else:
            sub_docs.append(sd)

    # Re-number doc_ids after merging
    for i, sd in enumerate(sub_docs):
        sd.doc_id = f"sub_{i + 1}"

    print(f"   {GREEN}Found {len(sub_docs)} sub-document(s):{RESET}")
    for sd in sub_docs:
        print(f"   {BOLD}• {sd.title}{RESET} {DIM}(pages {sd.page_start}–{sd.page_end}, {len(sd.text):,} chars){RESET}")

    if context.memory is not None:
        context.memory.set_fact("sub_documents", [sd.model_dump() for sd in sub_docs])
        context.memory.set_fact("sub_document_count", len(sub_docs))

    context.metadata["sub_document_count"] = len(sub_docs)

    recorder.record(
        "reasoning_step",
        agent="idp_splitter",
        input_summary=f"Split document ({page_count} pages)",
        output_summary=f"Found {len(sub_docs)} sub-document(s)",
        detail={
            "sub_documents": [
                {"doc_id": sd.doc_id, "title": sd.title, "pages": f"{sd.page_start}-{sd.page_end}"} for sd in sub_docs
            ],
        },
    )
    audit.append(
        actor="idp_splitter",
        action="document_split",
        resource="document",
        detail={"sub_document_count": len(sub_docs), "boundaries": boundaries},
    )

    return [sd.model_dump() for sd in sub_docs]


async def classify_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Classify each sub-document using the classifier agent template.

    Demonstrates: create_classifier_agent (structured output via
    ``output_type=ClassificationResult``), PromptTemplate,
    multi-document processing.

    The classifier agent returns a typed :class:`ClassificationResult`
    directly — no JSON parsing or regex extraction needed.
    """
    sub_docs_raw = inputs.get("input", [])
    if not isinstance(sub_docs_raw, list):
        sub_docs_raw = [sub_docs_raw]

    print(f"\n{CYAN}🏷️  Classifying {len(sub_docs_raw)} sub-document(s) with structured output...{RESET}")

    classified: list[dict[str, Any]] = []

    for sd_data in sub_docs_raw:
        sd = SubDocument.model_validate(sd_data) if isinstance(sd_data, dict) else sd_data
        text = sd.text if isinstance(sd, SubDocument) else str(sd)
        title = sd.title if isinstance(sd, SubDocument) else "unknown"
        doc_id = sd.doc_id if isinstance(sd, SubDocument) else "sub_1"

        print(f"\n   {BLUE}▸ Classifying: {BOLD}{title}{RESET}")

        # Build the prompt — categories and disambiguation rules are
        # already in the classifier agent's system prompt, so the user
        # prompt only needs to supply the document text.
        prompt = classification_prompt.render(
            max_chars=str(min(3000, len(text))),
            document_text=text[:3000],
        )

        # create_classifier_agent has output_type=ClassificationResult,
        # so agent.run() returns a typed object — no JSON parsing needed.
        classifier = _build_classifier()
        result = await classifier.run(prompt)
        cls_result = result.output  # ClassificationResult (structured)

        classification = DocumentClassification(
            doc_type=cls_result.category,
            confidence=cls_result.confidence,
            language="en",
            summary=cls_result.reasoning[:200],
        )

        print(f"     Result: {BOLD}{classification.doc_type}{RESET} (confidence: {classification.confidence:.0%})")

        classified.append(
            {
                "doc_id": doc_id,
                "title": title,
                "text": text,
                "classification": classification.model_dump(),
            }
        )

        recorder.record(
            "llm_call",
            agent="idp_classifier",
            input_summary=f"Classify '{title}' ({len(text):,} chars)",
            output_summary=f"{classification.doc_type} ({classification.confidence:.0%})",
            detail={
                "doc_id": doc_id,
                "doc_type": classification.doc_type,
                "confidence": classification.confidence,
            },
        )
        audit.append(
            actor="idp_classifier",
            action="classification",
            resource=doc_id,
            detail={"doc_type": classification.doc_type, "confidence": classification.confidence},
        )

    if context.memory is not None:
        context.memory.set_fact(
            "classifications",
            {c["doc_id"]: c["classification"] for c in classified},
        )

    return classified


# Custom retry prompt for OutputReviewer — does NOT re-include full document text.
_EXTRACTION_RETRY_PROMPT = (
    "Your previous extraction had validation errors:\n{errors}\n\n"
    "Please correct ONLY the fields mentioned above and return the complete "
    "JSON object with all fields. Keep all other fields exactly as they were.\n\n"
    "Key reminders:\n"
    "- officers_mentioned: ONLY company officers (affiliation='company')\n"
    "- signatories: ALL people who signed (state officials get affiliation='state')\n"
    "- sections: each must have page_number > 0 from [PAGE N] markers\n"
    "- authorized_shares.total_shares >= common_shares + preferred_shares\n"
    "- dates must be ISO 8601 (YYYY-MM-DD) or empty string\n\n"
    "Original request (instructions only):\n{original_prompt}"
)


async def _extract_single(
    text: str,
    doc_type: str,
    title: str,
    doc_id: str,
) -> CorporateDocumentData:
    """Extract structured data from a single sub-document.

    Uses the OutputReviewer loop first; on exhaustion, falls back to a
    direct agent call.  Returns a :class:`CorporateDocumentData` on
    success or raises on unrecoverable failure.
    """
    rendered = extraction_prompt.render(doc_type=doc_type, document_text=text[:30_000])

    extractor = _build_extractor()
    reviewer = OutputReviewer(
        output_type=CorporateDocumentData,
        validator=document_validator,
        max_retries=4,
        retry_prompt=_EXTRACTION_RETRY_PROMPT,
    )

    try:
        review_result = await reviewer.review(extractor, rendered)
        extracted = review_result.output
        if review_result.retry_history:
            print(f"     {YELLOW}OutputReviewer retried {len(review_result.retry_history)} time(s){RESET}")
        print(f"     {GREEN}Extraction succeeded on attempt {review_result.attempts}{RESET}")
        return extracted  # type: ignore[return-value]
    except Exception:
        print(f"     {YELLOW}OutputReviewer exhausted retries, trying direct agent call...{RESET}")
        result = await extractor.run(rendered)
        raw_output = result.output if hasattr(result, "output") else result
        if isinstance(raw_output, CorporateDocumentData):
            return raw_output
        if isinstance(raw_output, dict):
            return CorporateDocumentData.model_validate(raw_output)
        return CorporateDocumentData.model_validate_json(str(raw_output))


async def extract_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Extract structured fields from each classified sub-document.

    Demonstrates: create_extractor_agent (structured output), OutputReviewer
    (with custom retry prompt), PromptTemplate, ToolKit, multi-document.
    """
    classified = inputs.get("input", [])
    if not isinstance(classified, list):
        classified = [classified]

    print(f"\n{CYAN}🔍 Extracting fields from {len(classified)} sub-document(s)...{RESET}")

    min_extract_chars = 200
    extracted_results: list[dict[str, Any]] = []

    for item in classified:
        doc_id = item.get("doc_id", "sub_1")
        title = item.get("title", "unknown")
        text = item.get("text", "")
        cls_data = item.get("classification", {})
        doc_type = cls_data.get("doc_type", "corporate_filing")

        print(f"\n   {BLUE}▸ Extracting: {BOLD}{title}{RESET} ({doc_type})")

        # ── Guard: skip extraction for fragments too small to extract ──
        if len(text) < min_extract_chars:
            print(f"     {DIM}Skipped (only {len(text)} chars — below {min_extract_chars}-char minimum){RESET}")
            extracted_results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "doc_type": doc_type,
                    "extraction": CorporateDocumentData(
                        company_name="(fragment)",
                        doc_type=doc_type,
                    ).model_dump(),
                    "attempts": 0,
                }
            )
            continue

        # ── Per-subdoc error isolation ──────────────────────────────────
        # Wrap the entire extraction + fallback in try/except so that a
        # single sub-document failure does not crash the extract node and
        # trigger a pipeline-level retry of ALL sub-documents.
        try:
            extracted = await _extract_single(
                text,
                doc_type,
                title,
                doc_id,
            )
        except Exception as exc:
            print(f"     {RED}Extraction failed for '{title}': {exc}{RESET}")
            extracted_results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "doc_type": doc_type,
                    "extraction": {},
                    "attempts": 0,
                }
            )
            audit.append(
                actor="idp_extractor",
                action="extraction_failed",
                resource=doc_id,
                detail={"error": str(exc)},
            )
            continue

        if isinstance(extracted, CorporateDocumentData):
            company_officers = [o for o in extracted.officers_mentioned if o.affiliation == "company"]
            print(f"     Company: {BOLD}{extracted.company_name}{RESET}")
            print(f"     Sections: {len(extracted.sections)}")
            print(f"     Officers: {len(company_officers)}")
            if extracted.authorized_shares:
                print(f"     Authorized shares: {extracted.authorized_shares.total_shares:,}")

            extracted_results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "doc_type": doc_type,
                    "extraction": extracted.model_dump(),
                    "attempts": getattr(extracted, "_attempts", 1),
                }
            )

            recorder.record(
                "llm_call",
                agent="idp_extractor",
                input_summary=f"Extract from '{title}' ({doc_type}, {len(text):,} chars)",
                output_summary=(
                    f"company={extracted.company_name}, "
                    f"{len(extracted.sections)} sections, "
                    f"{len(company_officers)} officers"
                ),
                detail={
                    "doc_id": doc_id,
                    "sections_count": len(extracted.sections),
                    "officers_count": len(company_officers),
                    "has_shares": extracted.authorized_shares is not None,
                },
            )
            audit.append(
                actor="idp_extractor",
                action="extraction",
                resource=doc_id,
                detail={"company": extracted.company_name},
            )
        else:
            extracted_results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "doc_type": doc_type,
                    "extraction": {},
                    "attempts": 0,
                }
            )

    if context.memory is not None:
        context.memory.set_fact("extracted_results", extracted_results)
        total_attempts = sum(r.get("attempts", 0) for r in extracted_results)
        context.memory.set_fact("extraction_attempts", total_attempts)

    return extracted_results


async def validate_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Validate extracted fields + grounding for each sub-document.

    Demonstrates: OutputValidator, GroundingChecker, ReflexionPattern.
    """
    extracted_results = inputs.get("input", [])
    if not isinstance(extracted_results, list):
        extracted_results = [extracted_results]

    print(f"\n{CYAN}✅ Validating {len(extracted_results)} extraction(s)...{RESET}")

    validated: list[dict[str, Any]] = []
    source_text = ""
    if context.memory is not None:
        source_text = context.memory.get_fact("raw_text", "")

    for item in extracted_results:
        doc_id = item.get("doc_id", "sub_1")
        title = item.get("title", "unknown")
        doc_type = item.get("doc_type", "unknown")
        extracted = item.get("extraction", {})
        if not isinstance(extracted, dict):
            extracted = {}

        print(f"\n   {BLUE}▸ Validating: {BOLD}{title}{RESET}")

        report = document_validator.validate(extracted)
        if report.valid:
            print(f"     {GREEN}Validation: PASS ({report.error_count} errors){RESET}")
        else:
            print(f"     {RED}Validation: FAIL ({report.error_count} errors){RESET}")
        for err in report.errors:
            print(f"     {YELLOW}⚠ {err.field_name}: {err.message}{RESET}")

        grounding_score = 1.0
        ungrounded: list[str] = []
        if source_text and extracted:
            string_fields = {k: v for k, v in extracted.items() if isinstance(v, str) and v}
            grounding_score, grounding_map = grounding_checker.check(source_text, string_fields)
            ungrounded = [k for k, v in grounding_map.items() if not v]
            print(f"     Grounding: {grounding_score:.0%} ({len(ungrounded)} ungrounded)")
            if ungrounded:
                print(f"     ⚠ Ungrounded: {', '.join(ungrounded)}")

        used_reflexion = False
        if not report.valid:
            print(f"\n     {MAGENTA}🔄 Self-correcting with Reflexion...{RESET}")
            try:
                extractor = _build_extractor()
                reflexion = ReflexionPattern(max_steps=4, model=MODEL)
                error_details = "; ".join(f"{e.field_name}: {e.message}" for e in report.errors)
                correction_prompt = (
                    f"The following extracted data has validation errors:\n"
                    f"Errors: {error_details}\n"
                    f"Original data: {json.dumps(extracted, indent=2)}\n\n"
                    f"Please fix these errors and return the corrected data."
                )
                correction = await reflexion.execute(extractor, correction_prompt)
                used_reflexion = True

                try:
                    if isinstance(correction.output, dict):
                        extracted = correction.output
                    else:
                        extracted = CorporateDocumentData.model_validate_json(str(correction.output)).model_dump()
                except Exception:
                    pass

                report = document_validator.validate(extracted)
                status = "PASS" if report.valid else "FAIL"
                print(f"     After correction: {status}")
            except Exception as exc:
                print(f"     Reflexion could not self-correct: {exc}")

        validated.append(
            {
                "doc_id": doc_id,
                "title": title,
                "doc_type": doc_type,
                "extraction": extracted,
                "valid": report.valid,
                "error_count": report.error_count,
                "grounding_score": grounding_score,
                "ungrounded_fields": ungrounded,
            }
        )

        recorder.record(
            "reasoning_step",
            agent="validator",
            input_summary=f"Validate '{title}' ({len(extracted)} fields)",
            output_summary=(f"valid={report.valid}, errors={report.error_count}, grounding={grounding_score:.0%}"),
            detail={
                "doc_id": doc_id,
                "valid": report.valid,
                "error_count": report.error_count,
                "grounding_score": grounding_score,
                "used_reflexion": used_reflexion,
            },
        )
        audit.append(
            actor="validator",
            action="validation",
            resource=doc_id,
            detail={"valid": report.valid, "grounding": grounding_score},
            outcome="success" if report.valid else "failure",
        )

    return validated


async def assemble_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Assemble the final IDP result from all sub-document results."""
    validated = inputs.get("input") or []
    if not isinstance(validated, list):
        validated = [validated]

    documents: list[dict[str, Any]] = []
    all_valid = True
    total_errors = 0
    total_sections = 0

    for item in validated:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except (json.JSONDecodeError, TypeError):
                item = {}
        if not isinstance(item, dict):
            item = {}

        extraction = item.get("extraction", {})
        valid = item.get("valid", False)
        if not valid:
            all_valid = False
        total_errors += item.get("error_count", 0)
        sections = extraction.get("sections", [])
        total_sections += len(sections) if isinstance(sections, list) else 0

        documents.append(
            {
                "doc_id": item.get("doc_id", ""),
                "title": item.get("title", ""),
                "doc_type": item.get("doc_type", ""),
                "extracted_fields": extraction,
                "validation_passed": valid,
                "validation_errors": item.get("error_count", 0),
                "grounding_score": item.get("grounding_score", 0.0),
                "ungrounded_fields": item.get("ungrounded_fields", []),
            }
        )

    return {
        "text_hash": context.metadata.get("text_hash", ""),
        "page_count": context.metadata.get("page_count", 0),
        "chunk_count": context.metadata.get("chunk_count", 0),
        "sub_document_count": len(documents),
        "total_sections_found": total_sections,
        "all_validations_passed": all_valid,
        "total_validation_errors": total_errors,
        "documents": documents,
    }


async def explain_step_fn(context: PipelineContext, inputs: dict[str, Any]) -> Any:
    """Generate a human-readable explainability narrative using an LLM agent.

    Demonstrates: FireflyAgent for narrative generation, TraceRecorder,
    AuditTrail, ReportBuilder integration.
    """
    assembled = inputs.get("input") or {}
    if isinstance(assembled, str):
        try:
            assembled = json.loads(assembled)
        except (json.JSONDecodeError, TypeError):
            assembled = {}

    print(f"\n{CYAN}📝 Generating LLM-powered explainability narrative...{RESET}")

    report_builder = ReportBuilder(title="IDP Pipeline Explainability Report")
    explain_report = report_builder.build(recorder.records)

    trace_json = json.dumps(
        [r.model_dump(mode="json") for r in recorder.records],
        indent=2,
        default=str,
    )
    audit_json = audit.export_json()
    assembled_json = json.dumps(assembled, indent=2, default=str)

    prompt = explainability_prompt.render(
        trace_json=trace_json,
        audit_json=audit_json,
        assembled_json=assembled_json,
    )

    explainer = _build_explainer()
    result = await explainer.run(prompt)
    narrative = str(result.output if hasattr(result, "output") else result)
    print(f"   {GREEN}Narrative generated ({len(narrative):,} chars){RESET}")

    recorder.record(
        "llm_call",
        agent="idp_explainer",
        input_summary="Generate explainability narrative",
        output_summary=f"Narrative: {len(narrative):,} chars",
        detail={"narrative_length": len(narrative)},
    )
    audit.append(
        actor="idp_explainer",
        action="narrative_generation",
        resource="explainability_report",
        detail={"chars": len(narrative)},
    )

    return {
        "assembled": assembled,
        "narrative": narrative,
        "report": explain_report.model_dump(mode="json"),
        "audit_trail": json.loads(audit_json),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Pipeline DAG construction
# ═══════════════════════════════════════════════════════════════════════════


# ── Pipeline event handler ──────────────────────────────────────────────────


class IDPEventHandler:
    """Pipeline event handler that prints coloured progress to the console."""

    async def on_node_start(self, node_id: str, pipeline_name: str) -> None:
        print(f"  {DIM}⏳ [{pipeline_name}] Starting node '{node_id}'...{RESET}")

    async def on_node_complete(
        self,
        node_id: str,
        pipeline_name: str,
        latency_ms: float,
    ) -> None:
        print(f"  {GREEN}✔ [{pipeline_name}] Node '{node_id}' completed in {latency_ms:.0f}ms{RESET}")

    async def on_node_error(
        self,
        node_id: str,
        pipeline_name: str,
        error: str,
    ) -> None:
        print(f"  {RED}✘ [{pipeline_name}] Node '{node_id}' failed: {error}{RESET}")

    async def on_node_skip(
        self,
        node_id: str,
        pipeline_name: str,
        reason: str,
    ) -> None:
        print(f"  {YELLOW}⏭ [{pipeline_name}] Node '{node_id}' skipped: {reason}{RESET}")

    async def on_pipeline_complete(
        self,
        pipeline_name: str,
        success: bool,
        duration_ms: float,
    ) -> None:
        badge = f"{GREEN}SUCCESS{RESET}" if success else f"{RED}FAILED{RESET}"
        print(f"\n  {BOLD}Pipeline '{pipeline_name}' {badge} in {duration_ms:,.0f}ms{RESET}")


def build_pipeline():
    """Build the IDP pipeline DAG with event handler."""
    dag = (
        PipelineBuilder("idp-pipeline")
        .add_node("ingest", CallableStep(ingest_step), timeout_seconds=90)
        .add_node("split", CallableStep(split_step_fn), timeout_seconds=120)
        .add_node("classify", CallableStep(classify_step_fn), timeout_seconds=180)
        .add_node(
            "extract",
            CallableStep(extract_step_fn),
            retry_max=1,
            timeout_seconds=300,
        )
        .add_node("validate", CallableStep(validate_step_fn), timeout_seconds=180)
        .add_node("assemble", CallableStep(assemble_step_fn))
        .add_node("explain", CallableStep(explain_step_fn), timeout_seconds=120)
        .chain(
            "ingest",
            "split",
            "classify",
            "extract",
            "validate",
            "assemble",
            "explain",
        )
        .build_dag()
    )
    return PipelineEngine(dag, event_handler=IDPEventHandler())


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════


async def main() -> None:
    ensure_api_key()

    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD}  Intelligent Document Processing (IDP) Pipeline{RESET}")
    print(f"{DIM}  Firefly Agentic Framework — Complex Example{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 70}{RESET}")
    print(f"\n{DIM}PDF:{RESET} {PDF_URL}\n")

    pipeline = build_pipeline()

    ctx = PipelineContext(
        inputs=PDF_URL,
        metadata={"source": "example", "pipeline": "idp"},
        memory=memory,
    )

    conv_id = memory.new_conversation()
    memory.set_fact("conversation_id", conv_id)
    memory.set_fact("pdf_url", PDF_URL)

    print("🚀 Running pipeline: ingest → split → classify → extract → validate → assemble → explain\n")
    result = await pipeline.run(context=ctx)

    # ═══════════════════════════════════════════════════════════════════
    # RESULTS
    # ═══════════════════════════════════════════════════════════════════
    print(_header("PIPELINE RESULTS"))
    print(
        _pretty_json(
            {
                "pipeline": result.pipeline_name,
                "success": result.success,
                "total_duration_ms": round(result.total_duration_ms),
                "nodes_executed": len(result.outputs),
                "failed_nodes": result.failed_nodes or [],
            }
        )
    )

    # ── Per-node results ──
    print(_subheader("Node Results"))
    for node_id, node_result in result.outputs.items():
        if node_result.success:
            badge = f"{GREEN}✅ PASS{RESET}"
        elif node_result.skipped:
            badge = f"{YELLOW}⏭️  SKIP{RESET}"
        else:
            badge = f"{RED}❌ FAIL{RESET}"
        print(
            f"  {badge}  {BOLD}{node_id:<12}{RESET}  "
            f"{DIM}{node_result.latency_ms:>8.0f} ms{RESET}  "
            f"retries={node_result.retries}"
        )
        if node_result.error:
            print(f"         {RED}{node_result.error}{RESET}")

    # ── Extract explain output ──
    explain_output = {}
    if result.final_output and isinstance(result.final_output, dict):
        explain_output = result.final_output
    assembled = explain_output.get("assembled", {})

    # ── Document splitting summary ──
    if isinstance(assembled, dict) and assembled.get("documents"):
        print(_header("DOCUMENT SPLITTING"))
        docs = assembled["documents"]
        print(f"  {BOLD}Found {len(docs)} sub-document(s) in {assembled.get('page_count', '?')} pages{RESET}\n")
        for doc in docs:
            doc_type = doc.get("doc_type", "unknown")
            title = doc.get("title", "unknown")
            valid = doc.get("validation_passed", False)
            badge = f"{GREEN}✅{RESET}" if valid else f"{RED}❌{RESET}"
            grounding = doc.get("grounding_score", 0)
            print(f"  {badge} {BOLD}{title}{RESET}  → {CYAN}{doc_type}{RESET}  grounding={grounding:.0%}")

    # ── Per-document extracted data ──
    if isinstance(assembled, dict) and assembled.get("documents"):
        print(_header("PER-DOCUMENT RESULTS"))
        for doc in assembled["documents"]:
            title = doc.get("title", "unknown")
            doc_type = doc.get("doc_type", "unknown")
            valid = doc.get("validation_passed", False)
            badge = f"{GREEN}PASS{RESET}" if valid else f"{RED}FAIL{RESET}"

            print(f"\n  {BOLD}{CYAN}{'─' * 66}{RESET}")
            print(f"  {BOLD}{title}{RESET}  [{CYAN}{doc_type}{RESET}]  validation: {badge}")
            print(f"  {BOLD}{CYAN}{'─' * 66}{RESET}")
            print(_pretty_json(doc.get("extracted_fields", {})))

    # ── Execution trace ──
    print(_header("EXECUTION TRACE"))
    trace_json = [
        {
            "node_id": e.node_id,
            "status": e.status,
            "started_at": e.started_at.isoformat(),
            "completed_at": e.completed_at.isoformat(),
            "duration_ms": round((e.completed_at - e.started_at).total_seconds() * 1000),
        }
        for e in result.execution_trace
    ]
    print(_pretty_json(trace_json))

    # ── Working memory ──
    print(_subheader("Working Memory"))
    facts_to_show = [
        "doc_type",
        "doc_language",
        "raw_text_hash",
        "page_count",
        "chunk_count",
        "sub_document_count",
        "extraction_attempts",
    ]
    working_mem = {key: memory.get_fact(key) for key in facts_to_show if memory.get_fact(key) is not None}
    print(_pretty_json(working_mem))

    # ═══════════════════════════════════════════════════════════════════
    # EXPLAINABILITY
    # ═══════════════════════════════════════════════════════════════════
    print(_header("EXPLAINABILITY REPORT"))

    narrative = explain_output.get("narrative", "")
    if narrative:
        print(_subheader("LLM-Generated Narrative"))
        print(f"\n{narrative}")

    print(_subheader("Full Report (JSON)"))
    report_data = explain_output.get("report", {})
    print(_pretty_json(report_data))

    print(_subheader("Audit Trail (JSON)"))
    audit_data = explain_output.get("audit_trail", [])
    print(_pretty_json(audit_data))

    # ═══════════════════════════════════════════════════════════════════
    # FOOTER
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{CYAN}{'═' * 70}{RESET}")
    print(f"{DIM}  Features demonstrated: agents, tools (CachedTool), prompts, reasoning (Reflexion),{RESET}")
    print(f"{DIM}  content processing (chunking, compression), memory (working + conversation),{RESET}")
    print(f"{DIM}  validation (rules, grounding), pipeline DAG (PipelineEventHandler), document splitting,{RESET}")
    print(f"{DIM}  security (PromptGuard, OutputGuard, CostGuard warn-only), logging,{RESET}")
    print(f"{DIM}  explainability (TraceRecorder, AuditTrail, ReportBuilder, LLM narrative){RESET}")
    print(f"{CYAN}{'═' * 70}{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
