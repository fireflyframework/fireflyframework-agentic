# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""Unit tests for the unified binary-normalisation submodule."""

from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage

import pytest

from fireflyframework_agentic.content.binary import (
    ArchiveUnpacker,
    BinaryArtifact,
    BinaryConfig,
    BinaryNormalizationError,
    BinaryNormalizer,
    GotenbergConverter,
    LibreOfficeConverter,
    NoOpOfficeConverter,
    UnsupportedBinaryError,
    build_office_converter,
    sniff_media_type,
)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# --- sniffer ---------------------------------------------------------------


def test_sniff_pdf_by_magic() -> None:
    assert sniff_media_type(b"%PDF-1.7\n...") == "application/pdf"


def test_sniff_png_by_magic() -> None:
    assert sniff_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_sniff_text_by_extension() -> None:
    assert sniff_media_type(b"plain content", filename="notes.txt") == "text/plain"


def test_sniff_html_by_heuristic() -> None:
    assert sniff_media_type(b"<!DOCTYPE html><html></html>") == "text/html"


def test_sniff_docx_by_zip_central_directory() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<doc/>")
    assert sniff_media_type(buf.getvalue(), filename="x.docx") == DOCX


def test_sniff_falls_back_to_default_then_octet_stream() -> None:
    assert sniff_media_type(b"\x00\x01\x02opaque", default="application/x-thing") == "application/x-thing"
    assert sniff_media_type(b"\x00\x01\x02opaque") == "application/octet-stream"


# --- BinaryArtifact / errors ----------------------------------------------


def test_unsupported_error_is_415_and_subclass_of_value_error() -> None:
    err = UnsupportedBinaryError("nope")
    assert err.http_status == 415
    assert err.code == "unsupported_file"
    assert isinstance(err, BinaryNormalizationError)
    assert isinstance(err, ValueError)


# --- normalise: passthroughs ----------------------------------------------


async def test_normalise_empty_raises() -> None:
    with pytest.raises(BinaryNormalizationError):
        await BinaryNormalizer().normalise(b"")


async def test_normalise_text_passthrough() -> None:
    artifacts = await BinaryNormalizer().normalise(b"hello world", filename="a.txt")
    assert len(artifacts) == 1
    art = artifacts[0]
    assert isinstance(art, BinaryArtifact)
    assert art.media_type == "text/plain"
    assert art.kind == "text"
    assert art.page_count == 1
    assert art.derived_from == ()


async def test_normalise_png_passthrough_kind_image() -> None:
    artifacts = await BinaryNormalizer().normalise(b"\x89PNG\r\n\x1a\nbody", filename="p.png")
    assert artifacts[0].kind == "image"
    assert artifacts[0].media_type == "image/png"


async def test_normalise_docx_passthrough_with_noop_office() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<doc/>")
    artifacts = await BinaryNormalizer().normalise(buf.getvalue(), filename="report.docx")
    assert len(artifacts) == 1
    assert artifacts[0].kind == "docx"
    assert artifacts[0].media_type == DOCX


async def test_normalise_unsupported_raises_415() -> None:
    with pytest.raises(UnsupportedBinaryError):
        await BinaryNormalizer().normalise(b"\x00\x01\x02\x03binary-noise", filename="x.bin")


async def test_normalise_disabled_single_passthrough() -> None:
    norm = BinaryNormalizer(config=BinaryConfig(normalize_enabled=False))
    artifacts = await norm.normalise(b"\x00\x01\x02opaque", filename="x.bin")
    assert len(artifacts) == 1
    assert artifacts[0].kind == "unknown"


async def test_normalise_max_bytes_cap() -> None:
    norm = BinaryNormalizer(config=BinaryConfig(max_bytes=4))
    with pytest.raises(BinaryNormalizationError):
        await norm.normalise(b"toolong", filename="a.txt")


# --- normalise: archive fan-out -------------------------------------------


def _zip_with(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in members.items():
            zf.writestr(name, payload)
    return buf.getvalue()


async def test_normalise_zip_fans_out() -> None:
    data = _zip_with({"a.txt": b"alpha", "b.txt": b"beta"})
    artifacts = await BinaryNormalizer().normalise(data, filename="bundle.zip")
    names = sorted(a.filename for a in artifacts)
    assert names == ["a.txt", "b.txt"]
    assert all(a.kind == "text" for a in artifacts)
    assert all(a.derived_from == ("bundle.zip",) for a in artifacts)


async def test_normalise_zip_fanout_cap() -> None:
    data = _zip_with({"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"})
    norm = BinaryNormalizer(config=BinaryConfig(max_expanded_files=2))
    with pytest.raises(BinaryNormalizationError):
        await norm.normalise(data, filename="bundle.zip")


# --- normalise: office + email --------------------------------------------


class _FakeOffice:
    @staticmethod
    def supports(media_type: str) -> bool:
        return media_type == DOCX

    async def convert(self, data: bytes, *, media_type: str, filename: str | None = None) -> bytes:
        return b"%PDF-1.4 converted"


async def test_normalise_office_converts_to_pdf() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<doc/>")
    norm = BinaryNormalizer(office=_FakeOffice())
    artifacts = await norm.normalise(buf.getvalue(), filename="report.docx")
    assert len(artifacts) == 1
    assert artifacts[0].media_type == "application/pdf"
    assert artifacts[0].kind == "pdf"
    assert artifacts[0].filename == "report.pdf"
    assert artifacts[0].derived_from == ("report.docx",)


async def test_normalise_eml_body_fans_out() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Hi"
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg.set_content("the body text")
    artifacts = await BinaryNormalizer().normalise(msg.as_bytes(), filename="m.eml")
    assert any(a.filename == "body.txt" and a.kind == "text" for a in artifacts)


# --- office converter factory ---------------------------------------------


def test_build_office_converter_default_is_noop() -> None:
    assert isinstance(build_office_converter(BinaryConfig()), NoOpOfficeConverter)


def test_build_office_converter_gotenberg() -> None:
    conv = build_office_converter(BinaryConfig(office_converter="gotenberg"))
    assert isinstance(conv, GotenbergConverter)
    assert conv.supports(DOCX)


def test_build_office_converter_libreoffice() -> None:
    assert isinstance(build_office_converter(BinaryConfig(office_converter="libreoffice")), LibreOfficeConverter)


def test_noop_office_does_not_support_anything() -> None:
    assert NoOpOfficeConverter.supports(DOCX) is False


def test_archive_unpacker_supports() -> None:
    assert ArchiveUnpacker.supports("application/zip") is True
    assert ArchiveUnpacker.supports("application/pdf") is False
