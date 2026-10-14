# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Real binary fixtures for optional archive and image dependencies."""

from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path

import pytest

from fireflyframework_agentic.content.binary.archive_unpacker import ArchiveUnpacker
from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.errors import ArchiveExtractionError, ImageConversionError
from fireflyframework_agentic.content.binary.image_normalizer import ImageNormalizer


def _seven_zip(members: dict[str, bytes], *, password: str | None = None) -> bytes:
    py7zr = pytest.importorskip("py7zr")
    buffer = io.BytesIO()
    with py7zr.SevenZipFile(buffer, "w", password=password) as archive:
        archive.set_encoded_header_mode(False)
        for name, payload in members.items():
            archive.writestr(payload, name)
    return buffer.getvalue()


def test_7z_extracts_nested_members_in_memory_and_skips_empty_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    data = _seven_zip({"nested/a.txt": b"alpha", "b.txt": b"beta", "empty.txt": b""})
    result = ArchiveUnpacker(BinaryConfig(max_expanded_files=2, max_uncompressed_bytes=9)).unpack(
        data, media_type="application/x-7z-compressed"
    )
    assert result == [("nested/a.txt", b"alpha"), ("b.txt", b"beta")]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (BinaryConfig(max_expanded_files=1), "max 1 files"),
        (BinaryConfig(max_uncompressed_bytes=8), "8-byte ceiling"),
    ],
)
def test_7z_rejects_expansion_limits(config: BinaryConfig, message: str) -> None:
    data = _seven_zip({"a.txt": b"alpha", "b.txt": b"beta"})
    with pytest.raises(ArchiveExtractionError, match=message):
        ArchiveUnpacker(config).unpack(data, media_type="application/x-7z-compressed")


def test_7z_rejects_password_protected_archives() -> None:
    data = _seven_zip({"a.txt": b"secret"}, password="fixture-password")
    with pytest.raises(ArchiveExtractionError, match="password-protected"):
        ArchiveUnpacker().unpack(data, media_type="application/x-7z-compressed")


def test_7z_rejects_corrupt_input() -> None:
    with pytest.raises(ArchiveExtractionError, match="corrupt 7z"):
        ArchiveUnpacker().unpack(b"not an archive", media_type="application/x-7z-compressed")


@pytest.mark.parametrize("unsafe_name", ["../x.txt", "..\\x.txt", "/bad.txt", "C:/x.txt"])
def test_7z_rejects_unsafe_member_paths(unsafe_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Preserve a valid header/CRC while replacing the entry name; py7zr's writer
    # refuses unsafe names, so a hostile archive cannot be created through it.
    data = bytearray(_seven_zip({"safe.txt": b"hello"}))
    offset, size = struct.unpack_from("<QQ", data, 12)
    start = 32 + offset
    header = data[start : start + size].replace("safe.txt".encode("utf-16le"), unsafe_name.encode("utf-16le"))
    data[start : start + size] = header
    struct.pack_into("<I", data, 28, zlib.crc32(header))
    struct.pack_into("<I", data, 8, zlib.crc32(data[12:32]))
    with pytest.raises(ArchiveExtractionError, match="path|member"):
        ArchiveUnpacker().unpack(bytes(data), media_type="application/x-7z-compressed")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("media_type", ["image/heic", "image/heif"])
def test_heif_converts_without_prior_plugin_registration(media_type: str, monkeypatch: pytest.MonkeyPatch) -> None:
    image = pytest.importorskip("PIL.Image")
    pillow_heif = pytest.importorskip("pillow_heif")
    buffer = io.BytesIO()
    pillow_heif.from_pillow(image.new("RGB", (2, 3), "red")).save(buffer)
    image.init()
    # Isolate every registry changed by registration, even if another test has
    # already loaded the plugin, and restore the caller's Pillow state.
    for name in ("OPEN", "SAVE", "SAVE_ALL", "EXTENSION", "MIME"):
        monkeypatch.setattr(image, name, dict(getattr(image, name)))
    monkeypatch.setattr(image, "ID", list(image.ID))
    image.OPEN.pop("HEIF", None)
    result = ImageNormalizer().convert(buffer.getvalue(), media_type=media_type)
    assert result.media_type == "image/png"
    with image.open(io.BytesIO(result.bytes)) as converted:
        assert converted.format == "PNG"
        assert converted.size == (2, 3)


def test_avif_converts_with_pillow_decoder() -> None:
    image = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    image.new("RGB", (3, 2), "blue").save(buffer, format="AVIF")
    result = ImageNormalizer().convert(buffer.getvalue(), media_type="image/avif")
    assert result.media_type == "image/png"
    with image.open(io.BytesIO(result.bytes)) as converted:
        assert converted.size == (3, 2)


def test_heif_corrupt_bytes_raise_typed_error() -> None:
    pytest.importorskip("pillow_heif")
    with pytest.raises(ImageConversionError):
        ImageNormalizer().convert(b"not a HEIF image", media_type="image/heic")
