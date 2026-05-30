# Copyright 2026 Firefly Software Foundation
# Licensed under the Apache License, Version 2.0.
"""``EmailUnpacker`` -- expand EML (RFC 822) and Outlook MSG envelopes.

Returns one ``(filename, bytes)`` tuple per item. Plain-text / HTML bodies
are surfaced as ``body.txt`` / ``body.html`` so the caller can route them
like any other text source; attachments come out under their declared
filename. When :attr:`BinaryConfig.email_render_header` is set, a
``<stem>-headers.md`` markdown item carrying Subject/From/To/Date is emitted
first.

EML parsing is stdlib (``email``); MSG parsing uses ``extract-msg`` (lazy
import, ships in the ``binary`` extra).
"""

from __future__ import annotations

import contextlib
import email
import email.message
import email.policy
import io
import logging
from collections.abc import Iterator

from fireflyframework_agentic.content.binary.config import BinaryConfig
from fireflyframework_agentic.content.binary.errors import EmailParseError

logger = logging.getLogger(__name__)

_EMAIL_TYPES = {"message/rfc822", "application/vnd.ms-outlook"}


class EmailUnpacker:
    """Extract attachments + bodies (+ optional header) from an email envelope."""

    def __init__(self, config: BinaryConfig | None = None) -> None:
        self._render_header = (config or BinaryConfig()).email_render_header

    @staticmethod
    def supports(media_type: str) -> bool:
        return media_type in _EMAIL_TYPES

    def unpack(
        self,
        data: bytes,
        *,
        media_type: str,
        filename: str | None = None,
    ) -> list[tuple[str, bytes]]:
        try:
            if media_type == "message/rfc822":
                items = list(self._iter_eml(data, filename))
            elif media_type == "application/vnd.ms-outlook":
                items = list(self._iter_msg(data, filename))
            else:
                raise EmailParseError(f"unsupported email media type {media_type!r}", filename=filename)
        except EmailParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EmailParseError(f"email could not be parsed: {exc}", filename=filename) from exc
        return items

    # ------------------------------------------------------------------

    def _iter_eml(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        msg = email.message_from_bytes(data, policy=email.policy.default)
        if self._render_header:
            header = _render_eml_header(msg)
            if header:
                yield _header_filename(filename), header.encode("utf-8")
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            ctype = part.get_content_type()
            raw_payload = part.get_payload(decode=True)
            if not isinstance(raw_payload, (bytes, bytearray)):
                continue
            payload: bytes = bytes(raw_payload)
            if not payload:
                continue
            if disposition == "attachment" or part.get_filename():
                yield (part.get_filename() or _default_name(ctype)), payload
                continue
            if ctype == "text/plain":
                yield "body.txt", payload
            elif ctype == "text/html":
                yield "body.html", payload

    def _iter_msg(self, data: bytes, filename: str | None) -> Iterator[tuple[str, bytes]]:
        try:
            import extract_msg  # pyright: ignore[reportMissingImports]
        except ImportError as exc:  # pragma: no cover -- runtime dep guard
            raise EmailParseError("extract-msg is required for Outlook .msg input", filename=filename) from exc
        try:
            msg = extract_msg.openMsg(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise EmailParseError(f"could not parse .msg: {exc}", filename=filename) from exc
        try:
            if self._render_header:
                header = _render_msg_header(msg)
                if header:
                    yield _header_filename(filename), header.encode("utf-8")
            for att in getattr(msg, "attachments", []) or []:
                payload = getattr(att, "data", None)
                if not isinstance(payload, (bytes, bytearray)):
                    continue
                name = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None) or "attachment"
                yield name, bytes(payload)
            raw_body: object = getattr(msg, "body", None)
            raw_html: object = getattr(msg, "htmlBody", None)
            body = (
                raw_body.encode("utf-8", errors="replace")
                if isinstance(raw_body, str)
                else (bytes(raw_body) if isinstance(raw_body, (bytes, bytearray)) else b"")
            )
            html = (
                raw_html
                if isinstance(raw_html, bytes)
                else (raw_html.encode("utf-8", errors="replace") if isinstance(raw_html, str) else b"")
            )
            if body.strip():
                yield "body.txt", body
            if html.strip():
                yield "body.html", html
        finally:
            with contextlib.suppress(Exception):
                msg.close()


def _render_eml_header(msg: email.message.Message) -> str:
    lines = []
    for label in ("Subject", "From", "To", "Cc", "Date", "Message-ID"):
        value = msg.get(label, "")
        if value:
            lines.append(f"**{label}:** {value}")
    return "\n".join(lines)


def _render_msg_header(msg: object) -> str:
    lines = []
    for label, attr in (("Subject", "subject"), ("From", "sender"), ("To", "to"), ("Date", "date")):
        value = getattr(msg, attr, "")
        if value:
            lines.append(f"**{label}:** {value}")
    return "\n".join(lines)


def _header_filename(filename: str | None) -> str:
    base = (filename or "email").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] or "email"
    return f"{stem}-headers.md"


def _default_name(content_type: str) -> str:
    suffix = content_type.split("/")[-1] if "/" in content_type else "bin"
    return f"attachment.{suffix}"
