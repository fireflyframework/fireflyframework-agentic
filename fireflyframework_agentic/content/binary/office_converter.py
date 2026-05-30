# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Office -> PDF conversion behind a single ``OfficeConverter`` protocol.

Three adapters ship in-tree, selected by :attr:`BinaryConfig.office_converter`
via :func:`build_office_converter`:

* :class:`GotenbergConverter` -- HTTP client against a Gotenberg sidecar.
  Distroless-friendly: the application container carries no ``soffice``
  binary. DOC/DOCX/XLS/.../RTF go to ``/forms/libreoffice/convert``; HTML
  goes to ``/forms/chromium/convert/html``.
* :class:`LibreOfficeConverter` -- in-container subprocess wrapper around
  ``soffice --headless``. For images that bundle LibreOffice.
* :class:`NoOpOfficeConverter` -- the default. ``supports`` is always
  ``False`` so the normaliser passes Office formats through untouched (for a
  downstream text/markdown loader to handle).

``convert`` returns PDF bytes. ``httpx`` (Gotenberg) ships in the ``binary``
extra; ``soffice`` is an OS-level dependency of the runtime image.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.errors import OfficeConversionError

logger = logging.getLogger(__name__)

# The MIME set the office converters can render to PDF. The normaliser's
# ``office.supports`` check stays adapter-agnostic by consulting this.
OFFICE_MEDIA_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-powerpoint",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
        "application/rtf",
        "text/rtf",
        "text/html",
    }
)

# MIME -> filename extension. The converters need the right extension on the
# uploaded / temp file so LibreOffice picks the correct import filter.
_EXT: Final[dict[str, str]] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/vnd.oasis.opendocument.spreadsheet": "ods",
    "application/vnd.oasis.opendocument.presentation": "odp",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "text/html": "html",
}


@runtime_checkable
class OfficeConverter(Protocol):
    """Convert Office bytes to PDF bytes.

    Implementations raise :class:`OfficeConversionError` on any failure. The
    contract is async because every realistic adapter is I/O-bound (HTTP
    round-trip or subprocess wait).
    """

    @staticmethod
    def supports(media_type: str) -> bool: ...

    async def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> bytes: ...


def _supports(media_type: str) -> bool:
    return media_type in OFFICE_MEDIA_TYPES


class GotenbergConverter:
    """``OfficeConverter`` backed by a Gotenberg HTTP sidecar."""

    def __init__(self, config: BinaryConfig) -> None:
        self._base_url = config.gotenberg_url.rstrip("/")
        self._timeout_s = config.gotenberg_timeout_s

    @staticmethod
    def supports(media_type: str) -> bool:
        return _supports(media_type)

    async def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> bytes:
        import httpx

        ext = _EXT.get(media_type)
        if ext is None:
            raise OfficeConversionError(f"unsupported office media type {media_type!r}", filename=filename)
        url = (
            f"{self._base_url}/forms/chromium/convert/html"
            if ext == "html"
            else f"{self._base_url}/forms/libreoffice/convert"
        )
        if ext == "html":
            # The Chromium HTML endpoint expects a single ``index.html`` upload.
            files = {"files": ("index.html", data, "text/html")}
        else:
            upload_name = (filename or "document").rsplit("/", 1)[-1]
            if not upload_name.lower().endswith("." + ext):
                stem = upload_name.rsplit(".", 1)[0] if "." in upload_name else upload_name
                upload_name = f"{stem}.{ext}"
            files = {"files": (upload_name, data, media_type)}

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(url, files=files)
        except httpx.HTTPError as exc:
            raise OfficeConversionError(f"Gotenberg request failed: {exc}", filename=filename) from exc
        if resp.status_code >= 400:
            raise OfficeConversionError(
                f"Gotenberg returned HTTP {resp.status_code}: {resp.text[:200] or 'no body'}",
                filename=filename,
            )
        return resp.content


class LibreOfficeConverter:
    """``OfficeConverter`` that shells out to local ``soffice --headless``."""

    def __init__(self, config: BinaryConfig) -> None:
        self._binary = config.libreoffice_path
        self._timeout_s = config.libreoffice_timeout_s

    @staticmethod
    def supports(media_type: str) -> bool:
        return _supports(media_type)

    async def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> bytes:
        ext = _EXT.get(media_type)
        if ext is None:
            raise OfficeConversionError(f"unsupported office media type {media_type!r}", filename=filename)
        if shutil.which(self._binary) is None:
            raise OfficeConversionError(f"LibreOffice binary {self._binary!r} not found on PATH", filename=filename)

        # Per-call workdir + profile so concurrent conversions don't deadlock
        # on a shared soffice user profile.
        workdir = Path(tempfile.mkdtemp(prefix="firefly-soffice-"))
        try:
            stem = uuid.uuid4().hex
            input_path = workdir / f"{stem}.{ext}"
            output_path = workdir / f"{stem}.pdf"
            input_path.write_bytes(data)
            profile_dir = workdir / "profile"
            profile_dir.mkdir()
            cmd = [
                self._binary,
                "--headless",
                "--norestore",
                "--nologo",
                "--nofirststartwizard",
                f"-env:UserInstallation=file://{profile_dir}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(workdir),
                str(input_path),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)
                except TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise OfficeConversionError(
                        f"LibreOffice timed out after {self._timeout_s}s",
                        filename=filename,
                    ) from exc
            except FileNotFoundError as exc:
                raise OfficeConversionError(f"LibreOffice binary not executable: {exc}", filename=filename) from exc

            if proc.returncode != 0 or not output_path.exists():
                err = (stderr or b"").decode("utf-8", errors="replace").strip()[-200:]
                raise OfficeConversionError(
                    f"LibreOffice failed (rc={proc.returncode}): {err or 'no stderr'}",
                    filename=filename,
                )
            return output_path.read_bytes()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


class NoOpOfficeConverter:
    """Default converter: ``supports`` is always ``False``.

    The normaliser then passes Office formats through untouched, leaving
    conversion to a downstream text/markdown loader.
    """

    @staticmethod
    def supports(media_type: str) -> bool:
        return False

    async def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> bytes:
        raise OfficeConversionError(
            "office converter is disabled (set office_converter to 'gotenberg' or 'libreoffice')",
            filename=filename,
        )


def build_office_converter(config: BinaryConfig) -> OfficeConverter:
    """Return the converter named by :attr:`BinaryConfig.office_converter`."""
    choice = (config.office_converter or "none").strip().lower()
    if choice == "gotenberg":
        return GotenbergConverter(config)
    if choice == "libreoffice":
        return LibreOfficeConverter(config)
    return NoOpOfficeConverter()
