# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""``BinaryConfig`` -- host-agnostic configuration for binary normalisation.

The binary normaliser and its handlers do not read any host
settings object (``CanonSettings`` / ``IDPSettings`` / ...) directly --
that would couple the framework to a specific application. Instead the
host maps its own settings into this small, frozen DTO and injects it.

Every field has a conservative default so a bare ``BinaryConfig()`` is
usable out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass

# Per-archive uncompressed-bytes ceiling. Independent of the per-input
# file-count cap so a single archive cannot exhaust memory by holding one
# giant member while staying under the file-count limit.
DEFAULT_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024  # 256 MiB


@dataclass(slots=True, frozen=True)
class BinaryConfig:
    """Tunables for :class:`~fireflyframework_agentic.content.binary.normalizer.BinaryNormalizer`.

    ``office_converter`` selects the adapter built by
    :func:`~fireflyframework_agentic.content.binary.office_converter.build_office_converter`
    (``"none"`` | ``"gotenberg"`` | ``"libreoffice"``).

    ``wrap_text_as_pdf`` controls plain-text routing: when ``True`` (the
    multimodal-LLM use case) ``text/plain`` / ``text/markdown`` / ``text/csv``
    are wrapped in an HTML envelope and rendered to PDF via the office
    converter; when ``False`` (the document-loader use case) they pass
    through untouched for a downstream text loader to handle.

    ``email_render_header`` controls whether an extra ``<stem>-headers.md``
    artifact carrying Subject/From/To/Date is emitted alongside the email
    body parts.
    """

    normalize_enabled: bool = True
    max_bytes: int | None = None
    max_recursion_depth: int = 3
    max_expanded_files: int = 50
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES
    wrap_text_as_pdf: bool = False
    email_render_header: bool = False
    office_converter: str = "none"
    gotenberg_url: str = "http://gotenberg:3000"
    gotenberg_timeout_s: float = 60.0
    libreoffice_path: str = "soffice"
    libreoffice_timeout_s: float = 60.0
