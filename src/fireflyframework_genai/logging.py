# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Logging utilities for the Firefly GenAI framework.

All framework modules log under the ``fireflyframework_genai`` hierarchy.
Use :func:`configure_logging` or :func:`enable_debug` to turn on
framework-level logging without touching the root logger or third-party
libraries.

Quick start::

    from fireflyframework_genai.logging import configure_logging

    configure_logging("INFO")          # agent + reasoning progress
    configure_logging("DEBUG")         # includes LLM call timings

Or even shorter::

    from fireflyframework_genai.logging import enable_debug

    enable_debug()   # equivalent to configure_logging("DEBUG")
"""

from __future__ import annotations

import copy
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_LOGGER_NAME = "fireflyframework_genai"

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s  %(message)s"
_DEFAULT_DATEFMT = "%H:%M:%S"

# ANSI escape helpers
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"

_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": _DIM,
    "INFO": _GREEN,
    "WARNING": _YELLOW,
    "ERROR": _RED,
    "CRITICAL": f"{_BOLD}{_RED}",
}

# Symbols emitted by LoggingMiddleware that we can enhance.
_SYMBOL_COLORS: dict[str, str] = {
    "\u25b8": _CYAN,  # ▸  entry
    "\u2713": _GREEN,  # ✓  success
    "\u2717": _RED,  # ✗  failure
}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Emits fields: ``timestamp``, ``level``, ``logger``, ``message``,
    and any extra keys attached to the record.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ColoredFormatter(logging.Formatter):
    """Human-friendly formatter with ANSI colours for terminal output.

    Colour scheme:

    * **Level names** — DEBUG dim, INFO green, WARNING yellow, ERROR red.
    * **Timestamp** — dim.
    * **Logger name** — dim (truncated to last two dotted segments).
    * **Symbols** — ``\u25b8`` cyan, ``\u2713`` green, ``\u2717`` red.
    * **Agent name** (first word after a symbol) — bold cyan.
    * **Timing values** (e.g. ``123.4ms``) — yellow.

    Falls back to plain text automatically when the stream is not a TTY.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
    ) -> None:
        super().__init__(fmt or _DEFAULT_FORMAT, datefmt or _DEFAULT_DATEFMT)

    def format(self, record: logging.LogRecord) -> str:  # noqa: C901
        record = copy.copy(record)
        # Coloured level badge
        lvl = record.levelname
        color = _LEVEL_COLORS.get(lvl, "")
        record.levelname = f"{color}{lvl:<7}{_RESET}"

        # Dim timestamp
        record.asctime = f"{_DIM}{self.formatTime(record, self.datefmt)}{_RESET}"

        # Shorten logger name: keep last two segments
        parts = record.name.rsplit(".", 2)
        short = ".".join(parts[-2:]) if len(parts) > 2 else record.name
        record.name = f"{_DIM}{short}{_RESET}"

        # Coloured message symbols and agent names
        msg = record.getMessage()
        msg = self._colorise_message(msg)
        record.msg = msg
        record.args = None  # already formatted

        # Build final line — skip the parent's getMessage (we handled it)
        line = f"{record.asctime} {record.levelname} {record.name}  {record.msg}"
        if record.exc_info and record.exc_info[1]:
            line += "\n" + self.formatException(record.exc_info)
        return line

    @staticmethod
    def _colorise_message(msg: str) -> str:
        """Apply colour to known symbols, agent names, and timing values."""
        import re

        # Colour leading symbols (▸ ✓ ✗)
        for sym, col in _SYMBOL_COLORS.items():
            if msg.startswith(sym):
                # Symbol + agent name (first token after the symbol)
                rest = msg[len(sym) :].lstrip()
                # Agent name is everything up to the first dot or paren
                match = re.match(r"([\w-]+)", rest)
                if match:
                    agent = match.group(1)
                    after = rest[match.end() :]
                    msg = f"{col}{sym}{_RESET} {_BOLD}{_CYAN}{agent}{_RESET}{after}"
                else:
                    msg = f"{col}{sym}{_RESET} {rest}"
                break

        # Colour timing values like "123.4ms"
        msg = re.sub(
            r"(\d+\.\d+ms)",
            rf"{_YELLOW}\1{_RESET}",
            msg,
        )

        # Colour token/cost brackets like "[tokens=150, cost=$0.0023]"
        msg = re.sub(
            r"(\[tokens=.*?\])",
            rf"{_DIM}\1{_RESET}",
            msg,
        )

        return msg


def configure_logging(
    level: str | int = "INFO",
    *,
    fmt: str = _DEFAULT_FORMAT,
    datefmt: str = _DEFAULT_DATEFMT,
    stream: Any | None = None,
    format_style: str = "text",
) -> None:
    """Configure logging for all ``fireflyframework_genai`` modules.

    This attaches a :class:`logging.StreamHandler` to the framework's
    root logger so that agent, reasoning, memory, and tool operations
    are visible at the requested *level*.

    The handler is added **only** to the ``fireflyframework_genai`` logger,
    so third-party and application-level loggers are not affected.

    Calling this function multiple times replaces the previous handler.

    Parameters:
        level: Logging level as a string (``"DEBUG"``, ``"INFO"``, etc.)
            or an ``int`` constant from the :mod:`logging` module.
        fmt: Log record format string.
        datefmt: Date/time format string.
        stream: Output stream.  Defaults to :data:`sys.stderr`.
        format_style: ``"text"`` (default) for human-readable output,
            ``"json"`` for structured JSON lines, or ``"colored"`` for
            ANSI-coloured terminal output (falls back to plain text when
            the stream is not a TTY).
    """
    logger = logging.getLogger(_LOGGER_NAME)

    # Remove any previously installed handlers from this helper.
    for h in list(logger.handlers):
        if getattr(h, "_firefly_managed", False):
            logger.removeHandler(h)

    out_stream = stream or sys.stderr
    handler = logging.StreamHandler(out_stream)
    if format_style == "json":
        handler.setFormatter(JsonFormatter())
    elif format_style == "colored" and _is_tty(out_stream):
        handler.setFormatter(ColoredFormatter(fmt, datefmt))
    else:
        handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    handler._firefly_managed = True  # type: ignore[attr-defined]

    resolved_level = level if isinstance(level, int) else getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(resolved_level)
    handler.setLevel(resolved_level)
    logger.addHandler(handler)


def _is_tty(stream: object) -> bool:
    """Return *True* if *stream* looks like an interactive terminal."""
    return hasattr(stream, "isatty") and stream.isatty()  # type: ignore[union-attr]


def enable_debug() -> None:
    """Shortcut for ``configure_logging("DEBUG")``.

    Turns on the most verbose framework logging, including LLM call
    timings, structured output parsing, and memory integration details.
    """
    configure_logging("DEBUG")
