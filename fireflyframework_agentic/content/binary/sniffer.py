# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Magic-byte sniffer for every format the binary normaliser routes.

A free function rather than a class: stateless, dependency-free, callable
from both the normaliser and any loader registry. Inputs are
``(bytes, declared_media_type, filename)``; the return is the *normalised*
MIME (lowercased, no parameters), used as the routing key.

The filename hint disambiguates ZIP-based Office formats (DOCX, XLSX, PPTX,
ODT, ODS, ODP all share the ZIP magic bytes) and picks up text-ish formats
whose bytes don't carry unique magic.
"""

from __future__ import annotations

import os
import zipfile
from io import BytesIO

# --- Magic-byte signatures ---------------------------------------------------
_PDF = b"%PDF-"
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_GIF87 = b"GIF87a"
_GIF89 = b"GIF89a"
_RIFF = b"RIFF"
_WEBP = b"WEBP"
_TIFF_LE = b"II*\x00"
_TIFF_BE = b"MM\x00*"
_BMP = b"BM"
_ZIP = b"PK\x03\x04"
_ZIP_EMPTY = b"PK\x05\x06"
_ZIP_SPANNED = b"PK\x07\x08"
_GZ = b"\x1f\x8b"
_7Z = b"7z\xbc\xaf\x27\x1c"
_TAR_USTAR = b"ustar"  # at offset 257
_OLE_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls/.ppt and .msg
_HEIF_FTYP_OFFSET = 4
_HEIF_BRANDS = {
    b"heic",
    b"heix",
    b"hevc",
    b"hevx",
    b"heim",
    b"heis",
    b"hevm",
    b"hevs",
    b"mif1",
    b"msf1",
    b"avif",
}

# Heuristics for text-ish formats whose bytes don't have unique magic.
_SVG_HINTS = (b"<svg", b"<?xml")
_HTML_HINTS = (b"<!doctype html", b"<html", b"<HTML", b"<!DOCTYPE HTML")
_EML_HEADERS = (b"Received:", b"From:", b"Return-Path:", b"MIME-Version:", b"Message-ID:")
_RTF = b"{\\rtf"
_JSON_HINTS = (b"{", b"[")

# Extension -> MIME map used when magic bytes don't disambiguate (e.g.
# all ZIP-based Office formats look the same; the ZIP central directory
# listing pins them down, but the filename is a faster hint).
_EXTENSION_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".avif": "image/avif",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "application/xml",
    ".rtf": "application/rtf",
    ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".ppt": "application/vnd.ms-powerpoint",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".zip": "application/zip",
    ".7z": "application/x-7z-compressed",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".tgz": "application/gzip",
    ".eml": "message/rfc822",
    ".msg": "application/vnd.ms-outlook",
    ".vtt": "text/vtt",
    ".srt": "application/x-subrip",
}


def sniff_media_type(
    data: bytes,
    *,
    default: str | None = None,
    filename: str | None = None,
) -> str:
    """Best-effort content-type detection from magic bytes + filename hint.

    Returns the canonical lowercased MIME with no parameters. Falls back to
    ``default`` (also normalised) or ``application/octet-stream``.
    """
    if not data:
        return _normalize(default)

    # --- Unambiguous magic bytes -----------------------------------------
    if data.startswith(_PDF):
        return "application/pdf"
    if data.startswith(_PNG):
        return "image/png"
    if data.startswith(_JPEG):
        return "image/jpeg"
    if data.startswith(_GIF87) or data.startswith(_GIF89):
        return "image/gif"
    if data[:4] == _RIFF and data[8:12] == _WEBP:
        return "image/webp"
    if data.startswith(_TIFF_LE) or data.startswith(_TIFF_BE):
        return "image/tiff"
    if data.startswith(_BMP):
        return "image/bmp"
    if data.startswith(_7Z):
        return "application/x-7z-compressed"
    if data.startswith(_GZ):
        return "application/gzip"
    if data[257:262] == _TAR_USTAR:
        return "application/x-tar"
    if data.startswith(_RTF):
        return "application/rtf"

    # --- HEIF family (HEIC, HEIX, AVIF, ...) -----------------------------
    if len(data) >= _HEIF_FTYP_OFFSET + 8 and data[_HEIF_FTYP_OFFSET : _HEIF_FTYP_OFFSET + 4] == b"ftyp":
        brand = data[_HEIF_FTYP_OFFSET + 4 : _HEIF_FTYP_OFFSET + 8]
        if brand == b"avif":
            return "image/avif"
        if brand in _HEIF_BRANDS:
            return "image/heic"

    # --- ZIP-based formats (OOXML, ODF, EPUB, plain ZIP) -----------------
    if data.startswith(_ZIP) or data.startswith(_ZIP_EMPTY) or data.startswith(_ZIP_SPANNED):
        zipped = _peek_zip_kind(data)
        if zipped is not None:
            return zipped
        return "application/zip"

    # --- OLE Compound Format (legacy Office + Outlook MSG) ---------------
    if data.startswith(_OLE_CFB):
        # The MSG payload is OLE CFB; the doc/xls/ppt legacy formats are
        # too. The filename extension settles the dispute, falling back to
        # the OLE umbrella.
        ext_hint = _from_extension(filename)
        if ext_hint in {
            "application/vnd.ms-outlook",
            "application/msword",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
        }:
            return ext_hint
        return "application/x-cfb"

    # --- Text-ish heuristics ---------------------------------------------
    head = data[:512].lstrip()
    head_lower = head.lower()
    if any(head_lower.startswith(hint) for hint in _HTML_HINTS):
        return "text/html"
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:1024]):
        return "image/svg+xml"
    if head.startswith(b"<?xml"):
        return "application/xml"
    if any(header in head for header in _EML_HEADERS):
        return "message/rfc822"

    # --- Filename extension ----------------------------------------------
    ext_hint = _from_extension(filename)
    if ext_hint:
        return ext_hint

    return _normalize(default)


def _peek_zip_kind(data: bytes) -> str | None:
    """Inspect the ZIP central directory to disambiguate OOXML / ODF / EPUB /
    plain ZIP. Falls back to ``None`` on any read error -- the caller treats
    the result as a plain ZIP.
    """
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    if "[Content_Types].xml" in names:
        if any(n.startswith("word/") for n in names):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if any(n.startswith("xl/") for n in names):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if any(n.startswith("ppt/") for n in names):
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if "mimetype" in names:
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                mime = zf.read("mimetype").decode("ascii", errors="replace").strip()
            if mime:
                return mime
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, OSError):
            pass
    return None


def _from_extension(filename: str | None) -> str | None:
    if not filename:
        return None
    _, ext = os.path.splitext(filename.lower())
    return _EXTENSION_MAP.get(ext)


def _normalize(value: str | None) -> str:
    if not value:
        return "application/octet-stream"
    return value.split(";", 1)[0].strip().lower() or "application/octet-stream"
