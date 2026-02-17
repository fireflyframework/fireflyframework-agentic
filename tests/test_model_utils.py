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

"""Tests for the model_utils module."""

from __future__ import annotations

import pytest

from fireflyframework_genai.model_utils import (
    detect_model_family,
    extract_model_info,
    get_model_identifier,
)


class TestExtractModelInfo:
    """Tests for extract_model_info()."""

    def test_none_returns_empty(self):
        assert extract_model_info(None) == ("", "")

    def test_openai_string(self):
        assert extract_model_info("openai:gpt-4o") == ("openai", "gpt-4o")

    def test_bedrock_string(self):
        assert extract_model_info("bedrock:anthropic.claude-3-5-sonnet-latest") == (
            "bedrock",
            "anthropic.claude-3-5-sonnet-latest",
        )

    def test_azure_string(self):
        assert extract_model_info("azure:gpt-4o") == ("azure", "gpt-4o")

    def test_ollama_string(self):
        assert extract_model_info("ollama:llama3.2") == ("ollama", "llama3.2")

    def test_anthropic_string(self):
        assert extract_model_info("anthropic:claude-3-5-sonnet-latest") == (
            "anthropic",
            "claude-3-5-sonnet-latest",
        )

    def test_bare_model_name(self):
        assert extract_model_info("gpt-4o") == ("", "gpt-4o")

    def test_google_string(self):
        assert extract_model_info("google:gemini-2.0-flash") == ("google", "gemini-2.0-flash")


class TestGetModelIdentifier:
    """Tests for get_model_identifier()."""

    def test_none_returns_empty(self):
        assert get_model_identifier(None) == ""

    def test_string_passthrough(self):
        assert get_model_identifier("openai:gpt-4o") == "openai:gpt-4o"

    def test_bedrock_string(self):
        assert get_model_identifier("bedrock:anthropic.claude-3-5-sonnet-latest") == (
            "bedrock:anthropic.claude-3-5-sonnet-latest"
        )

    def test_bare_model_name(self):
        assert get_model_identifier("gpt-4o") == "gpt-4o"


class TestDetectModelFamily:
    """Tests for detect_model_family()."""

    def test_none_returns_unknown(self):
        assert detect_model_family(None) == "unknown"

    @pytest.mark.parametrize(
        ("model", "expected_family"),
        [
            ("openai:gpt-4o", "openai"),
            ("openai:gpt-4.1-mini", "openai"),
            ("openai:o3-mini", "openai"),
            ("anthropic:claude-3-5-sonnet-latest", "anthropic"),
            ("anthropic:claude-sonnet-4-20250514", "anthropic"),
            ("google:gemini-2.0-flash", "google"),
            ("google:gemini-2.5-pro", "google"),
            ("groq:llama-3.3-70b-versatile", "meta"),
            ("mistral:mistral-large-latest", "mistral"),
            ("mistral:mixtral-8x7b", "mistral"),
            ("deepseek:deepseek-chat", "deepseek"),
        ],
    )
    def test_direct_providers(self, model: str, expected_family: str):
        assert detect_model_family(model) == expected_family

    @pytest.mark.parametrize(
        ("model", "expected_family"),
        [
            ("bedrock:anthropic.claude-3-5-sonnet-latest", "anthropic"),
            ("bedrock:meta.llama-3-70b", "meta"),
            ("bedrock:mistral.mixtral-8x7b", "mistral"),
            ("azure:gpt-4o", "openai"),
        ],
    )
    def test_proxy_providers(self, model: str, expected_family: str):
        assert detect_model_family(model) == expected_family

    def test_unknown_model(self):
        assert detect_model_family("unknown:some-model") == "unknown"

    def test_empty_string(self):
        assert detect_model_family("") == "unknown"
