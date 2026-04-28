"""Tests for logging.py -- text and JSON formatters."""

from __future__ import annotations

import json
import logging

from fireflyframework_agentic.logging import JsonFormatter, configure_logging


class TestJsonFormatter:
    def test_format_produces_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_format_includes_exception(self) -> None:
        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="fail",
                args=(),
                exc_info=sys.exc_info(),
            )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exception" in parsed
        assert "boom" in parsed["exception"]


class TestConfigureLogging:
    def test_text_format(self) -> None:
        configure_logging("DEBUG")
        logger = logging.getLogger("fireflyframework_agentic")
        assert logger.level == logging.DEBUG

    def test_json_format(self) -> None:
        configure_logging("INFO", format_style="json")
        logger = logging.getLogger("fireflyframework_agentic")
        handler = [h for h in logger.handlers if getattr(h, "_firefly_managed", False)]
        assert len(handler) >= 1
        assert isinstance(handler[0].formatter, JsonFormatter)

    def test_replaces_previous_handler(self) -> None:
        configure_logging("INFO")
        configure_logging("DEBUG")
        logger = logging.getLogger("fireflyframework_agentic")
        managed = [h for h in logger.handlers if getattr(h, "_firefly_managed", False)]
        assert len(managed) == 1
