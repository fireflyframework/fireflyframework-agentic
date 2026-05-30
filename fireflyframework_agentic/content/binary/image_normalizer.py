# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Raster + vector image normalisation.

Multimodal LLM providers (and most OCR/loader paths) accept PNG, JPEG, GIF
and WebP natively. Everything else is converted here:

* **HEIC / HEIF / AVIF**  -- iPhone / modern-web photos -> PNG (pillow-heif).
* **Multi-frame TIFF**    -- fax scans -> a single multi-page PDF so the
                             downstream page count matches the document.
* **Single-frame TIFF / BMP** -> PNG.
* **SVG**                 -- vector -> PNG (cairosvg).
* **Animated inputs**     -- folded; GIF stays a still, TIFF becomes a PDF.

All third-party imports are lazy so the module imports cleanly without the
``binary`` extra installed; a conversion call then raises a typed
:class:`ImageConversionError`.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from fireflyframework_agentic.content.binary.errors import ImageConversionError

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class NormalisedImage:
    """Output of :meth:`ImageNormalizer.convert`.

    ``page_count`` is > 1 only for a multi-frame TIFF folded into a
    multi-page PDF; for everything else it is 1.
    """

    bytes: bytes
    media_type: str
    page_count: int


class ImageNormalizer:
    """Pillow-driven converter for image formats not natively renderable."""

    _HEIC_TYPES = {"image/heic", "image/heif", "image/avif"}
    _PASSTHROUGH = {"image/png", "image/jpeg", "image/gif", "image/webp"}

    def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> NormalisedImage:
        """Return a renderable PNG / PDF / passthrough image.

        Raises :class:`ImageConversionError` on any decode / encode failure.
        """
        if not data:
            raise ImageConversionError("image bytes are empty", filename=filename)

        if media_type in self._PASSTHROUGH:
            return NormalisedImage(bytes=data, media_type=media_type, page_count=1)
        if media_type == "image/svg+xml":
            return self._svg_to_png(data, filename)
        if media_type in self._HEIC_TYPES:
            return self._heic_to_png(data, filename)
        if media_type == "image/tiff":
            return self._tiff_to_pdf(data, filename)
        if media_type == "image/bmp":
            return self._raster_to_png(data, "BMP", filename)

        # Catch-all: Pillow autodetect + PNG re-encode. Covers exotic raster
        # formats (PCX, TGA, ...) without enumerating them.
        return self._raster_to_png(data, fmt=None, filename=filename)

    # ------------------------------------------------------------------

    def _heic_to_png(self, data: bytes, filename: str | None) -> NormalisedImage:
        # pillow-heif registers HEIF/HEIC/AVIF openers on import. The
        # side-effect registration is the library's published API, so the
        # import is load-bearing despite looking unused.
        try:
            import pillow_heif  # noqa: F401  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise ImageConversionError(
                "pillow-heif is required for HEIC/HEIF/AVIF input",
                filename=filename,
            ) from exc
        return self._raster_to_png(data, fmt=None, filename=filename)

    def _raster_to_png(self, data: bytes, fmt: str | None, filename: str | None) -> NormalisedImage:
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise ImageConversionError(
                "Pillow is required for image normalisation",
                filename=filename,
            ) from exc
        try:
            with Image.open(io.BytesIO(data)) as img:
                # Coerce to a mode PNG can always write (e.g. CMYK from a TIFF).
                if img.mode not in ("RGB", "RGBA", "L", "LA"):
                    img = img.convert("RGBA")
                # Multi-frame inputs (animated GIF) collapse to the first frame;
                # multi-page fan-out is the TIFF / archive path's job.
                if getattr(img, "n_frames", 1) > 1:
                    img.seek(0)
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
        except UnidentifiedImageError as exc:
            raise ImageConversionError(
                f"image bytes are not a recognised raster format: {exc}",
                filename=filename,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ImageConversionError(f"image conversion failed: {exc}", filename=filename) from exc
        return NormalisedImage(bytes=buf.getvalue(), media_type="image/png", page_count=1)

    def _tiff_to_pdf(self, data: bytes, filename: str | None) -> NormalisedImage:
        """Multi-frame TIFF -> multi-page PDF; single-frame TIFF -> PNG."""
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise ImageConversionError(
                "Pillow is required for TIFF normalisation",
                filename=filename,
            ) from exc
        try:
            with Image.open(io.BytesIO(data)) as img:
                frames: list[Image.Image] = []
                try:
                    while True:
                        frames.append(img.copy().convert("RGB"))
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass
        except UnidentifiedImageError as exc:
            raise ImageConversionError(f"TIFF bytes are not parseable: {exc}", filename=filename) from exc
        except Exception as exc:  # noqa: BLE001
            raise ImageConversionError(f"TIFF conversion failed: {exc}", filename=filename) from exc

        if not frames:
            raise ImageConversionError("TIFF contains no frames", filename=filename)

        if len(frames) == 1:
            buf = io.BytesIO()
            frames[0].save(buf, format="PNG", optimize=True)
            return NormalisedImage(bytes=buf.getvalue(), media_type="image/png", page_count=1)

        buf = io.BytesIO()
        frames[0].save(buf, format="PDF", save_all=True, append_images=frames[1:], resolution=200.0)
        return NormalisedImage(bytes=buf.getvalue(), media_type="application/pdf", page_count=len(frames))

    def _svg_to_png(self, data: bytes, filename: str | None) -> NormalisedImage:
        try:
            import cairosvg  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise ImageConversionError("cairosvg is required for SVG input", filename=filename) from exc
        try:
            raw = cairosvg.svg2png(bytestring=data, output_width=2048)
        except Exception as exc:  # noqa: BLE001
            raise ImageConversionError(f"SVG rasterisation failed: {exc}", filename=filename) from exc
        if not raw:
            raise ImageConversionError("SVG rasterisation produced no output", filename=filename)
        png_bytes: bytes = raw if isinstance(raw, bytes) else bytes(raw)
        return NormalisedImage(bytes=png_bytes, media_type="image/png", page_count=1)
