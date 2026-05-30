# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Typed exceptions raised by the binary-normalisation stage.

Each subclass carries a stable ``code`` and a default ``http_status`` so a
host application can map them to RFC 7807 problem-details without having to
translate. The base extends :class:`ValueError` so hosts that fall back to a
generic ``ValueError`` handler still catch these when no more specific
handler matches.
"""

from __future__ import annotations


class BinaryNormalizationError(ValueError):
    """Base class for every binary-normalisation failure."""

    code: str = "binary_normalization_error"
    http_status: int = 422

    def __init__(self, message: str, *, filename: str | None = None) -> None:
        super().__init__(message)
        self.filename = filename


class UnsupportedBinaryError(BinaryNormalizationError):
    """The bytes are recognised but no adapter handles the media type."""

    code = "unsupported_file"
    http_status = 415


class EncryptedPdfError(BinaryNormalizationError):
    """The inbound PDF is password-protected and no password was provided."""

    code = "encrypted_pdf"


class CorruptPdfError(BinaryNormalizationError):
    """The inbound PDF is corrupt / truncated / has an unparseable page tree."""

    code = "corrupt_pdf"


class ImageConversionError(BinaryNormalizationError):
    """Pillow / pillow-heif / cairosvg refused the inbound image."""

    code = "image_conversion_failed"


class ArchiveExtractionError(BinaryNormalizationError):
    """A ZIP / 7z / TAR / GZ archive could not be expanded (corrupt, encrypted,
    or over the configured fan-out / size limits)."""

    code = "archive_extraction_failed"


class OfficeConversionError(BinaryNormalizationError):
    """The office converter (Gotenberg / LibreOffice) failed to produce a PDF."""

    code = "office_conversion_failed"


class EmailParseError(BinaryNormalizationError):
    """An EML / MSG envelope could not be parsed."""

    code = "email_parse_failed"


class BinaryTooLargeError(BinaryNormalizationError):
    """The inbound payload exceeds the configured ``max_bytes`` cap."""

    code = "binary_too_large"
    http_status = 413


class BinaryFanoutError(BinaryNormalizationError):
    """Recursive expansion produced more artifacts than ``max_expanded_files``."""

    code = "binary_fanout_cap_exceeded"
