# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""``ArchiveUnpacker`` -- expand ZIP / 7z / TAR / GZ / EPUB members.

Returns one ``(path, bytes)`` tuple per member. The
:class:`~fireflyframework_agentic.content.binary.normalizer.BinaryNormalizer`
recurses on each member; the per-archive caps here (file count +
uncompressed bytes) plus the normaliser's depth cap guard against
zip-bomb fan-out.

``py7zr`` (7z) and stdlib ``zipfile`` / ``tarfile`` / ``gzip`` back the
formats. ``py7zr`` is imported lazily and ships in the ``binary`` extra.
"""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
import zipfile
from collections.abc import Iterator

from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.errors import ArchiveExtractionError

logger = logging.getLogger(__name__)

_ARCHIVE_TYPES = {
    "application/zip",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/epub+zip",
}


class ArchiveUnpacker:
    """Yield one ``(path, bytes)`` per archive member."""

    def __init__(self, config: BinaryConfig | None = None) -> None:
        config = config or BinaryConfig()
        self._max_files = config.max_expanded_files
        self._max_uncompressed = config.max_uncompressed_bytes

    @staticmethod
    def supports(media_type: str) -> bool:
        return media_type in _ARCHIVE_TYPES

    def unpack(
        self,
        data: bytes,
        *,
        media_type: str,
        filename: str | None = None,
    ) -> list[tuple[str, bytes]]:
        """Return every member as ``(path, bytes)``.

        Skips directories and zero-byte members. Raises
        :class:`ArchiveExtractionError` on corrupt archives, password-
        protected members, or a fan-out / size-limit breach.
        """
        try:
            return list(self._iter_members(data, media_type, filename))
        except ArchiveExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ArchiveExtractionError(f"archive could not be opened: {exc}", filename=filename) from exc

    # ------------------------------------------------------------------

    def _iter_members(self, data: bytes, media_type: str, filename: str | None) -> Iterator[tuple[str, bytes]]:
        if media_type in {"application/zip", "application/epub+zip"}:
            yield from self._iter_zip(data, filename)
        elif media_type == "application/x-7z-compressed":
            yield from self._iter_7z(data, filename)
        elif media_type == "application/x-tar":
            yield from self._iter_tar(data, filename)
        elif media_type == "application/gzip":
            yield from self._iter_gz(data, filename)
        else:
            raise ArchiveExtractionError(f"unsupported archive media type {media_type!r}", filename=filename)

    def _iter_zip(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise ArchiveExtractionError(f"corrupt zip: {exc}", filename=filename) from exc
        with zf:
            total_bytes = 0
            yielded = 0
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:  # password bit
                    raise ArchiveExtractionError(
                        f"zip member {info.filename!r} is password-protected",
                        filename=filename,
                    )
                if info.file_size <= 0:
                    continue
                total_bytes += info.file_size
                self._enforce_limits(yielded + 1, total_bytes, filename)
                try:
                    member_bytes = zf.read(info.filename)
                except (RuntimeError, zipfile.BadZipFile) as exc:
                    raise ArchiveExtractionError(
                        f"could not read zip entry {info.filename!r}: {exc}",
                        filename=filename,
                    ) from exc
                yielded += 1
                yield info.filename, member_bytes

    def _iter_7z(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        try:
            import py7zr  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise ArchiveExtractionError(
                "py7zr is required to extract 7z archives",
                filename=filename,
            ) from exc
        try:
            with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as sz:
                if sz.needs_password():
                    raise ArchiveExtractionError("password-protected 7z archives are not supported", filename=filename)
                contents: dict[str, io.BytesIO] = sz.readall() or {}  # pyright: ignore[reportAttributeAccessIssue]
        except ArchiveExtractionError:
            raise
        except Exception as exc:  # noqa: BLE001
            if "password" in str(exc).lower():
                raise ArchiveExtractionError(
                    "password-protected 7z archives are not supported", filename=filename
                ) from exc
            raise ArchiveExtractionError(f"corrupt 7z archive: {exc}", filename=filename) from exc

        total_bytes = 0
        yielded = 0
        for path, buf in contents.items():
            payload = buf.getvalue()
            if not payload:
                continue
            total_bytes += len(payload)
            self._enforce_limits(yielded + 1, total_bytes, filename)
            yielded += 1
            yield path, payload

    def _iter_tar(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:  # noqa: SIM117
                total_bytes = 0
                yielded = 0
                for info in tf:
                    if not info.isfile() or info.size <= 0:
                        continue
                    total_bytes += info.size
                    self._enforce_limits(yielded + 1, total_bytes, filename)
                    handle = tf.extractfile(info)
                    if handle is None:
                        continue
                    yielded += 1
                    yield info.name, handle.read()
        except ArchiveExtractionError:
            raise
        except tarfile.TarError as exc:
            raise ArchiveExtractionError(f"corrupt tar: {exc}", filename=filename) from exc

    def _iter_gz(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        try:
            decompressed = gzip.decompress(data)
        except (OSError, EOFError) as exc:
            raise ArchiveExtractionError(f"corrupt gzip: {exc}", filename=filename) from exc
        if len(decompressed) > self._max_uncompressed:
            raise ArchiveExtractionError(
                f"gzip exceeds the {self._max_uncompressed}-byte ceiling",
                filename=filename,
            )
        # A gzip stream is single-member by definition. Recover the inner
        # filename when present; fall back to the archive name without the
        # ``.gz`` / ``.tgz`` suffix.
        inner_name = (filename or "payload").removesuffix(".gz").removesuffix(".tgz") or "payload"
        yield inner_name, decompressed

    def _enforce_limits(self, count: int, total_bytes: int, filename: str | None) -> None:
        if count > self._max_files:
            raise ArchiveExtractionError(
                f"archive expansion exceeds max {self._max_files} files",
                filename=filename,
            )
        if total_bytes > self._max_uncompressed:
            raise ArchiveExtractionError(
                f"archive expansion exceeds the {self._max_uncompressed}-byte ceiling",
                filename=filename,
            )
