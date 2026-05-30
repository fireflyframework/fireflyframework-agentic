# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""``BinaryNormalizer`` -- caller bytes in, normalised artifacts out.

The normaliser is the single entry point for turning a raw caller-supplied
binary into one or more :class:`BinaryArtifact` rows that a downstream
consumer (a document loader, a multimodal LLM, ...) can use directly.

It:

1. Sniffs the actual media type from magic bytes (never trusts the declared
   Content-Type or filename extension alone).
2. Routes to the right handler:
   * **PDF**                         -> :class:`PdfGuard` integrity check, passthrough.
   * **Native rasters** (PNG/JPEG/GIF/WebP) -> passthrough.
   * **Convertible images** (HEIC/HEIF/AVIF/TIFF/BMP/SVG) -> :class:`ImageNormalizer`.
   * **Office docs** -> :class:`OfficeConverter` (when one is configured), else passthrough.
   * **Archives / Emails** -> fan out + recurse.
   * **Plain text/markdown/CSV** -> wrapped to PDF via the office converter
     when ``wrap_text_as_pdf`` is set, else passthrough.
3. Fans out into a list of :class:`BinaryArtifact`, each carrying its
   ``derived_from`` ancestry so callers can trace a member back to the
   inbound bundle.

Recursion depth and total fan-out are bounded by :class:`BinaryConfig`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fireflyframework_agentic.content.binary.archive_unpacker import ArchiveUnpacker
from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.email_unpacker import EmailUnpacker
from fireflyframework_agentic.content.binary.errors import (
    ArchiveExtractionError,
    BinaryFanoutError,
    BinaryNormalizationError,
    BinaryTooLargeError,
    UnsupportedBinaryError,
)
from fireflyframework_agentic.content.binary.image_normalizer import ImageNormalizer
from fireflyframework_agentic.content.binary.office_converter import OfficeConverter
from fireflyframework_agentic.content.binary.pdf_guard import PdfGuard
from fireflyframework_agentic.content.binary.sniffer import sniff_media_type

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class BinaryArtifact:
    """One normalised, consumer-ready unit emitted by the normaliser.

    A single inbound PDF yields one artifact; a ZIP of N files yields N
    artifacts, each carrying the ``derived_from`` ancestry tuple so a
    provenance / citation graph can trace back to the parent bundle.

    ``kind`` is a canonical lowercase token (``"pdf"``, ``"image"``,
    ``"docx"``, ``"archive"``, ...); hosts that maintain their own kind enum
    can construct it from this string. ``page_count`` is the PDF page count
    (1 for non-paged formats; > 1 for a multi-frame TIFF folded to PDF).
    """

    bytes: bytes
    media_type: str
    filename: str
    kind: str = ""
    page_count: int = 1
    derived_from: tuple[str, ...] = field(default_factory=tuple)


# Native rasters most LLM/loader paths accept without conversion.
_IMAGE_NATIVE = {"image/png", "image/jpeg", "image/gif", "image/webp"}
# Image formats that need conversion before use.
_IMAGE_CONVERT = {"image/heic", "image/heif", "image/avif", "image/tiff", "image/bmp", "image/svg+xml"}
# Plain-text-ish formats that the wrap-to-PDF path can render via the office converter.
_TEXT_WRAPPED = {"text/plain", "text/markdown", "text/csv"}
# Media-type -> canonical kind token for passthrough formats.
_KIND_OF: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/rtf": "rtf",
    "application/epub+zip": "epub",
    "text/html": "html",
    "text/markdown": "markdown",
    "text/plain": "text",
    "text/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/json": "json",
    "application/xml": "xml",
    "text/vtt": "transcript",
    "application/x-subrip": "transcript",
}


class BinaryNormalizer:
    """Caller bytes -> a list of :class:`BinaryArtifact`.

    Handlers are injected so a host can swap implementations (e.g. a
    Gotenberg vs LibreOffice office converter). Build the office converter
    with :func:`~fireflyframework_agentic.content.binary.office_converter.build_office_converter`.
    """

    def __init__(
        self,
        *,
        config: BinaryConfig | None = None,
        pdf_guard: PdfGuard | None = None,
        image: ImageNormalizer | None = None,
        office: OfficeConverter | None = None,
        archive: ArchiveUnpacker | None = None,
        email: EmailUnpacker | None = None,
    ) -> None:
        from fireflyframework_agentic.content.binary.office_converter import NoOpOfficeConverter

        self._config = config or BinaryConfig()
        self._pdf_guard = pdf_guard or PdfGuard()
        self._image = image or ImageNormalizer()
        self._office = office or NoOpOfficeConverter()
        self._archive = archive or ArchiveUnpacker(self._config)
        self._email = email or EmailUnpacker(self._config)

    async def normalise(
        self,
        data: bytes,
        *,
        declared_media_type: str | None = None,
        filename: str | None = None,
    ) -> list[BinaryArtifact]:
        """Normalise ``data`` into one or more artifacts. Never returns empty."""
        if not data:
            raise BinaryNormalizationError("inbound bytes are empty", filename=filename)
        if self._config.max_bytes is not None and len(data) > self._config.max_bytes:
            raise BinaryTooLargeError(
                f"binary exceeds the {self._config.max_bytes}-byte cap",
                filename=filename,
            )
        if not self._config.normalize_enabled:
            media_type = sniff_media_type(data, default=declared_media_type, filename=filename)
            return [
                BinaryArtifact(
                    bytes=data,
                    media_type=media_type,
                    filename=filename or "document",
                    kind=_kind_for(media_type),
                    page_count=_page_count_for(data, media_type),
                )
            ]

        sink: list[BinaryArtifact] = []
        await self._dispatch(
            data,
            declared_media_type=declared_media_type,
            filename=filename or "document",
            depth=0,
            ancestry=(),
            sink=sink,
        )
        if not sink:
            raise BinaryNormalizationError("normalisation produced no artifacts", filename=filename)
        return sink

    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        data: bytes,
        *,
        declared_media_type: str | None,
        filename: str,
        depth: int,
        ancestry: tuple[str, ...],
        sink: list[BinaryArtifact],
    ) -> None:
        if depth > self._config.max_recursion_depth:
            raise ArchiveExtractionError(
                f"binary nesting exceeds depth {self._config.max_recursion_depth}",
                filename=filename,
            )
        if len(sink) >= self._config.max_expanded_files:
            raise BinaryFanoutError(
                f"binary expansion exceeded {self._config.max_expanded_files} files",
                filename=filename,
            )

        media_type = sniff_media_type(data, default=declared_media_type, filename=filename)

        # Archives -> fan out + recurse.
        if self._archive.supports(media_type):
            for member_name, member_bytes in self._archive.unpack(data, media_type=media_type, filename=filename):
                await self._dispatch(
                    member_bytes,
                    declared_media_type=None,
                    filename=member_name.rsplit("/", 1)[-1],
                    depth=depth + 1,
                    ancestry=(*ancestry, filename),
                    sink=sink,
                )
            return

        # Emails -> fan out + recurse.
        if self._email.supports(media_type):
            for member_name, member_bytes in self._email.unpack(data, media_type=media_type, filename=filename):
                await self._dispatch(
                    member_bytes,
                    declared_media_type=None,
                    filename=member_name,
                    depth=depth + 1,
                    ancestry=(*ancestry, filename),
                    sink=sink,
                )
            return

        # PDF -> integrity check + passthrough.
        if media_type == "application/pdf":
            self._pdf_guard.check(data, filename=filename)
            sink.append(
                BinaryArtifact(
                    bytes=data,
                    media_type=media_type,
                    filename=filename,
                    kind="pdf",
                    page_count=_page_count_for(data, media_type),
                    derived_from=ancestry,
                )
            )
            return

        # Natively renderable rasters -> passthrough.
        if media_type in _IMAGE_NATIVE:
            sink.append(
                BinaryArtifact(
                    bytes=data,
                    media_type=media_type,
                    filename=filename,
                    kind="image",
                    page_count=1,
                    derived_from=ancestry,
                )
            )
            return

        # Images needing conversion.
        if media_type in _IMAGE_CONVERT:
            converted = self._image.convert(data, media_type=media_type, filename=filename)
            kind = "pdf" if converted.media_type == "application/pdf" else "image"
            sink.append(
                BinaryArtifact(
                    bytes=converted.bytes,
                    media_type=converted.media_type,
                    filename=_swap_extension(filename, converted.media_type),
                    kind=kind,
                    page_count=converted.page_count,
                    derived_from=(*ancestry, filename),
                )
            )
            return

        # Office formats -> PDF when a converter is configured.
        if self._office.supports(media_type):
            pdf_bytes = await self._office.convert(data, media_type=media_type, filename=filename)
            sink.append(
                BinaryArtifact(
                    bytes=pdf_bytes,
                    media_type="application/pdf",
                    filename=_swap_extension(filename, "application/pdf"),
                    kind="pdf",
                    page_count=_page_count_for(pdf_bytes, "application/pdf"),
                    derived_from=(*ancestry, filename),
                )
            )
            return

        # Plain text -> wrap in HTML + render to PDF (multimodal use case).
        if self._config.wrap_text_as_pdf and media_type in _TEXT_WRAPPED:
            wrapped = _wrap_text_as_html(data, media_type)
            pdf_bytes = await self._office.convert(wrapped, media_type="text/html", filename=filename)
            sink.append(
                BinaryArtifact(
                    bytes=pdf_bytes,
                    media_type="application/pdf",
                    filename=_swap_extension(filename, "application/pdf"),
                    kind="pdf",
                    page_count=_page_count_for(pdf_bytes, "application/pdf"),
                    derived_from=(*ancestry, filename),
                )
            )
            return

        # Loader-handled formats (DOCX/HTML/MD/TXT/CSV/...) -> passthrough.
        if media_type in _KIND_OF or media_type.startswith("text/"):
            sink.append(
                BinaryArtifact(
                    bytes=data,
                    media_type=media_type,
                    filename=filename,
                    kind=_kind_for(media_type),
                    page_count=_page_count_for(data, media_type),
                    derived_from=ancestry,
                )
            )
            return

        raise UnsupportedBinaryError(
            f"no normalisation route for media type {media_type!r}",
            filename=filename,
        )


def _kind_for(media_type: str) -> str:
    return _KIND_OF.get(media_type, "unknown")


def _page_count_for(data: bytes, media_type: str) -> int:
    if media_type != "application/pdf":
        return 1
    import io as _io

    try:
        import pypdf

        reader = pypdf.PdfReader(_io.BytesIO(data), strict=False)
        return max(1, len(reader.pages))
    except Exception:  # noqa: BLE001
        return 1


def _wrap_text_as_html(data: bytes, media_type: str) -> bytes:
    """Wrap plain text / markdown / CSV in a tiny ``<pre>`` HTML envelope.

    Escapes the content so pre-formatted layout survives an HTML->PDF import.
    No markdown->HTML conversion is performed (keeps the dependency surface
    tight); the text is rendered verbatim as preformatted.
    """
    import html as _html

    body = _html.escape(data.decode("utf-8", errors="replace"))
    document = (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8"></head>'
        f"<body><pre>{body}</pre></body></html>"
    )
    return document.encode("utf-8")


def _swap_extension(filename: str, media_type: str) -> str:
    """Return ``filename`` with its extension swapped for ``media_type``'s."""
    ext_for = {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    new_ext = ext_for.get(media_type, "bin")
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return f"{stem}.{new_ext}"
