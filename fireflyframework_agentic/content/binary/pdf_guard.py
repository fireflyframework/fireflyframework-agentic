# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""``PdfGuard`` -- pre-flight integrity check on inbound PDFs.

Rejects:

* encrypted PDFs            -> :class:`EncryptedPdfError` (422 ``encrypted_pdf``)
* corrupt / truncated PDFs  -> :class:`CorruptPdfError` (422 ``corrupt_pdf``)

Uses ``pypdf`` (lazy import) so encrypted / corrupt PDFs fail fast with a
typed error instead of crashing a downstream reader. ``pypdf`` ships in the
``binary`` optional extra.
"""

from __future__ import annotations

import logging
from io import BytesIO

from fireflyframework_agentic.content.binary.errors import CorruptPdfError, EncryptedPdfError

logger = logging.getLogger(__name__)


class PdfGuard:
    """Stateless guard; safe to reuse as a singleton."""

    def check(self, data: bytes, *, filename: str | None = None) -> None:
        """Raise on encrypted / corrupt PDFs; return ``None`` on success.

        Cheap: opens the PDF with pypdf in non-strict mode and peeks at the
        encryption flag and the page tree. No content streams are parsed.
        """
        import pypdf
        from pypdf.errors import PdfReadError

        try:
            reader = pypdf.PdfReader(BytesIO(data), strict=False)
        except PdfReadError as exc:
            raise CorruptPdfError(f"could not parse PDF: {exc}", filename=filename) from exc
        except Exception as exc:  # noqa: BLE001
            raise CorruptPdfError(f"could not parse PDF: {exc}", filename=filename) from exc

        if reader.is_encrypted:
            raise EncryptedPdfError(
                "PDF is encrypted; supply an unprotected copy.",
                filename=filename,
            )

        try:
            page_count = len(reader.pages)
        except Exception as exc:  # noqa: BLE001
            raise CorruptPdfError(f"could not enumerate PDF pages: {exc}", filename=filename) from exc
        if page_count <= 0:
            raise CorruptPdfError("PDF reports zero pages.", filename=filename)
