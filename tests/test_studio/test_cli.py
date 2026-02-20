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

"""Tests for the Firefly Studio CLI entry point."""

from __future__ import annotations

import pytest

pytest.importorskip("uvicorn", reason="uvicorn not installed")

from fireflyframework_genai.studio.cli import main, parse_args

# ---------------------------------------------------------------------------
# parse_args — defaults
# ---------------------------------------------------------------------------


class TestParseArgsDefaults:
    def test_default_port(self) -> None:
        args = parse_args([])
        assert args.port == 8470

    def test_default_host(self) -> None:
        args = parse_args([])
        assert args.host == "127.0.0.1"

    def test_default_no_browser(self) -> None:
        args = parse_args([])
        assert args.no_browser is False

    def test_default_dev(self) -> None:
        args = parse_args([])
        assert args.dev is False


# ---------------------------------------------------------------------------
# parse_args — overrides
# ---------------------------------------------------------------------------


class TestParseArgsOverrides:
    def test_port_override(self) -> None:
        args = parse_args(["--port", "9000"])
        assert args.port == 9000

    def test_host_override(self) -> None:
        args = parse_args(["--host", "0.0.0.0"])
        assert args.host == "0.0.0.0"

    def test_no_browser_flag(self) -> None:
        args = parse_args(["--no-browser"])
        assert args.no_browser is True

    def test_dev_flag(self) -> None:
        args = parse_args(["--dev"])
        assert args.dev is True

    def test_all_overrides(self) -> None:
        args = parse_args(["--port", "9000", "--host", "0.0.0.0", "--no-browser"])
        assert args.port == 9000
        assert args.host == "0.0.0.0"
        assert args.no_browser is True


# ---------------------------------------------------------------------------
# parse_args — explicit "studio" subcommand
# ---------------------------------------------------------------------------


class TestParseArgsSubcommand:
    def test_explicit_studio_subcommand(self) -> None:
        args = parse_args(["studio"])
        assert args.port == 8470
        assert args.host == "127.0.0.1"
        assert args.no_browser is False

    def test_studio_subcommand_with_flags(self) -> None:
        args = parse_args(["studio", "--port", "9000"])
        assert args.port == 9000

    def test_studio_subcommand_with_all_flags(self) -> None:
        args = parse_args(["studio", "--port", "9000", "--host", "0.0.0.0", "--no-browser", "--dev"])
        assert args.port == 9000
        assert args.host == "0.0.0.0"
        assert args.no_browser is True
        assert args.dev is True


# ---------------------------------------------------------------------------
# main — is callable
# ---------------------------------------------------------------------------


class TestMainCallable:
    def test_main_is_callable(self) -> None:
        assert callable(main)
