# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Binary normalisation -- caller bytes in, consumer-ready artifacts out.

Turns a raw uploaded file (PDF, DOCX, XLSX, images, archives, emails, ...)
into one or more :class:`BinaryArtifact` rows for a downstream document
loader or multimodal LLM. The stack is host-agnostic: configure it with a
:class:`BinaryConfig` and inject plain handler classes (no DI framework
required).

Optional third-party dependencies (``pypdf``, ``Pillow``, ``pillow-heif``,
``cairosvg``, ``py7zr``, ``extract-msg``, ``httpx``) ship in the
``fireflyframework-agentic[binary]`` extra and are imported lazily; a missing
dependency surfaces as a typed :class:`BinaryNormalizationError` only when the
relevant format is actually encountered.
"""

from __future__ import annotations

from fireflyframework_agentic.content.binary.archive_unpacker import ArchiveUnpacker
from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.email_unpacker import EmailUnpacker
from fireflyframework_agentic.content.binary.errors import (
    ArchiveExtractionError,
    BinaryFanoutError,
    BinaryNormalizationError,
    BinaryTooLargeError,
    CorruptPdfError,
    EmailParseError,
    EncryptedPdfError,
    ImageConversionError,
    OfficeConversionError,
    UnsupportedBinaryError,
)
from fireflyframework_agentic.content.binary.image_normalizer import ImageNormalizer, NormalisedImage
from fireflyframework_agentic.content.binary.normalizer import BinaryArtifact, BinaryNormalizer
from fireflyframework_agentic.content.binary.office_converter import (
    OFFICE_MEDIA_TYPES,
    GotenbergConverter,
    LibreOfficeConverter,
    NoOpOfficeConverter,
    OfficeConverter,
    build_office_converter,
)
from fireflyframework_agentic.content.binary.pdf_guard import PdfGuard
from fireflyframework_agentic.content.binary.sniffer import sniff_media_type

__all__ = [
    "OFFICE_MEDIA_TYPES",
    "ArchiveExtractionError",
    "ArchiveUnpacker",
    "BinaryArtifact",
    "BinaryConfig",
    "BinaryFanoutError",
    "BinaryNormalizationError",
    "BinaryNormalizer",
    "BinaryTooLargeError",
    "CorruptPdfError",
    "EmailParseError",
    "EmailUnpacker",
    "EncryptedPdfError",
    "GotenbergConverter",
    "ImageConversionError",
    "ImageNormalizer",
    "LibreOfficeConverter",
    "NoOpOfficeConverter",
    "NormalisedImage",
    "OfficeConversionError",
    "OfficeConverter",
    "PdfGuard",
    "UnsupportedBinaryError",
    "build_office_converter",
    "sniff_media_type",
]
